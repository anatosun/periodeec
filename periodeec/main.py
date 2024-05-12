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


env = Environment(os.getenv("CONFIG", "/config"))


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
                      playlists_path: str,
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
                          playlists_path=playlists_path,
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
                      playlists_path: str,
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
    playlist = sp.playlist(playlist_id=playlist_id)
    playlist_link = playlist["external_urls"]["spotify"]
    number_of_tracks = playlist["tracks"]["total"]
    playlist_name = playlist["name"]
    owner = playlist["owner"]["id"]
    snapshot_id = playlist["snapshot_id"]

    owner_folder = os.path.join(f"{cache_path}/playlists/{owner}")

    if not os.path.exists(owner_folder):
        os.makedirs(owner_folder)

    playlist_path = os.path.join(
        f"{owner_folder}/{playlist_name.replace(os.path.sep, '')}.json")

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

    logging.info(f"fetched {len(fetched)}/{number_of_tracks} tracks")

    if len(fetched) == 0:
        return
    if title is None:
        title = playlist_name
    if poster is None:
        poster = playlist["images"][0]["url"]
    if summary is None:
        summary = playlist["description"]

    if not os.path.exists(playlists_path):
        os.makedirs(playlists_path)

    m3u = os.path.join(
        f"{playlists_path}/{playlist_id}{'_collection' if collection else ''}.m3u")
    m3u = os.path.abspath(m3u)
    with open(m3u, "w") as f:
        f.write("#EXTM3U\n")
        for track, path in fetched:
            f.write(f"#EXTINF:0,{track}\n")
            f.write(f"{path}\n")

    if collection:

        pl = plex_server.createPlaylist(
            title=title+" (temp)",
            section=plex_section,
            m3ufilepath=m3u)
        items = pl.items()
        try:
            cl = plex_server.library.section(plex_section).collections().get(
                title=title)
            cl.delete()
        except Exception as e:
            pass
        cl = plex_server.createCollection(
            title=title,
            items=items,
            section=plex_section)
        pl.delete()
        cl.uploadPoster(url=poster)
        cl.editSummary(summary=summary)
        logging.info(f"created plex collection '{title}'")

    else:

        admin = plex_server.account().username
        pl_temp = plex_server.createPlaylist(
            title=title + " (temp)",
            section=plex_section,
            m3ufilepath=m3u)
        items = pl_temp.items()
        delete = True

        for username in plex_usernames:

            if username == admin:
                delete = False
                continue

            plex_server = plex_server.switchUser(username)

            try:
                pl = plex_server.playlist(title=title)
                pl.delete()
            except Exception as e:
                pass

            pl = plex_server.createPlaylist(
                title=title,
                section=plex_section,
                items=items)

            pl.uploadPoster(url=poster)
            pl.editSummary(summary=summary)
            logging.info(f"created plex playlist '{title}'"
                         + f" for user '{username}'")

            if delete:
                pl_temp.delete()

    with open(playlist_path, "w") as f:
        json.dump(playlist, f)


def main():

    with open(os.path.join(f"{env.config}/config.yaml"), 'r') as stream:
        data = yaml.safe_load(stream)

    playlists = {}
    for name, playlist_data in data['playlists'].items():
        playlists[name] = Playlist(**playlist_data)

    collections = {}
    for name, collection_data in data['collections'].items():
        collections[name] = Collection(**collection_data)

    usernames = {}
    for username, user_data in data['usernames'].items():
        usernames[username] = User(**user_data)

    settings_data = data['settings']
    settings = Settings(**settings_data)

    config = Config(playlists, collections, usernames, settings)
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

    for user in config.usernames:
        user = config.usernames[user]
        schedule.every(user.schedule).minutes.do(
            download_username,
            sp=sp,
            spotify_username=user.spotify_username,
            plex_usernames=user.sync_to_plex_users,
            plex_server=plex_server,
            cache_path=os.path.join(env.config, "cache"),
            playlists_path=config.settings.playlist,
            download_path=settings.downloads,
            beets=bt,
            downloaders=downloaders,
            download_missing=user.download_missing,
            collection=False,
            plex_section="Music"
        )

    for playlist in config.playlists:
        playlist = config.playlists[playlist]
        schedule.every(playlist.schedule).minutes.do(
            download_playlist,
            sp=sp,
            url=playlist.url,
            plex_usernames=playlist.sync_to_plex_users,
            plex_server=plex_server,
            cache_path=os.path.join(f"{env.config}/cache"),
            playlists_path=config.settings.playlist,
            download_path=settings.downloads,
            beets=bt,
            downloaders=downloaders,
            plex_section=config.settings.plex["section"],
            download_missing=playlist.download_missing,
            collection=False
        )

    for collection in config.collections:
        collection = config.collections[collection]
        schedule.every(collection.schedule).minutes.do(
            download_playlist,
            sp=sp,
            url=collection.url,
            plex_usernames=[],
            plex_server=plex_server,
            cache_path=os.path.join(f"{env.config}/cache"),
            playlists_path=config.settings.playlist,
            download_path=settings.downloads,
            beets=bt,
            downloaders=downloaders,
            plex_section=config.settings.plex["section"],
            download_missing=collection.download_missing,
            collection=True
        )

    schedule.run_all()
    while True:
        schedule.run_pending()
        time.sleep(1)
