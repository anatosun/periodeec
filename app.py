from dataclasses import dataclass
import logging
import os
import time
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

logging.basicConfig(level=logging.INFO)
deemix = deemix_dl.Deemix(env.deezer_arl, env.deemix_path)
tidal = tidal_dl.Tidal(env.tidal_client_id,
                       env.tidal_client_secret, tidal_dl=env.tidal_dl_path)
beets = beets.Beets(library_path=env.library_path, beet=env.beets_path)
not_found_file = os.path.join(env.config_path, "not_found.txt")
not_found = set()


def download(sp: spotipy.Spotify) -> None:

    usernames = env.spotify_usernames.split(",")
    for username in usernames:

        try:
            user_playlists = sp.user_playlists(username)
        except Exception as e:
            logging.error(f"skipping user {username}: {e}")
            continue

        if user_playlists is None:
            logging.error(f"skipping user {username}: playlists not found")

        for playlist in user_playlists["items"]:
            playlist_name = playlist["name"]
            playlist_link = playlist["external_urls"]["spotify"]
            owner = playlist["owner"]["id"]
            snapshot_id = playlist["snapshot_id"]
            number_of_tracks = playlist["tracks"]["total"]

            if not os.path.exists(f"{env.config_path}/cache/playlists/{owner}"):
                os.makedirs(f"{env.config_path}/cache/playlists/{owner}")

            playlist_path = f"{env.config_path}/cache/playlists/{owner}/{playlist_name}.json"
            if os.path.exists(playlist_path):
                with open(playlist_path, "r") as f:
                    data = json.load(f)
                    if data["snapshot_id"] == snapshot_id:
                        logging.info(
                            f"skipping {playlist_name}: already downloaded and no changes detected")
                        continue

            k = number_of_tracks // 100
            r = 1 if number_of_tracks > k * 100 else 0

            for i in range(k + r):

                try:
                    playlist_tracks = sp.playlist_tracks(
                        playlist_link, limit=100, offset=i)
                except Exception as e:
                    logging.error(f"skipping playlist {playlist_name}: {e}")
                    continue

                for track in playlist_tracks["items"]:

                    track_name = track["track"]["name"]
                    isrc = track["track"]["external_ids"].get("isrc")

                    if isrc is None:
                        logging.error(
                            f"skipping {track_name}: isrc not found")
                        continue

                    exists, path = beets.exists(isrc)

                    if exists:
                        logging.info(
                            f"skipping {track_name}: already exists at {path}")
                        continue

                    album = track["track"]["album"]
                    album_name = album["name"]
                    album_link = album["external_urls"]["spotify"]
                    album_id = album["id"]

                    try:
                        album = sp.album(album_link)
                    except Exception as e:
                        logging.error(f"skipping track {track_name}: {e}")
                        continue

                    upc = album["external_ids"].get("upc")

                    if upc in not_found:
                        logging.info(
                            f"skipping track {track_name}: album upc previously not found")
                        continue

                    if upc is None:
                        logging.error(
                            f"skipping track {track_name}: album upc not found")
                        continue

                    success = False
                    err = ""
                    if "deemix" in env.downloaders:
                        logging.info(
                            f"queuing {album_name} in Deemix")
                        success, path, err = deemix.enqueue(
                            upc, env.download_path)

                    if not success:
                        logging.error(
                            f"failed to download album {album_name}: {err}")

                    if not success and "tidal" in env.downloaders:
                        logging.info(
                            f"queuing {album_name} in Tidal")
                        success, path, err = tidal.enqueue(
                            upc, env.download_path)

                    if not success:
                        logging.error(
                            f"failed to download album {album_name}: {err}")
                        not_found.add(upc)
                        continue

                    if not os.path.exists(path):
                        logging.error(
                            f"failed to download album {album_name}: directory {path} doesn't exist")
                        not_found.add(upc)
                        continue

                    with open(os.path.join(path, "spotify.json"), "w") as f:
                        json.dump(album, f)

                    success = beets.add(path=path, search_id=album_id)

                    if success:
                        logging.info(
                            f"added {album_name} to beets library")
                    else:
                        logging.error(
                            f"failed to add {album_name} to beets library")
                        time.sleep(5)

                    time.sleep(1)

            with open(playlist_path, "w") as f:
                json.dump(playlist, f)


def main():

    while True:
        ccm = spotipy.SpotifyClientCredentials(
            env.spotify_client_id, env.spotify_client_secret,
        )
        sp = spotipy.Spotify(client_credentials_manager=ccm)
        not_found = set(line.strip() for line in open(not_found_file))
        download(sp)
        with open(not_found_file, "w") as f:
            for upc in not_found:
                f.write(f"{upc}\n")
        logging.info(f"sleeping for {env.interval} seconds")
        time.sleep(env.interval)


if __name__ == "__main__":
    main()
