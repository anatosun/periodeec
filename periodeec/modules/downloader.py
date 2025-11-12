from abc import ABC, abstractmethod
from typing import Optional
from dataclasses import dataclass


@dataclass
class MatchResult:
    """Result of a track/album match operation."""
    success: bool
    url: str = ""
    match_method: str = ""  # e.g., "isrc", "fuzzy", "artist_title"
    confidence: float = 0.0  # 0.0 to 1.0
    error_message: str = ""


@dataclass
class DownloadResult:
    """Result of a download operation."""
    success: bool
    path: str
    error_message: str = ""
    downloaded_files: list[str] | None = None


class Downloader(ABC):
    """
    Abstract base class for music downloaders.

    Implementations must provide methods for matching tracks and downloading content.
    All downloaders should handle errors gracefully and provide detailed logging.
    """

    def __init__(self, name: str):
        self.name = name
        self._is_available: Optional[bool] = None

    @abstractmethod
    def match(
        self,
        isrc: str,
        artist: str,
        title: str,
        album: str = "",
        release_year: int = 0
    ) -> MatchResult:
        """
        Match a track or album based on ISRC, artist, and title.

        Args:
            isrc: The ISRC (International Standard Recording Code) of the track.
            artist: The artist name associated with the track.
            title: The title of the track or album.
            album: The album name (optional, for better matching).
            release_year: The release year (optional, for validation).

        Returns:
            MatchResult containing success status, URL, match method, and confidence.
        """
        raise NotImplementedError(
            "The method 'match' must be implemented by the subclass.")

    @abstractmethod
    def enqueue(
        self,
        path: str,
        isrc: str,
        artist: str,
        title: str,
        album: str = "",
        release_year: int = 0
    ) -> DownloadResult:
        """
        Enqueue and execute a download.

        Args:
            path: Destination path for the downloaded content.
            isrc: The ISRC (International Standard Recording Code) of the track.
            artist: The artist name.
            title: The title of the track or album.

        Returns:
            DownloadResult with success status, path, and any error messages.
        """
        raise NotImplementedError(
            "The method 'enqueue' must be implemented by the subclass.")

    def is_available(self) -> bool:
        """
        Check if the downloader is available and properly configured.

        Returns:
            True if the downloader can be used, False otherwise.
        """
        if self._is_available is None:
            self._is_available = self._check_availability()
        return self._is_available

    def _check_availability(self) -> bool:
        """
        Internal method to check downloader availability.
        Should be overridden by subclasses for specific checks.

        Returns:
            True if available, False otherwise.
        """
        return True
