import os
import re
import logging
from plexapi.server import PlexServer
from plexapi.collection import Collection as PlexCollection
from plexapi.playlist import Playlist as PlexPlaylist
from periodeec.playlist import Playlist


class PlexHandler:
    def __init__(self, baseurl: str, token: str, section: str = "Music", m3u_path: str = "m3u"):
        self.plex_server = PlexServer(baseurl=baseurl, token=token)
        self.section = section
        self.m3u_path = m3u_path
        self.admin_user = self.plex_server.account().username

    def get_plex_instance_for_user(self, username: str):
        """Return a temporary Plex instance for a given user without modifying the class attribute."""
        if username and username != self.admin_user:
            return self.plex_server.switchUser(username)
        return self.plex_server

    def create_m3u(self, playlist: Playlist, username: str) -> str:
        """Creates an M3U file for the given playlist and returns the file path."""

        title = playlist.title

        re.sub(r'[^\w_. -/]', '_', username)
        re.sub(r'[^\w_. -/]', '_', title)

        m3u_path = os.path.join(self.m3u_path, username)
        if not os.path.exists(m3u_path):
            os.makedirs(m3u_path)

        m3u_file_path = os.path.join(m3u_path,  f"{title}.m3u")
        with open(m3u_file_path, "w") as m3u_file:
            m3u_file.write("#EXTM3U\n")
            for track in playlist.tracks:
                if track.path:
                    m3u_file.write(
                        f"#EXTINF:-1,{track.artist} - {track.title}\n")
                    m3u_file.write(f"{track.path}\n")

        logging.info(f"Created M3U file: {m3u_file_path}")
        return m3u_file_path

    def create(self, playlist: Playlist, username, collection: bool = False):
        """Create or update a Plex playlist or collection."""
        m3u_file = self.create_m3u(playlist, username)

        try:
            temp_playlist = self.plex_server.createPlaylist(
                title=f"{playlist.title} (temp)", section=self.section, m3ufilepath=m3u_file)
            items = temp_playlist.items()
        except Exception as e:
            logging.error(
                f"Failed to create temporary playlist '{playlist.title}': {e}")
            return None

        if collection:
            col: PlexCollection
            try:
                col = self.plex_server.library.section(
                    self.section).collection(title=playlist.title)
                col.delete()
                logging.info(
                    f"Updating existing Plex collection '{playlist.title}'")
            except:
                logging.info(
                    f"Creating new Plex collection '{playlist.title}'")

            try:
                col = self.plex_server.createCollection(
                    title=playlist.title, section=self.section, items=items)
                col.uploadPoster(url=playlist.poster)
                col.editSummary(summary=playlist.summary)
            except Exception as e:
                logging.error(
                    f"Failed to create collection {playlist.title}: {e}")

        else:
            try:
                plex_instance = self.get_plex_instance_for_user(username)
                pl: PlexPlaylist
                try:
                    res = plex_instance.playlist(title=playlist.title)

                    if res is not None:
                        pl = res
                        logging.info(
                            f"Updating existing Plex playlist '{playlist.title}' for '{username}'")
                        pl.removeItems(pl.items())
                        pl.addItems(items=items)
                        pl.uploadPoster(url=playlist.poster)
                        pl.editSummary(summary=playlist.summary)

                    else:
                        logging.error(
                            f"Failed to fetch Plex playlist '{playlist.title}' for '{username}', result is '{res}'")
                except Exception as e:
                    logging.info(
                        f"Creating new Plex playlist '{playlist.title}' for '{username}': {e}")
                    try:
                        pl = plex_instance.createPlaylist(
                            playlist.title, items=items, smart=False)
                        pl.uploadPoster(url=playlist.poster)
                        pl.editSummary(summary=playlist.summary)
                    except Exception as e:
                        logging.error(
                            f"Error creating playlist {playlist.title} {e} for '{username}'")
            except Exception as e:
                logging.error(
                    f"Failed to switch to Plex user '{username}': {e}")

        try:
            temp_playlist.delete()
        except Exception as e:
            logging.error(f"Error deleting temp playlist {e}")
