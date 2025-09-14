import os
import shutil
import logging
import json
from typing import List, Dict, Any, Optional
from datetime import datetime
from periodeec.modules.downloader import Downloader, DownloadResult, DownloadStatus, MatchQuality
from periodeec.schema import Track

logger = logging.getLogger(__name__)


class DownloadStats:
    """Statistics tracking for download operations."""
    
    def __init__(self):
        self.total_attempts = 0
        self.successful_downloads = 0
        self.failed_downloads = 0
        self.not_found = 0
        self.rate_limited = 0
        self.downloader_stats = {}
        self.quality_stats = {}
    
    def record_attempt(self, result: DownloadResult, downloader_name: str):
        """Record a download attempt and its result."""
        self.total_attempts += 1
        
        # Track by status
        if result.status == DownloadStatus.SUCCESS:
            self.successful_downloads += 1
        elif result.status == DownloadStatus.FAILED:
            self.failed_downloads += 1
        elif result.status == DownloadStatus.NOT_FOUND:
            self.not_found += 1
        elif result.status == DownloadStatus.RATE_LIMITED:
            self.rate_limited += 1
        
        # Track by downloader
        if downloader_name not in self.downloader_stats:
            self.downloader_stats[downloader_name] = {
                'attempts': 0, 'successes': 0, 'failures': 0
            }
        
        stats = self.downloader_stats[downloader_name]
        stats['attempts'] += 1
        if result.success:
            stats['successes'] += 1
        else:
            stats['failures'] += 1
        
        # Track by match quality
        if result.match_quality != MatchQuality.NO_MATCH:
            quality_key = result.match_quality.value
            if quality_key not in self.quality_stats:
                self.quality_stats[quality_key] = 0
            self.quality_stats[quality_key] += 1
    
    @property
    def success_rate(self) -> float:
        """Calculate overall success rate."""
        if self.total_attempts == 0:
            return 0.0
        return self.successful_downloads / self.total_attempts
    
    def get_downloader_success_rate(self, downloader_name: str) -> float:
        """Get success rate for a specific downloader."""
        if downloader_name not in self.downloader_stats:
            return 0.0
        
        stats = self.downloader_stats[downloader_name]
        if stats['attempts'] == 0:
            return 0.0
        
        return stats['successes'] / stats['attempts']
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary for serialization."""
        return {
            'total_attempts': self.total_attempts,
            'successful_downloads': self.successful_downloads,
            'failed_downloads': self.failed_downloads,
            'not_found': self.not_found,
            'rate_limited': self.rate_limited,
            'success_rate': self.success_rate,
            'downloader_stats': self.downloader_stats,
            'quality_stats': self.quality_stats,
            'timestamp': datetime.now().isoformat()
        }


class DownloadManager:
    """Download manager with error handling, statistics, and retry logic."""
    
    def __init__(self, downloaders: List[Downloader], download_path: str, 
                 failed_path: str, enable_retry: bool = True, max_retries: int = 2,
                 stats_file: Optional[str] = None):
        """
        Initialize the download manager.
        
        Args:
            downloaders: List of downloader instances
            download_path: Path where successful downloads will be stored
            failed_path: Path where failed downloads will be logged or moved
            enable_retry: Whether to enable retry logic for failed downloads
            max_retries: Maximum number of retry attempts per track
            stats_file: Optional file to persist download statistics
        """
        # Sort downloaders by priority (lower = higher priority)
        self.downloaders = sorted(downloaders, key=lambda d: d.priority)
        self.download_path = download_path
        self.failed_path = failed_path
        self.enable_retry = enable_retry
        self.max_retries = max_retries
        self.stats_file = stats_file
        
        # Create directories
        os.makedirs(self.download_path, exist_ok=True)
        os.makedirs(self.failed_path, exist_ok=True)
        
        # Initialize statistics
        self.stats = DownloadStats()
        self._load_stats()
        
        # Validate downloaders
        self._validate_downloaders()
        
        logger.info(f"Initialized download manager with {len(self.downloaders)} downloaders")
        for dl in self.downloaders:
            logger.info(f"  - {dl.name} (priority: {dl.priority})")
    
    def _validate_downloaders(self):
        """Validate that all downloaders are properly configured."""
        invalid_downloaders = []
        
        for downloader in self.downloaders:
            try:
                if not downloader.validate_credentials():
                    logger.warning(f"Downloader {downloader.name} has invalid credentials")
                    invalid_downloaders.append(downloader)
                else:
                    logger.info(f"Downloader {downloader.name} validated successfully")
            except Exception as e:
                logger.error(f"Error validating downloader {downloader.name}: {e}")
                invalid_downloaders.append(downloader)
        
        # Remove invalid downloaders
        for invalid in invalid_downloaders:
            self.downloaders.remove(invalid)
        
        if not self.downloaders:
            logger.error("No valid downloaders available!")
    
    def _load_stats(self):
        """Load statistics from file if available."""
        if self.stats_file and os.path.exists(self.stats_file):
            try:
                with open(self.stats_file, 'r') as f:
                    data = json.load(f)
                    
                # Restore basic stats
                self.stats.total_attempts = data.get('total_attempts', 0)
                self.stats.successful_downloads = data.get('successful_downloads', 0)
                self.stats.failed_downloads = data.get('failed_downloads', 0)
                self.stats.not_found = data.get('not_found', 0)
                self.stats.rate_limited = data.get('rate_limited', 0)
                self.stats.downloader_stats = data.get('downloader_stats', {})
                self.stats.quality_stats = data.get('quality_stats', {})
                
                logger.info("Loaded download statistics from file")
            except Exception as e:
                logger.warning(f"Could not load stats file: {e}")
    
    def _save_stats(self):
        """Save statistics to file."""
        if self.stats_file:
            try:
                with open(self.stats_file, 'w') as f:
                    json.dump(self.stats.to_dict(), f, indent=2)
            except Exception as e:
                logger.warning(f"Could not save stats file: {e}")
    
    def _create_folder_name(self, track: Track, downloader: Downloader) -> str:
        """Create a standardized folder name for downloads."""
        # Sanitize strings for filesystem
        def sanitize(s: str) -> str:
            invalid_chars = '<>:"/\\|?*'
            return ''.join(c if c not in invalid_chars else '_' for c in s)
        
        artist = sanitize(track.artist)
        album = sanitize(track.album)
        year = track.release_year
        downloader_name = sanitize(downloader.name)
        
        return f"{artist} - {album} ({year}) [{downloader_name}]"
    
    def _handle_previous_download(self, dl_path: str, failed_file_path: str):
        """Handle previously failed downloads that might be retried."""
        if os.path.exists(failed_file_path):
            try:
                logger.info(f"Moving previously failed download from {failed_file_path}")
                if os.path.exists(dl_path):
                    shutil.rmtree(dl_path)
                shutil.move(failed_file_path, dl_path)
            except Exception as e:
                logger.warning(f"Could not move previous download: {e}")
    
    def _handle_failed_download(self, dl_path: str, failed_file_path: str, 
                               result: DownloadResult, track: Track, downloader: Downloader):
        """Handle a failed download by moving files and logging errors."""
        error_message = f"Downloader {downloader.name} failed for '{track.title}' by '{track.artist}': {result.error_message}\n"
        error_message += f"Status: {result.status.value}\n"
        error_message += f"Match Quality: {result.match_quality.value}\n"
        error_message += f"Timestamp: {datetime.now().isoformat()}\n"
        error_message += "-" * 50 + "\n"
        
        # Log to error file
        error_log_path = os.path.join(self.failed_path, 'errors.log')
        try:
            with open(error_log_path, 'a', encoding='utf-8') as f:
                f.write(error_message)
        except Exception as e:
            logger.error(f"Could not write to error log: {e}")
        
        # Move download directory to failed path
        if os.path.exists(dl_path):
            try:
                if os.path.exists(failed_file_path):
                    shutil.rmtree(failed_file_path)
                shutil.move(dl_path, failed_file_path)
                logger.info(f"Moved failed download to {failed_file_path}")
            except Exception as e:
                logger.error(f"Could not move failed download: {e}")
    
    def enqueue(self, track: Track, retry_count: int = 0) -> DownloadResult:
        """
        Download a track using the available downloaders.
        
        Args:
            track: Track object to download
            retry_count: Current retry attempt (for internal use)
            
        Returns:
            DownloadResult with the final result
        """
        if not self.downloaders:
            return DownloadResult(
                status=DownloadStatus.FAILED,
                error_message="No valid downloaders available"
            )
        
        logger.info(f"Attempting to download: '{track.title}' by '{track.artist}'")
        
        last_result = None
        
        for downloader in self.downloaders:
            logger.info(f"Using {downloader.name} to download '{track.title}'")
            
            # Create folder path
            folder = self._create_folder_name(track, downloader)
            dl_path = os.path.join(self.download_path, folder)
            failed_file_path = os.path.join(self.failed_path, folder)
            
            # Handle previous download attempts
            self._handle_previous_download(dl_path, failed_file_path)
            
            # Ensure download directory exists
            os.makedirs(dl_path, exist_ok=True)
            
            # Attempt download
            try:
                result = downloader.enqueue(
                    path=dl_path,
                    isrc=track.isrc,
                    artist=track.artist,
                    title=track.title,
                    album=track.album
                )
                
                # Record statistics
                self.stats.record_attempt(result, downloader.name)
                
                if result.success:
                    logger.info(f"Successfully downloaded '{track.title}' using {downloader.name}")
                    track.path = dl_path  # Update track with download path
                    self._save_stats()
                    return result
                else:
                    logger.warning(f"Download failed with {downloader.name}: {result.error_message}")
                    self._handle_failed_download(dl_path, failed_file_path, result, track, downloader)
                    last_result = result
                    
                    # If rate limited, don't try other downloaders immediately
                    if result.status == DownloadStatus.RATE_LIMITED:
                        break
                        
            except Exception as e:
                error_msg = f"Unexpected error with {downloader.name}: {str(e)}"
                logger.error(error_msg)
                
                result = DownloadResult(
                    status=DownloadStatus.FAILED,
                    error_message=error_msg
                )
                self.stats.record_attempt(result, downloader.name)
                self._handle_failed_download(dl_path, failed_file_path, result, track, downloader)
                last_result = result
        
        # Handle retries
        if (self.enable_retry and retry_count < self.max_retries and 
            last_result and last_result.status in [DownloadStatus.FAILED, DownloadStatus.TIMEOUT]):
            
            logger.info(f"Retrying download for '{track.title}' (attempt {retry_count + 1}/{self.max_retries})")
            return self.enqueue(track, retry_count + 1)
        
        # All downloaders failed
        final_result = last_result or DownloadResult(
            status=DownloadStatus.FAILED,
            error_message="All downloaders failed"
        )
        
        logger.error(f"Failed to download '{track.title}' after trying all downloaders")
        self._save_stats()
        return final_result
    
    def get_stats(self) -> DownloadStats:
        """Get current download statistics."""
        return self.stats
    
    def print_stats(self):
        """Print formatted statistics to the console."""
        print("\n=== Download Statistics ===")
        print(f"Total attempts: {self.stats.total_attempts}")
        print(f"Successful downloads: {self.stats.successful_downloads}")
        print(f"Failed downloads: {self.stats.failed_downloads}")
        print(f"Not found: {self.stats.not_found}")
        print(f"Rate limited: {self.stats.rate_limited}")
        print(f"Overall success rate: {self.stats.success_rate:.1%}")
        
        if self.stats.downloader_stats:
            print("\n--- Per-Downloader Stats ---")
            for name, stats in self.stats.downloader_stats.items():
                success_rate = stats['successes'] / stats['attempts'] if stats['attempts'] > 0 else 0
                print(f"{name}: {stats['successes']}/{stats['attempts']} ({success_rate:.1%})")
        
        if self.stats.quality_stats:
            print("\n--- Match Quality Distribution ---")
            for quality, count in self.stats.quality_stats.items():
                print(f"{quality}: {count}")
        
        print("=" * 30)
    
    def cleanup(self):
        """Cleanup resources used by downloaders."""
        for downloader in self.downloaders:
            try:
                downloader.cleanup()
            except Exception as e:
                logger.warning(f"Error cleaning up {downloader.name}: {e}")
        
        self._save_stats()
    
    def __del__(self):
        """Ensure cleanup on deletion."""
        self.cleanup()
