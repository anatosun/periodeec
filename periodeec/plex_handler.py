import os
import logging
from plexapi.server import PlexServer
from plexapi.collection import Collection as PlexCollection
from plexapi.playlist import Playlist as PlexPlaylist
from periodeec.playlist import Playlist

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class PlexHandler:
    def __init__(self, baseurl: str, token: str, section: str = "Music", m3u_path: str = "m3u"):
        self.plex_server = PlexServer(baseurl=baseurl, token=token)
        self.section = section
        self.m3u_path = m3u_path
        self.admin_user = self.plex_server.account().username

    def get_plex_instance_for_user(self, username: str):
        """Return a Plex instance for a given user."""
        return self.plex_server.switchUser(username) if username and username != self.admin_user else self.plex_server

    def sanitize_filename(self, name: str) -> str:
        """Sanitize filenames by replacing invalid characters."""
        return ''.join('_' if char in '<>:"/\\|?* ' else char for char in name)

    def create_m3u(self, playlist: Playlist, username: str) -> str:
        """Creates an M3U file for the given playlist and returns the file path."""
        username = self.sanitize_filename(username)
        title = self.sanitize_filename(playlist.title)

        user_m3u_path = os.path.join(self.m3u_path, username)
        os.makedirs(user_m3u_path, exist_ok=True)

        m3u_file_path = os.path.join(user_m3u_path, f"{title}.m3u")
        with open(m3u_file_path, "w") as m3u_file:
            m3u_file.write("#EXTM3U\n")
            for track in playlist.tracks:
                if track.path:
                    m3u_file.write(
                        f"#EXTINF:-1,{track.artist} - {track.title}\n")
                    m3u_file.write(f"{track.path}\n")

        logger.info(f"Created M3U file: {m3u_file_path}")
        return m3u_file_path

    def create_collection(self, playlist: Playlist, items) -> bool:
        """Create or update a Plex collection."""
        section = self.plex_server.library.section(self.section)
        try:
            col = section.collection(title=playlist.title)
            if col is not None:
                logger.info(
                    f"Updating existing Plex collection '{playlist.title}'")
                col.removeItems(col.items())
                col.addItems(items)
                col.uploadPoster(url=playlist.poster)
                col.editSummary(summary=playlist.summary)
                return True
        except Exception as e:
            logger.info(
                f"Creating new Plex collection '{playlist.title}': {e}")

        try:
            col = self.plex_server.createCollection(
                title=playlist.title, section=self.section, items=items)
            col.uploadPoster(url=playlist.poster)
            col.editSummary(summary=playlist.summary)
            return True
        except Exception as e:
            logger.error(f"Failed to create collection {playlist.title}: {e}")
            return False

    def create_playlist(self, playlist: Playlist, username: str, items) -> bool:
        """Create or update a Plex playlist."""
        plex_instance = self.get_plex_instance_for_user(username)

        try:
            existing_playlist = plex_instance.playlist(title=playlist.title)
            if existing_playlist is not None:
                logger.info(
                    f"Updating existing Plex playlist '{playlist.title}' for '{username}'")
                existing_playlist.removeItems(existing_playlist.items())
                existing_playlist.addItems(items)
                existing_playlist.uploadPoster(url=playlist.poster)
                existing_playlist.editSummary(summary=playlist.summary)
            return True
        except:
            logger.info(
                f"Creating new Plex playlist '{playlist.title}' for '{username}'")
            try:
                new_playlist = plex_instance.createPlaylist(
                    playlist.title, items=items, smart=False)
                new_playlist.uploadPoster(url=playlist.poster)
                new_playlist.editSummary(summary=playlist.summary)
                return True
            except Exception as e:
                logger.error(
                    f"Error creating playlist {playlist.title} for '{username}': {e}")
                return False

    def create(self, playlist: Playlist, username: str, collection: bool = False) -> bool:
        """Create or update a Plex playlist or collection."""
        m3u_file = self.create_m3u(playlist, username)

        try:
            temp_playlist = self.plex_server.createPlaylist(
                title=f"{playlist.title} (temp)", section=self.section, m3ufilepath=m3u_file
            )
            items = temp_playlist.items()
            temp_playlist.delete()
        except Exception as e:
            logger.error(
                f"Failed to create temporary playlist '{playlist.title}': {e}")
            return False

        return self.create_collection(playlist, items) if collection else self.create_playlist(playlist, username, items)
