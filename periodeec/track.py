class Track:
    def __init__(self, title: str, isrc: str, album: str, artist: str, path: str = None):
        """
        Represents a track with relevant metadata.
        """
        self.title = title
        self.isrc = isrc
        self.album = album
        self.artist = artist
        self.path = path  # Optional local path if available

    def __repr__(self):
        return f"Track(title={self.title}, artist={self.artist}, album={self.album}, isrc={self.isrc}, path={self.path})"

    def to_dict(self):
        """Convert track object to dictionary."""
        return {
            "title": self.title,
            "isrc": self.isrc,
            "album": self.album,
            "artist": self.artist,
            "path": self.path
        }
