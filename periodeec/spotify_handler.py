import logging
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from periodeec.playlist import Playlist
from periodeec.track import Track


class SpotifyHandler:
    def __init__(self, client_id: str, client_secret: str, redirect_uri: str = "http://localhost:8080"):
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

    def fetch_playlist_tracks(self, url: str) -> Playlist:
        """
        Fetches all tracks from a Spotify playlist and returns a Playlist object.
        """
        playlist_id = url.split("/")[-1]
        error_msg = f"Skipping playlist '{url}'"

        try:
            playlist_data = self.sp.playlist(playlist_id=playlist_id)
        except Exception as e:
            logging.error(f"{error_msg}: {e}")
            return Playlist(title="Unknown", tracks=[], url=url)

        if not playlist_data or not playlist_data.get("tracks") or not playlist_data["tracks"].get("items"):
            logging.error(f"{error_msg}: No tracks found")
            if playlist_data and playlist_data.get("name"):
                title = playlist_data["name"]
            else:
                title = "None"
            return Playlist(title=title, tracks=[], url=url)

        tracks = []
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

        return Playlist(
            title=playlist_data["name"],
            tracks=tracks,
            description=playlist_data.get("description", ""),
            snapshot_id=playlist_data.get("snapshot_id", ""),
            poster=playlist_data["images"][0]["url"] if playlist_data.get(
                "images") else "",
            summary=playlist_data.get("description", ""),
            url=playlist_data["external_urls"]["spotify"]
        )

    def fetch_playlists_from_user(self, username: str) -> list[Playlist]:
        """
        Fetches all playlists from a Spotify user and returns a list of Playlist objects.
        """
        logging.info(f"Fetching playlists for user {username}")
        limit, total = 50, 0

        try:
            playlists_data = self.sp.user_playlists(username, limit=limit)
            if not playlists_data or not playlists_data.get("items"):
                logging.error(f"Skipping user {username}: No playlists found")
                return []
            total = playlists_data["total"]
        except Exception as e:
            logging.error(f"Skipping user {username}: {e}")
            return []

        playlists = []
        for playlist in playlists_data["items"]:
            if playlist.get("external_urls") and playlist["external_urls"].get("spotify"):
                playlist_obj = Playlist(
                    title=playlist["name"],
                    tracks=[],  # Tracks will be fetched later
                    description=playlist.get("description", ""),
                    snapshot_id=playlist.get("snapshot_id", ""),
                    poster=playlist["images"][0]["url"] if playlist.get(
                        "images") else "",
                    summary=playlist.get("description", ""),
                    url=playlist["external_urls"]["spotify"]
                )
                playlists.append(playlist_obj)

        logging.info(
            f"Fetched {len(playlists)}/{total} playlists for user {username}")
        return playlists

    def populate_playlist(self, playlist: Playlist):
        """
        Populates a given playlist with its corresponding tracks.
        """
        detailed_playlist = self.fetch_playlist_tracks(playlist.url)
        playlist.tracks = detailed_playlist.tracks
