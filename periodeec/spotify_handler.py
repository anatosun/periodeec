import logging
import random
import time
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from periodeec.playlist import Playlist
from periodeec.track import Track
from periodeec.user import User
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SpotifyHandler:
    def __init__(self, client_id: str, client_secret: str, path: str):
        """
        Initializes the Spotify handler with user authentication.

        :param client_id: Spotify Client ID
        :param client_secret: Spotify Client Secret
        :param redirect_uri: Redirect URI for Spotify authentication (default: http://localhost:8080)
        """
        self.auth_manager = SpotifyClientCredentials(
            client_id=client_id,
            client_secret=client_secret,
        )
        self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
        self.path = os.path.abspath(path)
        logging.info(f"Saving playlists at {self.path}")
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def user(self, username) -> User:

        user = self.sp.user(username)
        if user is None:
            logger.error(f"Error fetching data for user '{username}'")
            return User(id=username)

        return User(
            id=username,
            name=user.get("display_name"),
            url=user["external_urls"].get("spotify"),
            uri=user.get("uri")
        )

    def tracks(self, url: str,  number_of_tracks: int) -> list[Track]:
        """
        Fetches all tracks from a Spotify playlist and returns a list of Track objects.
        """
        tracks = []
        limit = 100
        offset = 0
        fields = "items(track(name,external_ids.isrc,album(name,artists(name),external_urls(spotify))))"
        error_msg = f"Skipping playlist '{url}'"

        try:
            playlist_tracks = self.sp.playlist_items(
                url, limit=limit, offset=offset, fields=fields)
            if not playlist_tracks or not playlist_tracks.get("items"):
                logger.error(f"{error_msg}: tracks not found")
                return []
        except Exception as e:
            logger.error(f"{error_msg}: {e}")
            return []

        tracks.extend(self.extract_tracks(playlist_tracks["items"]))
        offset = len(tracks)

        while offset < number_of_tracks:
            # Rate-limiting to avoid hitting API limits
            time.sleep(random.uniform(3, 5))
            error_offset_msg = f"Error getting '{url}' tracks at offset {offset}"
            try:
                playlist_tracks = self.sp.playlist_items(
                    url, limit=limit, offset=offset, fields=fields)
                if not playlist_tracks or not playlist_tracks.get("items"):
                    logger.error(error_offset_msg)
                    return tracks
                tracks.extend(self.extract_tracks(playlist_tracks["items"]))
                offset = len(tracks)
            except Exception as e:
                logger.error(f"{error_offset_msg}: {e}")
                return tracks

        return tracks

    def extract_tracks(self, items: list) -> list[Track]:
        """Helper method to parse track data."""
        parsed_tracks = []
        for item in items:
            track_info = item.get("track")
            if track_info and track_info.get("external_ids") and track_info["external_ids"].get("isrc"):
                track = Track(
                    title=track_info["name"],
                    isrc=track_info["external_ids"]["isrc"],
                    album=track_info["album"]["name"],
                    album_url=track_info["album"]["external_urls"].get(
                        "spotify"),
                    artist=track_info["album"]["artists"][0]["name"],
                    path=""
                )
                parsed_tracks.append(track)
        return parsed_tracks

    def playlists(self, username: str) -> list[Playlist]:
        """
        Fetches all playlists from a Spotify user and returns a list of Playlist objects.
        """
        logger.info(f"Fetching playlists for user {username}")
        limit, offset = 50, 0
        playlists = []
        error_msg = f"Skipping user {username}"

        try:
            playlists_data = self.sp.user_playlists(
                username, limit=limit, offset=offset)
            if not playlists_data or not playlists_data.get("items"):
                logger.error(f"{error_msg}: No playlists found")
                return []
            total = playlists_data.get("total", len(playlists_data["items"]))
        except Exception as e:
            logger.error(f"{error_msg}: {e}")
            return []

        playlists.extend(self.extract_playlists(playlists_data["items"]))
        offset = len(playlists)

        while offset < total:
            # Rate-limiting to avoid API limits
            time.sleep(random.uniform(3, 5))
            error_offset_msg = f"Error fetching playlists for user {username} at offset {offset}"
            try:
                playlists_data = self.sp.user_playlists(
                    username, limit=limit, offset=offset)
                if not playlists_data or not playlists_data.get("items"):
                    logger.error(error_offset_msg)
                    return playlists
                playlists.extend(self.extract_playlists(
                    playlists_data["items"]))
                offset = len(playlists)
            except Exception as e:
                logger.error(f"{error_offset_msg}: {e}")
                return playlists

        logger.info(
            f"Fetched {len(playlists)}/{total} playlists for user {username}")
        return playlists

    def extract_playlists(self, items: list) -> list[Playlist]:
        """Helper method to parse playlist data."""
        parsed_playlists = []
        for playlist in items:
            if playlist.get("external_urls") and playlist["external_urls"].get("spotify"):
                playlist_obj = Playlist(
                    title=playlist["name"],
                    tracks=[],  # Tracks will be fetched later
                    id=playlist["id"],
                    path=os.path.join(
                        self.path, f"{str(playlist['id'])}.json"),
                    number_of_tracks=playlist["tracks"]["total"],
                    description=playlist.get("description", ""),
                    snapshot_id=playlist.get("snapshot_id", ""),
                    poster=playlist["images"][0]["url"] if playlist.get(
                        "images") else "",
                    summary=playlist.get("description", ""),
                    url=playlist["external_urls"]["spotify"]
                )
                parsed_playlists.append(playlist_obj)
        return parsed_playlists
