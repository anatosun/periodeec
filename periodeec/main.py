from plexapi.server import PlexServer
from spotipy_anon import SpotifyAnon
from spotipy import Spotify
import periodeec.beets as beets
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


def sync_playlist_to_plex(playlist: Playlist, username: str, plex_handler: PlexHandler, spotify_handler: SpotifyHandler, bt, downloaders, download_path, collection=False):
    """Handles the process of fetching, matching, and syncing a Spotify playlist to Plex."""
    logging.info(f"Syncing playlist '{playlist.title}' to Plex")
    spotify_handler.populate_playlist(playlist)

    for track in playlist.tracks:
        exists, path = bt.exists(
            track.isrc, fuzzy=False, artist=track.artist, title=track.title)
        if exists:
            track.path = path
        else:
            exists, path = bt.exists(
                track.isrc, fuzzy=True, artist=track.artist, title=track.title)
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
                            success, path = bt.add(dl_path, track.isrc)
                            if success:
                                track.path = path
                            else:
                                success, path = bt.add(dl_path)
                                if success:
                                    track.path = path
                        else:
                            logging.error(err)

    plex_handler.create(playlist, username, collection)


def sync(spotify_handler, plex_handler, config, bt, downloaders, settings):
    """Syncs Spotify playlists and users to Plex using the correct logic."""
    if config.usernames:
        for user in config.usernames.values():
            playlists = spotify_handler.fetch_playlists_from_user(
                user.spotify_username)
            for playlist in playlists:
                schedule.every(user.schedule).minutes.do(
                    lambda pl=playlist: sync_playlist_to_plex(
                        pl, user.spotify_username, plex_handler, spotify_handler, bt, downloaders, settings.downloads
                    )
                )


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

    bt = beets.Beets(settings.music)

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
