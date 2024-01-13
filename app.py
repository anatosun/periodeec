from dataclasses import dataclass
import logging
import os
import time
import requests
import spotipy
import json

s = requests.Session()
logging.basicConfig(level=logging.INFO)


@dataclass
class Environment:
    config_path: str
    mode: str
    deemix_url: str
    deezer_email: str
    deezer_password: str
    deezer_arl: str
    spotify_client_id: str
    spotify_client_secret: str
    spotify_usernames: str
    interval: int


# Read ENV variables
env = Environment(
    config_path=os.getenv("CONFIG_PATH", "/config"),
    mode=os.getenv("EXECUTION_MODE", "albums"),
    deemix_url=os.getenv("DEEMIX_URL", "http://localhost:6595"),
    deezer_email=os.getenv("DEEZER_EMAIL", ""),
    deezer_password=os.getenv("DEEZER_PASSWORD", ""),
    deezer_arl=os.getenv("DEEZER_ARL", ""),
    spotify_client_id=os.getenv("SPOTIFY_CLIENT_ID", ""),
    spotify_client_secret=os.getenv("SPOTIFY_CLIENT_SECRET", ""),
    spotify_usernames=os.getenv("SPOTIFY_USERNAMES", ""),
    interval=int(os.getenv("INTERVAL", "")),
)


def login():
    try:
        response = s.post(
            f"{env.deemix_url}/api/loginEmail",
            json={
                "accessToken": "",
                "email": env.deezer_email,
                "password": env.deezer_password,
            },
        )
        if response.json().get("arl") is not None:
            arl = response.json()["arl"]
        else:
            arl = env.deezer_arl
        response = s.post(f"{env.deemix_url}/api/loginArl", json={"arl": arl})
        logging.info(
            f"loging user {env.deezer_email}: {response.json()['status']==1}")
        return response.json()["status"] == 1
    except Exception as e:
        logging.error(e)
        return False


def enqueue(url: str) -> bool:

    response = s.post(
        f"{env.deemix_url}/api/addToQueue",
        json={
            "bitrate": "null",
            "url": url,
        },
    )

    return True


def download() -> None:
    ccm = spotipy.SpotifyClientCredentials(
        env.spotify_client_id, env.spotify_client_secret
    )
    sp = spotipy.Spotify(client_credentials_manager=ccm)
    usernames = env.spotify_usernames.split(",")
    for username in usernames:
        user_playlists = sp.user_playlists(username)
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

            if env.mode == "playlists":
                logging.info(f"queuing {playlist_name}")
                enqueue(playlist_link)
                time.sleep(1)
            else:
                k = number_of_tracks // 100
                r = 1 if number_of_tracks > k * 100 else 0

                for i in range(k + r):

                    playlist_tracks = sp.playlist_tracks(
                        playlist_link, limit=100, offset=i)
                    for track in playlist_tracks["items"]:
                        track_name = track["track"]["name"]
                        track_link = track["track"]["external_urls"]["spotify"]
                        track_id = track["track"]["id"]
                        track_path = f"{env.config_path}/cache/tracks/{track_id}.json"

                        if not os.path.exists(f"{env.config_path}/cache/tracks"):
                            os.makedirs(f"{env.config_path}/cache/tracks")
                        if not os.path.exists(f"{env.config_path}/cache/albums"):
                            os.makedirs(f"{env.config_path}/cache/albums")

                        if env.mode == "tracks":

                            if os.path.exists(track_path):
                                with open(track_path) as f:
                                    data = json.load(f)
                                    if data["track"]["id"] == track_id:
                                        logging.info(
                                            f"skipping {track_name}: already downloaded")
                                        continue
                            logging.info(
                                f"queuing {track_name} from {playlist_name} offset {i}")
                            success = enqueue(track_link)
                            if success:
                                with open(track_path, "w") as f:
                                    json.dump(track, f)
                            time.sleep(1)
                        else:
                            album = track["track"]["album"]
                            album_name = album["name"]
                            album_link = album["external_urls"]["spotify"]
                            album_id = album["id"]
                            album_path = f"{env.config_path}/cache/albums/{album_id}.json"
                            if os.path.exists(album_path):
                                with open(album_path) as f:
                                    data = json.load(f)
                                    if data["id"] == album_id:
                                        logging.info(
                                            f"skipping {album_name}: already downloaded")
                                        continue
                            logging.info(
                                f"queuing {album_name} from {playlist_name} offset {i}")
                            album = sp.album(album_link)
                            success = enqueue(album_link)
                            if success:
                                with open(album_path, "w") as f:
                                    json.dump(album, f)
                                with open(track_path, "w") as f:
                                    json.dump(track, f)

                            time.sleep(1)

            with open(playlist_path, "w") as f:
                json.dump(playlist, f)


def clear_queue():
    response = s.post(f"{env.deemix_url}/api/removeFinishedDownloads")
    logging.info(f"clearing queue: {response.text}")


def main():
    while not login():
        wait = 60
        logging.error(f"could not login, retrying in {wait} seconds")
        time.sleep(wait)

    while True:
        clear_queue()
        download()
        time.sleep(env.interval)
        logging.info(f"sleeping for {env.interval} seconds")


if __name__ == "__main__":
    main()
