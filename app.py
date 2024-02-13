from dataclasses import dataclass
import logging
import os
import time
import random
import spotipy
import json
import deemix_dl
import tidal_dl
import beets


@dataclass
class Environment:
    library_path: str
    downloaders: str
    deemix_path: str
    tidal_dl_path: str
    freyr_path: str
    beets_path: str
    config_path: str
    download_path: str
    tidal_client_id: str
    tidal_client_secret: str
    deezer_arl: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_usernames: str
    interval: int


# Read ENV variables
env = Environment(
    library_path=os.getenv("PERIODEEC_LIBRARY_PATH", "/music"),
    downloaders=os.getenv("PERIODEEC_DOWNLOADERS", "deemix"),
    deemix_path=os.getenv("DEEMIX_PATH", "/usr/bin/deemix"),
    tidal_dl_path=os.getenv("TIDAL_DL_PATH", "/usr/bin/tidal-dl"),
    freyr_path=os.getenv("FREYR_PATH", "/usr/bin/freyr"),
    beets_path=os.getenv("BEETS_PATH", "/usr/bin/beet"),
    config_path=os.getenv("PERIODEEC_CONFIG_PATH", "/config"),
    download_path=os.getenv("PERIODEEC_DOWNLOAD_PATH", "/downloads"),
    tidal_client_id=os.getenv("TIDAL_CLIENT_ID", ""),
    tidal_client_secret=os.getenv("TIDAL_CLIENT_SECRET", ""),
    deezer_arl=os.getenv("DEEZER_ARL", ""),
    spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
    spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", ""),
    spotify_usernames=os.getenv("SPOTIFY_USERNAMES", ""),
    interval=int(os.getenv("INTERVAL", "")),
)

logging.basicConfig(
    # filename=os.path.join(env.config_path, "logs"),
    format='%(asctime)s %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.INFO)
deemix = deemix_dl.Deemix(env.deezer_arl, env.deemix_path)
tidal = tidal_dl.Tidal(env.tidal_client_id,
                       env.tidal_client_secret, tidal_dl=env.tidal_dl_path)
beets = beets.Beets(library_path=env.library_path, beet=env.beets_path)
not_found_file = os.path.join(env.config_path, "not_found.txt")


def get_playlist_tracks(sp: spotipy.Spotify, playlist_link: str, playlist_name: str, number_of_tracks: int) -> list:
    try:
        playlist_tracks = sp.playlist_tracks(
            playlist_link, limit=100, offset=0, fields="items(id,track(name,external_ids.isrc,href,album(name,id,href,external_urls.spotify,external_ids.upc)))")
        playlist_tracks = playlist_tracks["items"]
    except Exception as e:
        logging.error(f"skipping playlist '{playlist_name}': {e}")
        return []

    while len(playlist_tracks) < number_of_tracks:
        time.sleep(random.uniform(1, 5))
        try:
            playlist_track_continued = sp.playlist_tracks(
                playlist_link, limit=100, offset=len(playlist_tracks), fields="items(id,track(name,external_ids.isrc,href,album(name,id,href,external_urls.spotify,external_ids.upc)))")
            playlist_tracks.extend(playlist_track_continued["items"])
        except Exception as e:
            logging.error(
                f"error getting '{playlist_name}' tracks at offset {len(playlist_tracks)}: {e}")
            return playlist_tracks

    return playlist_tracks


def get_username_playlists(sp: spotipy.Spotify, username: str,  force=False, offset=0, items=[]) -> list:

    queued_playlists = []
    number_of_playlists = 0
    try:
        user_playlists = sp.user_playlists(username, limit=50)
        number_of_playlists = user_playlists["total"]

    except Exception as e:
        logging.error(f"skipping user {username}: {e}")
        return queued_playlists

    if user_playlists is None:
        logging.error(f"skipping user {username}: playlists not found")
        return queued_playlists

    playlists = user_playlists["items"]

    while len(playlists) < number_of_playlists:
        try:
            user_playlists = sp.user_playlists(
                username, limit=50, offset=len(playlists))
            playlists.extend(user_playlists["items"])
        except Exception as e:
            logging.error(
                f"error getting '{username} playlists at offset {len(playlists)}: {e}")

    for playlist in playlists:
        playlist_name = playlist["name"]
        owner = playlist["owner"]["id"]
        snapshot_id = playlist["snapshot_id"]

        if not os.path.exists(f"{env.config_path}/cache/playlists/{owner}"):
            os.makedirs(f"{env.config_path}/cache/playlists/{owner}")

        playlist_path = f"{env.config_path}/cache/playlists/{owner}/{playlist_name}.json"

        if os.path.exists(playlist_path) and not force:
            with open(playlist_path, "r") as f:
                data = json.load(f)
                if data["snapshot_id"] == snapshot_id:
                    continue

        queued_playlists.append((playlist, playlist_path))
    return queued_playlists


def download_tracks(sp: spotipy.Spotify, tracks: list):

    for track in tracks:
        track_name = track["track"]["name"]
        isrc = track["track"]["external_ids"].get("isrc")
        album = track["track"]["album"]
        album_id = album["id"]
        album_link = album["external_urls"]["spotify"]
        album_name = album["name"]

        if isrc is None:
            logging.info(
                f"skipping {track_name}: isrc not found")
            continue

        exists, path = beets.exists(isrc)

        if exists:
            logging.debug(
                f"skipping {track_name}: already exists at {path}")
            continue

        success = False
        err = ""
        path = ""
        if "deemix" in env.downloaders:
            logging.debug(
                f"queuing {album_name} in Deemix")
            success, path, err = deemix.enqueue(env.download_path, isrc)

        if not success:
            logging.error(
                f"failed to download album {album_name} in Deemix: {err}")
            continue

        if not os.path.exists(path):
            logging.error(
                f"failed to download album {album_name}: directory {path} doesn't exist")
            continue

        with open(os.path.join(path, "spotify.json"), "w") as f:
            json.dump(album, f)

        success, e = beets.add(path=path, search_id=album_link)

        if success:
            logging.info(
                f"added {album_name} to beets library")
            continue
        else:
            logging.error(
                f"failed to add {album_name} to beets library: {e}")


def download(sp: spotipy.Spotify, force=False) -> None:
    usernames = env.spotify_usernames.split(",")
    for username in usernames:

        queued_playlists = get_username_playlists(
            sp=sp, username=username, force=force)

        for playlist, playlist_path in queued_playlists:

            playlist_link = playlist["external_urls"]["spotify"]
            number_of_tracks = playlist["tracks"]["total"]
            playlist_name = playlist["name"]
            logging.info(
                f"queuing playlist '{playlist_name}' from '{username}' profile")

            tracks = get_playlist_tracks(
                sp=sp,
                playlist_link=playlist_link,
                playlist_name=playlist_name,
                number_of_tracks=number_of_tracks)

            download_tracks(sp=sp, tracks=tracks)

            with open(playlist_path, "w") as f:
                json.dump(playlist, f)


def main():

    while True:
        ccm = spotipy.SpotifyClientCredentials(
            env.spotify_client_id, env.spotify_client_secret,
        )
        sp = spotipy.Spotify(client_credentials_manager=ccm)

        download(sp=sp)

        logging.info(f"sleeping for {env.interval} seconds")
        time.sleep(env.interval)


if __name__ == "__main__":
    main()
