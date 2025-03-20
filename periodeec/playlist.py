from periodeec.track import Track
import logging
import json
import os


class Playlist:
    def __init__(self, title: str, tracks: list[Track], id: str, path: str, description: str = "", snapshot_id: str = "", poster: str = "", summary: str = "", url: str = ""):
        """
        Represents a Spotify/Plex playlist.
        """
        self.title = title
        self.tracks = tracks  # List of Track objects
        self.description = description
        self.snapshot_id = snapshot_id  # Unique identifier for updates
        self.poster = poster  # Playlist poster image URL
        self.summary = summary  # Playlist summary/description
        self.url = url  # Link to the original Spotify playlist
        self.id = id
        self.path = os.path.join(os.path.abspath(path), f"{id}.json")

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self, f)

    def is_up_to_date(self):
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                data = json.load(f)
                if data["snapshot_id"] == self.snapshot_id:
                    logging.info(f"{self.title}: already downloaded")
                    return True
        return False

    def __repr__(self):
        return f"Playlist(title={self.title}, tracks={len(self.tracks)}, description={self.description}, snapshot_id={self.snapshot_id}, poster={self.poster}, summary={self.summary}, url={self.url})"

    def to_dict(self):
        """Convert playlist object to dictionary."""
        return {
            "title": self.title,
            "tracks": [track.to_dict() for track in self.tracks],
            "description": self.description,
            "snapshot_id": self.snapshot_id,
            "poster": self.poster,
            "summary": self.summary,
            "url": self.url
        }

    def add_track(self, track: Track):
        """Add a track to the playlist."""
        self.tracks.append(track)

    def remove_track(self, isrc: str):
        """Remove a track from the playlist by ISRC."""
        self.tracks = [track for track in self.tracks if track.isrc != isrc]

    def get_tracklist(self):
        """Return a list of track titles."""
        return [track.title for track in self.tracks]
