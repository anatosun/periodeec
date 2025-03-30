from periodeec import download_manager
from periodeec.beets_handler import BeetsHandler
from periodeec.plex_handler import PlexHandler
from dataclasses import dataclass
import os
import yaml
import logging
import schedule
import importlib
import time
from periodeec.modules.downloader import Downloader
from periodeec.config import Config, Settings, User
from periodeec.download_manager import DownloadManager
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


def sync_user(user: User, spotify_handler: SpotifyHandler, plex_handler: PlexHandler, bt: BeetsHandler, download_manager: DownloadManager):
    spotify_username = user.spotify_username
    plex_users = user.sync_to_plex_users

    spotify_user = spotify_handler.user(spotify_username)
    friendly_name = spotify_user.name

    logger.info(f"Syncing Spotify user '{friendly_name}' to '{plex_users}'")
    playlists = spotify_handler.playlists(spotify_username)

    for playlist in playlists:
        logger.info(f"Syncing playlist '{playlist.title}'")

        if playlist.is_up_to_date():
            logger.info(
                f"Playlist '{playlist.title}' is the most recent version")
        else:
            logger.info(f"Updating playlist '{playlist.title}'")
            tracks = spotify_handler.tracks(
                playlist.url, playlist.number_of_tracks)
            logger.info(f"Fetched {len(tracks)} tracks from Spotify")
            playlist.tracks = playlist.update_tracklist(
                tracks, playlist.tracks)

            for track in playlist.tracks:
                if track.path is None or track.path == "":
                    exists, path = bt.exists(
                        isrc=track.isrc, artist=track.artist, title=track.title)
                    if exists:
                        track.path = path
                    else:
                        success, dl_path = download_manager.enqueue(
                            track=track)

                        if success:
                            success = bt.add(
                                dl_path, track.album_url)
                            if success:
                                exists, path = bt.exists(
                                    isrc=track.isrc, artist=track.artist, title=track.title)
                                if exists:
                                    track.path = path
                                else:
                                    logger.error(
                                        f"Could not retrieve freshly added track '{track.title}' by '{track.artist}'")
                            else:
                                logger.error(
                                    f"Could not autotag track '{track.title}' by '{track.artist}'")

                        else:
                            logger.error(
                                f"Could not download track '{track.title}' by '{track.artist}'")
            playlist.save()

        for username in plex_users:
            if playlist.is_up_to_date_for(username):
                logger.info(
                    f"Playlist '{playlist.title}' is up-to-date for '{username}'")
                continue
            success = plex_handler.create(playlist, username, False)
            if success:
                playlist.update_for(username)
                playlist.save()


def sync(spotify_handler, plex_handler, config, bt, download_manager):
    """Syncs Spotify playlists and users to Plex using the correct logic."""
    if config.usernames:
        for username in config.usernames.keys():
            user = config.usernames[username]
            logger.info(
                f"Syncing {username}'s playlist every {user.schedule} minutes")
            schedule.every(user.schedule).minutes.do(
                sync_user, user, spotify_handler, plex_handler, bt, download_manager)


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

    downloaders = []
    for client in settings.clients:
        logger.info(f"Importing module {client}")
        module = f"periodeec.modules.{client}"
        logging.getLogger(client).setLevel(logging.WARNING)
        class_ = getattr(importlib.import_module(module), client.capitalize())
        downloader = class_(
            **settings.clients[client]) if settings.clients[client] else class_()
        downloaders.append(downloader)
        logging.getLogger(client).setLevel(logging.ERROR)

    bt = BeetsHandler(**settings.beets,
                      plex_baseurl=settings.plex['baseurl'],
                      plex_token=settings.plex['token'],
                      plex_section=settings.plex['section'],
                      spotify_client_id=settings.spotify['client_id'],
                      spotify_client_secret=settings.spotify['client_secret']
                      )

    logger.info("Initializing Spotify Handler")
    spotify_handler = SpotifyHandler(
        **config.settings.spotify, path=os.path.join(settings.beets["directory"], "playlists"))
    logger.info("Initializing Plex Handler")
    plex_handler = PlexHandler(
        **settings.plex, m3u_path=os.path.join(settings.beets["directory"], "m3u"))

    download_manager = DownloadManager(
        downloaders=downloaders, download_path=settings.downloads, failed_path=settings.failed)

    sync(spotify_handler, plex_handler, config, bt, download_manager)

    if env.run:
        schedule.run_all()

    while True:
        schedule.run_pending()
        time.sleep(1)


if __name__ == "__main__":
    main()
