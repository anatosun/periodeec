import os
import logging
import time
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import quote
from pathvalidate import sanitize_filename
from plexapi.server import PlexServer
from plexapi.collection import Collection as PlexCollection
from plexapi.playlist import Playlist as PlexPlaylist
from plexapi.audio import Track as PlexTrack, Album as PlexAlbum
from plexapi.exceptions import NotFound, BadRequest, Unauthorized
from periodeec.playlist import Playlist
from periodeec.schema import Track

logger = logging.getLogger(__name__)


class PlexOperationResult:
    """Result of a Plex operation with detailed status information."""
    
    def __init__(self, success: bool, message: str = "", details: Dict[str, Any] = None):
        self.success = success
        self.message = message
        self.details = details or {}
        self.timestamp = time.time()


class PlexHandler:
    """Plex handler with error handling, caching, and features."""
    
    def __init__(self, baseurl: str, token: str, section: str = "Music", 
                 m3u_path: str = "m3u", verify_ssl: bool = True, 
                 timeout: int = 30, retry_attempts: int = 3):
        """
        Initialize the Plex handler.
        
        Args:
            baseurl: Plex server URL
            token: Plex authentication token
            section: Music library section name
            m3u_path: Path for M3U playlist files
            verify_ssl: Whether to verify SSL certificates
            timeout: Request timeout in seconds
            retry_attempts: Number of retry attempts for failed operations
        """
        self.baseurl = baseurl.rstrip('/')
        self.token = token
        self.section_name = section
        self.m3u_path = m3u_path
        self.verify_ssl = verify_ssl
        self.timeout = timeout
        self.retry_attempts = retry_attempts
        
        # Create M3U directory
        os.makedirs(self.m3u_path, exist_ok=True)
        
        # Initialize connection
        self._plex_server = None
        self._section = None
        self._admin_user = None
        self._user_cache = {}
        self._track_cache = {}
        
        # Connect and validate
        self._connect()
    
    def _connect(self) -> bool:
        """Establish connection to Plex server."""
        try:
            self._plex_server = PlexServer(
                baseurl=self.baseurl,
                token=self.token,
                timeout=self.timeout
            )
            
            # Get admin user
            self._admin_user = self._plex_server.account().username
            logger.info(f"Connected to Plex server as {self._admin_user}")
            
            # Get music section
            self._section = self._plex_server.library.section(self.section_name)
            logger.info(f"Found music section: {self.section_name}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to connect to Plex server: {e}")
            raise
    
    def _retry_operation(self, operation, *args, **kwargs):
        """Retry an operation with exponential backoff."""
        last_error = None
        
        for attempt in range(self.retry_attempts):
            try:
                return operation(*args, **kwargs)
            except Exception as e:
                last_error = e
                if attempt < self.retry_attempts - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Operation failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                else:
                    logger.error(f"Operation failed after {self.retry_attempts} attempts: {e}")
        
        raise last_error
    
    def get_plex_instance_for_user(self, username: str):
        """Get a Plex instance for a specific user with caching."""
        if not username or username == self._admin_user:
            return self._plex_server
        
        if username in self._user_cache:
            return self._user_cache[username]
        
        try:
            user_instance = self._plex_server.switchUser(username)
            self._user_cache[username] = user_instance
            logger.info(f"Switched to user: {username}")
            return user_instance
        except Exception as e:
            logger.error(f"Failed to switch to user {username}: {e}")
            return self._plex_server
    
    def sanitize_filename(self, name: str, max_length: int = 255) -> str:
        """Sanitize filename for filesystem compatibility."""
        if not name:
            return "Unknown"
        
        # Use pathvalidate library for better sanitization
        sanitized = sanitize_filename(name, replacement_text="_")
        
        # Ensure length limits
        if len(sanitized) > max_length:
            sanitized = sanitized[:max_length-3] + "..."
        
        return sanitized
    
    def find_tracks_in_library(self, playlist: Playlist) -> Tuple[List[PlexTrack], List[Track]]:
        """
        Find tracks from playlist in Plex library.
        
        Returns:
            Tuple of (found_plex_tracks, missing_tracks)
        """
        found_tracks = []
        missing_tracks = []
        
        logger.info(f"Searching for {len(playlist.tracks)} tracks in Plex library")
        
        for track in playlist.tracks:
            plex_track = self._find_track_in_library(track)
            if plex_track:
                found_tracks.append(plex_track)
            else:
                missing_tracks.append(track)
        
        logger.info(f"Found {len(found_tracks)}/{len(playlist.tracks)} tracks in library")
        if missing_tracks:
            logger.warning(f"Missing {len(missing_tracks)} tracks from library")
        
        return found_tracks, missing_tracks
    
    def _find_track_in_library(self, track: Track) -> Optional[PlexTrack]:
        """Find a specific track in the Plex library."""
        # Check cache first
        cache_key = f"{track.artist}:{track.title}:{track.isrc}"
        if cache_key in self._track_cache:
            return self._track_cache[cache_key]
        
        # Search strategies in order of preference
        search_strategies = [
            # Strategy 1: Exact ISRC match (most reliable)
            lambda: self._search_by_isrc(track.isrc) if track.isrc else None,
            
            # Strategy 2: Artist + Title + Album
            lambda: self._search_by_metadata(track.artist, track.title, track.album),
            
            # Strategy 3: Artist + Title (no album)
            lambda: self._search_by_metadata(track.artist, track.title),
            
            # Strategy 4: Fuzzy search by title
            lambda: self._fuzzy_search_by_title(track.title)
        ]
        
        for strategy in search_strategies:
            try:
                result = strategy()
                if result:
                    self._track_cache[cache_key] = result
                    return result
            except Exception as e:
                logger.debug(f"Search strategy failed: {e}")
                continue
        
        logger.debug(f"Could not find track: {track.artist} - {track.title}")
        return None
    
    def _search_by_isrc(self, isrc: str) -> Optional[PlexTrack]:
        """Search for track by ISRC."""
        if not isrc:
            return None
        
        try:
            # Plex doesn't have direct ISRC search, but we can search in track metadata
            results = self._section.searchTracks(guid=f"*{isrc}*")
            return results[0] if results else None
        except Exception:
            return None
    
    def _search_by_metadata(self, artist: str, title: str, album: str = "") -> Optional[PlexTrack]:
        """Search for track by metadata."""
        try:
            # Search by artist and title
            if album:
                results = self._section.searchTracks(
                    **{"artist.title": artist, "track.title": title, "album.title": album}
                )
            else:
                results = self._section.searchTracks(
                    **{"artist.title": artist, "track.title": title}
                )
            
            return results[0] if results else None
        except Exception:
            return None
    
    def _fuzzy_search_by_title(self, title: str) -> Optional[PlexTrack]:
        """Fuzzy search by track title."""
        try:
            results = self._section.searchTracks(title=title)
            # Return first result - could be improved with similarity matching
            return results[0] if results else None
        except Exception:
            return None
    
    def create_m3u(self, playlist: Playlist, username: str = "") -> PlexOperationResult:
        """Create an M3U file for the playlist."""
        try:
            # Sanitize names
            user_folder = self.sanitize_filename(username) if username else "admin"
            playlist_name = self.sanitize_filename(playlist.title)
            
            # Create user directory
            user_m3u_path = os.path.join(self.m3u_path, user_folder)
            os.makedirs(user_m3u_path, exist_ok=True)
            
            # Create M3U file
            m3u_file_path = os.path.join(user_m3u_path, f"{playlist_name}.m3u")
            
            with open(m3u_file_path, "w", encoding="utf-8") as m3u_file:
                m3u_file.write("#EXTM3U\n")
                m3u_file.write(f"#PLAYLIST:{playlist.title}\n")
                
                valid_tracks = 0
                for track in playlist.tracks:
                    if track.path and os.path.exists(track.path):
                        # Find audio files in the track path
                        audio_files = self._find_audio_files(track.path)
                        
                        for audio_file in audio_files:
                            m3u_file.write(f"#EXTINF:-1,{track.artist} - {track.title}\n")
                            m3u_file.write(f"{audio_file}\n")
                            valid_tracks += 1
                            break  # Only use the first audio file found
            
            logger.info(f"Created M3U file: {m3u_file_path} with {valid_tracks} tracks")
            
            return PlexOperationResult(
                success=True,
                message=f"M3U file created successfully",
                details={
                    "file_path": m3u_file_path,
                    "track_count": valid_tracks,
                    "total_tracks": len(playlist.tracks)
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to create M3U file: {e}")
            return PlexOperationResult(
                success=False,
                message=f"Failed to create M3U file: {e}"
            )
    
    def _find_audio_files(self, directory: str) -> List[str]:
        """Find audio files in a directory."""
        audio_extensions = {'.mp3', '.flac', '.m4a', '.aac', '.ogg', '.wav', '.wma'}
        audio_files = []
        
        try:
            if os.path.isfile(directory):
                # Single file
                if any(directory.lower().endswith(ext) for ext in audio_extensions):
                    audio_files.append(directory)
            else:
                # Directory - recursively find audio files
                for root, dirs, files in os.walk(directory):
                    for file in files:
                        if any(file.lower().endswith(ext) for ext in audio_extensions):
                            audio_files.append(os.path.join(root, file))
        except Exception as e:
            logger.warning(f"Error scanning directory {directory}: {e}")
        
        return audio_files
    
    def create_collection(self, playlist: Playlist, overwrite: bool = True) -> PlexOperationResult:
        """Create or update a Plex collection."""
        try:
            # Find tracks in library
            plex_tracks, missing_tracks = self.find_tracks_in_library(playlist)
            
            if not plex_tracks:
                return PlexOperationResult(
                    success=False,
                    message="No tracks found in Plex library for this playlist",
                    details={"missing_count": len(missing_tracks)}
                )
            
            collection_title = playlist.title
            
            # Try to find existing collection
            existing_collection = None
            try:
                existing_collection = self._section.collection(title=collection_title)
            except NotFound:
                pass
            
            if existing_collection:
                if overwrite:
                    logger.info(f"Updating existing collection: {collection_title}")
                    # Remove all items and add new ones
                    existing_collection.removeItems(existing_collection.items())
                    existing_collection.addItems(plex_tracks)
                    
                    # Update metadata
                    if playlist.poster:
                        try:
                            existing_collection.uploadPoster(url=playlist.poster)
                        except Exception as e:
                            logger.warning(f"Failed to update collection poster: {e}")
                    
                    if playlist.summary:
                        try:
                            existing_collection.editSummary(summary=playlist.summary)
                        except Exception as e:
                            logger.warning(f"Failed to update collection summary: {e}")
                    
                    collection = existing_collection
                else:
                    return PlexOperationResult(
                        success=False,
                        message=f"Collection '{collection_title}' already exists and overwrite is disabled"
                    )
            else:
                logger.info(f"Creating new collection: {collection_title}")
                # Get albums from tracks for collection
                albums = list(set(track.album() for track in plex_tracks if track.album()))
                
                collection = self._plex_server.createCollection(
                    title=collection_title,
                    section=self.section_name,
                    items=albums or plex_tracks  # Use albums if available, otherwise tracks
                )
                
                # Set metadata
                if playlist.poster:
                    try:
                        collection.uploadPoster(url=playlist.poster)
                    except Exception as e:
                        logger.warning(f"Failed to set collection poster: {e}")
                
                if playlist.summary:
                    try:
                        collection.editSummary(summary=playlist.summary)
                    except Exception as e:
                        logger.warning(f"Failed to set collection summary: {e}")
            
            logger.info(f"Collection '{collection_title}' created/updated successfully")
            
            return PlexOperationResult(
                success=True,
                message=f"Collection '{collection_title}' created/updated successfully",
                details={
                    "collection_id": collection.key,
                    "track_count": len(plex_tracks),
                    "missing_count": len(missing_tracks),
                    "collection_type": "new" if not existing_collection else "updated"
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to create collection '{playlist.title}': {e}")
            return PlexOperationResult(
                success=False,
                message=f"Failed to create collection: {e}"
            )
    
    def create_playlist(self, playlist: Playlist, username: str = "", 
                       overwrite: bool = True) -> PlexOperationResult:
        """Create or update a Plex playlist."""
        try:
            # Get Plex instance for user
            plex_instance = self.get_plex_instance_for_user(username)
            
            # Find tracks in library
            plex_tracks, missing_tracks = self.find_tracks_in_library(playlist)
            
            if not plex_tracks:
                return PlexOperationResult(
                    success=False,
                    message="No tracks found in Plex library for this playlist",
                    details={"missing_count": len(missing_tracks)}
                )
            
            playlist_title = playlist.title
            
            # Try to find existing playlist
            existing_playlist = None
            try:
                existing_playlist = plex_instance.playlist(title=playlist_title)
            except NotFound:
                pass
            
            if existing_playlist:
                if overwrite:
                    logger.info(f"Updating existing playlist: {playlist_title} for user: {username or 'admin'}")
                    # Remove all items and add new ones
                    existing_playlist.removeItems(existing_playlist.items())
                    existing_playlist.addItems(plex_tracks)
                    
                    # Update metadata
                    if playlist.poster:
                        try:
                            existing_playlist.uploadPoster(url=playlist.poster)
                        except Exception as e:
                            logger.warning(f"Failed to update playlist poster: {e}")
                    
                    if playlist.summary:
                        try:
                            existing_playlist.editSummary(summary=playlist.summary)
                        except Exception as e:
                            logger.warning(f"Failed to update playlist summary: {e}")
                    
                    plex_playlist = existing_playlist
                else:
                    return PlexOperationResult(
                        success=False,
                        message=f"Playlist '{playlist_title}' already exists and overwrite is disabled"
                    )
            else:
                logger.info(f"Creating new playlist: {playlist_title} for user: {username or 'admin'}")
                
                plex_playlist = plex_instance.createPlaylist(
                    title=playlist_title,
                    items=plex_tracks,
                    smart=False
                )
                
                # Set metadata
                if playlist.poster:
                    try:
                        plex_playlist.uploadPoster(url=playlist.poster)
                    except Exception as e:
                        logger.warning(f"Failed to set playlist poster: {e}")
                
                if playlist.summary:
                    try:
                        plex_playlist.editSummary(summary=playlist.summary)
                    except Exception as e:
                        logger.warning(f"Failed to set playlist summary: {e}")
            
            logger.info(f"Playlist '{playlist_title}' created/updated successfully")
            
            return PlexOperationResult(
                success=True,
                message=f"Playlist '{playlist_title}' created/updated successfully",
                details={
                    "playlist_id": plex_playlist.key,
                    "track_count": len(plex_tracks),
                    "missing_count": len(missing_tracks),
                    "playlist_type": "new" if not existing_playlist else "updated"
                }
            )
            
        except Exception as e:
            logger.error(f"Failed to create playlist '{playlist.title}' for user '{username}': {e}")
            return PlexOperationResult(
                success=False,
                message=f"Failed to create playlist: {e}"
            )
    
    def create(self, playlist: Playlist, username: str = "", 
               collection: bool = False, create_m3u: bool = True) -> PlexOperationResult:
        """
        Create playlist/collection and optionally M3U file.
        
        Args:
            playlist: Playlist object to create
            username: Target username (empty for admin)
            collection: Create as collection instead of playlist
            create_m3u: Also create M3U file
        """
        if not playlist.tracks:
            return PlexOperationResult(
                success=False,
                message="Cannot create playlist/collection with no tracks"
            )
        
        # Create M3U file first if requested
        m3u_result = None
        if create_m3u:
            m3u_result = self.create_m3u(playlist, username)
            if not m3u_result.success:
                logger.warning(f"M3U creation failed: {m3u_result.message}")
        
        # Create playlist or collection
        if collection:
            result = self.create_collection(playlist)
        else:
            if not username:
                return PlexOperationResult(
                    success=False,
                    message="Username required for playlist creation"
                )
            result = self.create_playlist(playlist, username)
        
        # Combine results
        if m3u_result and result.success:
            result.details["m3u_result"] = m3u_result.details
        
        return result
    
    def get_server_info(self) -> Dict[str, Any]:
        """Get Plex server information."""
        try:
            return {
                "friendlyName": self._plex_server.friendlyName,
                "version": self._plex_server.version,
                "platform": self._plex_server.platform,
                "machineIdentifier": self._plex_server.machineIdentifier,
                "musicSection": self.section_name,
                "connectedUser": self._admin_user
            }
        except Exception as e:
            logger.error(f"Failed to get server info: {e}")
            return {}
    
    def validate_connection(self) -> PlexOperationResult:
        """Validate the Plex connection and permissions."""
        try:
            # Test server connection
            server_info = self.get_server_info()
            if not server_info:
                return PlexOperationResult(
                    success=False,
                    message="Cannot connect to Plex server"
                )
            
            # Test section access
            try:
                section_info = {
                    "title": self._section.title,
                    "type": self._section.type,
                    "agent": getattr(self._section, 'agent', 'Unknown'),
                    "scanner": getattr(self._section, 'scanner', 'Unknown'),
                    "location": []  # Initialize as empty list
                }
                
                # Safely get locations
                try:
                    if hasattr(self._section, 'locations'):
                        locations = self._section.locations
                        if locations:
                            section_info["location"] = [
                                getattr(loc, 'path', str(loc)) for loc in locations
                            ]
                except Exception as e:
                    logger.debug(f"Could not get section locations: {e}")
                    section_info["location"] = ["Location unavailable"]
                    
            except Exception as e:
                return PlexOperationResult(
                    success=False,
                    message=f"Cannot access music section '{self.section_name}': {e}"
                )
            
            return PlexOperationResult(
                success=True,
                message="Plex connection validated successfully",
                details={
                    "server": server_info,
                    "section": section_info
                }
            )
            
        except Exception as e:
            return PlexOperationResult(
                success=False,
                message=f"Connection validation failed: {e}"
            )
