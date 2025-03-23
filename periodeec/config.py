import yaml


class Config:
    def __init__(self, settings, playlists=None, collections=None, usernames=None):
        self.playlists = playlists
        self.collections = collections
        self.usernames = usernames
        self.settings = settings


class Playlist:
    def __init__(self, url, sync_mode=None, title=None, sync_to_plex_users=[], summary=None, poster=None, download_missing=False, schedule=1440):
        self.url = url
        self.sync_mode = sync_mode
        self.title = title
        self.sync_to_plex_users = sync_to_plex_users
        self.summary = summary
        self.poster = poster
        self.download_missing = download_missing
        self.schedule = int(schedule)


class Collection:
    def __init__(self, url, sync_mode=None, title=None, summary=None, poster=None, download_missing=False, schedule=1440):
        self.url = url
        self.sync_mode = sync_mode
        self.title = title
        self.summary = summary
        self.poster = poster
        self.download_missing = bool(download_missing)
        self.schedule = int(schedule)


class User:
    def __init__(self, spotify_username, sync_mode=None, sync_to_plex_users=[], download_missing=False, schedule=1440):
        self.spotify_username = str(spotify_username)
        self.sync_mode = sync_mode
        self.sync_to_plex_users = list(sync_to_plex_users)
        self.download_missing = bool(download_missing)
        self.schedule = int(schedule)


class Plex:
    def __init__(self, baseurl, token, section):
        self.baseurl = baseurl
        self.token = token
        self.section = section


class Settings:
    def __init__(self, config, beets, downloads, unmatched, failed, spotify, clients, plex, playlists):
        self.config = config
        self.downloads = downloads
        self.beets = beets
        self.unmatched = unmatched
        self.failed = failed
        self.spotify = spotify
        self.clients = clients
        self.plex = plex
        self.playlist = playlists
