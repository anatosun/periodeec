from periodeec.track import Track
import logging
import json
import os
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


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
                logger.info(
                    f"Playlist {self.title} exists at path {self.path}")
                with open(self.path, "r") as f:
                    data = json.load(f)
                    if data.get("tracks") is not None:
                        self.tracks = [Track(**track)
                                       for track in data["tracks"]]
                        logger.info(
                            f"Loaded {len(self.tracks)} tracks from cache")

                    if data["snapshot_id"] == self.snapshot_id:
                        self.uptodate = True
                        logger.info(f"Playlist {self.title} is up-to-date")
                    if data.get("users") is not None:
                        self.users = data["users"]

        except Exception as e:
            logger.error(e)

    def save(self):
        logger.info(
            f"Saving playlist {self.title} with snapshot {self.snapshot_id}")
        with open(self.path, "w") as f:
            json.dump(self.to_dict(), f)

    def update_for(self, username):
        self.users[username] = self.snapshot_id

    def is_up_to_date(self):
        return self.uptodate

    def update_tracklist(self, tracks, old_tracks):

        if len(old_tracks) > 0:
            logger.info(
                f"Updating tracklist for {self.title} (new: {len(tracks)}), old: {len(old_tracks)}")
            for track in tracks:
                for old in old_tracks:
                    if track.isrc == old.isrc:
                        logger.debug(f"Found {track.title} at path {old.path}")
                        track.path = old.path
                        old_tracks.remove(old)
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
