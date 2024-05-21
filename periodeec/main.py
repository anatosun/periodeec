from dataclasses import dataclass

from plexapi import media
from plexapi.audio import Track
from periodeec.config import Config, Collection, Playlist, Settings, User
import yaml
import logging
import os
import time
import random
import spotipy
import json
import periodeec.beets as beets
import schedule
from plexapi.server import PlexServer
import importlib


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


def get_playlist_tracks(sp: spotipy.Spotify, playlist_link: str, playlist_name: str, number_of_tracks: int) -> list:
    try:
        playlist_tracks = sp.playlist_tracks(
            playlist_link, limit=100, offset=0, fields="items(id,track(name,external_ids.isrc,href,album(name,id,href,external_urls.spotify,external_ids.upc)))")
        playlist_tracks = playlist_tracks["items"]
    except Exception as e:
        logging.error(f"skipping playlist '{playlist_name}': {e}")
        return []

    while len(playlist_tracks) < number_of_tracks:
        time.sleep(random.uniform(3, 5))
        try:
            playlist_track_continued = sp.playlist_tracks(
                playlist_link, limit=100, offset=len(playlist_tracks), fields="items(id,track(name,external_ids.isrc,href,album(name,id,href,external_urls.spotify,external_ids.upc)))")
            playlist_tracks.extend(playlist_track_continued["items"])
        except Exception as e:
            logging.error(
                f"error getting '{playlist_name}' tracks at offset {len(playlist_tracks)}: {e}")
            return playlist_tracks

    return playlist_tracks


def get_username_playlists(sp: spotipy.Spotify, username: str) -> list:

    logging.info(f"getting playlists for user {username}")
    number_of_playlists = 0
    try:
        user_playlists = sp.user_playlists(username, limit=50)
        number_of_playlists = user_playlists["total"]

    except Exception as e:
        logging.error(f"skipping user {username}: {e}")
        return []

    if user_playlists is None:
        logging.error(f"skipping user {username}: playlists not found")
        return []

    playlists = user_playlists["items"]

    while len(playlists) < number_of_playlists:
        time.sleep(random.uniform(3, 5))
        try:
            user_playlists = sp.user_playlists(
                username, limit=50, offset=len(playlists))
            playlists.extend(user_playlists["items"])
        except Exception as e:
            logging.error(
                f"error getting '{username} playlists at offset {len(playlists)}: {e}")

    return playlists


def get_tracks(sp: spotipy.Spotify, tracks: list, download_missing: bool, download_path: str, beets: beets.Beets, downloaders: dict) -> list:

    fetched = []
    for track in tracks:
        track_name = track["track"]["name"]
        isrc = track["track"]["external_ids"].get("isrc")
        album = track["track"]["album"]
        album_id = album["id"]
        album_link = album["external_urls"].get("spotify")
        album_name = album["name"]

        if isrc is None:
            logging.debug(
                f"skipping {track_name}: isrc not found")
            continue

        if album_link is None:
            logging.debug(
                f"skipping {track_name}: album link found")
            continue

        exists, path = beets.exists(isrc)

        if exists:
            logging.debug(
                f"skipping {track_name}: already exists at {path}")
            fetched.append((track_name, path))
            continue

        success = False
        err = ""
        path = ""

        if download_missing:
            if downloaders.get("deemix") is not None:
                deemix = downloaders["deemix"]
                logging.debug(
                    f"queuing {album_name} in Deemix")
                success, path, err = deemix.enqueue(download_path, isrc)

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
                exists, path = beets.exists(isrc)
                if exists:
                    fetched.append((track_name, path))
                continue
            else:
                logging.error(
                    f"failed to add {album_name} to beets library: {e}")
    return fetched


def download_username(sp: spotipy.Spotify,
                      spotify_username: str,
                      plex_usernames: list,
                      plex_server: PlexServer,
                      m3u_path: str,
                      cache_path: str,
                      download_path: str,
                      beets: beets.Beets,
                      downloaders: dict,
                      download_missing=True,
                      collection=False,
                      plex_section="Music") -> None:

    playlists = get_username_playlists(
        sp=sp,
        username=spotify_username)

    for playlist in playlists:

        url = playlist["external_urls"]["spotify"]
        download_playlist(sp=sp,
                          url=url,
                          plex_usernames=plex_usernames,
                          plex_server=plex_server,
                          m3u_path=m3u_path,
                          cache_path=cache_path,
                          download_path=download_path,
                          beets=beets,
                          downloaders=downloaders,
                          download_missing=download_missing,
                          collection=collection,
                          plex_section=plex_section)


def download_playlist(sp: spotipy.Spotify,
                      url: str,
                      plex_usernames: list,
                      plex_server: PlexServer,
                      m3u_path: str,
                      cache_path: str,
                      download_path: str,
                      beets: beets.Beets,
                      downloaders: dict,
                      download_missing=True,
                      collection=False,
                      title=None,
                      poster=None,
                      summary=None,
                      plex_section="Music") -> None:
    playlist_id = url.split("/")[-1]
    try:
        playlist = sp.playlist(playlist_id=playlist_id)
    except Exception as e:
        logging.error(f"skipping playlist '{playlist_id}': {e}")
        return
    playlist_link = playlist["external_urls"]["spotify"]
    number_of_tracks = playlist["tracks"]["total"]
    playlist_name = playlist["name"]
    owner = playlist["owner"]["id"]
    snapshot_id = playlist["snapshot_id"]

    playlists_folder = os.path.join(f"{cache_path}/playlists")

    if not os.path.exists(playlists_folder):
        os.makedirs(playlists_folder)

    playlist_path = os.path.join(f"{playlists_folder}/{playlist_id}.json")

    if os.path.exists(playlist_path):
        with open(playlist_path, "r") as f:
            data = json.load(f)
            if data["snapshot_id"] == snapshot_id:
                logging.info(
                    f"skipping playlist '{playlist_name}': already downloaded")
                return

    logging.info(
        f"queuing playlist '{playlist_name}': {playlist_link}")

    tracks = get_playlist_tracks(
        sp=sp,
        playlist_link=playlist_link,
        playlist_name=playlist_name,
        number_of_tracks=number_of_tracks)

    fetched = get_tracks(sp=sp,
                         tracks=tracks,
                         download_missing=download_missing,
                         download_path=download_path,
                         beets=beets,
                         downloaders=downloaders)

    if len(fetched) == 0:
        with open(playlist_path, "w") as f:
            json.dump(playlist, f)

        logging.info(f"skipped playlist '{playlist_name}': no tracks found")
        return

    logging.info(f"fetched {len(fetched)}/{number_of_tracks} tracks")

    if title is None:
        title = playlist_name
    if poster is None:
        poster = playlist["images"][0]["url"]
    if summary is None:
        summary = playlist["description"]

    if collection:

        m3u_path = os.path.join(f"{m3u_path}/collections")
        m3u_path = os.path.abspath(m3u_path)

        if not os.path.exists(m3u_path):
            os.makedirs(m3u_path)

        m3u_path = os.path.join(f"{m3u_path}/{playlist_id}.m3u")

        with open(m3u_path, "w") as f:
            f.write("#EXTM3U\n")
            for track, path in fetched:
                f.write(f"#EXTINF:0,{track}\n")
                f.write(f"{path}\n")

        pl = plex_server.createPlaylist(
            title=title+" (temp)",
            section=plex_section,
            m3ufilepath=m3u_path)

        items = pl.items()

        try:
            cl = plex_server.library.section(
                plex_section).collection(title=title)
            cl.delete()
        except Exception as e:
            logging.error(
                f"failed to delete plex collection '{title}': {e}")
        cl = plex_server.createCollection(
            title=title,
            items=items,
            section=plex_section)
        pl.delete()
        cl.uploadPoster(url=poster)
        cl.editSummary(summary=summary)
        logging.info(f"created plex collection '{title}'")

        with open(playlist_path, "w") as f:
            json.dump(playlist, f)

        return

    admin = plex_server.account().username
    plex_server_username = plex_server

    for username in plex_usernames:

        m3u_path_username = os.path.join(f"{m3u_path}/playlists/{username}")
        m3u_path_username = os.path.abspath(m3u_path_username)

        if not os.path.exists(m3u_path_username):
            os.makedirs(m3u_path_username)

        m3u_path_username = os.path.join(
            f"{m3u_path_username}/{playlist_id}.m3u")

        with open(m3u_path_username, "w") as f:
            f.write("#EXTM3U\n")
            for track, path in fetched:
                f.write(f"#EXTINF:0,{track}\n")
                f.write(f"{path}\n")

        try:

            pl_temp = plex_server.createPlaylist(
                title=title,
                section=plex_section,
                m3ufilepath=m3u_path_username)
            items = pl_temp.items()

        except Exception as e:
            logging.error(
                f"failed to create plex playlist '{title}': {e}")
            with open(playlist_path, "w") as f:
                json.dump(playlist, f)
                return

        try:
            if username != plex_server_username.myPlexUsername:
                plex_server_username = plex_server.switchUser(username)
        except Exception as e:
            logging.error(
                f"failed to switch to plex user '{username}': {e}")
            pl_temp.delete()
            continue

        try:

            pl = plex_server_username.playlist(title=title)
            if username != admin:
                pl.removeItems(pl.items())
                pl.addItems(items)
            pl.uploadPoster(url=poster)
            pl.editSummary(summary=summary)
            logging.info(f"edited plex playlist '{title}' for '{username}'")

        except Exception as e:

            try:
                pl = plex_server_username.createPlaylist(
                    title=title,
                    section=plex_section,
                    items=items)
                pl.uploadPoster(url=poster)
                pl.editSummary(summary=summary)
                logging.info(f"created plex playlist" +
                             "'{title}' for '{username}'")

            except Exception as e:
                logging.error(
                    f"failed to create plex playlist '{title}': {e}")
                with open(playlist_path, "w") as f:
                    json.dump(playlist, f)
                return

        try:
            if username != admin:
                pl_temp.delete()
        except Exception as e:
            logging.error(
                f"failed to delete temporary plex playlist '{title}': {e}")

    with open(playlist_path, "w") as f:
        json.dump(playlist, f)


def main():

    with open(os.path.join(f"{env.config}/config.yaml"), 'r') as stream:
        data = yaml.safe_load(stream)

    if data.get('playlists') is None:
        playlists = None
    else:
        playlists = {}
        for name, playlist_data in data['playlists'].items():
            playlists[name] = Playlist(**playlist_data)

    if data.get('collections') is None:
        collections = None
    else:
        collections = {}
        for name, collection_data in data['collections'].items():
            collections[name] = Collection(**collection_data)

    if data.get('usernames') is None:
        usernames = None
    else:
        usernames = {}
        for username, user_data in data['usernames'].items():
            usernames[username] = User(**user_data)

    if data.get('settings') is None:
        logging.error(f"settings not found in {env.config}/config.yaml")

    settings_data = data['settings']
    settings = Settings(**settings_data)

    config = Config(settings=settings,
                    playlists=playlists,
                    collections=collections,
                    usernames=usernames)

    downloaders = {}
    for client in config.settings.clients:
        module = f"periodeec.modules.{client}"
        class_ = getattr(importlib.import_module(
            module), f"{client}".capitalize())
        instance = class_(**config.settings.clients[client])
        downloaders[client] = instance

    ccm = spotipy.SpotifyClientCredentials(**config.settings.spotify)
    sp = spotipy.Spotify(client_credentials_manager=ccm)
    plex_server = PlexServer(baseurl=config.settings.plex["baseurl"],
                             token=config.settings.plex["token"])
    bt = beets.Beets(config.settings.music)

    if config.usernames is not None:
        for user in config.usernames:
            user = config.usernames[user]
            schedule.every(user.schedule).minutes.do(
                download_username,
                sp=sp,
                spotify_username=user.spotify_username,
                plex_usernames=user.sync_to_plex_users,
                plex_server=plex_server,
                cache_path=os.path.join(env.config, "cache"),
                m3u_path=os.path.join(f"{config.settings.music}/m3u"),
                download_path=settings.downloads,
                beets=bt,
                downloaders=downloaders,
                download_missing=user.download_missing,
                collection=False,
                plex_section="Music"
            )

    if config.playlists is not None:
        for playlist in config.playlists:
            playlist = config.playlists[playlist]
            schedule.every(playlist.schedule).minutes.do(
                download_playlist,
                sp=sp,
                url=playlist.url,
                plex_usernames=playlist.sync_to_plex_users,
                plex_server=plex_server,
                cache_path=os.path.join(f"{env.config}/cache"),
                m3u_path=os.path.join(f"{config.settings.music}/m3u"),
                download_path=settings.downloads,
                beets=bt,
                downloaders=downloaders,
                plex_section=config.settings.plex["section"],
                download_missing=playlist.download_missing,
                collection=False,
                title=playlist.title,
                poster=playlist.poster,
                summary=playlist.summary
            )

    if config.collections is not None:
        for collection in config.collections:
            collection = config.collections[collection]
            schedule.every(collection.schedule).minutes.do(
                download_playlist,
                sp=sp,
                url=collection.url,
                plex_usernames=[],
                plex_server=plex_server,
                cache_path=os.path.join(f"{env.config}/cache"),
                m3u_path=os.path.join(f"{config.settings.music}/m3u"),
                download_path=settings.downloads,
                beets=bt,
                downloaders=downloaders,
                plex_section=config.settings.plex["section"],
                download_missing=collection.download_missing,
                collection=True,
                title=collection.title,
                poster=collection.poster,
                summary=collection.summary
            )

    if env.run:
        schedule.run_all()

    while True:
        schedule.run_pending()
        time.sleep(1)
