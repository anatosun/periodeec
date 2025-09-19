"""
Consolidated Spotify music service importer.

This module implements the complete Spotify service importer with all functionality
previously split between SpotifyHandler and SpotifyImporter merged into a single,
unified implementation.
"""

import os
import json
import time
import random
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, parse_qs

import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException

from periodeec.importers.base_importer import MusicServiceImporter, AuthenticationError, ImporterError, RateLimitError
from periodeec.schema import User, Track, UserPreferences, UserStats
from periodeec.playlist import Playlist

logger = logging.getLogger(__name__)


class SpotifyRateLimiter:
    """Rate limiter for Spotify API requests."""

    def __init__(self, requests_per_minute: int = 100):
        self.requests_per_minute = requests_per_minute
        self.min_interval = 60.0 / requests_per_minute
        self.last_request_time = 0
        self.request_count = 0
        self.window_start = time.time()

    def wait_if_needed(self):
        """Wait if necessary to respect rate limits."""
        current_time = time.time()

        # Reset window if needed
        if current_time - self.window_start >= 60:
            self.window_start = current_time
            self.request_count = 0

        # Check if we need to wait
        if self.request_count >= self.requests_per_minute:
            wait_time = 60 - (current_time - self.window_start)
            if wait_time > 0:
                logger.info(f"Rate limit reached, waiting {wait_time:.1f}s")
                time.sleep(wait_time)
                self.window_start = time.time()
                self.request_count = 0

        # Ensure minimum interval between requests
        time_since_last = current_time - self.last_request_time
        if time_since_last < self.min_interval:
            time.sleep(self.min_interval - time_since_last)

        self.last_request_time = time.time()
        self.request_count += 1


class SpotifyCache:
    """Simple file-based cache for Spotify API responses."""

    def __init__(self, cache_dir: str = ".cache", ttl_hours: int = 24):
        self.cache_dir = cache_dir
        self.ttl_seconds = ttl_hours * 3600
        os.makedirs(cache_dir, exist_ok=True)

    def _cache_path(self, key: str) -> str:
        """Get cache file path for a key."""
        safe_key = "".join(c if c.isalnum() or c in '-_' else '_' for c in key)
        return os.path.join(self.cache_dir, f"{safe_key}.json")

    def get(self, key: str) -> Optional[Any]:
        """Get cached value if it exists and is not expired."""
        cache_file = self._cache_path(key)

        if not os.path.exists(cache_file):
            return None

        try:
            with open(cache_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Check if expired
            if time.time() - data['timestamp'] > self.ttl_seconds:
                os.remove(cache_file)
                return None

            return data['value']
        except Exception:
            # Remove corrupted cache file
            try:
                os.remove(cache_file)
            except Exception:
                pass
            return None

    def set(self, key: str, value: Any):
        """Cache a value."""
        cache_file = self._cache_path(key)

        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump({
                    'timestamp': time.time(),
                    'value': value
                }, f, default=str)
        except Exception as e:
            logger.debug(f"Failed to cache value: {e}")


class SpotifyImporter(MusicServiceImporter):
    """
    Complete Spotify service importer implementation.

    Combines all Spotify functionality into a single importer that conforms
    to the MusicServiceImporter interface while maintaining all existing features.
    """

    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the Spotify importer.

        Args:
            config: Spotify configuration dictionary
        """
        super().__init__("spotify", config)

        # Spotify-specific configuration
        self.client_id = config.get('client_id', '')
        self.client_secret = config.get('client_secret', '')
        self.anonymous = config.get('anonymous', False)
        self.cache_enabled = config.get('cache_enabled', True)
        self.cache_ttl_hours = config.get('cache_ttl_hours', 24)
        self.retry_attempts = config.get('retry_attempts', 3)
        self.request_timeout = config.get('request_timeout', 30)
        self.include_collaborative = config.get('include_collaborative', True)
        self.include_followed = config.get('include_followed', False)

        # Initialize components
        self.spotify_rate_limiter = SpotifyRateLimiter(self.rate_limit_rpm)
        self.cache = SpotifyCache(
            cache_dir=".cache/spotify",
            ttl_hours=self.cache_ttl_hours
        ) if self.cache_enabled else None

        # Spotify client (initialized during authentication)
        self.sp: Optional[spotipy.Spotify] = None

        # Statistics
        self.stats = {
            'requests_made': 0,
            'cache_hits': 0,
            'rate_limit_waits': 0,
            'errors': 0,
            'playlists_fetched': 0,
            'tracks_fetched': 0
        }

        self.logger.info("Spotify importer initialized")

    def _initialize_spotify_client(self) -> spotipy.Spotify:
        """Initialize the Spotify client."""
        try:
            if self.anonymous:
                # Anonymous mode (if spotipy_anon is available)
                try:
                    import spotipy_anon
                    return spotipy_anon.Spotify()
                except ImportError:
                    raise ImporterError("spotipy_anon not available for anonymous mode")
            else:
                # Client credentials flow
                if not self.client_id or not self.client_secret:
                    raise ImporterError("Spotify client_id and client_secret are required")

                auth_manager = SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
                return spotipy.Spotify(
                    auth_manager=auth_manager,
                    requests_timeout=self.request_timeout,
                    retries=self.retry_attempts
                )

        except Exception as e:
            raise ImporterError(f"Failed to initialize Spotify client: {e}")

    def _make_request(self, func, *args, use_cache: bool = True, cache_key: str = None, **kwargs):
        """Make a Spotify API request with caching and rate limiting."""
        # Check cache first
        if use_cache and self.cache and cache_key:
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                self.stats['cache_hits'] += 1
                return cached_result

        # Apply rate limiting
        self.spotify_rate_limiter.wait_if_needed()

        try:
            result = func(*args, **kwargs)
            self.stats['requests_made'] += 1

            # Cache the result
            if use_cache and self.cache and cache_key:
                self.cache.set(cache_key, result)

            return result

        except SpotifyException as e:
            self.stats['errors'] += 1
            if e.http_status == 429:  # Rate limited
                retry_after = int(e.headers.get('Retry-After', 60))
                self.logger.warning(f"Spotify rate limited, waiting {retry_after}s")
                time.sleep(retry_after)
                return self._make_request(func, *args, use_cache=use_cache, cache_key=cache_key, **kwargs)
            else:
                raise ImporterError(f"Spotify API error: {e}")
        except Exception as e:
            self.stats['errors'] += 1
            raise ImporterError(f"Spotify request failed: {e}")

    async def authenticate(self) -> bool:
        """Authenticate with Spotify."""
        try:
            self.sp = self._initialize_spotify_client()

            # Test the connection
            test_result = self._make_request(
                self.sp.search,
                q="test",
                type="track",
                limit=1,
                cache_key="auth_test"
            )

            if test_result:
                self._authenticated = True
                self.logger.info("Spotify authentication successful")
                return True
            else:
                raise AuthenticationError("Spotify authentication test failed")

        except Exception as e:
            self.logger.error(f"Spotify authentication failed: {e}")
            self._authenticated = False
            raise AuthenticationError(f"Spotify authentication error: {e}")

    async def validate_connection(self) -> bool:
        """Validate the Spotify connection."""
        if not self.sp:
            return False

        try:
            self._make_request(
                self.sp.search,
                q="test",
                type="track",
                limit=1,
                cache_key="connection_test"
            )
            return True
        except Exception as e:
            self.logger.error(f"Spotify connection validation failed: {e}")
            return False

    async def get_user_info(self, user_id: str) -> User:
        """Get Spotify user information."""
        try:
            self._rate_limit_wait()

            # Get user profile
            cache_key = f"user_{user_id}"
            user_data = self._make_request(
                self.sp.user,
                user_id,
                cache_key=cache_key
            )

            # Get user's playlists count for stats
            playlists_data = self._make_request(
                self.sp.user_playlists,
                user_id,
                limit=1,
                cache_key=f"user_playlists_count_{user_id}"
            )

            # Create User object
            user = User(
                id=user_id,
                name=user_data.get('display_name', user_id),
                spotify_username=user_id,
                plex_usernames=[],
                preferences=UserPreferences(),
                stats=UserStats(
                    total_playlists=playlists_data.get('total', 0),
                    last_sync=datetime.now()
                )
            )

            # Add Spotify-specific data
            user.spotify_uri = user_data.get('uri', '')
            user.external_urls = user_data.get('external_urls', {})

            return user

        except Exception as e:
            self.logger.error(f"Failed to get Spotify user info for {user_id}: {e}")
            raise ImporterError(f"Cannot retrieve Spotify user {user_id}: {e}")

    async def get_user_playlists(self, user_id: str, **kwargs) -> List[Playlist]:
        """Get all playlists for a Spotify user."""
        try:
            self._rate_limit_wait()

            include_collaborative = kwargs.get('include_collaborative', self.include_collaborative)
            include_followed = kwargs.get('include_followed', self.include_followed)
            limit = kwargs.get('limit', None)

            playlists = []
            offset = 0
            batch_size = 50

            while True:
                # Get batch of playlists
                cache_key = f"user_playlists_{user_id}_{offset}_{batch_size}"
                playlists_data = self._make_request(
                    self.sp.user_playlists,
                    user_id,
                    limit=batch_size,
                    offset=offset,
                    cache_key=cache_key
                )

                if not playlists_data or not playlists_data.get('items'):
                    break

                # Process playlists
                for item in playlists_data['items']:
                    # Skip if None (Spotify sometimes returns None items)
                    if not item:
                        continue

                    # Apply filters
                    if not include_collaborative and item.get('collaborative', False):
                        continue

                    if not include_followed and item.get('owner', {}).get('id') != user_id:
                        continue

                    # Create Playlist object
                    playlist = self._create_playlist_from_item(item, user_id)
                    if playlist:
                        if self.add_source_to_titles:
                            playlist.title = self.add_source_tag_to_title(playlist.title)
                        playlists.append(playlist)

                    # Check limit
                    if limit and len(playlists) >= limit:
                        break

                # Check for more pages
                if not playlists_data.get('next') or (limit and len(playlists) >= limit):
                    break

                offset += batch_size

            self.stats['playlists_fetched'] += len(playlists)
            self.logger.info(f"Retrieved {len(playlists)} playlists for Spotify user {user_id}")
            return playlists

        except Exception as e:
            self.logger.error(f"Failed to get Spotify playlists for {user_id}: {e}")
            raise ImporterError(f"Cannot retrieve Spotify playlists for {user_id}: {e}")

    def _create_playlist_from_item(self, item: Dict[str, Any], user_id: str) -> Optional[Playlist]:
        """Create a Playlist object from a Spotify playlist item."""
        try:
            # Extract basic info
            playlist_id = item.get('id', '')
            name = item.get('name', 'Unknown Playlist')
            description = item.get('description', '')
            track_count = item.get('tracks', {}).get('total', 0)

            # Get images
            images = item.get('images', [])
            poster_url = images[0]['url'] if images else ''

            # Create playlist object
            playlist = Playlist(
                title=name,
                tracks=[],  # Tracks loaded separately
                id=playlist_id,
                path="",
                number_of_tracks=track_count,
                description=description,
                poster=poster_url,
                url=item.get('external_urls', {}).get('spotify', ''),
                snapshot_id=item.get('snapshot_id', '')
            )

            return playlist

        except Exception as e:
            self.logger.debug(f"Error creating playlist from item: {e}")
            return None

    async def get_playlist_tracks(self, playlist_url: str, limit: int = None) -> List[Track]:
        """Get all tracks from a Spotify playlist."""
        try:
            self._rate_limit_wait()

            # Extract playlist ID from URL
            playlist_id = self._extract_playlist_id(playlist_url)
            if not playlist_id:
                raise ImporterError(f"Invalid Spotify playlist URL: {playlist_url}")

            tracks = []
            offset = 0
            batch_size = 100

            while True:
                # Get batch of tracks
                cache_key = f"playlist_tracks_{playlist_id}_{offset}_{batch_size}"
                tracks_data = self._make_request(
                    self.sp.playlist_tracks,
                    playlist_id,
                    limit=batch_size,
                    offset=offset,
                    cache_key=cache_key
                )

                if not tracks_data or not tracks_data.get('items'):
                    break

                # Process tracks
                for item in tracks_data['items']:
                    if not item or not item.get('track'):
                        continue

                    track = self._create_track_from_item(item['track'])
                    if track:
                        tracks.append(track)

                    # Check limit
                    if limit and len(tracks) >= limit:
                        break

                # Check for more pages
                if not tracks_data.get('next') or (limit and len(tracks) >= limit):
                    break

                offset += batch_size

            self.stats['tracks_fetched'] += len(tracks)
            self.logger.info(f"Retrieved {len(tracks)} tracks from Spotify playlist {playlist_url}")
            return tracks

        except Exception as e:
            self.logger.error(f"Failed to get tracks from Spotify playlist {playlist_url}: {e}")
            raise ImporterError(f"Cannot retrieve tracks from Spotify playlist: {e}")

    def _extract_playlist_id(self, url: str) -> Optional[str]:
        """Extract playlist ID from Spotify URL."""
        try:
            if 'open.spotify.com' in url:
                # Web URL format
                parsed = urlparse(url)
                path_parts = parsed.path.strip('/').split('/')
                if 'playlist' in path_parts:
                    idx = path_parts.index('playlist')
                    if idx + 1 < len(path_parts):
                        return path_parts[idx + 1].split('?')[0]
            elif 'spotify:playlist:' in url:
                # URI format
                return url.split('spotify:playlist:')[1]
            else:
                # Assume it's just the ID
                return url.split('?')[0].split('/')[-1]

        except Exception as e:
            self.logger.debug(f"Error extracting playlist ID from {url}: {e}")

        return None

    def _create_track_from_item(self, track_item: Dict[str, Any]) -> Optional[Track]:
        """Create a Track object from a Spotify track item."""
        try:
            # Basic track info
            name = track_item.get('name', 'Unknown Track')
            track_id = track_item.get('id', '')
            duration_ms = track_item.get('duration_ms', 0)
            track_number = track_item.get('track_number', 0)
            disc_number = track_item.get('disc_number', 1)
            explicit = track_item.get('explicit', False)

            # Artist information
            artists = track_item.get('artists', [])
            primary_artist = artists[0]['name'] if artists else 'Unknown Artist'
            all_artists = [artist['name'] for artist in artists]

            # Album information
            album_data = track_item.get('album', {})
            album_name = album_data.get('name', '')
            album_artist = album_data.get('artists', [{}])[0].get('name', primary_artist)
            release_year = 0

            # Parse release date
            release_date = album_data.get('release_date', '')
            if release_date:
                try:
                    release_year = int(release_date.split('-')[0])
                except (ValueError, IndexError):
                    pass

            # External IDs
            external_ids = track_item.get('external_ids', {})
            isrc = external_ids.get('isrc', '')

            # URLs
            spotify_url = track_item.get('external_urls', {}).get('spotify', '')
            album_url = album_data.get('external_urls', {}).get('spotify', '')

            # Create Track object
            track = Track(
                title=name,
                artist=primary_artist,
                album=album_name,
                isrc=isrc,
                album_url=album_url,
                release_year=release_year,
                path="",
                all_artists=all_artists,
                primary_artist=primary_artist,
                albumartist=album_artist,
                track_number=track_number,
                disc_number=disc_number,
                duration_ms=duration_ms,
                spotify_id=track_id,
                import_source="spotify"
            )

            # Add additional Spotify-specific data
            if explicit:
                track.add_tag("explicit")

            return track

        except Exception as e:
            self.logger.debug(f"Error creating track from item: {e}")
            return None

    async def search_tracks(self, query: str, limit: int = 20) -> List[Track]:
        """Search for tracks on Spotify."""
        try:
            self._rate_limit_wait()

            cache_key = f"search_tracks_{query}_{limit}"
            search_data = self._make_request(
                self.sp.search,
                q=query,
                type="track",
                limit=limit,
                cache_key=cache_key
            )

            tracks = []
            if search_data and 'tracks' in search_data:
                for item in search_data['tracks']['items']:
                    track = self._create_track_from_item(item)
                    if track:
                        tracks.append(track)

            self.logger.info(f"Spotify search for '{query}' returned {len(tracks)} results")
            return tracks

        except Exception as e:
            self.logger.error(f"Spotify track search failed for query '{query}': {e}")
            raise ImporterError(f"Spotify track search failed: {e}")

    def get_service_stats(self) -> Dict[str, Any]:
        """Get Spotify service statistics."""
        base_stats = super().get_service_stats()
        return {
            **base_stats,
            'spotify_stats': self.stats
        }

    def print_stats(self):
        """Print formatted Spotify statistics."""
        print(f"\n=== Spotify Statistics ===")
        print(f"Requests made: {self.stats['requests_made']}")
        print(f"Cache hits: {self.stats['cache_hits']}")
        print(f"Rate limit waits: {self.stats['rate_limit_waits']}")
        print(f"Errors: {self.stats['errors']}")
        print(f"Playlists fetched: {self.stats['playlists_fetched']}")
        print(f"Tracks fetched: {self.stats['tracks_fetched']}")

        if self.stats['requests_made'] > 0:
            cache_rate = (self.stats['cache_hits'] /
                         (self.stats['cache_hits'] + self.stats['requests_made'])) * 100
            print(f"Cache hit rate: {cache_rate:.1f}%")

        print("=" * 26)