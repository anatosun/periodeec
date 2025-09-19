"""
Base importer interface for music services.

This module defines the abstract base class that all music service importers
must implement to ensure consistent behavior across different services.
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from datetime import datetime

from periodeec.schema import User, Track
from periodeec.playlist import Playlist

logger = logging.getLogger(__name__)


class ImporterError(Exception):
    """Base exception for importer-related errors."""
    pass


class AuthenticationError(ImporterError):
    """Raised when authentication with a music service fails."""
    pass


class RateLimitError(ImporterError):
    """Raised when API rate limits are exceeded."""
    pass


class ServiceUnavailableError(ImporterError):
    """Raised when the music service is temporarily unavailable."""
    pass


class MusicServiceImporter(ABC):
    """
    Abstract base class for music service importers.

    Each music service (Spotify, LastFM, ListenBrainz) should implement this
    interface to provide consistent access to playlists, tracks, and user data.
    """

    def __init__(self, service_name: str, config: Dict[str, Any]):
        """
        Initialize the importer.

        Args:
            service_name: Name of the music service (e.g., "spotify", "lastfm")
            config: Service-specific configuration dictionary
        """
        self.service_name = service_name
        self.config = config
        self.logger = logging.getLogger(f"{__name__}.{service_name}")
        self._authenticated = False
        self._last_request_time = 0
        self._request_count = 0

        # Rate limiting configuration
        self.rate_limit_rpm = config.get('rate_limit_rpm', 60)
        self.min_request_interval = 60.0 / self.rate_limit_rpm if self.rate_limit_rpm > 0 else 0

        # Service source tagging
        self.add_source_to_titles = config.get('add_source_to_titles', False)
        self.source_tag_format = config.get('source_tag_format', '({service})')

    @property
    def is_authenticated(self) -> bool:
        """Check if the importer is authenticated with the service."""
        return self._authenticated

    @abstractmethod
    async def authenticate(self) -> bool:
        """
        Authenticate with the music service.

        Returns:
            True if authentication successful, False otherwise

        Raises:
            AuthenticationError: If authentication fails
        """
        pass

    @abstractmethod
    async def validate_connection(self) -> bool:
        """
        Validate the connection to the music service.

        Returns:
            True if connection is valid, False otherwise
        """
        pass

    @abstractmethod
    async def get_user_info(self, user_id: str) -> User:
        """
        Get user information from the service.

        Args:
            user_id: Service-specific user identifier

        Returns:
            User object with service information

        Raises:
            ImporterError: If user cannot be retrieved
        """
        pass

    @abstractmethod
    async def get_user_playlists(self, user_id: str, **kwargs) -> List[Playlist]:
        """
        Get all playlists for a user.

        Args:
            user_id: Service-specific user identifier
            **kwargs: Service-specific options (e.g., include_collaborative)

        Returns:
            List of Playlist objects

        Raises:
            ImporterError: If playlists cannot be retrieved
        """
        pass

    @abstractmethod
    async def get_playlist_tracks(self, playlist_url: str, limit: int = None) -> List[Track]:
        """
        Get all tracks from a playlist.

        Args:
            playlist_url: Service-specific playlist identifier/URL
            limit: Maximum number of tracks to retrieve (None for all)

        Returns:
            List of Track objects

        Raises:
            ImporterError: If tracks cannot be retrieved
        """
        pass

    @abstractmethod
    async def search_tracks(self, query: str, limit: int = 20) -> List[Track]:
        """
        Search for tracks on the service.

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of Track objects matching the query

        Raises:
            ImporterError: If search fails
        """
        pass

    # Optional methods with default implementations

    async def get_user_top_tracks(self, user_id: str, time_range: str = "medium_term",
                                 limit: int = 50) -> List[Track]:
        """
        Get user's top tracks (if supported by service).

        Args:
            user_id: Service-specific user identifier
            time_range: Time period ("short_term", "medium_term", "long_term")
            limit: Maximum number of tracks

        Returns:
            List of top tracks, empty list if not supported
        """
        self.logger.info(f"{self.service_name} does not support top tracks")
        return []

    async def get_user_listening_history(self, user_id: str, limit: int = 50,
                                       start_date: Optional[datetime] = None,
                                       end_date: Optional[datetime] = None) -> List[Track]:
        """
        Get user's listening history (if supported by service).

        Args:
            user_id: Service-specific user identifier
            limit: Maximum number of tracks
            start_date: Start date for history (None for no limit)
            end_date: End date for history (None for current time)

        Returns:
            List of recently played tracks, empty list if not supported
        """
        self.logger.info(f"{self.service_name} does not support listening history")
        return []

    async def get_user_saved_tracks(self, user_id: str, limit: int = None) -> List[Track]:
        """
        Get user's saved/liked tracks (if supported by service).

        Args:
            user_id: Service-specific user identifier
            limit: Maximum number of tracks (None for all)

        Returns:
            List of saved tracks, empty list if not supported
        """
        self.logger.info(f"{self.service_name} does not support saved tracks")
        return []

    def add_source_tag_to_title(self, title: str) -> str:
        """
        Add service source tag to playlist title if configured.

        Args:
            title: Original playlist title

        Returns:
            Title with source tag added if enabled
        """
        if not self.add_source_to_titles:
            return title

        # Format the service name for display
        service_display = self.service_name.capitalize()
        source_tag = self.source_tag_format.format(service=service_display)

        # Add tag if not already present
        if source_tag not in title:
            title = f"{title} {source_tag}"

        return title

    def get_service_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the importer's usage.

        Returns:
            Dictionary with service statistics
        """
        return {
            'service_name': self.service_name,
            'authenticated': self._authenticated,
            'rate_limit_rpm': self.rate_limit_rpm,
            'request_count': self._request_count,
            'add_source_to_titles': self.add_source_to_titles
        }

    def _rate_limit_wait(self):
        """Internal method to handle rate limiting."""
        import time
        current_time = time.time()
        time_since_last = current_time - self._last_request_time

        if time_since_last < self.min_request_interval:
            wait_time = self.min_request_interval - time_since_last
            self.logger.debug(f"Rate limiting: waiting {wait_time:.2f}s")
            time.sleep(wait_time)

        self._last_request_time = time.time()
        self._request_count += 1