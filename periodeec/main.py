from plexapi.server import PlexServer
from spotipy_anon import SpotifyAnon
from spotipy import Spotify
from periodeec.beets_handler import BeetsHandler
from periodeec.plex_handler import PlexHandler
from dataclasses import dataclass
import os
import yaml
import logging
import schedule
import importlib
import time
import hashlib
from periodeec.config import Config, Settings, User
from periodeec.playlist import Playlist
from periodeec.track import Track
from periodeec.spotify_handler import SpotifyHandler
import colorama
colorama.init(strip=True, convert=False)


@dataclass
class Environment:
    config: str
    run: bool


env = Environment(os.getenv("PD_CONFIG", "/config"),
                  bool(os.getenv("PD_RUN", False)))

logging.basicConfig(
    format='%(asctime)s %(message)s',
    datefmt='%m/%d/%Y %I:%M:%S %p',
    level=logging.INFO)


def match(bt: BeetsHandler, track: Track):
    exists, path = bt.exists(track.isrc, fuzzy=False)
    if exists:
        return exists, path

    exists, path = bt.exists(track.isrc, fuzzy=True,
                             artist=track.artist, title=track.title)

    return exists, path


def sync_user(user: User, spotify_handler: SpotifyHandler, plex_handler: PlexHandler, bt: BeetsHandler, download_path: str, downloaders: dict):
    spotify_username = user.spotify_username
    plex_users = user.sync_to_plex_users
    playlists = spotify_handler.fetch_playlists_from_user(spotify_username)

    for playlist in playlists:
        spotify_handler.populate_playlist(playlist)

        for track in playlist.tracks:
            exists, path = match(bt, track)
            if exists:
                track.path = path
            else:
                if download_path and downloaders:
                    for downloader in downloaders.values():
                        hash = hashlib.sha256(
                            f"{track.artist}{track.album}{downloader}".encode()).hexdigest()[:]
                        dl_path = os.path.join(download_path, hash)
                        success, path, err = downloader.enqueue(
                            path=dl_path, isrc=track.isrc, fallback_album_query=f"{track.artist} {track.album}"
                        )

                        if success:
                            success, err = bt.add(dl_path, track.isrc)
                            if success:
                                exists, path = match(bt, track)

                        if not success or not exists:
                            logging.error(err)

        for username in plex_users:
            plex_handler.create(playlist, username, False)


def sync(spotify_handler, plex_handler, config, bt, downloaders, settings):
    """Syncs Spotify playlists and users to Plex using the correct logic."""
    if config.usernames:
        for user in config.usernames.values():
            schedule.every(user.schedule).minutes.do(
                sync_user, user, spotify_handler, plex_handler, bt, settings.downloads, downloaders)


def main():
    with open(os.path.join(env.config, "config.yaml"), 'r') as stream:
        data = yaml.safe_load(stream)

    settings_data = data.get('settings')
    if not settings_data:
        logging.error(f"Settings not found in {env.config}/config.yaml")
        return

    settings = Settings(**settings_data)
    config = Config(
        settings=settings,
        usernames={user: User(**usr)
                   for user, usr in data.get('usernames', {}).items()}
    )

    downloaders = {}
    for client in settings.clients:
        module = f"periodeec.modules.{client}"
        class_ = getattr(importlib.import_module(module), client.capitalize())
        downloaders[client] = class_(
            **settings.clients[client]) if settings.clients[client] else class_()

    bt = BeetsHandler(settings.music)

    spotify_handler = SpotifyHandler(**config.settings.spotify)
    plex_handler = PlexHandler(settings.plex["baseurl"], settings.plex["token"],
                               settings.plex["section"], m3u_path=os.path.join(settings.music, "m3u"))

    sync(spotify_handler, plex_handler, config, bt, downloaders, settings)

    if env.run:
        schedule.run_all()

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
