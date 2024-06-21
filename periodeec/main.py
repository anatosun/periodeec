from dataclasses import dataclass
import re
import html
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


def fetch_playlist_tracks_from_sp(sp: spotipy.Spotify, link: str, name: str, number_of_tracks: int) -> list:
    """
    Fetch playlist tracks from Spotify
    sp: Spotify instance
    link: Spotify playlist link
    name: Spotify playlist name
    number_of_tracks: number of tracks in playlist
    """

    l = 100
    o = 0
    f = "items(id,track(name,external_ids.isrc,href,album(name,id,href,external_urls.spotify,artists(name,id))))"
    error = f"skipping playlist '{name}'"

    try:
        tracks = sp.playlist_tracks(link, limit=l, offset=o, fields=f)
        if tracks is None or tracks.get("items") is None:
            logging.error(
                f"{error}: tracks not found")
            return []
    except Exception as e:
        logging.error(f"{error}: {e}")
        return []

    tracks = tracks["items"]
    o = len(tracks)

    while o < number_of_tracks:
        time.sleep(random.uniform(3, 5))
        o = len(tracks)
        error = f"error getting '{name}' tracks at offset {o}"
        try:
            tracks_cont = sp.playlist_tracks(link, limit=l, offset=o, fields=f)
            if tracks_cont is None or tracks_cont.get("items") is None:
                logging.error(error)
                return tracks
            tracks.extend(tracks_cont["items"])
        except Exception as e:
            logging.error(f"{error}: {e}")
            return tracks

    return tracks


def fetch_playlists_from_spotify_username(sp: spotipy.Spotify, username: str) -> list:
    """
    Fetch playlists from Spotify username
    sp: Spotify instance
    username: Spotify username
    """

    logging.info(f"getting playlists for user {username}")
    l = 50
    n = 0
    try:
        playlists = sp.user_playlists(username, limit=l)
        if playlists is None or playlists.get("items") is None:
            logging.error(
                f"skipping user {username}: playlists not found")
            return []
        n = playlists["total"]

    except Exception as e:
        logging.error(f"skipping user {username}: {e}")
        return []

    if playlists is None:
        logging.error(f"skipping user {username}: playlists not found")
        return []

    playlists = playlists["items"]
    o = len(playlists)

    while o < n:
        o = len(playlists)
        error = f"error getting '{username} playlists at offset {o}"
        time.sleep(random.uniform(3, 5))
        try:
            playlists_cont = sp.user_playlists(username, limit=50, offset=o)
            if playlists_cont is None or playlists_cont.get("items") is None:
                logging.error(error)
                return playlists
            playlists.extend(playlists_cont["items"])
        except Exception as e:
            logging.error(f"{error}: {e}")

    logging.info(f"parsed {len(playlists)}/{n} playlists for user {username}")
    return playlists


def match_tracks_from_sp(tracks: list, download_missing: bool, download_path: str, beets: beets.Beets, downloaders: dict) -> list:
    """
    Match tracks from Spotify to local library
    tracks: list of Spotify tracks
    download_missing: download missing tracks
    download_path: path to download missing tracks
    beets: Beets instance
    downloaders: downloaders dict
    """

    fetched = []
    for track in tracks:
        track_name = track["track"]["name"]
        isrc = track["track"]["external_ids"].get("isrc")
        album = track["track"]["album"]
        album_link = album["external_urls"].get("spotify")
        album_name = album["name"]
        artist_name = album["artists"][0]["name"]
        error = f"failed to fetch {track_name}"

        if isrc is None:
            logging.debug(f"{error}: isrc not found")
            continue

        if album_link is None:
            logging.debug(f"{error}: album link found")
            continue

        exists, path = beets.exists(isrc)

        if exists:
            logging.debug(f"{error}: already exists at {path}")
            fetched.append((track_name, path))
            continue

        if download_missing:

            error = f"failed to download {track_name}"
            if len(downloaders) == 0:
                logging.error(f"{error}: no downloaders found")
                return fetched

            fallback_album_query = f"{artist_name} {album_name}"

            for dl in downloaders:
                error = f"failed to download {track_name} in {dl}"
                downloader = downloaders[dl]
                logging.debug(f"queuing {album_name} in {dl}")
                success, path, e = downloader.enqueue(
                    path=download_path,
                    isrc=isrc,
                    link=album_link,
                    fallback_album_query=fallback_album_query)

                if not success:
                    logging.error(f"{error}: {e}")
                    continue

                if not os.path.exists(path):
                    logging.error(f"{error}: directory {path} doesn't exist")
                    continue

                with open(os.path.join(path, "spotify.json"), "w") as f:
                    json.dump(album, f)

                success, e = beets.add(path=path, search_id=album_link)
                details = f"album '{album_name}' including '{track_name}'"
                where = "to beets library"
                details = f"{details} {where}"

                if success:
                    success_message = f"added {details}"
                    logging.info(success_message)
                    exists, path = beets.exists(isrc)
                    if exists:
                        fetched.append((track_name, path))
                    break
                else:
                    error = f"failed to add {details}: {e}"
                    logging.error(error)
                    continue
    return fetched


def sp_username_to_plex_playlists(sp: spotipy.Spotify,
                                  spotify_username: str,
                                  plex_usernames: list,
                                  plex_server: PlexServer,
                                  m3u_path: str,
                                  cache_path: str,
                                  download_path: str,
                                  beets: beets.Beets,
                                  downloaders: dict,
                                  download_missing=True,
                                  plex_section="Music") -> None:
    """
    Match Spotify username's playlist to Plex users 
    sp: Spotify instance
    spotify_username: Spotify username 
    plex_usernames: list of Plex usernames 
    plex_server: Plex server instance 
    m3u_path: path to m3u files
    cache_path: path to cache files
    download_path: path to download missing tracks
    beets: Beets instance
    downloaders: downloaders dict 
    download_missing: download missing tracks 
    plex_section: Plex section 
    """

    playlists = fetch_playlists_from_spotify_username(
        sp=sp,
        username=spotify_username)

    for playlist in playlists:

        if playlist.get("external_urls") is None or playlist["external_urls"].get("spotify") is None:
            logging.error(f"skipping playlist '{playlist['name']}':"
                          + " link not found")
            continue
        url = playlist["external_urls"]["spotify"]
        sp_playlist_to_plex_playlist(sp=sp,
                                     url=url,
                                     plex_usernames=plex_usernames,
                                     plex_server=plex_server,
                                     m3u_path=m3u_path,
                                     cache_path=cache_path,
                                     download_path=download_path,
                                     beets=beets,
                                     downloaders=downloaders,
                                     download_missing=download_missing,
                                     plex_section=plex_section)


def sp_playlist_to_plex_collection(sp: spotipy.Spotify,
                                   url: str,
                                   plex_server: PlexServer,
                                   m3u_path: str,
                                   cache_path: str,
                                   download_path: str,
                                   beets: beets.Beets,
                                   downloaders: dict,
                                   download_missing=True,
                                   title=None,
                                   poster=None,
                                   summary=None,
                                   plex_section="Music") -> None:
    """
    Match Spotify playlist to Plex Collection
    sp: Spotify instance
    url: Spotify playlist link
    plex_server: Plex server instance
    m3u_path: path to m3u files
    cache_path: path to cache files
    download_path: path to download missing tracks
    beets: Beets instance
    downloaders: downloaders dict 
    download_missing: download missing tracks
    title: collection title
    poster: collection poster
    summary: collection summary
    plex_section: Plex section
    """

    playlist_id = url.split("/")[-1]

    try:
        playlist = sp.playlist(playlist_id=playlist_id)
    except Exception as e:
        logging.error(f"skipping playlist '{playlist_id}': {e}")
        return

    if playlist is None:
        logging.error(f"skipping playlist '{playlist_id}': not found")
        return
    if playlist.get("external_urls") is None or playlist["external_urls"].get("spotify") is None:
        logging.error(f"skipping playlist '{playlist_id}': link not found")
        return
    playlist_link = playlist["external_urls"]["spotify"]
    if playlist.get("tracks") is None or playlist["tracks"].get("total") is None:
        logging.error(f"skipping playlist '{playlist_id}': tracks not found")
        return
    number_of_tracks = playlist["tracks"]["total"]
    if playlist.get("name") is None:
        logging.error(f"skipping playlist '{playlist_id}': name not found")
        return
    playlist_name = playlist["name"]
    if playlist.get("snapshot_id") is None:
        logging.error(f"skipping playlist '{playlist_id}':"
                      + " snapshot_id not found")
        return
    snapshot_id = playlist["snapshot_id"]

    collections_folder = os.path.join(f"{cache_path}/collections")

    if not os.path.exists(collections_folder):
        os.makedirs(collections_folder)

    collection_path = os.path.join(f"{collections_folder}/{playlist_id}.json")

    if os.path.exists(collection_path):
        with open(collection_path, "r") as f:
            data = json.load(f)
            if data["snapshot_id"] == snapshot_id:
                logging.info(
                    f"skipping playlist '{playlist_name}': already downloaded")
                return

    logging.info(
        f"queuing playlist '{playlist_name}': {playlist_link}")

    tracks = fetch_playlist_tracks_from_sp(
        sp=sp,
        link=playlist_link,
        name=playlist_name,
        number_of_tracks=number_of_tracks)

    fetched = match_tracks_from_sp(
        tracks=tracks,
        download_missing=download_missing,
        download_path=download_path,
        beets=beets,
        downloaders=downloaders)

    if len(fetched) == 0:
        with open(collection_path, "w") as f:
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
        summary = re.sub("""(<a href="(.*?)">)|(</a>)""", "", summary)
        summary = html.unescape(summary)

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

    with open(collection_path, "w") as f:
        json.dump(playlist, f)


def sp_playlist_to_plex_playlist(sp: spotipy.Spotify,
                                 url: str,
                                 plex_usernames: list,
                                 plex_server: PlexServer,
                                 m3u_path: str,
                                 cache_path: str,
                                 download_path: str,
                                 beets: beets.Beets,
                                 downloaders: dict,
                                 download_missing=True,
                                 title=None,
                                 poster=None,
                                 summary=None,
                                 plex_section="Music") -> None:
    """
    Match Spotify playlist to Plex playlist 
    sp: Spotify instance
    url: Spotify playlist link
    plex_usernames: list of Plex usernames
    plex_server: Plex server instance
    m3u_path: path to m3u files
    cache_path: path to cache files
    download_path: path to download missing tracks
    beets: Beets instance
    downloaders: downloaders dict 
    download_missing: download missing tracks
    title: playlist title
    poster: playlist poster
    summary: playlist summary
    plex_section: Plex section
    """

    playlist_id = url.split("/")[-1]
    error = f"skippping playlist '{playlist_id}'"

    try:
        playlist = sp.playlist(playlist_id=playlist_id)
    except Exception as e:
        logging.error(f"{error}: {e}")
        return

    if playlist is None:
        logging.error(f"{error}: not found")
        return
    if playlist.get("external_urls") is None or playlist["external_urls"].get("spotify") is None:
        logging.error(f"{error}: link not found")
        return
    playlist_link = playlist["external_urls"]["spotify"]
    if playlist.get("tracks") is None or playlist["tracks"].get("total") is None:
        logging.error(f"{error}: tracks not found")
        return
    number_of_tracks = playlist["tracks"]["total"]
    if playlist.get("name") is None:
        logging.error(f"{error}: name not found")
        return
    playlist_name = playlist["name"]
    if playlist.get("snapshot_id") is None:
        logging.error(f"{error}: snapshot_id not found")
        return
    error = f"skippping playlist '{playlist_name}' ({playlist_id})"
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
                    f"{error}: already downloaded")
                return

    logging.info(
        f"queuing playlist '{playlist_name}': {playlist_link}")

    tracks = fetch_playlist_tracks_from_sp(
        sp=sp,
        link=playlist_link,
        name=playlist_name,
        number_of_tracks=number_of_tracks)

    fetched = match_tracks_from_sp(
        tracks=tracks,
        download_missing=download_missing,
        download_path=download_path,
        beets=beets,
        downloaders=downloaders)

    if len(fetched) == 0:
        with open(playlist_path, "w") as f:
            json.dump(playlist, f)

        logging.info(f"{error}: no tracks found")
        return

    logging.info(f"fetched {len(fetched)}/{number_of_tracks} tracks")

    if title is None:
        title = playlist_name
    if poster is None:
        poster = playlist["images"][0]["url"]
    if summary is None:
        summary = playlist["description"]
        summary = re.sub("""(<a href="(.*?)">)|(</a>)""", "", summary)
        summary = html.unescape(summary)

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
                "failed to switch to plex user '{username}': {e}")
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
                             f" '{title}' for '{username}'")

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
        if config.settings.clients[client] is None:
            instance = class_()
        else:
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
                sp_username_to_plex_playlists,
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
                plex_section="Music"
            )

    if config.playlists is not None:
        for playlist in config.playlists:
            playlist = config.playlists[playlist]
            schedule.every(playlist.schedule).minutes.do(
                sp_playlist_to_plex_playlist,
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
                title=playlist.title,
                poster=playlist.poster,
                summary=playlist.summary
            )

    if config.collections is not None:
        for collection in config.collections:
            collection = config.collections[collection]
            schedule.every(collection.schedule).minutes.do(
                sp_playlist_to_plex_collection,
                sp=sp,
                url=collection.url,
                plex_server=plex_server,
                cache_path=os.path.join(f"{env.config}/cache"),
                m3u_path=os.path.join(f"{config.settings.music}/m3u"),
                download_path=settings.downloads,
                beets=bt,
                downloaders=downloaders,
                plex_section=config.settings.plex["section"],
                download_missing=collection.download_missing,
                title=collection.title,
                poster=collection.poster,
                summary=collection.summary
            )

    if env.run:
        schedule.run_all()

    while True:
        schedule.run_pending()
        time.sleep(1)
