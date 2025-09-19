"""
Last.FM music service importer.

This module implements the Last.FM music service importer for accessing
user listening history, top tracks, and loved tracks.
"""

import logging
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
    import pylast
except ImportError:
    pylast = None
    logger.warning("pylast library not available. LastFM importer will not function.")


class LastFMImporter(MusicServiceImporter):
    """
    Last.FM service importer implementation.

    Provides access to Last.FM user data including listening history,
    top tracks, loved tracks, and user information.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Last.FM importer.

        Args:
            config: Last.FM configuration dictionary containing:
                - api_key: Last.FM API key
                - api_secret: Last.FM API secret
                - rate_limit_rpm: Requests per minute limit (default: 200)
                - add_source_to_titles: Whether to add "(Last.FM)" to playlist titles
                - source_tag_format: Format string for source tag
        """
        super().__init__("lastfm", config)

        if pylast is None:
            raise ImporterError("pylast library is required for Last.FM support. Install with: pip install pylast")

        # Initialize Last.FM network
        try:
            self.network = pylast.LastFMNetwork(
                api_key=config['api_key'],
                api_secret=config['api_secret']
            )
            self.logger.info("Last.FM importer initialized successfully")
        except Exception as e:
            self.logger.error(f"Failed to initialize Last.FM network: {e}")
            raise ImporterError(f"Last.FM initialization failed: {e}")

        # Last.FM specific settings
        self.default_limit = config.get('default_limit', 50)
        self.max_retries = config.get('max_retries', 3)

    async def authenticate(self) -> bool:
        """
        Authenticate with Last.FM.

        For Last.FM API key access, we just test the connection.

        Returns:
            True if authentication successful

        Raises:
            AuthenticationError: If authentication fails
        """
        try:
            # Test the connection by getting Last.FM info
            self._rate_limit_wait()
            test_user = self.network.get_user("lastfm")  # Official Last.FM account
            test_user.get_name()  # This will fail if API key is invalid

            self._authenticated = True
            self.logger.info("Last.FM authentication successful")
            return True

        except Exception as e:
            self.logger.error(f"Last.FM authentication failed: {e}")
            self._authenticated = False
            raise AuthenticationError(f"Last.FM authentication error: {e}")

    async def validate_connection(self) -> bool:
        """
        Validate the connection to Last.FM.

        Returns:
            True if connection is valid
        """
        try:
            self._rate_limit_wait()
            test_user = self.network.get_user("lastfm")
            test_user.get_name()
            return True
        except Exception as e:
            self.logger.error(f"Last.FM connection validation failed: {e}")
            return False

    async def get_user_info(self, user_id: str) -> User:
        """
        Get Last.FM user information.

        Args:
            user_id: Last.FM username

        Returns:
            User object with Last.FM information

        Raises:
            ImporterError: If user cannot be retrieved
        """
        try:
            self._rate_limit_wait()
            lastfm_user = self.network.get_user(user_id)

            # Get user info
            name = lastfm_user.get_name()
            real_name = getattr(lastfm_user, 'get_real_name', lambda: '')() or name
            playcount = getattr(lastfm_user, 'get_playcount', lambda: 0)()

            # Create User object
            user = User(
                id=user_id,
                name=real_name,
                spotify_username="",  # Last.FM user, no Spotify connection
                plex_usernames=[],
                preferences=UserPreferences(),
                stats=UserStats(
                    total_tracks=playcount,
                    last_sync=datetime.now(timezone.utc)
                )
            )

            # Add Last.FM specific data
            user.lastfm_username = user_id
            user.external_urls = getattr(user, 'external_urls', {})
            user.external_urls['lastfm'] = f"https://www.last.fm/user/{user_id}"

            self.logger.info(f"Retrieved Last.FM user info for {user_id}")
            return user

        except Exception as e:
            self.logger.error(f"Failed to get Last.FM user info for {user_id}: {e}")
            raise ImporterError(f"Cannot retrieve Last.FM user {user_id}: {e}")

    async def get_user_playlists(self, user_id: str, **kwargs) -> List[Playlist]:
        """
        Get user's "playlists" from Last.FM (top tracks, loved tracks, etc.).

        Args:
            user_id: Last.FM username
            **kwargs: Additional options:
                - include_top_tracks: Include top tracks playlists (default: True)
                - include_loved_tracks: Include loved tracks playlist (default: True)
                - top_tracks_periods: List of periods for top tracks

        Returns:
            List of Playlist objects representing Last.FM data

        Raises:
            ImporterError: If data cannot be retrieved
        """
        try:
            playlists = []

            include_top_tracks = kwargs.get('include_top_tracks', True)
            include_loved_tracks = kwargs.get('include_loved_tracks', True)
            top_tracks_periods = kwargs.get('top_tracks_periods', ['overall', '12month', '6month', '3month'])

            # Get top tracks for different periods
            if include_top_tracks:
                for period in top_tracks_periods:
                    try:
                        top_tracks = await self.get_user_top_tracks(user_id, time_range=period, limit=50)
                        if top_tracks:
                            period_name = self._format_period_name(period)
                            title = f"{user_id}'s Top Tracks - {period_name}"
                            if self.add_source_to_titles:
                                title = self.add_source_tag_to_title(title)

                            playlist = Playlist(
                                title=title,
                                tracks=top_tracks,
                                id=f"lastfm_top_{user_id}_{period}",
                                path="",
                                number_of_tracks=len(top_tracks),
                                description=f"Top tracks from Last.FM for {period_name}",
                                url=f"https://www.last.fm/user/{user_id}/charts"
                            )
                            playlists.append(playlist)
                    except Exception as e:
                        self.logger.warning(f"Failed to get top tracks for period {period}: {e}")

            # Get loved tracks
            if include_loved_tracks:
                try:
                    loved_tracks = await self.get_user_saved_tracks(user_id, limit=500)
                    if loved_tracks:
                        title = f"{user_id}'s Loved Tracks"
                        if self.add_source_to_titles:
                            title = self.add_source_tag_to_title(title)

                        playlist = Playlist(
                            title=title,
                            tracks=loved_tracks,
                            id=f"lastfm_loved_{user_id}",
                            path="",
                            number_of_tracks=len(loved_tracks),
                            description="Loved tracks from Last.FM",
                            url=f"https://www.last.fm/user/{user_id}/loved"
                        )
                        playlists.append(playlist)
                except Exception as e:
                    self.logger.warning(f"Failed to get loved tracks: {e}")

            self.logger.info(f"Retrieved {len(playlists)} playlists for Last.FM user {user_id}")
            return playlists

        except Exception as e:
            self.logger.error(f"Failed to get Last.FM playlists for {user_id}: {e}")
            raise ImporterError(f"Cannot retrieve Last.FM playlists for {user_id}: {e}")

    async def get_playlist_tracks(self, playlist_url: str, limit: int = None) -> List[Track]:
        """
        Get tracks from a Last.FM "playlist" (not directly supported).

        Args:
            playlist_url: Last.FM playlist identifier
            limit: Maximum number of tracks

        Returns:
            Empty list (Last.FM doesn't have traditional playlists)
        """
        self.logger.info("Last.FM doesn't support traditional playlists")
        return []

    async def search_tracks(self, query: str, limit: int = 20) -> List[Track]:
        """
        Search for tracks on Last.FM.

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

            # Search for tracks
            search_results = self.network.search_for_track(query)
            tracks = []

            for i, result in enumerate(search_results):
                if i >= limit:
                    break

                try:
                    # Get track information
                    artist_name = result.get_artist().get_name()
                    track_title = result.get_name()

                    # Create Track object
                    track = Track(
                        title=track_title,
                        artist=artist_name,
                        album="",  # Last.FM search doesn't always provide album
                        isrc="",
                        album_url="",
                        release_year=0,
                        path="",
                        all_artists=[artist_name],
                        duration_ms=0,
                        lastfm_url=result.get_url()
                    )
                    tracks.append(track)

                except Exception as e:
                    self.logger.debug(f"Error processing search result: {e}")
                    continue

            self.logger.info(f"Last.FM search for '{query}' returned {len(tracks)} results")
            return tracks

        except Exception as e:
            self.logger.error(f"Last.FM track search failed for query '{query}': {e}")
            raise ImporterError(f"Last.FM track search failed: {e}")

    async def get_user_top_tracks(self, user_id: str, time_range: str = "overall",
                                 limit: int = 50) -> List[Track]:
        """
        Get user's top tracks from Last.FM.

        Args:
            user_id: Last.FM username
            time_range: Time period ("overall", "12month", "6month", "3month", "1month", "7day")
            limit: Maximum number of tracks

        Returns:
            List of top tracks
        """
        try:
            self._rate_limit_wait()
            lastfm_user = self.network.get_user(user_id)

            # Map time range to Last.FM period
            period_map = {
                "overall": pylast.PERIOD_OVERALL,
                "12month": pylast.PERIOD_12MONTHS,
                "6month": pylast.PERIOD_6MONTHS,
                "3month": pylast.PERIOD_3MONTHS,
                "1month": pylast.PERIOD_1MONTH,
                "7day": pylast.PERIOD_7DAYS
            }

            period = period_map.get(time_range, pylast.PERIOD_OVERALL)

            # Get top tracks
            top_tracks_data = lastfm_user.get_top_tracks(period=period, limit=limit)
            tracks = []

            for track_item in top_tracks_data:
                try:
                    track_obj = track_item.item
                    playcount = track_item.weight

                    artist_name = track_obj.get_artist().get_name()
                    track_title = track_obj.get_name()

                    # Try to get additional track info
                    album_name = ""
                    duration_ms = 0
                    try:
                        track_info = track_obj.get_correction()
                        if track_info:
                            album_obj = track_info.get_album()
                            if album_obj:
                                album_name = album_obj.get_name()
                    except:
                        pass

                    track = Track(
                        title=track_title,
                        artist=artist_name,
                        album=album_name,
                        isrc="",
                        album_url="",
                        release_year=0,
                        path="",
                        all_artists=[artist_name],
                        duration_ms=duration_ms,
                        lastfm_url=track_obj.get_url(),
                        play_count=playcount
                    )
                    tracks.append(track)

                except Exception as e:
                    self.logger.debug(f"Error processing top track: {e}")
                    continue

            self.logger.info(f"Retrieved {len(tracks)} top tracks for Last.FM user {user_id}")
            return tracks

        except Exception as e:
            self.logger.error(f"Failed to get Last.FM top tracks for {user_id}: {e}")
            return []

    async def get_user_listening_history(self, user_id: str, limit: int = 50,
                                       start_date: Optional[datetime] = None,
                                       end_date: Optional[datetime] = None) -> List[Track]:
        """
        Get user's recent listening history from Last.FM.

        Args:
            user_id: Last.FM username
            limit: Maximum number of tracks
            start_date: Start date for history
            end_date: End date for history

        Returns:
            List of recently played tracks
        """
        try:
            self._rate_limit_wait()
            lastfm_user = self.network.get_user(user_id)

            # Get recent tracks
            recent_tracks = lastfm_user.get_recent_tracks(limit=limit)
            tracks = []

            for track_item in recent_tracks:
                try:
                    track_obj = track_item.track
                    timestamp = track_item.timestamp

                    # Filter by date range if specified
                    if start_date and timestamp and timestamp < start_date.timestamp():
                        continue
                    if end_date and timestamp and timestamp > end_date.timestamp():
                        continue

                    artist_name = track_obj.get_artist().get_name()
                    track_title = track_obj.get_name()

                    track = Track(
                        title=track_title,
                        artist=artist_name,
                        album="",
                        isrc="",
                        album_url="",
                        release_year=0,
                        path="",
                        all_artists=[artist_name],
                        duration_ms=0,
                        lastfm_url=track_obj.get_url(),
                        last_played=datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None
                    )
                    tracks.append(track)

                except Exception as e:
                    self.logger.debug(f"Error processing recent track: {e}")
                    continue

            self.logger.info(f"Retrieved {len(tracks)} recent tracks for Last.FM user {user_id}")
            return tracks

        except Exception as e:
            self.logger.error(f"Failed to get Last.FM listening history for {user_id}: {e}")
            return []

    async def get_user_saved_tracks(self, user_id: str, limit: int = None) -> List[Track]:
        """
        Get user's loved tracks from Last.FM.

        Args:
            user_id: Last.FM username
            limit: Maximum number of tracks

        Returns:
            List of loved tracks
        """
        try:
            self._rate_limit_wait()
            lastfm_user = self.network.get_user(user_id)

            # Get loved tracks
            loved_tracks = lastfm_user.get_loved_tracks(limit=limit or 500)
            tracks = []

            for track_item in loved_tracks:
                try:
                    track_obj = track_item.track
                    timestamp = track_item.timestamp

                    artist_name = track_obj.get_artist().get_name()
                    track_title = track_obj.get_name()

                    track = Track(
                        title=track_title,
                        artist=artist_name,
                        album="",
                        isrc="",
                        album_url="",
                        release_year=0,
                        path="",
                        all_artists=[artist_name],
                        duration_ms=0,
                        lastfm_url=track_obj.get_url(),
                        loved_at=datetime.fromtimestamp(timestamp, tz=timezone.utc) if timestamp else None
                    )
                    track.add_tag("loved")
                    tracks.append(track)

                except Exception as e:
                    self.logger.debug(f"Error processing loved track: {e}")
                    continue

            self.logger.info(f"Retrieved {len(tracks)} loved tracks for Last.FM user {user_id}")
            return tracks

        except Exception as e:
            self.logger.error(f"Failed to get Last.FM loved tracks for {user_id}: {e}")
            return []

    def _format_period_name(self, period: str) -> str:
        """Format period name for display."""
        period_names = {
            "overall": "All Time",
            "12month": "Last 12 Months",
            "6month": "Last 6 Months",
            "3month": "Last 3 Months",
            "1month": "Last Month",
            "7day": "Last 7 Days"
        }
        return period_names.get(period, period.title())