from abc import ABC, abstractmethod


class Downloader(ABC):
    def __init__(self, name: str):
        self.name = name

    @abstractmethod
    def match(self, isrc: str, artist: str, title: str) -> str:
        """
        Abstract method to match a track or album based on ISRC, artist, and title.
        Args:
            isrc: The ISRC (International Standard Recording Code) of the track.
            artist: The artist name associated with the track.
            title: The title of the track or album.

        Returns:
            A URL to the matched track or album.
        """
        raise NotImplementedError(
            "The method 'match' must be implemented by the subclass.")

    @abstractmethod
    def enqueue(self, path: str, isrc: str, artist: str, title: str) -> tuple[bool, str]:
        """
        Abstract method to enqueue a download.
        Args:
            path: Destination path for the downloaded content.
            isrc: The ISRC (International Standard Recording Code) of the track.
            artist: The artist name.
            title: The title of the track or album.

        Returns:
            A tuple with a boolean indicating success and the path.
        """
        raise NotImplementedError(
            "The method 'enqueue' must be implemented by the subclass.")
