import yaml


class Config:
    def __init__(self, playlists, collections, usernames, settings):
        self.playlists = playlists
        self.collections = collections
        self.usernames = usernames
        self.settings = settings


class Playlist:
    def __init__(self, url, sync_mode, name, sync_to_plex_users, summary, cover, download_missing, schedule):
        self.url = url
        self.sync_mode = sync_mode
        self.name = name
        self.sync_to_plex_users = sync_to_plex_users
        self.summary = summary
        self.cover = cover
        self.download_missing = download_missing
        self.schedule = int(schedule)


class Collection:
    def __init__(self, url, sync_mode, name, summary, cover, download_missing, schedule):
        self.url = url
        self.sync_mode = sync_mode
        self.name = name
        self.summary = summary
        self.cover = cover
        self.download_missing = download_missing
        self.schedule = int(schedule)


class User:
    def __init__(self, spotify_username, sync_mode, sync_to_plex_users, download_missing, schedule):
        self.spotify_username = str(spotify_username)
        self.sync_mode = str(sync_mode)
        self.sync_to_plex_users = list(sync_to_plex_users)
        self.download_missing = bool(download_missing)
        self.schedule = int(schedule)


class Plex:
    def __init__(self, baseurl, token, section):
        self.baseurl = baseurl
        self.token = token
        self.section = section


class Settings:
    def __init__(self, config, music, downloads, unmatched, failed, spotify, clients, plex, playlists):
        self.config = config
        self.downloads = downloads
        self.music = music
        self.unmatched = unmatched
        self.failed = failed
        self.spotify = spotify
        self.clients = clients
        self.plex = plex
        self.playlist = playlists
