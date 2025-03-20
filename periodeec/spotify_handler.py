import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from periodeec.playlist import Playlist
from periodeec.track import Track
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SpotifyHandler:
    def __init__(self, client_id: str, client_secret: str, path="/config/.playlists"):
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
        if not os.path.exists(self.path):
            os.makedirs(self.path)

    def tracks(self, url: str) -> list:
        """
        Fetches all tracks from a Spotify playlist and returns a Playlist object.
        """
        playlist_id = url.split("/")[-1]
        error_msg = f"Skipping playlist '{url}'"
        tracks = []

        try:
            playlist_data = self.sp.playlist(playlist_id=playlist_id)
        except Exception as e:
            logger.error(f"{error_msg}: {e}")
            return tracks

        if not playlist_data or not playlist_data.get("tracks") or not playlist_data["tracks"].get("items"):
            return tracks

        for item in playlist_data["tracks"]["items"]:
            track_info = item.get("track")
            if track_info and track_info.get("external_ids") and track_info["external_ids"].get("isrc"):
                track = Track(
                    title=track_info["name"],
                    isrc=track_info["external_ids"]["isrc"],
                    album=track_info["album"]["name"],
                    artist=track_info["album"]["artists"][0]["name"],
                    path=""
                )
                tracks.append(track)

        return tracks

    def playlists(self, username: str) -> list[Playlist]:
        """
        Fetches all playlists from a Spotify user and returns a list of Playlist objects.
        """
        logger.info(f"Fetching playlists for user {username}")
        limit, total = 50, 0

        try:
            playlists_data = self.sp.user_playlists(username, limit=limit)
            if not playlists_data or not playlists_data.get("items"):
                logger.error(f"Skipping user {username}: No playlists found")
                return []
            total = playlists_data["total"]
        except Exception as e:
            logger.error(f"Skipping user {username}: {e}")
            return []

        playlists = []
        for playlist in playlists_data["items"]:
            if playlist.get("external_urls") and playlist["external_urls"].get("spotify"):
                playlist_obj = Playlist(
                    title=playlist["name"],
                    tracks=[],  # Tracks will be fetched later
                    id=playlist["id"],
                    path=self.path,
                    description=playlist.get("description", ""),
                    snapshot_id=playlist.get("snapshot_id", ""),
                    poster=playlist["images"][0]["url"] if playlist.get(
                        "images") else "",
                    summary=playlist.get("description", ""),
                    url=playlist["external_urls"]["spotify"]
                )
                playlists.append(playlist_obj)

        logger.info(
            f"Fetched {len(playlists)}/{total} playlists for user {username}")
        return playlists
