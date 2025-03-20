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
        self.uptodate = False
        self.description = description
        self.snapshot_id = snapshot_id  # Unique identifier for updates
        self.poster = poster  # Playlist poster image URL
        self.summary = summary  # Playlist summary/description
        self.url = url  # Link to the original Spotify playlist
        self.id = id
        self.users = {}
        self.path = os.path.join(os.path.abspath(path), f"{id}.json")
        try:
            if os.path.exists(self.path):
                with open(self.path, "r") as f:
                    data = json.load(f)
                    if data.get("tracks") is not None:
                        self.tracks = data["tracks"]
                    if data["snapshot_id"] == self.snapshot_id:
                        self.uptodate = True
                    if data.get("users") is not None:
                        self.users = data["users"]

        except Exception as e:
            logging.error(e)

    def save(self):
        with open(self.path, "w") as f:
            json.dump(self.to_dict(), f)

    def update_for(self, username):
        self.users[username] = self.snapshot_id

    def is_up_to_date(self):
        return self.uptodate

    def update_tracklist(self, tracks, old_tracks):

        for track in tracks:
            for old in old_tracks:
                if track.isrc == old.isrc:
                    track.path = old.path
                    break

        return tracks

    def is_up_to_date_for(self, username):

        if self.users.get(username) is None:
            return False

        return self.users[username] == self.snapshot_id

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
            "url": self.url,
            "id": self.id,
            "path": self.path,
            "users": self.users
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
