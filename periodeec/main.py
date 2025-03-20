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
    format='%(asctime)s - %(levelname)s - %(name)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    level=logging.INFO
)
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


def match(bt: BeetsHandler, track: Track):
    exists, path = bt.exists(track.isrc, fuzzy=False,
                             artist=track.artist, title=track.title)
    if exists:
        return exists, path

    return bt.exists(track.isrc, fuzzy=True,
                     artist=track.artist, title=track.title)


def sync_user(user: User, spotify_handler: SpotifyHandler, plex_handler: PlexHandler, bt: BeetsHandler, download_path: str, downloaders: dict):
    spotify_username = user.spotify_username
    plex_users = user.sync_to_plex_users
    logger.info(f"Syncing user {spotify_username} to {plex_users}")
    playlists = spotify_handler.playlists(spotify_username)

    for playlist in playlists:
        logger.info(f"Syncing playlist {playlist.title}")

        if playlist.is_up_to_date():
            logger.info(
                f"Playlist {playlist.title} is the most recent version")
        else:
            logger.info(f"Updating playlist {playlist.title}")
            tracks = spotify_handler.tracks(playlist.url)
            logger.info(f"Fetched {len(tracks)} from Spotify")
            playlist.tracks = playlist.update_tracklist(
                tracks, playlist.tracks)

            for track in playlist.tracks:
                if track.path is None or track.path == "":
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
                                if err != "":
                                    logger.error(err)

                                if success:
                                    success, err = bt.add(dl_path, track.isrc)
                                    if success:
                                        exists, path = match(bt, track)
                                    if err != "":
                                        logger.error(err)
            playlist.save()

        for username in plex_users:
            if playlist.is_up_to_date_for(username):
                logger.info(
                    f"Playlist {playlist.title} is up-to-date for {username}.")
                continue
            success = plex_handler.create(playlist, username, False)
            if success:
                playlist.update_for(username)
                playlist.save()


def sync(spotify_handler, plex_handler, config, bt, downloaders, settings):
    """Syncs Spotify playlists and users to Plex using the correct logic."""
    if config.usernames:
        for username in config.usernames.keys():
            user = config.usernames[username]
            logger.info(
                f"Syncing {username}'s playlist every {user.schedule} minutes")
            schedule.every(user.schedule).minutes.do(
                sync_user, user, spotify_handler, plex_handler, bt, settings.downloads, downloaders)


def main():
    with open(os.path.join(env.config, "config.yaml"), 'r') as stream:
        data = yaml.safe_load(stream)

    settings_data = data.get('settings')
    if not settings_data:
        logger.error(f"Settings not found in {env.config}/config.yaml")
        return

    settings = Settings(**settings_data)
    config = Config(
        settings=settings,
        usernames={user: User(**usr)
                   for user, usr in data.get('usernames', {}).items()}
    )

    downloaders = {}
    for client in settings.clients:
        logger.info(f"Importing module {client}")
        module = f"periodeec.modules.{client}"
        logging.getLogger(client).setLevel(logging.WARNING)
        class_ = getattr(importlib.import_module(module), client.capitalize())
        downloaders[client] = class_(
            **settings.clients[client]) if settings.clients[client] else class_()
        logging.getLogger(client).setLevel(logging.WARNING)

    bt = BeetsHandler(settings.music)

    logger.info("Initializing Spotify Handler")
    spotify_handler = SpotifyHandler(**config.settings.spotify)
    logger.info("Initializing Plex Handler")
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
