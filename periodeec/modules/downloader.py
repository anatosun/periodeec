from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
import logging

logger = logging.getLogger(__name__)


class DownloadStatus(Enum):
    """Status of a download operation."""
    SUCCESS = "success"
    FAILED = "failed"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    RATE_LIMITED = "rate_limited"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"


class MatchQuality(Enum):
    """Quality of a match result."""
    EXACT = "exact"          # Perfect ISRC match
    HIGH = "high"            # Artist + Album + Title match
    MEDIUM = "medium"        # Artist + Title match
    LOW = "low"              # Fuzzy match
    NO_MATCH = "no_match"    # No suitable match found


class DownloadResult:
    """Represents the result of a download operation."""
    
    def __init__(self, 
                 status: DownloadStatus,
                 path: str = "",
                 match_quality: MatchQuality = MatchQuality.NO_MATCH,
                 match_url: str = "",
                 error_message: str = "",
                 metadata: Optional[Dict[str, Any]] = None):
        self.status = status
        self.path = path
        self.match_quality = match_quality
        self.match_url = match_url
        self.error_message = error_message
        self.metadata = metadata or {}
        
    @property
    def success(self) -> bool:
        """Returns True if download was successful."""
        return self.status == DownloadStatus.SUCCESS
    
    def __repr__(self) -> str:
        return f"DownloadResult(status={self.status.value}, path={self.path}, quality={self.match_quality.value})"


class MatchResult:
    """Represents the result of a track matching operation."""
    
    def __init__(self,
                 quality: MatchQuality,
                 url: str = "",
                 confidence: float = 0.0,
                 metadata: Optional[Dict[str, Any]] = None):
        self.quality = quality
        self.url = url
        self.confidence = confidence  # 0.0 to 1.0
        self.metadata = metadata or {}
        
    @property
    def found(self) -> bool:
        """Returns True if a match was found."""
        return self.quality != MatchQuality.NO_MATCH
    
    def __repr__(self) -> str:
        return f"MatchResult(quality={self.quality.value}, url={self.url}, confidence={self.confidence:.2f})"


class Downloader(ABC):
    """Abstract base class for music downloaders."""
    
    def __init__(self, name: str, priority: int = 50, timeout: int = 300):
        """
        Initialize the downloader.
        
        Args:
            name: Human-readable name of the downloader
            priority: Priority for downloader selection (lower = higher priority)
            timeout: Timeout in seconds for download operations
        """
        self.name = name
        self.priority = priority
        self.timeout = timeout
        self._logger = logging.getLogger(f"{__name__}.{name}")
        
    @abstractmethod
    def match(self, isrc: str, artist: str, title: str, album: str = "") -> MatchResult:
        """
        Find the best match for a track.
        
        Args:
            isrc: The ISRC (International Standard Recording Code) of the track
            artist: The artist name associated with the track
            title: The title of the track
            album: The album name (optional)
            
        Returns:
            MatchResult object containing match information
        """
        raise NotImplementedError("The method 'match' must be implemented by the subclass.")
    
    @abstractmethod
    def enqueue(self, path: str, isrc: str, artist: str, title: str, album: str = "") -> DownloadResult:
        """
        Enqueue a download operation.
        
        Args:
            path: Destination path for the downloaded content
            isrc: The ISRC (International Standard Recording Code) of the track
            artist: The artist name
            title: The title of the track
            album: The album name (optional)
            
        Returns:
            DownloadResult object containing the operation result
        """
        raise NotImplementedError("The method 'enqueue' must be implemented by the subclass.")
    
    def get_capabilities(self) -> Dict[str, bool]:
        """
        Return the capabilities of this downloader.
        
        Returns:
            Dictionary of capability flags
        """
        return {
            "supports_isrc_search": True,
            "supports_fuzzy_search": True,
            "supports_album_download": True,
            "supports_batch_download": False,
            "supports_high_quality": True,
            "requires_authentication": True
        }
    
    def validate_credentials(self) -> bool:
        """
        Validate that the downloader's credentials are working.
        
        Returns:
            True if credentials are valid, False otherwise
        """
        return True
    
    def get_rate_limit_info(self) -> Dict[str, Any]:
        """
        Get information about rate limiting for this downloader.
        
        Returns:
            Dictionary containing rate limit information
        """
        return {
            "requests_per_minute": 60,
            "concurrent_downloads": 1,
            "retry_after_seconds": 60
        }
    
    def cleanup(self) -> None:
        """Cleanup resources used by the downloader."""
        pass
    
    def __lt__(self, other) -> bool:
        """Enable sorting by priority."""
        return self.priority < other.priority
    
    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(name={self.name}, priority={self.priority})"
