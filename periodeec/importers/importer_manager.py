"""
Importer Manager for coordinating multiple music service importers.

This module manages all available music service importers and provides
a unified interface for accessing playlists and tracks from multiple services.
"""

import logging
import asyncio
from typing import Dict, List, Any, Optional, Tuple

from periodeec.importers.base_importer import MusicServiceImporter, ImporterError
from periodeec.importers.spotify_importer import SpotifyImporter
from periodeec.importers.lastfm_importer import LastFMImporter
from periodeec.importers.listenbrainz_importer import ListenBrainzImporter
from periodeec.schema import User, Track
from periodeec.playlist import Playlist

logger = logging.getLogger(__name__)


class ImporterManager:
    """
    Manages multiple music service importers.

    Provides a unified interface for working with different music services
    and coordinates authentication, playlist retrieval, and track synchronization.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the importer manager.

        Args:
            config: Configuration dictionary containing service configurations
        """
        self.config = config
        self.importers: Dict[str, MusicServiceImporter] = {}
        self.logger = logging.getLogger(__name__)

        # Initialize available importers based on configuration
        self._initialize_importers()

    def _initialize_importers(self):
        """Initialize all configured importers."""
        importers_config = self.config.get('importers', {})

        # Initialize Spotify importer
        spotify_config = importers_config.get('spotify', {})
        if spotify_config.get('enabled', False):
            try:
                self.importers['spotify'] = SpotifyImporter(spotify_config)
                self.logger.info("Spotify importer initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize Spotify importer: {e}")

        # Initialize Last.FM importer
        lastfm_config = importers_config.get('lastfm', {})
        if lastfm_config.get('enabled', False):
            try:
                self.importers['lastfm'] = LastFMImporter(lastfm_config)
                self.logger.info("Last.FM importer initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize Last.FM importer: {e}")

        # Initialize ListenBrainz importer
        listenbrainz_config = importers_config.get('listenbrainz', {})
        if listenbrainz_config.get('enabled', False):
            try:
                self.importers['listenbrainz'] = ListenBrainzImporter(listenbrainz_config)
                self.logger.info("ListenBrainz importer initialized")
            except Exception as e:
                self.logger.error(f"Failed to initialize ListenBrainz importer: {e}")

        self.logger.info(f"Initialized {len(self.importers)} importers: {list(self.importers.keys())}")

    def get_available_services(self) -> List[str]:
        """
        Get list of available and configured services.

        Returns:
            List of service names
        """
        return list(self.importers.keys())

    def get_importer(self, service: str) -> Optional[MusicServiceImporter]:
        """
        Get a specific importer by service name.

        Args:
            service: Service name (e.g., 'spotify', 'lastfm', 'listenbrainz')

        Returns:
            Importer instance or None if not available
        """
        return self.importers.get(service)

    async def authenticate_all(self) -> Dict[str, bool]:
        """
        Authenticate all configured importers.

        Returns:
            Dictionary mapping service names to authentication status
        """
        results = {}

        for service, importer in self.importers.items():
            try:
                self.logger.info(f"Authenticating {service}...")
                results[service] = await importer.authenticate()
                if results[service]:
                    self.logger.info(f"{service} authentication successful")
                else:
                    self.logger.warning(f"{service} authentication failed")
            except Exception as e:
                self.logger.error(f"{service} authentication error: {e}")
                results[service] = False

        successful = sum(1 for success in results.values() if success)
        self.logger.info(f"Authentication complete: {successful}/{len(results)} services authenticated")

        return results

    async def validate_all_connections(self) -> Dict[str, bool]:
        """
        Validate connections for all importers.

        Returns:
            Dictionary mapping service names to connection status
        """
        results = {}

        for service, importer in self.importers.items():
            try:
                results[service] = await importer.validate_connection()
            except Exception as e:
                self.logger.error(f"{service} connection validation error: {e}")
                results[service] = False

        return results

    async def get_user_playlists_from_service(self, service: str, user_id: str, **kwargs) -> List[Playlist]:
        """
        Get playlists from a specific service.

        Args:
            service: Service name
            user_id: User identifier for the service
            **kwargs: Service-specific options

        Returns:
            List of playlists from the service

        Raises:
            ImporterError: If service not available or operation fails
        """
        importer = self.get_importer(service)
        if not importer:
            raise ImporterError(f"Service {service} not available")

        if not importer.is_authenticated:
            await importer.authenticate()

        return await importer.get_user_playlists(user_id, **kwargs)

    async def get_user_playlists_from_all_services(self, user_config: Dict[str, Any]) -> Dict[str, List[Playlist]]:
        """
        Get playlists from all configured services for a user.

        Args:
            user_config: User configuration containing service usernames

        Returns:
            Dictionary mapping service names to lists of playlists
        """
        results = {}
        tasks = []

        # Create async tasks for each service
        for service, importer in self.importers.items():
            # Get the username for this service
            username_key = f"{service}_username"
            username = user_config.get('service_connections', {}).get(username_key)

            if not username:
                self.logger.debug(f"No username configured for {service}")
                continue

            if not importer.is_authenticated:
                try:
                    await importer.authenticate()
                except Exception as e:
                    self.logger.error(f"Authentication failed for {service}: {e}")
                    continue

            # Create task for this service
            task = self._get_playlists_for_service(service, importer, username, user_config)
            tasks.append((service, task))

        # Execute all tasks in parallel
        for service, task in tasks:
            try:
                playlists = await task
                results[service] = playlists
                self.logger.info(f"Retrieved {len(playlists)} playlists from {service}")
            except Exception as e:
                self.logger.error(f"Failed to get playlists from {service}: {e}")
                results[service] = []

        return results

    async def _get_playlists_for_service(self, service: str, importer: MusicServiceImporter,
                                       username: str, user_config: Dict[str, Any]) -> List[Playlist]:
        """Helper method to get playlists from a specific service."""
        try:
            # Get service-specific options from user config
            service_options = user_config.get('import_preferences', {}).get(service, {})

            # Get playlists
            playlists = await importer.get_user_playlists(username, **service_options)

            return playlists

        except Exception as e:
            self.logger.error(f"Error getting playlists from {service} for user {username}: {e}")
            return []

    async def search_tracks_across_services(self, query: str, services: Optional[List[str]] = None,
                                          limit: int = 20) -> Dict[str, List[Track]]:
        """
        Search for tracks across multiple services.

        Args:
            query: Search query
            services: List of services to search (None for all)
            limit: Maximum results per service

        Returns:
            Dictionary mapping service names to lists of tracks
        """
        if services is None:
            services = list(self.importers.keys())

        results = {}
        tasks = []

        # Create search tasks for each service
        for service in services:
            importer = self.get_importer(service)
            if importer and importer.is_authenticated:
                task = importer.search_tracks(query, limit)
                tasks.append((service, task))

        # Execute searches in parallel
        for service, task in tasks:
            try:
                tracks = await task
                results[service] = tracks
            except Exception as e:
                self.logger.error(f"Search failed for {service}: {e}")
                results[service] = []

        return results

    def get_service_stats(self) -> Dict[str, Dict[str, Any]]:
        """
        Get statistics for all importers.

        Returns:
            Dictionary mapping service names to their statistics
        """
        stats = {}

        for service, importer in self.importers.items():
            try:
                stats[service] = importer.get_service_stats()
            except Exception as e:
                self.logger.error(f"Error getting stats for {service}: {e}")
                stats[service] = {'error': str(e)}

        return stats

    def get_manager_stats(self) -> Dict[str, Any]:
        """
        Get overall manager statistics.

        Returns:
            Dictionary with manager statistics
        """
        total_services = len(self.importers)
        authenticated_services = sum(1 for importer in self.importers.values() if importer.is_authenticated)

        return {
            'total_services': total_services,
            'authenticated_services': authenticated_services,
            'available_services': list(self.importers.keys()),
            'authentication_rate': authenticated_services / total_services if total_services > 0 else 0,
            'service_stats': self.get_service_stats()
        }

    async def shutdown(self):
        """
        Shutdown all importers and clean up resources.
        """
        self.logger.info("Shutting down importer manager...")

        for service, importer in self.importers.items():
            try:
                # If importers have cleanup methods, call them here
                if hasattr(importer, 'shutdown'):
                    await importer.shutdown()
                self.logger.debug(f"Shutdown {service} importer")
            except Exception as e:
                self.logger.error(f"Error shutting down {service} importer: {e}")

        self.importers.clear()
        self.logger.info("Importer manager shutdown complete")