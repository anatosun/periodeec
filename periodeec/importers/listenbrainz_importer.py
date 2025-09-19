"""
ListenBrainz music service importer.

This module implements the ListenBrainz music service importer for accessing
user listening history and statistics from the open-source music tracking service.
"""

import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import time

from periodeec.importers.base_importer import (
    MusicServiceImporter, AuthenticationError, ImporterError, RateLimitError
)
from periodeec.schema import User, Track, UserPreferences, UserStats
from periodeec.playlist import Playlist

logger = logging.getLogger(__name__)

try:
    import requests
except ImportError:
    requests = None
    logger.warning("requests library not available. ListenBrainz importer will not function.")


class ListenBrainzImporter(MusicServiceImporter):
    """
    ListenBrainz service importer implementation.

    Provides access to ListenBrainz user data including listening history,
    statistics, and recommendations from the open-source music tracking platform.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the ListenBrainz importer.

        Args:
            config: ListenBrainz configuration dictionary containing:
                - user_token: ListenBrainz user token (optional for public data)
                - server_url: ListenBrainz server URL (default: https://listenbrainz.org)
                - rate_limit_rpm: Requests per minute limit (default: 60)
                - add_source_to_titles: Whether to add "(ListenBrainz)" to playlist titles
                - source_tag_format: Format string for source tag
        """
        super().__init__("listenbrainz", config)

        if requests is None:
            raise ImporterError("requests library is required for ListenBrainz support. Install with: pip install requests")

        # Initialize ListenBrainz connection
        self.server_url = config.get('server_url', 'https://listenbrainz.org')
        self.user_token = config.get('user_token', '')
        self.api_base = f"{self.server_url}/1"

        # Request session with headers
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Periodeec/1.0.0 (https://github.com/anatosun/periodeec)',
            'Content-Type': 'application/json'
        })

        if self.user_token:
            self.session.headers.update({
                'Authorization': f'Token {self.user_token}'
            })

        self.logger.info("ListenBrainz importer initialized successfully")

        # ListenBrainz specific settings
        self.default_limit = config.get('default_limit', 100)
        self.max_retries = config.get('max_retries', 3)

    async def authenticate(self) -> bool:
        """
        Authenticate with ListenBrainz.

        For ListenBrainz, we test the connection and token validity.

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            # Test the connection
            self._rate_limit_wait()
            response = self.session.get(f"{self.api_base}/stats/sitewide/artists")
            response.raise_for_status()

            # Test user token if provided
            if self.user_token:
                test_response = self.session.get(f"{self.api_base}/validate-token")
                if test_response.status_code == 200:
                    token_data = test_response.json()
                    if token_data.get('valid'):
                        self.logger.info(f"ListenBrainz token valid for user: {token_data.get('user_name')}")
                    else:
                        raise AuthenticationError("ListenBrainz token is invalid")
                else:
                    raise AuthenticationError("ListenBrainz token validation failed")

            self._authenticated = True
            self.logger.info("ListenBrainz authentication successful")
            return True

        except Exception as e:
            self.logger.error(f"ListenBrainz authentication failed: {e}")
            self._authenticated = False
            raise AuthenticationError(f"ListenBrainz authentication error: {e}")

    async def validate_connection(self) -> bool:
        """
        Validate the connection to ListenBrainz.

        Returns:
            True if connection is valid
        """
        try:
            self._rate_limit_wait()
            response = self.session.get(f"{self.api_base}/stats/sitewide/artists")
            return response.status_code == 200
        except Exception as e:
            self.logger.error(f"ListenBrainz connection validation failed: {e}")
            return False

    async def get_user_info(self, user_id: str) -> User:
        """
        Get ListenBrainz user information.

        Args:
            user_id: ListenBrainz username

        Returns:
            User object with ListenBrainz information

        Raises:
            ImporterError: If user cannot be retrieved
        """
        try:
            self._rate_limit_wait()

            # Get user statistics to verify user exists and get info
            response = self.session.get(f"{self.api_base}/stats/user/{user_id}/listening-activity")

            if response.status_code == 404:
                raise ImporterError(f"ListenBrainz user {user_id} not found")

            response.raise_for_status()

            # Get additional user stats
            stats_response = self.session.get(f"{self.api_base}/stats/user/{user_id}/artists")
            total_listens = 0

            if stats_response.status_code == 200:
                stats_data = stats_response.json()
                total_listens = stats_data.get('payload', {}).get('total_artist_count', 0)

            # Create User object
            user = User(
                id=user_id,
                name=user_id,  # ListenBrainz doesn't provide display names via API
                spotify_username="",  # ListenBrainz user, no direct Spotify connection
                plex_usernames=[],
                preferences=UserPreferences(),
                stats=UserStats(
                    total_tracks=total_listens,
                    last_sync=datetime.now(timezone.utc)
                )
            )

            # Add ListenBrainz specific data
            user.listenbrainz_username = user_id
            user.external_urls = getattr(user, 'external_urls', {})
            user.external_urls['listenbrainz'] = f"{self.server_url}/user/{user_id}"

            self.logger.info(f"Retrieved ListenBrainz user info for {user_id}")
            return user

        except Exception as e:
            self.logger.error(f"Failed to get ListenBrainz user info for {user_id}: {e}")
            raise ImporterError(f"Cannot retrieve ListenBrainz user {user_id}: {e}")

    async def get_user_playlists(self, user_id: str, **kwargs) -> List[Playlist]:
        """
        Get user's "playlists" from ListenBrainz (statistics-based playlists).

        Args:
            user_id: ListenBrainz username
            **kwargs: Additional options:
                - include_top_artists: Include top artists playlist (default: True)
                - include_recent_listens: Include recent listens playlist (default: True)

        Returns:
            List of Playlist objects representing ListenBrainz data

        Raises:
            ImporterError: If data cannot be retrieved
        """
        try:
            playlists = []

            include_top_artists = kwargs.get('include_top_artists', True)
            include_recent_listens = kwargs.get('include_recent_listens', True)

            # Get top artists tracks
            if include_top_artists:
                try:
                    top_tracks = await self.get_user_top_tracks(user_id, limit=50)
                    if top_tracks:
                        title = f"{user_id}'s Top Artists Tracks"
                        if self.add_source_to_titles:
                            title = self.add_source_tag_to_title(title)

                        playlist = Playlist(
                            title=title,
                            tracks=top_tracks,
                            id=f"listenbrainz_top_artists_{user_id}",
                            path="",
                            number_of_tracks=len(top_tracks),
                            description="Top tracks based on most listened artists from ListenBrainz",
                            url=f"{self.server_url}/user/{user_id}/stats"
                        )
                        playlists.append(playlist)
                except Exception as e:
                    self.logger.warning(f"Failed to get top artists tracks: {e}")

            # Get recent listening history
            if include_recent_listens:
                try:
                    recent_tracks = await self.get_user_listening_history(user_id, limit=100)
                    if recent_tracks:
                        title = f"{user_id}'s Recent Listens"
                        if self.add_source_to_titles:
                            title = self.add_source_tag_to_title(title)

                        playlist = Playlist(
                            title=title,
                            tracks=recent_tracks,
                            id=f"listenbrainz_recent_{user_id}",
                            path="",
                            number_of_tracks=len(recent_tracks),
                            description="Recent listening history from ListenBrainz",
                            url=f"{self.server_url}/user/{user_id}"
                        )
                        playlists.append(playlist)
                except Exception as e:
                    self.logger.warning(f"Failed to get recent listens: {e}")

            self.logger.info(f"Retrieved {len(playlists)} playlists for ListenBrainz user {user_id}")
            return playlists

        except Exception as e:
            self.logger.error(f"Failed to get ListenBrainz playlists for {user_id}: {e}")
            raise ImporterError(f"Cannot retrieve ListenBrainz playlists for {user_id}: {e}")

    async def get_playlist_tracks(self, playlist_url: str, limit: int = None) -> List[Track]:
        """
        Get tracks from a ListenBrainz "playlist" (not directly supported).

        Args:
            playlist_url: ListenBrainz playlist identifier
            limit: Maximum number of tracks

        Returns:
            Empty list (ListenBrainz doesn't have traditional playlists)
        """
        self.logger.info("ListenBrainz doesn't support traditional playlists")
        return []

    async def search_tracks(self, query: str, limit: int = 20) -> List[Track]:
        """
        Search for tracks on ListenBrainz (via MusicBrainz).

        Args:
            query: Search query string
            limit: Maximum number of results

        Returns:
            List of Track objects matching the query

        Raises:
            ImporterError: If search fails
        """
        try:
            self._rate_limit_wait()

            # Use MusicBrainz search through ListenBrainz
            # This is a simplified implementation
            self.logger.info(f"ListenBrainz track search not fully implemented")
            return []

        except Exception as e:
            self.logger.error(f"ListenBrainz track search failed for query '{query}': {e}")
            raise ImporterError(f"ListenBrainz track search failed: {e}")

    async def get_user_top_tracks(self, user_id: str, time_range: str = "all_time",
                                 limit: int = 50) -> List[Track]:
        """
        Get user's top tracks from ListenBrainz (based on top artists).

        Args:
            user_id: ListenBrainz username
            time_range: Time period (not used for ListenBrainz)
            limit: Maximum number of tracks

        Returns:
            List of top tracks based on artist statistics
        """
        try:
            self._rate_limit_wait()

            # Get top artists
            response = self.session.get(f"{self.api_base}/stats/user/{user_id}/artists")

            if response.status_code == 404:
                self.logger.info(f"No statistics available for user {user_id}")
                return []

            response.raise_for_status()
            data = response.json()

            artists_data = data.get('payload', {}).get('artists', [])
            tracks = []

            # For each top artist, create representative tracks
            for i, artist_data in enumerate(artists_data):
                if i >= limit:
                    break

                try:
                    artist_name = artist_data.get('artist_name', '')
                    listen_count = artist_data.get('listen_count', 0)

                    # Create a representative track for this artist
                    # Note: This is a simplified approach since ListenBrainz
                    # doesn't directly provide track rankings
                    track = Track(
                        title=f"Representative track",  # Placeholder
                        artist=artist_name,
                        album="",
                        isrc="",
                        album_url="",
                        release_year=0,
                        path="",
                        all_artists=[artist_name],
                        duration_ms=0,
                        play_count=listen_count
                    )

                    # Add MusicBrainz data if available
                    if 'artist_mbids' in artist_data:
                        track.musicbrainz_id = artist_data['artist_mbids'][0] if artist_data['artist_mbids'] else ""

                    tracks.append(track)

                except Exception as e:
                    self.logger.debug(f"Error processing top artist: {e}")
                    continue

            self.logger.info(f"Retrieved {len(tracks)} top artist tracks for ListenBrainz user {user_id}")
            return tracks

        except Exception as e:
            self.logger.error(f"Failed to get ListenBrainz top tracks for {user_id}: {e}")
            return []

    async def get_user_listening_history(self, user_id: str, limit: int = 50,
                                       start_date: Optional[datetime] = None,
                                       end_date: Optional[datetime] = None) -> List[Track]:
        """
        Get user's recent listening history from ListenBrainz.

        Args:
            user_id: ListenBrainz username
            limit: Maximum number of tracks
            start_date: Start date for history
            end_date: End date for history

        Returns:
            List of recently played tracks
        """
        try:
            self._rate_limit_wait()

            # Build query parameters
            params = {'count': min(limit, 100)}  # ListenBrainz limits to 100

            if start_date:
                params['min_ts'] = int(start_date.timestamp())
            if end_date:
                params['max_ts'] = int(end_date.timestamp())

            response = self.session.get(f"{self.api_base}/user/{user_id}/listens", params=params)

            if response.status_code == 404:
                self.logger.info(f"No listens found for user {user_id}")
                return []

            response.raise_for_status()
            data = response.json()

            listens = data.get('payload', {}).get('listens', [])
            tracks = []

            for listen in listens:
                try:
                    track_metadata = listen.get('track_metadata', {})
                    listened_at = listen.get('listened_at')

                    artist_name = track_metadata.get('artist_name', '')
                    track_title = track_metadata.get('track_name', '')
                    album_name = track_metadata.get('release_name', '')

                    track = Track(
                        title=track_title,
                        artist=artist_name,
                        album=album_name,
                        isrc="",
                        album_url="",
                        release_year=0,
                        path="",
                        all_artists=[artist_name],
                        duration_ms=0,
                        last_played=datetime.fromtimestamp(listened_at, tz=timezone.utc) if listened_at else None
                    )

                    # Add MusicBrainz data if available
                    additional_info = track_metadata.get('additional_info', {})
                    if 'recording_mbid' in additional_info:
                        track.musicbrainz_recording_id = additional_info['recording_mbid']
                    if 'artist_mbids' in additional_info:
                        track.musicbrainz_id = additional_info['artist_mbids'][0] if additional_info['artist_mbids'] else ""

                    tracks.append(track)

                except Exception as e:
                    self.logger.debug(f"Error processing listen: {e}")
                    continue

            self.logger.info(f"Retrieved {len(tracks)} recent listens for ListenBrainz user {user_id}")
            return tracks

        except Exception as e:
            self.logger.error(f"Failed to get ListenBrainz listening history for {user_id}: {e}")
            return []