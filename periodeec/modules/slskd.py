import os
import time
import requests
import logging
from typing import Dict, Any, List, Optional
from urllib.parse import quote
from periodeec.modules.downloader import Downloader, DownloadResult, MatchResult, DownloadStatus, MatchQuality

logger = logging.getLogger(__name__)


class Slskd(Downloader):
    """Simplified Soulseek downloader using slskd daemon API."""

    def __init__(self, host: str = "localhost", port: int = 5030,
                 api_key: str = "", username: str = "", password: str = "",
                 use_https: bool = False, priority: int = 30, timeout: int = 300,
                 max_results: int = 50, min_bitrate: int = 320,
                 preferred_formats: List[str] = None):
        """Initialize simplified Soulseek downloader."""
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

        self._session: Optional[requests.Session] = None
        self._authenticated = False

    def _get_session(self) -> requests.Session:
        """Get or create requests session."""
        if self._session is None:
            self._session = requests.Session()

            if self.api_key:
                self._session.headers.update({'X-API-Key': self.api_key})

            # Set timeout and disable SSL verification
            self._session.timeout = self.timeout
            self._session.verify = False

        return self._session

    def _authenticate(self) -> bool:
        """Authenticate with slskd if needed."""
        if self.api_key:
            self._authenticated = True
            return True

        if not self.username or not self.password:
            self._logger.error("No API key or username/password provided")
            return False

        session = self._get_session()
        try:
            auth_data = {'username': self.username, 'password': self.password}
            resp = session.post(f"{self.base_url}/session", json=auth_data, timeout=self.timeout)
            if resp.status_code == 200:
                self._authenticated = True
                self._logger.info("Successfully authenticated with slskd")
                return True
            else:
                self._logger.error(f"Authentication failed: {resp.status_code}")
                return False
        except Exception as e:
            self._logger.error(f"Authentication error: {e}")
            return False

    def _extract_quality_info(self, filename: str) -> Dict[str, Any]:
        """Extract audio quality information from filename."""
        filename_lower = filename.lower()

        # Extract file extension
        ext = filename_lower.split('.')[-1] if '.' in filename else ''

        # Extract bitrate
        bitrate = 0
        for part in filename.split():
            part_lower = part.lower()
            if 'kbps' in part_lower or part_lower.endswith('k'):
                try:
                    bitrate = int(''.join(filter(str.isdigit, part_lower)))
                    break
                except ValueError:
                    pass

        # Simple quality scoring
        if ext in ['flac', 'alac', 'ape', 'wav']:
            quality_score = 100
        elif bitrate >= 320:
            quality_score = 80
        elif bitrate >= 256:
            quality_score = 70
        elif bitrate >= 192:
            quality_score = 60
        else:
            quality_score = 40

        return {
            'format': ext,
            'bitrate': bitrate,
            'quality_score': quality_score
        }

    def _simple_search(self, query: str) -> List[Dict[str, Any]]:
        """Simple search for files on Soulseek network."""
        if not self._authenticated:
            self._authenticate()

        if not self._authenticated:
            return []

        session = self._get_session()

        try:
            # Start search
            resp = session.post(f"{self.base_url}/searches",
                              json={'searchText': query}, timeout=self.timeout)
            if resp.status_code not in [200, 201]:
                self._logger.error(f"Search failed: {resp.status_code}")
                return []

            search_data = resp.json()
            search_id = search_data.get('id')

            if not search_id:
                self._logger.error("No search ID returned")
                return []

            # Wait for search to complete (simplified - just wait 15 seconds)
            time.sleep(15)

            # Get results
            resp = session.get(f"{self.base_url}/searches/{search_id}/responses", timeout=self.timeout)
            if resp.status_code != 200:
                return []

            responses = resp.json()

            # Process results
            results = []
            for response in responses[:self.max_results]:
                username = response.get('username', '')
                files = response.get('files', [])

                for file_info in files:
                    filename = file_info.get('filename', '')
                    quality_info = self._extract_quality_info(filename)

                    # Basic quality filter
                    if (quality_info['bitrate'] >= self.min_bitrate or
                        quality_info['format'] in ['flac', 'alac', 'ape', 'wav']):

                        results.append({
                            'username': username,
                            'filename': filename,
                            'path': file_info.get('filename', ''),  # Full path from slskd
                            'size': file_info.get('size', 0),
                            'quality_info': quality_info,
                            'speed': response.get('uploadSpeed', 0)
                        })

            # Clean up search
            try:
                session.delete(f"{self.base_url}/searches/{search_id}", timeout=self.timeout)
            except:
                pass  # Ignore cleanup errors

            return results

        except Exception as e:
            self._logger.error(f"Search error: {e}")
            return []

    def _meets_criteria(self, result: Dict[str, Any], artist: str, album: str) -> bool:
        """Check if result meets basic matching criteria."""
        filename = result['filename'].lower()
        full_path = result.get('path', filename).lower()

        # Check if this is a quality audio file
        ext = filename.split('.')[-1] if '.' in filename else ''
        is_audio_file = ext in ['flac', 'mp3', 'm4a', 'wav', 'alac', 'ape']

        if not is_audio_file:
            return False

        # If artist is specified, it should match somewhere in the path
        if artist:
            artist_lower = artist.lower()
            if not (artist_lower in filename or artist_lower in full_path):
                return False

        # Album matching with fallback logic:
        # 1. Direct album match in path
        # 2. Album words in path
        # 3. If we have artist match + quality audio file, let beets decide
        if album:
            album_lower = album.lower()
            album_words = [word for word in album_lower.split() if len(word) > 2]

            album_match = (album_lower in full_path or
                          any(word in full_path for word in album_words))

            # Fallback: if folder structure suggests album + we have quality files,
            # trust that beets will sort it out during import
            if not album_match and artist and is_audio_file:
                return True

        return True

    def _sort_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Sort results by quality preference, prioritizing complete albums."""
        from collections import defaultdict

        # Group by folder/directory to identify potential albums
        folder_groups = defaultdict(list)
        for result in results:
            # Extract folder path (everything before the filename)
            full_path = result.get('path', result['filename'])
            if '/' in full_path:
                folder = '/'.join(full_path.split('/')[:-1])
            elif '\\' in full_path:
                folder = '\\'.join(full_path.split('\\')[:-1])
            else:
                folder = 'root'
            folder_groups[folder].append(result)

        def quality_key(result):
            quality_info = result['quality_info']
            format_pref = 0

            # Format preference scoring
            if quality_info['format'] in ['flac', 'alac']:
                format_pref = 100
            elif quality_info['format'] == 'ape':
                format_pref = 90
            elif quality_info['format'] == 'wav':
                format_pref = 85
            elif quality_info['format'] == 'm4a':
                format_pref = 70
            elif quality_info['format'] == 'mp3':
                format_pref = 60

            # Bonus for being part of a multi-track album (3+ tracks suggests complete album)
            folder_path = result.get('path', result['filename'])
            folder = '/'.join(folder_path.split('/')[:-1]) if '/' in folder_path else folder_path
            album_bonus = 20 if len(folder_groups.get(folder, [])) >= 3 else 0

            return (format_pref + album_bonus, quality_info['bitrate'], result.get('speed', 0))

        return sorted(results, key=quality_key, reverse=True)

    def _match(self, isrc: str, artist: str, title: str, album: str = "") -> MatchResult:
        """Simple match method - search for artist + album."""
        # Build simple query
        if album and artist:
            query = f"{artist} {album}"
        elif artist and title:
            query = f"{artist} {title}"
        elif album:
            query = album
        else:
            query = artist or title

        if not query.strip():
            return MatchResult(MatchQuality.NO_MATCH,
                             metadata={"error": "No search terms"})

        self._logger.info(f"Searching Soulseek for: {query}")

        # Search
        results = self._simple_search(query)

        if not results:
            return MatchResult(MatchQuality.NO_MATCH,
                             metadata={"error": "No results found"})

        # Filter results that match criteria
        good_results = []
        for result in results:
            if self._meets_criteria(result, artist, album):
                good_results.append(result)
            else:
                # Debug: log why results were filtered out
                self._logger.debug(f"Filtered out: {result['filename']} (artist: {artist}, album: {album})")

        if not good_results:
            return MatchResult(MatchQuality.NO_MATCH,
                             metadata={"error": "No matching results"})

        # Sort by quality and return best
        sorted_results = self._sort_results(good_results)
        best_result = sorted_results[0]

        # Simple quality determination
        quality_score = best_result['quality_info']['quality_score']
        if quality_score >= 90:
            quality = MatchQuality.HIGH
        elif quality_score >= 70:
            quality = MatchQuality.MEDIUM
        else:
            quality = MatchQuality.LOW

        return MatchResult(
            quality=quality,
            url=f"soulseek://{best_result['username']}/{best_result['filename']}",
            confidence=quality_score / 100.0,
            metadata={
                'filename': best_result['filename'],
                'username': best_result['username'],
                'size': best_result['size'],
                'quality_info': best_result['quality_info'],
                'alternatives': sorted_results[1:5]  # Top alternatives
            }
        )

    def match(self, isrc: str, artist: str, title: str, album: str = "") -> MatchResult:
        """Find the best match for a track on Soulseek network."""
        try:
            return self._match(isrc, artist, title, album)
        except Exception as e:
            self._logger.error(f"Match failed: {e}")
            return MatchResult(MatchQuality.NO_MATCH, metadata={"error": str(e)})

    def _download(self, username: str, filename: str, destination: str) -> bool:
        """Download a file from Soulseek user."""
        session = self._get_session()

        try:
            # Initiate download
            download_data = {'username': username, 'files': [filename]}

            resp = session.post(f"{self.base_url}/transfers/downloads",
                              json=download_data, timeout=self.timeout)
            if resp.status_code != 201:
                self._logger.error(f"Download failed: {resp.status_code}")
                return False

            transfer_data = resp.json()
            transfer_id = transfer_data.get('id')

            if not transfer_id:
                return False

            # Simple download monitoring - wait for completion
            for _ in range(self.timeout // 5):  # Check every 5 seconds
                time.sleep(5)

                resp = session.get(f"{self.base_url}/transfers/downloads/{transfer_id}", timeout=self.timeout)
                if resp.status_code != 200:
                    continue

                transfer_info = resp.json()
                state = transfer_info.get('state', '')

                if state == 'Completed, Succeeded':
                    self._logger.info("Download completed")
                    return True
                elif 'Errored' in state or 'Cancelled' in state:
                    self._logger.error(f"Download failed: {state}")
                    return False

            self._logger.error("Download timed out")
            return False

        except Exception as e:
            self._logger.error(f"Download error: {e}")
            return False

    def _enqueue(self, path: str, isrc: str, artist: str,
                title: str, album: str = "") -> DownloadResult:
        """Simple enqueue method."""
        # Find match
        match_result = self._match(isrc, artist, title, album)

        if not match_result.found:
            return DownloadResult(
                status=DownloadStatus.NOT_FOUND,
                error_message="No match found",
                match_quality=match_result.quality
            )

        # Extract download info
        metadata = match_result.metadata
        username = metadata.get('username', '')
        filename = metadata.get('filename', '')

        if not username or not filename:
            return DownloadResult(
                status=DownloadStatus.FAILED,
                error_message="Invalid match data"
            )

        # Create download directory
        os.makedirs(path, exist_ok=True)

        # Download
        success = self._download(username, filename, path)

        if success:
            return DownloadResult(
                status=DownloadStatus.SUCCESS,
                path=path,
                match_quality=match_result.quality,
                match_url=match_result.url,
                metadata=metadata
            )
        else:
            return DownloadResult(
                status=DownloadStatus.FAILED,
                error_message="Download failed",
                match_quality=match_result.quality
            )

    def enqueue(self, path: str, isrc: str, artist: str, title: str, album: str = "") -> DownloadResult:
        """Download a track from Soulseek network."""
        try:
            return self._enqueue(path, isrc, artist, title, album)
        except Exception as e:
            self._logger.error(f"Enqueue failed: {e}")
            return DownloadResult(status=DownloadStatus.FAILED, error_message=str(e))

    def get_capabilities(self) -> Dict[str, bool]:
        """Return capabilities."""
        return {
            "supports_isrc_search": False,
            "supports_fuzzy_search": True,
            "supports_album_download": True,
            "supports_batch_download": False,
            "supports_high_quality": True,
            "requires_authentication": bool(self.username or self.api_key)
        }

    def get_rate_limit_info(self) -> Dict[str, Any]:
        """Get rate limit info."""
        return {
            "requests_per_minute": 60,
            "concurrent_downloads": 3,
            "retry_after_seconds": 10
        }

    def cleanup(self) -> None:
        """Cleanup resources."""
        if self._session:
            self._session.close()