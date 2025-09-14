import os
import json
import time
import asyncio
import aiohttp
import logging
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import quote
from difflib import SequenceMatcher
from periodeec.modules.downloader import Downloader, DownloadResult, MatchResult, DownloadStatus, MatchQuality

logger = logging.getLogger(__name__)


class Slskd(Downloader):
    """Soulseek downloader using slskd daemon API."""
    
    def __init__(self, host: str = "localhost", port: int = 5030, 
                 api_key: str = "", username: str = "", password: str = "",
                 use_https: bool = False, priority: int = 30, timeout: int = 600,
                 max_results: int = 100, min_bitrate: int = 320, 
                 preferred_formats: List[str] = None):
        """
        Initialize Soulseek downloader.
        
        Args:
            host: slskd daemon host
            port: slskd daemon port
            api_key: API key for slskd
            username: Soulseek username (if not using API key)
            password: Soulseek password (if not using API key)
            use_https: Whether to use HTTPS
            priority: Download priority
            timeout: Download timeout in seconds
            max_results: Maximum search results to consider
            min_bitrate: Minimum bitrate to accept (kbps)
            preferred_formats: List of preferred file formats (e.g., ['flac', 'mp3'])
        """
        super().__init__("slskd", priority, timeout)
        
        self.host = host
        self.port = port
        self.api_key = api_key
        self.username = username
        self.password = password
        self.protocol = "https" if use_https else "http"
        self.base_url = f"{self.protocol}://{host}:{port}/api/v0"
        self.max_results = max_results
        self.min_bitrate = min_bitrate
        self.preferred_formats = preferred_formats or ['flac', 'alac', 'mp3', 'm4a']
        
        # Session will be created when needed
        self._session: Optional[aiohttp.ClientSession] = None
        self._authenticated = False
        self._last_search_time = 0  # Track last search time for rate limiting
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Get or create aiohttp session with proper headers."""
        if self._session is None or self._session.closed:
            headers = {}
            if self.api_key:
                headers['X-API-Key'] = self.api_key
            
            timeout = aiohttp.ClientTimeout(total=self.timeout)
            self._session = aiohttp.ClientSession(
                headers=headers,
                timeout=timeout,
                connector=aiohttp.TCPConnector(verify_ssl=False)
            )
        
        return self._session
    
    async def _authenticate(self) -> bool:
        """Authenticate with slskd if needed."""
        if self.api_key:
            # API key authentication
            self._authenticated = True
            return True
        
        if not self.username or not self.password:
            self._logger.error("No API key or username/password provided")
            return False
        
        session = await self._get_session()
        
        try:
            auth_data = {
                'username': self.username,
                'password': self.password
            }
            
            async with session.post(f"{self.base_url}/session", json=auth_data) as resp:
                if resp.status == 200:
                    self._authenticated = True
                    self._logger.info("Successfully authenticated with slskd")
                    return True
                else:
                    self._logger.error(f"Authentication failed: {resp.status}")
                    return False
        except Exception as e:
            self._logger.error(f"Authentication error: {e}")
            return False
    
    def get_capabilities(self) -> Dict[str, bool]:
        """Return slskd-specific capabilities."""
        return {
            "supports_isrc_search": False,  # Soulseek doesn't support ISRC
            "supports_fuzzy_search": True,
            "supports_album_download": True,
            "supports_batch_download": True,
            "supports_high_quality": True,
            "requires_authentication": bool(self.username or self.api_key)
        }
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get slskd rate limit information."""
        return {
            "requests_per_minute": 120,
            "concurrent_downloads": 5,
            "retry_after_seconds": 30
        }
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings."""
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()
    
    def _extract_audio_info(self, filename: str) -> Dict[str, Any]:
        """Extract audio information from filename."""
        filename_lower = filename.lower()
        
        # Extract file extension
        ext = filename_lower.split('.')[-1] if '.' in filename else ''
        
        # Extract bitrate (look for patterns like 320kbps, 320k, etc.)
        bitrate = 0
        for part in filename.split():
            part_lower = part.lower()
            if 'kbps' in part_lower:
                try:
                    bitrate = int(''.join(filter(str.isdigit, part_lower)))
                    break
                except ValueError:
                    pass
            elif part_lower.endswith('k') and part_lower[:-1].isdigit():
                try:
                    bitrate = int(part_lower[:-1])
                    break
                except ValueError:
                    pass
        
        # Determine quality score
        quality_score = 0
        if ext in ['flac', 'alac', 'ape']:
            quality_score = 100
        elif ext == 'wav':
            quality_score = 95
        elif bitrate >= 320:
            quality_score = 80
        elif bitrate >= 256:
            quality_score = 70
        elif bitrate >= 192:
            quality_score = 60
        elif bitrate >= 128:
            quality_score = 40
        else:
            quality_score = 20
        
        return {
            'format': ext,
            'bitrate': bitrate,
            'quality_score': quality_score
        }
    
    async def _search(self, query: str) -> List[Dict[str, Any]]:
        """Search for files on Soulseek network."""
        if not self._authenticated:
            await self._authenticate()
        
        if not self._authenticated:
            return []
        
        session = await self._get_session()

        try:
            # Rate limiting - ensure minimum delay between searches to avoid conflicts
            current_time = time.time()
            min_search_interval = 1.0  # Minimum 1 second between searches

            if current_time - self._last_search_time < min_search_interval:
                wait_time = min_search_interval - (current_time - self._last_search_time)
                self._logger.debug(f"Rate limiting: waiting {wait_time:.1f}s before search")
                await asyncio.sleep(wait_time)

            self._last_search_time = time.time()

            # URL encode the query
            encoded_query = quote(query)

            # Start search with retry logic for conflicts
            search_id = None
            max_retries = 3

            for attempt in range(max_retries):
                async with session.post(f"{self.base_url}/searches",
                                      json={'searchText': query}) as resp:
                    if resp.status == 201:
                        search_data = await resp.json()
                        search_id = search_data.get('id')
                        break
                    elif resp.status == 409:
                        # Conflict - search already running or rate limited
                        if attempt < max_retries - 1:
                            wait_time = (attempt + 1) * 2  # 2, 4, 6 seconds
                            self._logger.warning(f"Search conflict (409), retrying in {wait_time}s... (attempt {attempt + 1}/{max_retries})")
                            await asyncio.sleep(wait_time)
                            continue
                        else:
                            self._logger.error(f"Search initiation failed after {max_retries} attempts: 409 Conflict (too many concurrent searches or duplicate query)")
                            return []
                    else:
                        self._logger.error(f"Search initiation failed: {resp.status}")
                        if attempt < max_retries - 1:
                            await asyncio.sleep(1)
                            continue
                        return []
            
            if not search_id:
                self._logger.error("No search ID returned")
                return []
            
            # Wait for search to complete (with timeout)
            search_timeout = min(30, self.timeout // 2)
            start_time = time.time()
            
            while time.time() - start_time < search_timeout:
                async with session.get(f"{self.base_url}/searches/{search_id}") as resp:
                    if resp.status == 200:
                        search_status = await resp.json()
                        state = search_status.get('state', '')
                        
                        if state in ['Completed', 'TimedOut']:
                            break
                        elif state == 'Errored':
                            self._logger.error("Search errored")
                            return []
                
                await asyncio.sleep(1)
            
            # Get search results
            async with session.get(f"{self.base_url}/searches/{search_id}/responses") as resp:
                if resp.status != 200:
                    self._logger.error(f"Failed to get search results: {resp.status}")
                    return []
                
                responses = await resp.json()
            
            # Process and flatten results
            results = []
            for response in responses[:self.max_results]:
                username = response.get('username', '')
                files = response.get('files', [])
                
                for file_info in files:
                    audio_info = self._extract_audio_info(file_info.get('filename', ''))
                    
                    # Filter by minimum bitrate and preferred formats
                    if (audio_info['bitrate'] >= self.min_bitrate or 
                        audio_info['format'] in ['flac', 'alac', 'ape', 'wav']):
                        
                        results.append({
                            'username': username,
                            'filename': file_info.get('filename', ''),
                            'size': file_info.get('size', 0),
                            'path': file_info.get('filename', ''),  # Full path on remote
                            'audio_info': audio_info,
                            'speed': response.get('uploadSpeed', 0),
                            'queue_length': response.get('queueLength', 0)
                        })
            
            return results
        
        except Exception as e:
            self._logger.error(f"Search failed: {e}")
            return []
    
    def _score_result(self, result: Dict[str, Any], artist: str, title: str, 
                     album: str = "") -> Tuple[float, MatchQuality]:
        """Score a search result against the target track."""
        filename = result['filename'].lower()
        audio_info = result['audio_info']
        
        # Calculate text similarity
        artist_score = 0.0
        title_score = 0.0
        album_score = 0.0
        
        # Score artist match
        if artist:
            artist_score = max([
                self._calculate_similarity(artist, part)
                for part in filename.split()
                if len(part) > 2
            ] + [0.0])
        
        # Score title match  
        if title:
            title_score = max([
                self._calculate_similarity(title, part)
                for part in filename.split()
                if len(part) > 2
            ] + [0.0])
        
        # Score album match
        if album:
            album_score = max([
                self._calculate_similarity(album, part)
                for part in filename.split()
                if len(part) > 2
            ] + [0.0])
        
        # Calculate combined text score with album priority (since we're doing album-based matching)
        if album and artist:
            # For album-based searches, prioritize album and artist matches over individual track
            text_score = (album_score * 0.5) + (artist_score * 0.4) + (title_score * 0.1)
        elif album:
            # Album-only search
            text_score = album_score
        else:
            # Fallback to track-based scoring
            text_score = (artist_score + title_score) / 2
        
        # Quality bonus
        quality_bonus = audio_info['quality_score'] / 100.0 * 0.2

        # Album structure bonus (favor results that look like album downloads)
        album_structure_bonus = 0.0
        path = result.get('path', '').lower()
        if album and artist:
            # Check if the path contains album-like structure (Artist/Album/ or Album/ patterns)
            if any(pattern in path for pattern in [
                f"{artist.lower()}/{album.lower()}",
                f"{album.lower()}/",
                f"/{album.lower()}/",
                f"[{album.lower()}]",
                f"({album.lower()})"
            ]):
                album_structure_bonus = 0.15

        # Speed bonus (prefer faster sources)
        speed_bonus = min(result.get('speed', 0) / 1000000, 0.1)  # Max 0.1 bonus

        # Queue penalty (prefer sources with shorter queues)
        queue_penalty = min(result.get('queue_length', 0) * 0.01, 0.2)
        
        total_score = text_score + quality_bonus + album_structure_bonus + speed_bonus - queue_penalty
        
        # Determine quality level
        quality = MatchQuality.NO_MATCH
        if total_score > 0.9:
            quality = MatchQuality.EXACT
        elif total_score > 0.75:
            quality = MatchQuality.HIGH
        elif total_score > 0.6:
            quality = MatchQuality.MEDIUM
        elif total_score > 0.4:
            quality = MatchQuality.LOW
        
        return total_score, quality
    
    async def _async_match(self, isrc: str, artist: str, title: str, album: str = "") -> MatchResult:
        """Async version of match method."""
        # Build album-focused search query since we're matching with beets
        # Priority: Album + Artist (better for beets album matching)
        query_parts = []

        if album and artist:
            # Primary strategy: search for the album by the artist
            query_parts.append(f'"{artist}"')
            query_parts.append(f'"{album}"')
            # Add file type hints to improve results
            query_parts.append("(flac OR mp3 OR m4a)")
        elif artist and title:
            # Fallback: individual track search if no album info
            query_parts.append(f'"{artist}"')
            query_parts.append(f'"{title}"')
        elif album:
            # Album only
            query_parts.append(f'"{album}"')
        elif artist:
            # Artist only
            query_parts.append(f'"{artist}"')
        elif title:
            # Title only (last resort)
            query_parts.append(f'"{title}"')

        query = " ".join(query_parts)
        
        if not query.strip():
            return MatchResult(MatchQuality.NO_MATCH, metadata={"error_message": "No search terms provided"})
        
        if album and artist:
            self._logger.info(f"Searching Soulseek for album: {artist} - {album}")
        else:
            self._logger.info(f"Searching Soulseek for track: {query}")
        
        # Search for results
        results = await self._search(query)
        
        if not results:
            self._logger.warning(f"No results found for: {query}")
            return MatchResult(MatchQuality.NO_MATCH, metadata={"error_message": "No search results"})
        
        # Score and rank results
        scored_results = []
        for result in results:
            score, quality = self._score_result(result, artist, title, album)
            if quality != MatchQuality.NO_MATCH:
                scored_results.append((score, quality, result))
        
        if not scored_results:
            return MatchResult(MatchQuality.NO_MATCH, metadata={"error_message": "No suitable matches found"})
        
        # Sort by score (descending)
        scored_results.sort(key=lambda x: x[0], reverse=True)
        best_score, best_quality, best_result = scored_results[0]
        
        self._logger.info(f"Best match: {best_result['filename']} (score: {best_score:.2f})")
        
        return MatchResult(
            quality=best_quality,
            url=f"soulseek://{best_result['username']}/{best_result['path']}",
            confidence=best_score,
            metadata={
                'filename': best_result['filename'],
                'username': best_result['username'],
                'size': best_result['size'],
                'audio_info': best_result['audio_info'],
                'speed': best_result.get('speed', 0),
                'queue_length': best_result.get('queue_length', 0),
                'alternatives': [
                    {
                        'filename': r[2]['filename'],
                        'username': r[2]['username'],
                        'score': r[0],
                        'audio_info': r[2]['audio_info']
                    }
                    for r in scored_results[1:6]  # Top 5 alternatives
                ]
            }
        )
    
    def match(self, isrc: str, artist: str, title: str, album: str = "") -> MatchResult:
        """Find the best match for a track on Soulseek network."""
        # Note: ISRC is not used as Soulseek doesn't support it
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(self._async_match(isrc, artist, title, album))
        except Exception as e:
            self._logger.error(f"Match operation failed: {e}")
            return MatchResult(MatchQuality.NO_MATCH, metadata={"error_message": str(e)})
    
    async def _async_download(self, username: str, filename: str, destination: str) -> bool:
        """Download a file from a Soulseek user."""
        session = await self._get_session()
        
        try:
            # Initiate download
            download_data = {
                'username': username,
                'files': [filename]
            }
            
            async with session.post(f"{self.base_url}/transfers/downloads", 
                                  json=download_data) as resp:
                if resp.status != 201:
                    self._logger.error(f"Download initiation failed: {resp.status}")
                    return False
                
                transfer_data = await resp.json()
                transfer_id = transfer_data.get('id')
            
            if not transfer_id:
                self._logger.error("No transfer ID returned")
                return False
            
            # Monitor download progress
            start_time = time.time()
            last_progress = 0
            
            while time.time() - start_time < self.timeout:
                async with session.get(f"{self.base_url}/transfers/downloads/{transfer_id}") as resp:
                    if resp.status != 200:
                        await asyncio.sleep(2)
                        continue
                    
                    transfer_info = await resp.json()
                    state = transfer_info.get('state', '')
                    progress = transfer_info.get('bytesTransferred', 0)
                    total_size = transfer_info.get('size', 0)
                    
                    # Log progress periodically
                    if total_size > 0 and progress > last_progress + (total_size * 0.1):
                        percent = (progress / total_size) * 100
                        self._logger.info(f"Download progress: {percent:.1f}%")
                        last_progress = progress
                    
                    if state == 'Completed, Succeeded':
                        self._logger.info("Download completed successfully")
                        return True
                    elif state in ['Completed, Errored', 'Completed, Cancelled']:
                        self._logger.error(f"Download failed: {state}")
                        return False
                    elif state in ['Queued', 'Initializing', 'InProgress']:
                        await asyncio.sleep(2)
                        continue
                
                await asyncio.sleep(1)
            
            self._logger.error("Download timed out")
            return False
        
        except Exception as e:
            self._logger.error(f"Download error: {e}")
            return False
    
    async def _async_enqueue(self, path: str, isrc: str, artist: str, 
                           title: str, album: str = "") -> DownloadResult:
        """Async version of enqueue method."""
        # Find the track first
        match_result = await self._async_match(isrc, artist, title, album)
        
        if not match_result.found:
            return DownloadResult(
                status=DownloadStatus.NOT_FOUND,
                error_message="No suitable match found on Soulseek",
                match_quality=match_result.quality
            )
        
        # Extract download info from match
        metadata = match_result.metadata
        username = metadata.get('username', '')
        filename = metadata.get('filename', '')
        
        if not username or not filename:
            return DownloadResult(
                status=DownloadStatus.FAILED,
                error_message="Invalid match result - missing username or filename",
                match_quality=match_result.quality
            )
        
        # Create download directory
        os.makedirs(path, exist_ok=True)
        
        # Start download
        self._logger.info(f"Downloading '{filename}' from user '{username}'")
        
        try:
            success = await self._async_download(username, filename, path)
            
            if success:
                return DownloadResult(
                    status=DownloadStatus.SUCCESS,
                    path=path,
                    match_quality=match_result.quality,
                    match_url=match_result.url,
                    metadata={
                        **metadata,
                        'download_source': 'soulseek',
                        'download_method': 'slskd_api'
                    }
                )
            else:
                return DownloadResult(
                    status=DownloadStatus.FAILED,
                    error_message="Download failed",
                    match_quality=match_result.quality,
                    match_url=match_result.url
                )
        
        except Exception as e:
            error_msg = str(e)
            self._logger.error(f"Download failed: {error_msg}")
            
            status = DownloadStatus.FAILED
            if "timeout" in error_msg.lower():
                status = DownloadStatus.TIMEOUT
            elif "rate limit" in error_msg.lower():
                status = DownloadStatus.RATE_LIMITED
            elif "unauthorized" in error_msg.lower():
                status = DownloadStatus.UNAUTHORIZED
            
            return DownloadResult(
                status=status,
                error_message=error_msg,
                match_quality=match_result.quality,
                match_url=match_result.url
            )
    
    def enqueue(self, path: str, isrc: str, artist: str, title: str, album: str = "") -> DownloadResult:
        """Download a track from Soulseek network."""
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        try:
            return loop.run_until_complete(self._async_enqueue(path, isrc, artist, title, album))
        except Exception as e:
            self._logger.error(f"Enqueue operation failed: {e}")
            return DownloadResult(
                status=DownloadStatus.FAILED,
                error_message=str(e)
            )
    
    async def cleanup(self) -> None:
        """Cleanup resources."""
        if self._session and not self._session.closed:
            await self._session.close()
    
    def __del__(self):
        """Ensure cleanup on deletion."""
        if self._session and not self._session.closed:
            try:
                loop = asyncio.get_event_loop()
                loop.create_task(self.cleanup())
            except:
                pass  # Ignore cleanup errors during deletion
