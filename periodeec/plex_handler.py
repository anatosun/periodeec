import os
import logging
from plexapi.server import PlexServer
from plexapi.collection import Collection as PlexCollection
from plexapi.playlist import Playlist as PlexPlaylist
from periodeec.playlist import Playlist

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class PlexOperationResult:
    """Simple result class for compatibility with existing code."""

    def __init__(self, success: bool, message: str = ""):
        self.success = success
        self.message = message


class PlexHandler:
    def __init__(self, baseurl: str, token: str, section: str = "Music", m3u_path: str = "m3u",
                 verify_ssl: bool = True, timeout: int = 30, retry_attempts: int = 3,
                 music_directory: str = None):
        self.plex_server = PlexServer(baseurl=baseurl, token=token)
        self.section = section
        self.m3u_path = m3u_path
        self.music_directory = music_directory  # Beets music directory
        self.admin_user = self.plex_server.account().username

    def get_plex_instance_for_user(self, username: str):
        """Return a Plex instance for a given user."""
        return self.plex_server.switchUser(username) if username and username != self.admin_user else self.plex_server

    def sanitize_filename(self, name: str) -> str:
        """Sanitize filenames by replacing invalid characters and emojis."""
        if not name:
            return "Unknown"

        # Replace problematic filesystem characters
        invalid_chars = '<>:"/\\|?*&'
        sanitized = ''.join('_' if char in invalid_chars else char for char in name)

        # Remove or replace emoji and other non-ASCII characters that might cause issues
        # Keep basic accented characters but replace complex unicode
        result = ""
        for char in sanitized:
            if ord(char) < 128:  # Basic ASCII
                result += char
            elif ord(char) < 256:  # Extended ASCII (accented chars)
                result += char
            else:  # Replace complex unicode/emoji with underscore
                result += "_"

        # Clean up multiple underscores and trim
        result = "_".join(part for part in result.split("_") if part.strip())

        # Ensure reasonable length
        if len(result) > 100:
            result = result[:100]

        return result or "Unknown"

    def create_m3u(self, playlist: Playlist, username: str) -> str:
        """Creates an M3U file for the given playlist and returns the file path."""
        username = self.sanitize_filename(username)
        title = self.sanitize_filename(playlist.title)

        # Use the configured M3U path from configuration
        user_m3u_path = os.path.join(self.m3u_path, username)
        os.makedirs(user_m3u_path, exist_ok=True)

        m3u_file_path = os.path.join(user_m3u_path, f"{title}.m3u")

        # Write with explicit UTF-8 encoding to handle unicode characters properly
        with open(m3u_file_path, "w", encoding="utf-8") as m3u_file:
            m3u_file.write("#EXTM3U\n")
            for track in playlist.tracks:
                if track.path:
                    # Sanitize track info for M3U format
                    artist = track.artist.replace('\n', ' ').replace('\r', ' ')
                    title_clean = track.title.replace('\n', ' ').replace('\r', ' ')
                    m3u_file.write(f"#EXTINF:-1,{artist} - {title_clean}\n")
                    m3u_file.write(f"{track.path}\n")

        logger.info(f"Created M3U file: {m3u_file_path}")
        return m3u_file_path

    def create_collection(self, playlist: Playlist, items) -> bool:
        """Create or update a Plex collection."""
        section = self.plex_server.library.section(self.section)

        # First, try to find an existing collection
        existing_collection = None
        try:
            existing_collection = section.collection(title=playlist.title)
        except Exception as e:
            # Only log if it's not a "not found" type error
            if "not found" not in str(e).lower():
                logger.debug(f"Error checking for existing collection '{playlist.title}': {e}")

        # If collection exists, update it
        if existing_collection is not None:
            try:
                logger.info(f"Updating existing Plex collection '{playlist.title}'")
                existing_collection.removeItems(existing_collection.items())
                existing_collection.addItems(items)
                if playlist.poster:
                    existing_collection.uploadPoster(url=playlist.poster)
                if playlist.summary:
                    existing_collection.editSummary(summary=playlist.summary)
                return True
            except Exception as e:
                logger.error(f"Error updating existing collection '{playlist.title}': {e}")
                return False

        # If collection doesn't exist, create a new one
        try:
            logger.info(f"Creating new Plex collection '{playlist.title}'")
            col = self.plex_server.createCollection(
                title=playlist.title, section=self.section, items=items)
            if playlist.poster:
                col.uploadPoster(url=playlist.poster)
            if playlist.summary:
                col.editSummary(summary=playlist.summary)
            return True
        except Exception as e:
            logger.error(f"Failed to create collection {playlist.title}: {e}")
            return False

    def create_playlist(self, playlist: Playlist, username: str, items) -> bool:
        """Create or update a Plex playlist."""
        plex_instance = self.get_plex_instance_for_user(username)

        # First, try to find an existing playlist
        existing_playlist = None
        try:
            existing_playlist = plex_instance.playlist(title=playlist.title)
        except Exception as e:
            # Only log if it's not a "not found" type error
            if "not found" not in str(e).lower():
                logger.debug(f"Error checking for existing playlist '{playlist.title}': {e}")

        # If playlist exists, update it
        if existing_playlist is not None:
            try:
                logger.info(f"Updating existing Plex playlist '{playlist.title}' for '{username}'")
                existing_playlist.removeItems(existing_playlist.items())
                existing_playlist.addItems(items)
                if playlist.poster:
                    existing_playlist.uploadPoster(url=playlist.poster)
                if playlist.summary:
                    existing_playlist.editSummary(summary=playlist.summary)
                return True
            except Exception as e:
                logger.error(f"Error updating existing playlist '{playlist.title}' for '{username}': {e}")
                return False

        # If playlist doesn't exist, create a new one
        try:
            logger.info(f"Creating new Plex playlist '{playlist.title}' for '{username}'")
            new_playlist = plex_instance.createPlaylist(
                playlist.title, items=items, smart=False)
            if playlist.poster:
                new_playlist.uploadPoster(url=playlist.poster)
            if playlist.summary:
                new_playlist.editSummary(summary=playlist.summary)
            return True
        except Exception as e:
            logger.error(f"Error creating playlist '{playlist.title}' for '{username}': {e}")
            return False

    def create(self, playlist: Playlist, username="", collection: bool = False, create_m3u: bool = True) -> PlexOperationResult:
        """Create or update a Plex playlist or collection."""

        if username == "" and not collection:
            error_msg = f"Failed to create playlist {playlist.title}, username not provided without 'collection' flag"
            logger.error(error_msg)
            return PlexOperationResult(success=False, message=error_msg)

        if len(playlist.tracks) < 1:
            error_msg = f"Failed to create playlist {playlist.title}, no tracks provided"
            logger.error(error_msg)
            return PlexOperationResult(success=False, message=error_msg)

        m3u_file = self.create_m3u(playlist, username)

        try:
            # Use sanitized title for temporary playlist to avoid character issues
            sanitized_title = self.sanitize_filename(playlist.title)
            temp_playlist_name = f"{sanitized_title}_temp"

            logger.info(f"Creating temporary playlist '{temp_playlist_name}' from M3U file: {m3u_file}")

            # Ensure we're using the admin server instance for temporary playlist creation
            # This is crucial because only the admin has access to the M3U files
            admin_server = self.plex_server  # This should be the admin instance
            temp_playlist = admin_server.createPlaylist(
                title=temp_playlist_name,
                section=self.section,
                m3ufilepath=m3u_file
            )

            items = temp_playlist.items()
            logger.info(f"Temporary playlist created with {len(items)} items")

            # Clean up the temporary playlist
            temp_playlist.delete()
            logger.debug(f"Temporary playlist '{temp_playlist_name}' deleted")

        except Exception as e:
            error_msg = f"Failed to create temporary playlist from M3U '{m3u_file}': {e}"
            logger.error(error_msg)

            # Add debugging information
            logger.error(f"M3U file exists: {os.path.exists(m3u_file)}")
            if os.path.exists(m3u_file):
                logger.error(f"M3U file size: {os.path.getsize(m3u_file)} bytes")
                logger.error(f"M3U file readable: {os.access(m3u_file, os.R_OK)}")

            # Try to provide more specific error information
            if "m3u" in str(e).lower():
                error_msg += " - Check if M3U file is accessible by Plex and contains valid file paths"
            elif "permission" in str(e).lower():
                error_msg += " - Check if Plex has permission to read the M3U file"
            elif "not found" in str(e).lower():
                error_msg += " - M3U file or tracks within it cannot be found by Plex"

            # Try to clean up the M3U file if it exists
            try:
                if os.path.exists(m3u_file):
                    logger.debug(f"Cleaning up failed M3U file: {m3u_file}")
                    # Don't delete it for debugging purposes
                    # os.remove(m3u_file)
            except Exception:
                pass

            return PlexOperationResult(success=False, message=error_msg)

        success = self.create_collection(playlist, items) if collection else self.create_playlist(playlist, username, items)

        if success:
            return PlexOperationResult(
                success=True,
                message=f"{'Collection' if collection else 'Playlist'} '{playlist.title}' created successfully"
            )
        else:
            return PlexOperationResult(
                success=False,
                message=f"Failed to create {'collection' if collection else 'playlist'} '{playlist.title}'"
            )

    def validate_connection(self) -> PlexOperationResult:
        """Validate the Plex connection."""
        try:
            # Test basic server connection
            server_info = self.plex_server.friendlyName

            # Test section access
            section = self.plex_server.library.section(self.section)

            return PlexOperationResult(
                success=True,
                message=f"Connected to {server_info}, section: {section.title}"
            )
        except Exception as e:
            return PlexOperationResult(
                success=False,
                message=f"Connection validation failed: {e}"
            )
