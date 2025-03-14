import os
import json
import logging
from plexapi.server import PlexServer
from periodeec.playlist import Playlist
from periodeec.track import Track


class PlexHandler:
    def __init__(self, baseurl: str, token: str, section: str = "Music", m3u_path: str = "m3u"):
        self.plex_server = PlexServer(baseurl=baseurl, token=token)
        self.section = section
        self.m3u_path = m3u_path
        self.admin_user = self.plex_server.account().username

    def get_plex_instance_for_user(self, username: str):
        """Return a temporary Plex instance for a given user without modifying the class attribute."""
        if username and username != self.admin_user:
            try:
                return self.plex_server.switchUser(username)
            except Exception as e:
                logging.error(
                    f"Failed to switch to Plex user '{username}': {e}")
                return self.plex_server
        return self.plex_server

    def create_m3u(self, playlist: Playlist) -> str:
        """Creates an M3U file for the given playlist and returns the file path."""
        if not os.path.exists(self.m3u_path):
            os.makedirs(self.m3u_path)

        m3u_file_path = os.path.join(self.m3u_path, f"{playlist.title}.m3u")
        with open(m3u_file_path, "w") as m3u_file:
            m3u_file.write("#EXTM3U\n")
            for track in playlist.tracks:
                if track.path:
                    m3u_file.write(
                        f"#EXTINF:-1,{track.artist} - {track.title}\n")
                    m3u_file.write(f"{track.path}\n")

        logging.info(f"Created M3U file: {m3u_file_path}")
        return m3u_file_path

    def create(self, playlist: Playlist, collection: bool = False):
        """Create or update a Plex playlist or collection."""
        plex_instance = self.plex_server

        if collection:
            existing_collection = None
            try:
                existing_collection = plex_instance.library.section(
                    self.section).collection(title=playlist.title)
            except:
                pass

            if existing_collection:
                logging.info(
                    f"Updating existing Plex collection '{playlist.title}'")
                self.update(playlist, collection=True)
            else:
                logging.info(
                    f"Creating new Plex collection '{playlist.title}'")
                self.create_collection(playlist)
        else:
            existing_playlist = None
            try:
                existing_playlist = plex_instance.playlist(
                    title=playlist.title)
            except:
                pass

            if existing_playlist:
                logging.info(
                    f"Updating existing Plex playlist '{playlist.title}'")
                self.update(playlist)
            else:
                logging.info(f"Creating new Plex playlist '{playlist.title}'")
                self.create_playlist(playlist)

    def create_playlist(self, playlist: Playlist):
        """Create a new Plex playlist using an M3U file."""
        m3u_file = self.create_m3u(playlist)
        plex_instance = self.get_plex_instance_for_user(self.admin_user)

        try:
            temp_playlist = plex_instance.createPlaylist(
                title=f"{playlist.title} (temp)", section=self.section, m3ufilepath=m3u_file)
            items = temp_playlist.items()
        except Exception as e:
            logging.error(
                f"Failed to create temporary playlist '{playlist.title}': {e}")
            return None

        try:
            final_playlist = plex_instance.createPlaylist(
                title=playlist.title, section=self.section, items=items)
            logging.info(f"Created Plex playlist '{playlist.title}'")
        except Exception as e:
            logging.error(
                f"Failed to create Plex playlist '{playlist.title}': {e}")
            return None

        temp_playlist.delete()
        return final_playlist

    def update(self, playlist: Playlist, collection: bool = False):
        """Update an existing Plex playlist or collection by replacing its items."""
        plex_instance = self.plex_server

        if collection:
            try:
                col = plex_instance.library.section(
                    self.section).collection(title=playlist.title)
                if col:
                    col.delete()
                    self.create_collection(playlist)
                    logging.info(f"Updated Plex collection '{playlist.title}'")
            except Exception as e:
                logging.error(
                    f"Failed to update Plex collection '{playlist.title}': {e}")
        else:
            plex_instance = self.get_plex_instance_for_user(self.admin_user)
            try:
                pl = plex_instance.playlist(title=playlist.title)
                if pl:
                    pl.removeItems(pl.items())
                    self.create_playlist(playlist)
                    logging.info(f"Updated Plex playlist '{playlist.title}'")
            except Exception as e:
                logging.error(
                    f"Failed to update Plex playlist '{playlist.title}': {e}")

    def create_collection(self, playlist: Playlist):
        """Create a Plex collection with given playlist items."""
        plex_instance = self.plex_server

        try:
            collection = plex_instance.library.section(self.section).createCollection(
                title=playlist.title, items=playlist.tracks)
            if playlist.poster:
                collection.uploadPoster(url=playlist.poster)
            if playlist.summary:
                collection.editSummary(summary=playlist.summary)
            logging.info(f"Created Plex collection '{playlist.title}'")
        except Exception as e:
            logging.error(
                f"Failed to create Plex collection '{playlist.title}': {e}")
