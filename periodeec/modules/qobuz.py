import os
import logging
import sys
import contextlib
import time
from typing import Dict, Any, Optional
from qobuz_dl.core import QobuzDL
from periodeec.modules.downloader import Downloader, DownloadResult, MatchResult, DownloadStatus, MatchQuality
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)


@contextlib.contextmanager
def suppress_stdout_stderr():
    """Context manager to suppress stdout and stderr."""
    with open(os.devnull, 'w') as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr


class Qobuz(Downloader):
    """Qobuz downloader"""
    
    def __init__(self, email: str, password: str, quality: int = 27, 
                 embed_art: bool = True, cover_og_quality: bool = False, 
                 priority: int = 10, timeout: int = 300):
        """
        Initialize Qobuz downloader.
        
        Args:
            email: Qobuz account email
            password: Qobuz account password
            quality: Download quality (27=Hi-Res, 7=Lossless, 6=CD, 5=MP3 320)
            embed_art: Whether to embed album art
            cover_og_quality: Whether to download original quality covers
            priority: Download priority (lower = higher priority)
            timeout: Download timeout in seconds
        """
        super().__init__("qobuz-dl", priority, timeout)
        
        if not email or not password:
            raise ValueError("Email and password cannot be empty.")
        
        self.quality = quality
        self.embed_art = embed_art
        self.cover_og_quality = cover_og_quality
        self._authenticated = False
        
        try:
            self.qobuz = QobuzDL(
                quality=quality,
                embed_art=embed_art,
                cover_og_quality=cover_og_quality
            )
            self.qobuz.get_tokens()
            self.qobuz.initialize_client(
                email, password, self.qobuz.app_id, self.qobuz.secrets
            )
            self._authenticated = True
            self._logger.info(f"Successfully authenticated with Qobuz")
        except Exception as e:
            self._logger.error(f"Failed to initialize {self.name}: {e}")
            raise
    
    def get_capabilities(self) -> Dict[str, bool]:
        """Return Qobuz-specific capabilities."""
        return {
            "supports_isrc_search": True,
            "supports_fuzzy_search": True,
            "supports_album_download": True,
            "supports_batch_download": False,
            "supports_high_quality": True,
            "requires_authentication": True
        }
    
    def validate_credentials(self) -> bool:
        """Validate Qobuz credentials."""
        return self._authenticated
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get Qobuz rate limit information."""
        return {
            "requests_per_minute": 30,
            "concurrent_downloads": 1,
            "retry_after_seconds": 60
        }
    
    def _calculate_similarity(self, str1: str, str2: str) -> float:
        """Calculate similarity between two strings."""
        return SequenceMatcher(None, str1.lower(), str2.lower()).ratio()
    
    def _search_by_isrc(self, isrc: str) -> MatchResult:
        """Search for track by ISRC."""
        try:
            results = self.qobuz.search_by_type(isrc, item_type="track", lucky=True)
            if results and len(results) > 0:
                result = results[0]
                if isinstance(result, dict) and 'url' in result:
                    track_id = result['url'].split("/")[-1]
                elif isinstance(result, str):
                    track_id = result.split("/")[-1]
                else:
                    self._logger.debug(f"Unexpected result format: {type(result)} - Content: {result}")
                    return MatchResult(MatchQuality.NO_MATCH)
                track_meta = self.qobuz.client.get_track_meta(track_id)
                
                album_url = track_meta.get('album', {}).get('url', '')
                metadata = {
                    'track_id': track_id,
                    'album_id': track_meta.get('album', {}).get('id', ''),
                    'artist': track_meta.get('performer', {}).get('name', ''),
                    'title': track_meta.get('title', ''),
                    'album': track_meta.get('album', {}).get('title', ''),
                    'duration': track_meta.get('duration', 0)
                }
                
                self._logger.info(f"Found ISRC match: {metadata['artist']} - {metadata['title']}")
                return MatchResult(
                    quality=MatchQuality.EXACT,
                    url=album_url,
                    confidence=1.0,
                    metadata=metadata
                )
        except Exception as e:
            self._logger.debug(f"ISRC search failed: {e}")
        
        return MatchResult(MatchQuality.NO_MATCH)
    
    def _search_by_metadata(self, artist: str, title: str, album: str = "") -> MatchResult:
        """Search for track by artist, title, and optionally album."""
        # Try album search first if album is provided
        if album:
            query = f'"{artist}" "{album}"'
            try:
                results = self.qobuz.search_by_type(
                    query=query, item_type="album", lucky=False
                )
                if results:
                    best_match = self._find_best_album_match(results, artist, album, title)
                    if best_match:
                        return best_match
            except Exception as e:
                self._logger.debug(f"Album search failed: {e}")
        
        # Fallback to track search
        query = f'"{artist}" "{title}"'
        try:
            results = self.qobuz.search_by_type(
                query=query, item_type="track", lucky=False
            )
            if results:
                return self._find_best_track_match(results, artist, title, album)
        except Exception as e:
            self._logger.debug(f"Track search failed: {e}")
        
        return MatchResult(MatchQuality.NO_MATCH)
    
    def _find_best_album_match(self, results: list, artist: str, album: str, title: str) -> Optional[MatchResult]:
        """Find the best matching album from search results."""
        best_score = 0.0
        best_result = None
        
        for result in results[:5]:  # Check top 5 results
            try:
                if isinstance(result, dict) and 'url' in result:
                    album_id = result['url'].split("/")[-1]
                elif isinstance(result, str):
                    album_id = result.split("/")[-1]
                else:
                    self._logger.debug(f"Unexpected album result format: {type(result)} - Content: {result}")
                    continue
                album_meta = self.qobuz.client.get_album_meta(album_id)
                
                album_artist = album_meta.get('artist', {}).get('name', '')
                album_title = album_meta.get('title', '')
                
                artist_score = self._calculate_similarity(artist, album_artist)
                album_score = self._calculate_similarity(album, album_title)
                combined_score = (artist_score + album_score) / 2
                
                if combined_score > best_score and combined_score > 0.7:
                    # Check if the album contains the target track
                    tracks = album_meta.get('tracks', {}).get('items', [])
                    track_found = any(
                        self._calculate_similarity(title, track.get('title', '')) > 0.8
                        for track in tracks
                    )
                    
                    if track_found:
                        best_score = combined_score
                        metadata = {
                            'album_id': album_id,
                            'artist': album_artist,
                            'album': album_title,
                            'track_count': len(tracks)
                        }
                        result_url = result['url'] if isinstance(result, dict) and 'url' in result else result
                        best_result = MatchResult(
                            quality=MatchQuality.HIGH if combined_score > 0.9 else MatchQuality.MEDIUM,
                            url=result_url,
                            confidence=combined_score,
                            metadata=metadata
                        )
            except Exception as e:
                self._logger.debug(f"Error processing album result: {e}")
                continue
        
        return best_result
    
    def _find_best_track_match(self, results: list, artist: str, title: str, album: str = "") -> MatchResult:
        """Find the best matching track from search results."""
        best_score = 0.0
        best_result = MatchResult(MatchQuality.NO_MATCH)
        
        for result in results[:10]:  # Check top 10 results
            try:
                if isinstance(result, dict) and 'url' in result:
                    track_id = result['url'].split("/")[-1]
                elif isinstance(result, str):
                    track_id = result.split("/")[-1]
                else:
                    self._logger.debug(f"Unexpected track result format: {type(result)} - Content: {result}")
                    continue
                track_meta = self.qobuz.client.get_track_meta(track_id)
                
                track_artist = track_meta.get('performer', {}).get('name', '')
                track_title = track_meta.get('title', '')
                track_album = track_meta.get('album', {}).get('title', '')
                
                artist_score = self._calculate_similarity(artist, track_artist)
                title_score = self._calculate_similarity(title, track_title)
                
                # Calculate combined score
                if album:
                    album_score = self._calculate_similarity(album, track_album)
                    combined_score = (artist_score + title_score + album_score) / 3
                else:
                    combined_score = (artist_score + title_score) / 2
                
                if combined_score > best_score:
                    best_score = combined_score
                    quality = MatchQuality.NO_MATCH
                    
                    if combined_score > 0.95:
                        quality = MatchQuality.EXACT
                    elif combined_score > 0.85:
                        quality = MatchQuality.HIGH
                    elif combined_score > 0.7:
                        quality = MatchQuality.MEDIUM
                    elif combined_score > 0.5:
                        quality = MatchQuality.LOW
                    
                    album_url = track_meta.get('album', {}).get('url', '')
                    metadata = {
                        'track_id': track_id,
                        'album_id': track_meta.get('album', {}).get('id', ''),
                        'artist': track_artist,
                        'title': track_title,
                        'album': track_album,
                        'duration': track_meta.get('duration', 0)
                    }
                    
                    best_result = MatchResult(
                        quality=quality,
                        url=album_url,
                        confidence=combined_score,
                        metadata=metadata
                    )
            except Exception as e:
                self._logger.debug(f"Error processing track result: {e}")
                continue
        
        return best_result
    
    def match(self, isrc: str, artist: str, title: str, album: str = "") -> MatchResult:
        """
        Find the best match for a track using multiple search strategies.
        
        Args:
            isrc: The ISRC code
            artist: Artist name
            title: Track title
            album: Album name (optional)
            
        Returns:
            MatchResult with the best match found
        """
        if not self._authenticated:
            return MatchResult(
                quality=MatchQuality.NO_MATCH,
                error_message="Not authenticated with Qobuz"
            )
        
        # Try ISRC search first (most accurate)
        if isrc:
            result = self._search_by_isrc(isrc)
            if result.found:
                self._logger.info(f"Found match via ISRC: {result.url}")
                return result
        
        # Fallback to metadata search
        result = self._search_by_metadata(artist, title, album)
        if result.found:
            self._logger.info(f"Found match via metadata search: {result.url} (confidence: {result.confidence:.2f})")
        else:
            self._logger.warning(f"No match found for: {artist} - {title}")
        
        return result
    
    def enqueue(self, path: str, isrc: str, artist: str, title: str, album: str = "") -> DownloadResult:
        """
        Download a track to the specified path.
        
        Args:
            path: Destination directory
            isrc: The ISRC code
            artist: Artist name
            title: Track title
            album: Album name (optional)
            
        Returns:
            DownloadResult with the operation result
        """
        if not self._authenticated:
            return DownloadResult(
                status=DownloadStatus.UNAUTHORIZED,
                error_message="Not authenticated with Qobuz"
            )
        
        # Find the track first
        match_result = self.match(isrc, artist, title, album)
        if not match_result.found:
            return DownloadResult(
                status=DownloadStatus.NOT_FOUND,
                error_message="No suitable match found",
                match_quality=match_result.quality
            )
        
        # Extract album ID from URL
        try:
            album_id = match_result.url.split("/")[-1]
        except (IndexError, AttributeError):
            return DownloadResult(
                status=DownloadStatus.FAILED,
                error_message="Invalid album URL in match result",
                match_quality=match_result.quality
            )
        
        # Create download directory
        os.makedirs(path, exist_ok=True)
        
        # Attempt download
        try:
            with suppress_stdout_stderr():
                self._logger.info(f"Downloading album {album_id} to {path}")
                start_time = time.time()
                
                self.qobuz.download_from_id(
                    item_id=album_id,
                    album=True,
                    alt_path=path
                )
                
                download_time = time.time() - start_time
                self._logger.info(f"Download completed in {download_time:.1f}s")
                
                return DownloadResult(
                    status=DownloadStatus.SUCCESS,
                    path=path,
                    match_quality=match_result.quality,
                    match_url=match_result.url,
                    metadata={
                        **match_result.metadata,
                        'download_time': download_time,
                        'quality': self.quality
                    }
                )
        
        except TimeoutError:
            return DownloadResult(
                status=DownloadStatus.TIMEOUT,
                error_message=f"Download timed out after {self.timeout}s",
                match_quality=match_result.quality
            )
        except Exception as e:
            error_msg = str(e)
            self._logger.error(f"Download failed: {error_msg}")
            
            # Determine specific error type
            status = DownloadStatus.FAILED
            if "rate limit" in error_msg.lower():
                status = DownloadStatus.RATE_LIMITED
            elif "unauthorized" in error_msg.lower() or "forbidden" in error_msg.lower():
                status = DownloadStatus.UNAUTHORIZED
            
            return DownloadResult(
                status=status,
                error_message=error_msg,
                match_quality=match_result.quality,
                match_url=match_result.url
            )
