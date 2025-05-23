import logging
import random
import time
from datetime import datetime
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
from periodeec.playlist import Playlist
from periodeec.track import Track
from periodeec.user import User
import os

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class SpotifyHandler:
    def __init__(self, path: str, client_id: str = "", client_secret: str = "", anonymous: bool = False):
        """
        Initializes the Spotify handler with user authentication.

        :param client_id: Spotify Client ID
        :param client_secret: Spotify Client Secret
        :param path: Path where to store playlists
        """
        if anonymous:
            try:
                from spotipy_anon import SpotifyAnon
            except Exception as e:
                logger.error(
                    f"Failed to load SpotifyAnon, this module must be installed to run Spotify in anonymous mode!")
                exit(1)
            self.auth_manager = SpotifyAnon()
            logger.info("Spotify is running in anonymous mode")
        else:
            if client_id == "" or client_secret == "":
                raise ValueError(
                    "Valid Spotify Client ID and Secret must be provided unless in anonymous mode")
            self.auth_manager = SpotifyClientCredentials(
                client_id=client_id,
                client_secret=client_secret,
            )
        self.sp = spotipy.Spotify(auth_manager=self.auth_manager)
        self.path = os.path.abspath(path)
        logger.info(f"Saving playlists at {self.path}")
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
        fields = "items(track(name,external_ids.isrc,artists(name),album(name,release_date,external_urls(spotify))))"
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
            timeout = int(random.uniform(5, 10))
            time.sleep(timeout)
            logger.info(f"Sleeping for {timeout}s to prevent rate limiting")
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
            if not track_info:
                continue

            external_ids = track_info.get("external_ids") or {}
            isrc = external_ids.get("isrc")
            if not isrc:
                continue

            album_info = track_info.get("album") or {}
            album_name = album_info.get("name", "")
            album_url = (album_info.get("external_urls")
                         or {}).get("spotify", "")
            release_date_str = album_info.get("release_date", "")
            release_year = 1970

            if release_date_str:
                try:
                    release_date = datetime.strptime(
                        release_date_str, "%Y-%m-%d")
                    release_year = release_date.year
                except ValueError:
                    # fallback for release_date formats like "YYYY-MM" or "YYYY"
                    release_year = release_date_str.split("-")[0]

            artists = track_info.get("artists") or []
            artist_name = artists[0].get("name", "")

            title = track_info.get("name", "")

            track = Track(
                title=title,
                isrc=isrc,
                album=album_name,
                album_url=album_url,
                release_year=release_year,
                artist=artist_name,
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
            timeout = int(random.uniform(5, 10))
            time.sleep(timeout)
            logger.info(f"Sleeping for {timeout}s to prevent rate limiting")
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
            external_urls = playlist.get("external_urls") or {}
            url = external_urls.get("spotify")
            if not url:
                continue

            playlist_id = playlist.get("id", "")
            title = playlist.get("name", "")
            description = playlist.get("description", "")
            snapshot_id = playlist.get("snapshot_id", "")
            images = playlist.get("images") or []
            poster = images[0]["url"] if images else ""

            tracks_info = playlist.get("tracks") or {}
            number_of_tracks = tracks_info.get("total", 0)

            path = os.path.join(self.path, f"{playlist_id}.json")

            playlist_obj = Playlist(
                title=title,
                tracks=[],  # Tracks will be fetched later
                id=playlist_id,
                path=path,
                number_of_tracks=number_of_tracks,
                description=description,
                snapshot_id=snapshot_id,
                poster=poster,
                summary=description,
                url=url
            )
            parsed_playlists.append(playlist_obj)

        return parsed_playlists
