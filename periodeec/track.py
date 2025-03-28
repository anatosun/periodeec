class Track:
    def __init__(self, title: str, isrc: str, album: str, album_url: str, release_year: int, artist: str, path: str = ""):
        """
        Represents a track with relevant metadata.
        """
        self.title = title
        self.isrc = isrc
        self.album = album
        self.album_url = album_url
        self.release_year = release_year
        self.artist = artist
        self.path = path  # Optional local path if available

    def __repr__(self):
        return f"Track(title={self.title}, artist={self.artist}, album={self.album}, album_url={self.album_url}, isrc={self.isrc}, path={self.path})"

    def to_dict(self):
        """Convert track object to dictionary."""
        return {
            "title": str(self.title),
            "isrc": str(self.isrc),
            "album": str(self.album),
            "album_url": str(self.album_url),
            "release_year": str(self.release_year),
            "artist": str(self.artist),
            "path": str(self.path)
        }
