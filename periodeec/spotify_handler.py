import logging
import random
import time
import json
import os
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from urllib.parse import urlparse, parse_qs
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from spotipy.exceptions import SpotifyException
from periodeec.playlist import Playlist
from periodeec.schema import Track, User

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
    """Cache for Spotify API responses."""
    
    def __init__(self, cache_dir: str = None, ttl_hours: int = 24):
        self.cache_dir = cache_dir or os.path.join(os.getcwd(), '.spotify_cache')
        self.ttl_seconds = ttl_hours * 3600
        os.makedirs(self.cache_dir, exist_ok=True)
    
    def _get_cache_path(self, key: str) -> str:
        """Get cache file path for a key."""
        return os.path.join(self.cache_dir, f"{key}.json")
    
    def get(self, key: str) -> Optional[Any]:
        """Get item from cache."""
        try:
            cache_path = self._get_cache_path(key)
            if not os.path.exists(cache_path):
                return None
            
            with open(cache_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Check if expired
            if time.time() - data['timestamp'] > self.ttl_seconds:
                os.remove(cache_path)
                return None
            
            return data['value']
        except Exception as e:
            logger.debug(f"Cache read error: {e}")
            return None
    
    def set(self, key: str, value: Any) -> None:
        """Set item in cache."""
        try:
            cache_path = self._get_cache_path(key)
            data = {
                'timestamp': time.time(),
                'value': value
            }
            
            with open(cache_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.debug(f"Cache write error: {e}")


class SpotifyHandler:
    """Spotify handler with caching, rate limiting, and better error handling."""
    
    def __init__(self, client_id: str = "", client_secret: str = "", 
                 path: str = "playlists", anonymous: bool = False,
                 cache_enabled: bool = True, cache_ttl_hours: int = 24,
                 rate_limit_rpm: int = 100, retry_attempts: int = 3,
                 request_timeout: int = 30):
        """
        Initialize the Spotify handler.
        
        Args:
            client_id: Spotify Client ID
            client_secret: Spotify Client Secret  
            path: Path to store playlist cache files
            anonymous: Use anonymous mode (requires spotipy_anon)
            cache_enabled: Enable response caching
            cache_ttl_hours: Cache TTL in hours
            rate_limit_rpm: Rate limit in requests per minute
            retry_attempts: Number of retry attempts for failed requests
            request_timeout: Request timeout in seconds
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.path = os.path.abspath(path)
        self.anonymous = anonymous
        self.retry_attempts = retry_attempts
        self.request_timeout = request_timeout
        
        # Create directories
        os.makedirs(self.path, exist_ok=True)
        
        # Initialize components
        self.rate_limiter = SpotifyRateLimiter(rate_limit_rpm)
        self.cache = SpotifyCache(
            cache_dir=os.path.join(self.path, '.cache'),
            ttl_hours=cache_ttl_hours
        ) if cache_enabled else None
        
        # Initialize Spotify client
        self.sp = self._initialize_spotify_client()
        
        # Statistics
        self.stats = {
            'requests_made': 0,
            'cache_hits': 0,
            'rate_limit_waits': 0,
            'errors': 0,
            'session_start': time.time()
        }
        
        logger.info(f"Spotify handler initialized (anonymous={anonymous}, cache={cache_enabled})")
    
    def _initialize_spotify_client(self):
        """Initialize the Spotify client."""
        if self.anonymous:
            try:
                from spotipy_anon import SpotifyAnon
                auth_manager = SpotifyAnon()
                logger.info("Using anonymous Spotify mode")
            except ImportError:
                logger.error("spotipy_anon not available, falling back to client credentials")
                if not self.client_id or not self.client_secret:
                    raise ValueError("Client credentials required when spotipy_anon is not available")
                auth_manager = SpotifyClientCredentials(
                    client_id=self.client_id,
                    client_secret=self.client_secret
                )
        else:
            if not self.client_id or not self.client_secret:
                raise ValueError("Valid Spotify Client ID and Secret must be provided")
            auth_manager = SpotifyClientCredentials(
                client_id=self.client_id,
                client_secret=self.client_secret
            )
        
        return spotipy.Spotify(
            auth_manager=auth_manager,
            requests_timeout=self.request_timeout
        )
    
    def _make_request(self, request_func, *args, **kwargs):
        """Make a Spotify API request with rate limiting and retries."""
        self.rate_limiter.wait_if_needed()
        
        for attempt in range(self.retry_attempts):
            try:
                result = request_func(*args, **kwargs)
                self.stats['requests_made'] += 1
                return result
            except SpotifyException as e:
                if e.http_status == 429:  # Rate limited
                    retry_after = int(e.headers.get('Retry-After', 60))
                    logger.warning(f"Rate limited, waiting {retry_after}s")
                    time.sleep(retry_after)
                    self.stats['rate_limit_waits'] += 1
                    continue
                elif e.http_status in [500, 502, 503, 504] and attempt < self.retry_attempts - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Server error {e.http_status}, retrying in {wait_time}s")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Spotify API error: {e}")
                    self.stats['errors'] += 1
                    raise
            except Exception as e:
                if attempt < self.retry_attempts - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Request failed, retrying in {wait_time}s: {e}")
                    time.sleep(wait_time)
                    continue
                else:
                    logger.error(f"Request failed after {self.retry_attempts} attempts: {e}")
                    self.stats['errors'] += 1
                    raise
        
        return None
    
    def _cached_request(self, cache_key: str, request_func, *args, **kwargs):
        """Make a request with caching."""
        if self.cache:
            cached_result = self.cache.get(cache_key)
            if cached_result is not None:
                self.stats['cache_hits'] += 1
                logger.debug(f"Cache hit for key: {cache_key}")
                return cached_result
        
        result = self._make_request(request_func, *args, **kwargs)
        
        if self.cache and result is not None:
            self.cache.set(cache_key, result)
        
        return result
    
    def parse_spotify_url(self, url: str) -> Dict[str, str]:
        """Parse a Spotify URL to extract type and ID."""
        try:
            parsed = urlparse(url)
            
            if 'spotify.com' in parsed.netloc:
                # Web URL format: https://open.spotify.com/playlist/37i9dQZF1DX0XUsuxWHRQd
                path_parts = parsed.path.strip('/').split('/')
                if len(path_parts) >= 2:
                    return {
                        'type': path_parts[0],
                        'id': path_parts[1].split('?')[0]
                    }
            elif url.startswith('spotify:'):
                # URI format: spotify:playlist:37i9dQZF1DX0XUsuxWHRQd
                parts = url.split(':')
                if len(parts) >= 3:
                    return {
                        'type': parts[1],
                        'id': parts[2]
                    }
            
            # Direct ID (assume playlist)
            if len(url) == 22 and url.isalnum():
                return {
                    'type': 'playlist',
                    'id': url
                }
            
            raise ValueError(f"Invalid Spotify URL format: {url}")
            
        except Exception as e:
            logger.error(f"Failed to parse Spotify URL '{url}': {e}")
            raise
    
    def user(self, username: str) -> User:
        """Get Spotify user information with caching."""
        if not username:
            return User(id="unknown")
        
        cache_key = f"user_{username}"
        
        def fetch_user():
            return self.sp.user(username)
        
        try:
            user_data = self._cached_request(cache_key, fetch_user)
            if not user_data:
                logger.warning(f"User '{username}' not found")
                return User(id=username)
            
            return User(
                id=username,
                name=user_data.get("display_name", username),
                url=user_data.get("external_urls", {}).get("spotify", ""),
                uri=user_data.get("uri", "")
            )
        except Exception as e:
            logger.error(f"Error fetching user '{username}': {e}")
            return User(id=username)
    
    def get_playlist_info(self, url: str) -> Dict[str, Any]:
        """Get basic playlist information."""
        try:
            url_info = self.parse_spotify_url(url)
            playlist_id = url_info['id']
            
            cache_key = f"playlist_info_{playlist_id}"
            
            def fetch_playlist_info():
                return self.sp.playlist(playlist_id, fields="id,name,description,images,snapshot_id,tracks.total,external_urls,owner")
            
            return self._cached_request(cache_key, fetch_playlist_info) or {}
            
        except Exception as e:
            logger.error(f"Error fetching playlist info for '{url}': {e}")
            return {}
    
    def tracks(self, url: str, number_of_tracks: int) -> List[Track]:
        """
        Fetch all tracks from a Spotify playlist with better error handling and progress tracking.
        """
        try:
            url_info = self.parse_spotify_url(url)
            playlist_id = url_info['id']
            
            logger.info(f"Fetching {number_of_tracks} tracks from playlist {playlist_id}")
            
            tracks = []
            limit = 100
            offset = 0
            fields = "items(track(name,external_ids.isrc,artists(name),album(name,release_date,external_urls(spotify)),duration_ms))"
            
            # Progress tracking
            last_progress_report = 0
            progress_interval = max(1, number_of_tracks // 10)  # Report every 10%

            # Safety measures to prevent infinite loops
            max_requests = max(100, (number_of_tracks // limit) + 10)  # Allow extra requests for safety
            requests_made = 0

            while offset < number_of_tracks and requests_made < max_requests:
                try:
                    requests_made += 1
                    cache_key = f"playlist_tracks_{playlist_id}_{offset}_{limit}"

                    def fetch_tracks():
                        return self.sp.playlist_items(
                            playlist_id,
                            limit=limit,
                            offset=offset,
                            fields=fields
                        )

                    playlist_tracks = self._cached_request(cache_key, fetch_tracks)
                    
                    if not playlist_tracks or not playlist_tracks.get("items"):
                        logger.warning(f"No tracks returned at offset {offset}")
                        break
                    
                    batch_tracks = self.extract_tracks(playlist_tracks["items"])
                    tracks.extend(batch_tracks)

                    # Correctly increment offset by actual API response items
                    returned_items = len(playlist_tracks["items"])
                    offset += returned_items

                    # Safety check: if no items were returned but we haven't reached the end, break to prevent infinite loop
                    if returned_items == 0:
                        logger.warning(f"API returned 0 items at offset {offset}, ending track fetch")
                        break

                    # Progress reporting
                    if offset - last_progress_report >= progress_interval:
                        progress = (offset / number_of_tracks) * 100
                        logger.info(f"Progress: {offset}/{number_of_tracks} tracks ({progress:.1f}%)")
                        last_progress_report = offset
                    
                    # Smart delay to avoid rate limiting
                    if offset < number_of_tracks:
                        delay = random.uniform(0.5, 1.5)
                        time.sleep(delay)
                
                except Exception as e:
                    logger.error(f"Error fetching tracks at offset {offset}: {e}")
                    break

            # Check if we hit the safety limit
            if requests_made >= max_requests:
                logger.warning(f"Hit safety limit of {max_requests} requests, stopping track fetch")

            logger.info(f"Successfully fetched {len(tracks)} tracks in {requests_made} requests")
            return tracks
            
        except Exception as e:
            logger.error(f"Error fetching tracks from '{url}': {e}")
            return []
    
    def extract_tracks(self, items: List[Dict]) -> List[Track]:
        """Track extraction with better error handling."""
        parsed_tracks = []
        local_tracks_count = 0
        skipped_count = 0
        
        for i, item in enumerate(items):
            try:
                track_info = item.get("track")
                if not track_info:
                    logger.debug(f"No track info in item {i}")
                    skipped_count += 1
                    continue
                
                # Get basic track info first
                title = track_info.get("name", "Unknown Title")
                track_id = track_info.get("id")

                # Check for local files or unavailable tracks - but still try to extract info
                if not track_id:
                    logger.info(f"Found local/unavailable track: '{title}' - will attempt to download from other sources")
                    local_tracks_count += 1
                
                # Extract ISRC (may not be available for local tracks)
                external_ids = track_info.get("external_ids") or {}
                isrc = external_ids.get("isrc", "")

                if not isrc and track_id:
                    logger.debug(f"No ISRC for track: '{title}'")
                elif not isrc and not track_id:
                    logger.debug(f"Local track without ISRC: '{title}' - will rely on artist/title matching")
                
                # Extract album information
                album_info = track_info.get("album") or {}
                album_name = album_info.get("name", "Unknown Album")
                album_url = (album_info.get("external_urls") or {}).get("spotify", "")
                
                # Parse release date
                release_date_str = album_info.get("release_date", "")
                release_year = self._parse_release_year(release_date_str)
                
                # Extract artist information
                artists = track_info.get("artists") or []
                if not artists:
                    logger.warning(f"No artist info for track: '{title}' - this may be a local file with incomplete metadata")
                    # For local tracks, we might not have artist info, but we can still try
                    # to create a track with minimal info for download attempts
                    primary_artist = "Unknown Artist"
                    all_artists = ["Unknown Artist"]
                    artist_name = "Unknown Artist"
                else:
                    # Use primary artist
                    primary_artist = artists[0].get("name", "Unknown Artist")

                    # Additional artists for collaborations
                    all_artists = [artist.get("name", "") for artist in artists]
                    artist_name = ", ".join(filter(None, all_artists))
                duration_ms = track_info.get("duration_ms", 0)
                
                track = Track(
                    title=title,
                    isrc=isrc,
                    album=album_name,
                    album_url=album_url,
                    release_year=release_year,
                    artist=artist_name,
                    path=""
                )
                
                # Add additional metadata
                track.duration_ms = duration_ms
                track.all_artists = all_artists
                track.primary_artist = primary_artist
                track.spotify_id = track_info.get("id", "")

                # Log successful track extraction
                if not track_id:
                    logger.info(f"Extracted local track: '{artist_name} - {title}' (Album: {album_name})")
                else:
                    logger.debug(f"Extracted Spotify track: '{artist_name} - {title}' (ID: {track_id})")

                parsed_tracks.append(track)
                
            except Exception as e:
                logger.warning(f"Error parsing track at position {i}: {e}")
                skipped_count += 1
                continue

        # Log extraction summary
        total_items = len(items)
        if total_items > 0:
            logger.info(f"Track extraction complete: {len(parsed_tracks)} extracted, {local_tracks_count} local/unavailable, {skipped_count} skipped from {total_items} items")

        return parsed_tracks
    
    def _parse_release_year(self, release_date_str: str) -> int:
        """Parse release year from various date formats."""
        if not release_date_str:
            return 1970
        
        try:
            # Try full date format first
            if len(release_date_str) >= 10:
                release_date = datetime.strptime(release_date_str[:10], "%Y-%m-%d")
                return release_date.year
            # Try year-month format
            elif len(release_date_str) >= 7:
                return int(release_date_str[:4])
            # Try year only
            elif len(release_date_str) >= 4:
                return int(release_date_str[:4])
        except (ValueError, TypeError):
            logger.debug(f"Could not parse release date: {release_date_str}")
        
        return 1970
    
    def playlists(self, username: str, include_collaborative: bool = True,
                  include_followed: bool = False) -> List[Playlist]:
        """
        Fetch all playlists from a Spotify user with filtering options.
        """
        logger.info(f"Fetching playlists for user '{username}'")
        
        try:
            playlists = []
            limit = 50
            offset = 0
            total = None
            max_requests = 100  # Safety limit
            requests_made = 0
            
            while requests_made < max_requests:
                try:
                    # Make direct API request without caching to avoid pagination issues
                    playlists_data = self._make_request(
                        self.sp.user_playlists, 
                        username, 
                        limit=limit, 
                        offset=offset
                    )
                    requests_made += 1
                    
                    if not playlists_data or not playlists_data.get("items"):
                        logger.debug(f"No more playlists found at offset {offset}")
                        break
                    
                    items = playlists_data["items"]
                    if not items:
                        break
                    
                    # Get total on first request
                    if total is None:
                        total = playlists_data.get("total", 0)
                        logger.info(f"Found {total} total playlists for user '{username}'")
                    
                    batch_playlists = self.extract_playlists(
                        items, 
                        username, 
                        include_collaborative, 
                        include_followed
                    )
                    playlists.extend(batch_playlists)
                    
                    # Update offset by actual items returned
                    offset += len(items)
                    
                    # Check if we're done
                    if offset >= total or len(items) < limit:
                        logger.debug(f"Reached end of playlists: offset={offset}, total={total}, returned={len(items)}")
                        break
                    
                    # Progress reporting for large collections
                    if total > 50:
                        progress = (offset / total) * 100
                        logger.info(f"Playlist fetch progress: {offset}/{total} ({progress:.1f}%)")
                    
                    # Rate limiting
                    time.sleep(random.uniform(0.3, 0.8))
                
                except Exception as e:
                    logger.error(f"Error fetching playlists at offset {offset}: {e}")
                    break
            
            logger.info(f"Successfully fetched {len(playlists)} playlists for user '{username}' (from {total or 'unknown'} total) in {requests_made} requests")
            return playlists
            
        except Exception as e:
            logger.error(f"Error fetching playlists for user '{username}': {e}")
            return []
    
    def extract_playlists(self, items: List[Dict], username: str, 
                         include_collaborative: bool = True, 
                         include_followed: bool = False) -> List[Playlist]:
        """Playlist extraction with filtering."""
        parsed_playlists = []
        
        for i, playlist_data in enumerate(items):
            try:
                # Basic validation
                playlist_id = playlist_data.get("id", "")
                if not playlist_id:
                    logger.debug(f"No ID for playlist at position {i}")
                    continue
                
                external_urls = playlist_data.get("external_urls") or {}
                url = external_urls.get("spotify", "")
                if not url:
                    logger.debug(f"No URL for playlist {playlist_id}")
                    continue
                
                # Owner information
                owner = playlist_data.get("owner", {})
                owner_id = owner.get("id", "")
                is_owned = owner_id.lower() == username.lower()
                
                # Filtering logic
                collaborative = playlist_data.get("collaborative", False)
                public = playlist_data.get("public", True)
                
                if not is_owned and not include_followed:
                    continue
                
                if collaborative and not include_collaborative:
                    continue
                
                # Extract metadata
                title = playlist_data.get("name", "Untitled Playlist")
                description = playlist_data.get("description", "")
                snapshot_id = playlist_data.get("snapshot_id", "")
                
                # Images
                images = playlist_data.get("images", [])
                poster = images[0]["url"] if images else ""
                
                # Track count
                tracks_info = playlist_data.get("tracks", {})
                number_of_tracks = tracks_info.get("total", 0)
                
                # Create playlist path
                path = os.path.join(self.path, f"{playlist_id}.json")
                
                playlist_obj = Playlist(
                    title=title,
                    tracks=[],  # Tracks will be fetched separately
                    id=playlist_id,
                    path=path,
                    number_of_tracks=number_of_tracks,
                    description=description,
                    snapshot_id=snapshot_id,
                    poster=poster,
                    summary=description,
                    url=url
                )
                
                # Additional metadata
                playlist_obj.owner_id = owner_id
                playlist_obj.is_owned = is_owned
                playlist_obj.collaborative = collaborative
                playlist_obj.public = public
                playlist_obj.followers = playlist_data.get("followers", {}).get("total", 0)
                
                parsed_playlists.append(playlist_obj)
                
            except Exception as e:
                logger.warning(f"Error parsing playlist at position {i}: {e}")
                continue
        
        return parsed_playlists
    
    def search_playlists(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search for public playlists."""
        try:
            cache_key = f"search_playlists_{query}_{limit}"
            
            def search():
                return self.sp.search(q=query, type='playlist', limit=limit)
            
            results = self._cached_request(cache_key, search)
            
            if results and results.get('playlists', {}).get('items'):
                return results['playlists']['items']
            
            return []
            
        except Exception as e:
            logger.error(f"Error searching playlists for '{query}': {e}")
            return []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get handler statistics."""
        uptime = time.time() - self.stats['session_start']
        
        return {
            **self.stats,
            'uptime_seconds': uptime,
            'requests_per_hour': (self.stats['requests_made'] / uptime) * 3600 if uptime > 0 else 0,
            'cache_hit_rate': (self.stats['cache_hits'] / max(1, self.stats['requests_made'])) * 100,
            'error_rate': (self.stats['errors'] / max(1, self.stats['requests_made'])) * 100
        }
    
    def print_stats(self):
        """Print formatted statistics."""
        stats = self.get_stats()
        
        print("\n=== Spotify Handler Statistics ===")
        print(f"Session uptime: {stats['uptime_seconds']:.1f}s")
        print(f"Total requests: {stats['requests_made']}")
        print(f"Cache hits: {stats['cache_hits']} ({stats['cache_hit_rate']:.1f}%)")
        print(f"Rate limit waits: {stats['rate_limit_waits']}")
        print(f"Errors: {stats['errors']} ({stats['error_rate']:.1f}%)")
        print(f"Request rate: {stats['requests_per_hour']:.1f}/hour")
        print("=" * 35)
    
    def validate_connection(self) -> bool:
        """Validate Spotify connection."""
        try:
            # Test with a simple search
            result = self.sp.search(q="test", type="track", limit=1)
            return result is not None
        except Exception as e:
            logger.error(f"Spotify connection validation failed: {e}")
            return False
