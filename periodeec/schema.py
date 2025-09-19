import os
import logging
from typing import Dict, Any, Optional, List, Union
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class TrackStatus(Enum):
    """Status of a track in the system."""
    UNKNOWN = "unknown"
    FOUND_IN_LIBRARY = "found_in_library"
    DOWNLOADED = "downloaded"
    DOWNLOAD_FAILED = "download_failed"
    NOT_AVAILABLE = "not_available"
    PROCESSING = "processing"


class AudioFormat(Enum):
    """Supported audio formats."""
    MP3 = "mp3"
    FLAC = "flac"
    ALAC = "alac"
    AAC = "aac"
    M4A = "m4a"
    OGG = "ogg"
    WAV = "wav"
    WMA = "wma"
    APE = "ape"


@dataclass
class AudioMetadata:
    """Audio file metadata information."""
    format: Optional[AudioFormat] = None
    bitrate: int = 0
    sample_rate: int = 0
    duration_seconds: int = 0
    file_size_bytes: int = 0
    channels: int = 0
    bit_depth: int = 0
    quality_score: int = 0  # 0-100 quality rating


@dataclass
class DownloadInfo:
    """Information about download attempts and results."""
    attempted: bool = False
    successful: bool = False
    last_attempt: Optional[datetime] = None
    attempt_count: int = 0
    downloader_used: Optional[str] = None
    error_message: Optional[str] = None
    match_quality: Optional[str] = None
    download_time_seconds: float = 0.0


class Track:
    """Track class with comprehensive metadata and status tracking."""
    
    def __init__(self, title: str, artist: str, album: str = "", 
                 isrc: str = "", album_url: str = "", release_year: int = 1970, 
                 path: str = "", **kwargs):
        """
        Initialize a track.
        
        Args:
            title: Track title
            artist: Primary artist name
            album: Album name
            isrc: International Standard Recording Code
            album_url: URL to the album (e.g., Spotify URL)
            release_year: Release year
            path: Local file path if available
            **kwargs: Additional metadata
        """
        # Core metadata
        self.title = title.strip()
        self.artist = artist.strip()
        self.album = album.strip()
        self.isrc = isrc.strip().upper()
        self.album_url = album_url.strip()
        self.release_year = max(1900, min(release_year, datetime.now().year + 1))
        self.path = path.strip()
        
        # Extended metadata
        self.all_artists: List[str] = kwargs.get('all_artists', [artist] if artist else [])
        self.primary_artist: str = kwargs.get('primary_artist', artist)
        self.albumartist: str = kwargs.get('albumartist', artist)
        self.track_number: int = kwargs.get('track_number', 0)
        self.disc_number: int = kwargs.get('disc_number', 1)
        self.genre: str = kwargs.get('genre', '').strip()
        self.duration_ms: int = kwargs.get('duration_ms', 0)
        
        # External IDs
        self.spotify_id: str = kwargs.get('spotify_id', '').strip()
        self.musicbrainz_id: str = kwargs.get('musicbrainz_id', '').strip()
        self.musicbrainz_recording_id: str = kwargs.get('musicbrainz_recording_id', '').strip()

        # Multi-service support
        self.lastfm_url: str = kwargs.get('lastfm_url', '').strip()
        self.listenbrainz_recording_mbid: str = kwargs.get('listenbrainz_recording_mbid', '').strip()
        self.import_source: str = kwargs.get('import_source', '').strip()

        # Playback statistics
        self.play_count: int = kwargs.get('play_count', 0)
        self.last_played: Optional[datetime] = kwargs.get('last_played', None)
        self.loved_at: Optional[datetime] = kwargs.get('loved_at', None)
        
        # Audio metadata
        self.audio_metadata = AudioMetadata()
        if 'audio_metadata' in kwargs:
            audio_data = kwargs['audio_metadata']
            if isinstance(audio_data, dict):
                self.audio_metadata = AudioMetadata(**audio_data)
            elif isinstance(audio_data, AudioMetadata):
                self.audio_metadata = audio_data
        
        # Status tracking
        self.status = TrackStatus(kwargs.get('status', TrackStatus.UNKNOWN.value))
        self.download_info = DownloadInfo()
        if 'download_info' in kwargs:
            download_data = kwargs['download_info']
            if isinstance(download_data, dict):
                self.download_info = DownloadInfo(**download_data)
            elif isinstance(download_data, DownloadInfo):
                self.download_info = download_data
        
        # Timestamps
        self.created_at = kwargs.get('created_at', datetime.now())
        self.updated_at = kwargs.get('updated_at', datetime.now())
        self.last_checked = kwargs.get('last_checked')
        
        # Additional metadata
        self.explicit: bool = kwargs.get('explicit', False)
        self.popularity: int = kwargs.get('popularity', 0)  # 0-100 Spotify popularity
        self.preview_url: str = kwargs.get('preview_url', '').strip()
        self.external_urls: Dict[str, str] = kwargs.get('external_urls', {})
        
        # Custom tags for user organization
        self.tags: List[str] = kwargs.get('tags', [])
        self.notes: str = kwargs.get('notes', '').strip()
    
    @property
    def duration_seconds(self) -> int:
        """Get duration in seconds."""
        return self.duration_ms // 1000 if self.duration_ms > 0 else 0
    
    @property
    def duration_formatted(self) -> str:
        """Get formatted duration string (MM:SS)."""
        if self.duration_ms <= 0:
            return "0:00"
        
        total_seconds = self.duration_seconds
        minutes = total_seconds // 60
        seconds = total_seconds % 60
        return f"{minutes}:{seconds:02d}"
    
    @property
    def all_artists_string(self) -> str:
        """Get all artists as a formatted string."""
        if not self.all_artists:
            return self.artist
        return ", ".join(self.all_artists)
    
    @property
    def has_local_file(self) -> bool:
        """Check if track has a valid local file."""
        return bool(self.path and os.path.exists(self.path))
    
    @property
    def file_extension(self) -> Optional[str]:
        """Get file extension if path exists."""
        if not self.path:
            return None
        return os.path.splitext(self.path)[1].lower().lstrip('.')
    
    @property
    def audio_format(self) -> Optional[AudioFormat]:
        """Get audio format based on file extension or metadata."""
        if self.audio_metadata.format:
            return self.audio_metadata.format
        
        ext = self.file_extension
        if ext:
            try:
                return AudioFormat(ext)
            except ValueError:
                return None
        
        return None
    
    def update_path(self, new_path: str, update_metadata: bool = True):
        """
        Update the file path and optionally refresh metadata.
        
        Args:
            new_path: New file path
            update_metadata: Whether to update file metadata
        """
        old_path = self.path
        self.path = new_path.strip()
        self.updated_at = datetime.now()
        
        if update_metadata and self.has_local_file:
            self._update_file_metadata()
            
        logger.debug(f"Updated path for '{self.title}': {old_path} -> {new_path}")
    
    def _update_file_metadata(self):
        """Update file-based metadata like size, format, etc."""
        if not self.has_local_file:
            return
        
        try:
            # Get file stats
            stat = os.stat(self.path)
            self.audio_metadata.file_size_bytes = stat.st_size
            
            # Determine format from extension
            ext = self.file_extension
            if ext:
                try:
                    self.audio_metadata.format = AudioFormat(ext)
                except ValueError:
                    logger.debug(f"Unknown audio format: {ext}")
            
            # Calculate quality score based on format and file size
            self.audio_metadata.quality_score = self._calculate_quality_score()
            
        except Exception as e:
            logger.debug(f"Error updating file metadata for '{self.path}': {e}")
    
    def _calculate_quality_score(self) -> int:
        """Calculate a quality score (0-100) based on format and metadata."""
        score = 0
        
        # Base score by format
        format_scores = {
            AudioFormat.FLAC: 100,
            AudioFormat.ALAC: 95,
            AudioFormat.WAV: 90,
            AudioFormat.APE: 85,
            AudioFormat.AAC: 70,
            AudioFormat.M4A: 70,
            AudioFormat.MP3: 60,
            AudioFormat.OGG: 55,
            AudioFormat.WMA: 45
        }
        
        if self.audio_metadata.format:
            score = format_scores.get(self.audio_metadata.format, 30)
        
        # Adjust for bitrate (if available)
        if self.audio_metadata.bitrate > 0:
            if self.audio_metadata.bitrate >= 1411:  # CD quality or higher
                score = min(100, score + 10)
            elif self.audio_metadata.bitrate >= 320:
                score = min(100, score + 5)
            elif self.audio_metadata.bitrate < 128:
                score = max(10, score - 20)
        
        # Adjust for sample rate
        if self.audio_metadata.sample_rate > 0:
            if self.audio_metadata.sample_rate >= 96000:  # Hi-res
                score = min(100, score + 10)
            elif self.audio_metadata.sample_rate >= 44100:  # CD quality
                score = min(100, score + 5)
        
        return max(0, min(100, score))
    
    def mark_download_attempt(self, downloader_name: str, success: bool, 
                            error_message: str = "", match_quality: str = "",
                            download_time: float = 0.0):
        """Mark a download attempt and its result."""
        self.download_info.attempted = True
        self.download_info.successful = success
        self.download_info.last_attempt = datetime.now()
        self.download_info.attempt_count += 1
        self.download_info.downloader_used = downloader_name
        self.download_info.error_message = error_message
        self.download_info.match_quality = match_quality
        self.download_info.download_time_seconds = download_time
        self.updated_at = datetime.now()
        
        if success:
            self.status = TrackStatus.DOWNLOADED
        else:
            self.status = TrackStatus.DOWNLOAD_FAILED
    
    def mark_found_in_library(self, library_path: str):
        """Mark track as found in music library."""
        self.path = library_path
        self.status = TrackStatus.FOUND_IN_LIBRARY
        self.last_checked = datetime.now()
        self.updated_at = datetime.now()
        self._update_file_metadata()
    
    def add_tag(self, tag: str):
        """Add a tag to the track."""
        tag = tag.strip().lower()
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now()
    
    def remove_tag(self, tag: str):
        """Remove a tag from the track."""
        tag = tag.strip().lower()
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = datetime.now()
    
    def get_search_string(self) -> str:
        """Get a string suitable for searching/matching."""
        parts = [self.artist, self.title]
        if self.album:
            parts.append(self.album)
        return " ".join(part.strip() for part in parts if part.strip())
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert track to dictionary for serialization."""
        return {
            # Core metadata
            "title": self.title,
            "artist": self.artist,
            "album": self.album,
            "isrc": self.isrc,
            "album_url": self.album_url,
            "release_year": self.release_year,
            "path": self.path,
            
            # Extended metadata
            "all_artists": self.all_artists,
            "primary_artist": self.primary_artist,
            "albumartist": self.albumartist,
            "track_number": self.track_number,
            "disc_number": self.disc_number,
            "genre": self.genre,
            "duration_ms": self.duration_ms,
            
            # External IDs
            "spotify_id": self.spotify_id,
            "musicbrainz_id": self.musicbrainz_id,
            "musicbrainz_recording_id": self.musicbrainz_recording_id,
            
            # Audio metadata
            "audio_metadata": {
                "format": self.audio_metadata.format.value if self.audio_metadata.format else None,
                "bitrate": self.audio_metadata.bitrate,
                "sample_rate": self.audio_metadata.sample_rate,
                "duration_seconds": self.audio_metadata.duration_seconds,
                "file_size_bytes": self.audio_metadata.file_size_bytes,
                "channels": self.audio_metadata.channels,
                "bit_depth": self.audio_metadata.bit_depth,
                "quality_score": self.audio_metadata.quality_score
            },
            
            # Status and download info
            "status": self.status.value,
            "download_info": {
                "attempted": self.download_info.attempted,
                "successful": self.download_info.successful,
                "last_attempt": self.download_info.last_attempt.isoformat() if self.download_info.last_attempt else None,
                "attempt_count": self.download_info.attempt_count,
                "downloader_used": self.download_info.downloader_used,
                "error_message": self.download_info.error_message,
                "match_quality": self.download_info.match_quality,
                "download_time_seconds": self.download_info.download_time_seconds
            },
            
            # Timestamps
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_checked": self.last_checked.isoformat() if self.last_checked else None,
            
            # Additional metadata
            "explicit": self.explicit,
            "popularity": self.popularity,
            "preview_url": self.preview_url,
            "external_urls": self.external_urls,
            "tags": self.tags,
            "notes": self.notes
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Track':
        """Create track from dictionary."""
        # Parse timestamps
        for timestamp_field in ['created_at', 'updated_at', 'last_checked']:
            if data.get(timestamp_field):
                try:
                    data[timestamp_field] = datetime.fromisoformat(data[timestamp_field])
                except (ValueError, TypeError):
                    data[timestamp_field] = None
        
        # Parse download attempt timestamp
        if data.get('download_info', {}).get('last_attempt'):
            try:
                data['download_info']['last_attempt'] = datetime.fromisoformat(
                    data['download_info']['last_attempt']
                )
            except (ValueError, TypeError):
                data['download_info']['last_attempt'] = None
        
        # Parse audio format
        if data.get('audio_metadata', {}).get('format'):
            try:
                data['audio_metadata']['format'] = AudioFormat(data['audio_metadata']['format'])
            except (ValueError, TypeError):
                data['audio_metadata']['format'] = None
        
        # Parse status
        if data.get('status'):
            try:
                data['status'] = TrackStatus(data['status'])
            except (ValueError, TypeError):
                data['status'] = TrackStatus.UNKNOWN
        
        return cls(**data)
    
    def __str__(self) -> str:
        """String representation of the track."""
        return f"Track('{self.artist} - {self.title}', status={self.status.value})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return (f"Track(title='{self.title}', artist='{self.artist}', "
                f"album='{self.album}', isrc='{self.isrc}', status={self.status.value}, "
                f"path='{self.path}')")
    
    def __eq__(self, other) -> bool:
        """Compare tracks for equality."""
        if not isinstance(other, Track):
            return False
        
        # Primary comparison by ISRC if available
        if self.isrc and other.isrc:
            return self.isrc == other.isrc
        
        # Fallback to artist/title comparison
        return (self.artist.lower() == other.artist.lower() and 
                self.title.lower() == other.title.lower())
    
    def __hash__(self) -> int:
        """Hash function for use in sets/dicts."""
        if self.isrc:
            return hash(self.isrc)
        return hash((self.artist.lower(), self.title.lower()))


class UserRole(Enum):
    """User roles in the system."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"


@dataclass
class UserPreferences:
    """User preferences and settings."""
    preferred_quality: str = "high"  # low, medium, high, lossless
    preferred_formats: List[str] = field(default_factory=lambda: ['flac', 'mp3'])
    auto_download: bool = True
    create_m3u: bool = True
    include_collaborative_playlists: bool = True
    include_followed_playlists: bool = False
    notification_enabled: bool = True
    sync_interval_minutes: int = 1440  # 24 hours


@dataclass
class UserStats:
    """User statistics and activity tracking."""
    total_playlists: int = 0
    total_tracks: int = 0
    tracks_downloaded: int = 0
    tracks_failed: int = 0
    last_sync: Optional[datetime] = None
    total_sync_time_minutes: float = 0.0
    successful_syncs: int = 0
    failed_syncs: int = 0


class User:
    """User class with preferences, statistics, and role management."""
    
    def __init__(self, id: str, name: str = "", **kwargs):
        """
        Initialize a user.
        
        Args:
            id: User identifier (e.g., Spotify username)
            name: Display name
            **kwargs: Additional user data
        """
        # Core identity
        self.id = id.strip()
        self.name = name.strip() or id
        self.email = kwargs.get('email', '').strip()
        self.role = UserRole(kwargs.get('role', UserRole.USER.value))
        
        # External service connections
        self.spotify_username = kwargs.get('spotify_username', id).strip()
        self.plex_usernames: List[str] = kwargs.get('plex_usernames', [])

        # Multi-service support
        self.lastfm_username: str = kwargs.get('lastfm_username', '').strip()
        self.listenbrainz_username: str = kwargs.get('listenbrainz_username', '').strip()
        self.external_urls: Dict[str, str] = kwargs.get('external_urls', {})
        
        # Service URIs/IDs
        self.spotify_uri = kwargs.get('spotify_uri', '').strip()
        self.musicbrainz_id = kwargs.get('musicbrainz_id', '').strip()
        
        # Preferences
        prefs_data = kwargs.get('preferences', {})
        if isinstance(prefs_data, dict):
            self.preferences = UserPreferences(**prefs_data)
        else:
            self.preferences = UserPreferences()
        
        # Statistics
        stats_data = kwargs.get('stats', {})
        if isinstance(stats_data, dict):
            # Parse datetime fields
            if stats_data.get('last_sync'):
                try:
                    stats_data['last_sync'] = datetime.fromisoformat(stats_data['last_sync'])
                except (ValueError, TypeError):
                    stats_data['last_sync'] = None
            self.stats = UserStats(**stats_data)
        else:
            self.stats = UserStats()
        
        # Timestamps
        self.created_at = kwargs.get('created_at', datetime.now())
        self.updated_at = kwargs.get('updated_at', datetime.now())
        self.last_login = kwargs.get('last_login')
        self.last_activity = kwargs.get('last_activity')
        
        # Parse timestamp strings
        for field in ['created_at', 'updated_at', 'last_login', 'last_activity']:
            value = getattr(self, field)
            if isinstance(value, str):
                try:
                    setattr(self, field, datetime.fromisoformat(value))
                except (ValueError, TypeError):
                    setattr(self, field, None)
        
        # Status and flags
        self.active = kwargs.get('active', True)
        self.verified = kwargs.get('verified', False)
        self.notifications_enabled = kwargs.get('notifications_enabled', True)
        
        # Custom data
        self.tags: List[str] = kwargs.get('tags', [])
        self.notes: str = kwargs.get('notes', '').strip()
        self.custom_data: Dict[str, Any] = kwargs.get('custom_data', {})
    
    def add_plex_username(self, username: str):
        """Add a Plex username to the user."""
        username = username.strip()
        if username and username not in self.plex_usernames:
            self.plex_usernames.append(username)
            self.updated_at = datetime.now()
    
    def remove_plex_username(self, username: str):
        """Remove a Plex username from the user."""
        username = username.strip()
        if username in self.plex_usernames:
            self.plex_usernames.remove(username)
            self.updated_at = datetime.now()
    
    def update_stats(self, **kwargs):
        """Update user statistics."""
        for key, value in kwargs.items():
            if hasattr(self.stats, key):
                setattr(self.stats, key, value)
        
        self.stats.last_sync = datetime.now()
        self.last_activity = datetime.now()
        self.updated_at = datetime.now()
    
    def increment_sync_stats(self, success: bool, duration_minutes: float = 0.0):
        """Increment sync statistics."""
        if success:
            self.stats.successful_syncs += 1
        else:
            self.stats.failed_syncs += 1
        
        self.stats.total_sync_time_minutes += duration_minutes
        self.stats.last_sync = datetime.now()
        self.last_activity = datetime.now()
        self.updated_at = datetime.now()
    
    def get_sync_success_rate(self) -> float:
        """Get sync success rate as percentage."""
        total = self.stats.successful_syncs + self.stats.failed_syncs
        if total == 0:
            return 0.0
        return (self.stats.successful_syncs / total) * 100
    
    def get_download_success_rate(self) -> float:
        """Get download success rate as percentage."""
        total = self.stats.tracks_downloaded + self.stats.tracks_failed
        if total == 0:
            return 0.0
        return (self.stats.tracks_downloaded / total) * 100
    
    def add_tag(self, tag: str):
        """Add a tag to the user."""
        tag = tag.strip().lower()
        if tag and tag not in self.tags:
            self.tags.append(tag)
            self.updated_at = datetime.now()
    
    def remove_tag(self, tag: str):
        """Remove a tag from the user."""
        tag = tag.strip().lower()
        if tag in self.tags:
            self.tags.remove(tag)
            self.updated_at = datetime.now()
    
    def is_admin(self) -> bool:
        """Check if user has admin role."""
        return self.role == UserRole.ADMIN
    
    def can_write(self) -> bool:
        """Check if user has write permissions."""
        return self.role in [UserRole.ADMIN, UserRole.USER]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert user to dictionary for serialization."""
        return {
            # Core identity
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "role": self.role.value,
            
            # External connections
            "spotify_username": self.spotify_username,
            "plex_usernames": self.plex_usernames,
            "external_urls": self.external_urls,
            "spotify_uri": self.spotify_uri,
            "musicbrainz_id": self.musicbrainz_id,
            
            # Preferences
            "preferences": {
                "preferred_quality": self.preferences.preferred_quality,
                "preferred_formats": self.preferences.preferred_formats,
                "auto_download": self.preferences.auto_download,
                "create_m3u": self.preferences.create_m3u,
                "include_collaborative_playlists": self.preferences.include_collaborative_playlists,
                "include_followed_playlists": self.preferences.include_followed_playlists,
                "notification_enabled": self.preferences.notification_enabled,
                "sync_interval_minutes": self.preferences.sync_interval_minutes
            },
            
            # Statistics
            "stats": {
                "total_playlists": self.stats.total_playlists,
                "total_tracks": self.stats.total_tracks,
                "tracks_downloaded": self.stats.tracks_downloaded,
                "tracks_failed": self.stats.tracks_failed,
                "last_sync": self.stats.last_sync.isoformat() if self.stats.last_sync else None,
                "total_sync_time_minutes": self.stats.total_sync_time_minutes,
                "successful_syncs": self.stats.successful_syncs,
                "failed_syncs": self.stats.failed_syncs
            },
            
            # Timestamps
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "last_login": self.last_login.isoformat() if self.last_login else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
            
            # Status and flags
            "active": self.active,
            "verified": self.verified,
            "notifications_enabled": self.notifications_enabled,
            
            # Custom data
            "tags": self.tags,
            "notes": self.notes,
            "custom_data": self.custom_data
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'User':
        """Create user from dictionary."""
        return cls(**data)
    
    def __str__(self) -> str:
        """String representation of the user."""
        return f"User({self.name} [{self.id}], role={self.role.value})"
    
    def __repr__(self) -> str:
        """Detailed string representation."""
        return (f"User(id='{self.id}', name='{self.name}', "
                f"role={self.role.value}, active={self.active})")
    
    def __eq__(self, other) -> bool:
        """Compare users for equality."""
        if not isinstance(other, User):
            return False
        return self.id == other.id
    
    def __hash__(self) -> int:
        """Hash function for use in sets/dicts."""
        return hash(self.id)


# Compatibility aliases for backward compatibility
# Track alias for backwards compatibility
# User alias for backwards compatibility
