import logging
import os
import subprocess
from redis import client
import requests
import base64
import datetime

config = """
{
  "albumFolderFormat": "{AlbumID}",
  "apiKeyIndex": 4,
  "audioQuality": "HiFi",
  "checkExist": true,
  "downloadDelay": true,
  "downloadPath": "downloads",
  "includeEP": true,
  "language": "0",
  "lyricFile": true,
  "multiThread": true,
  "playlistFolderFormat": "Playlist/{PlaylistName} [{PlaylistUUID}]",
  "saveAlbumInfo": true,
  "saveCovers": true,
  "showProgress": true,
  "showTrackInfo": true,
  "trackFileFormat": "{TrackNumber}-{TrackTitle}",
  "usePlaylistFolder": false,
  "videoFileFormat": "{VideoNumber} - {ArtistName} - {VideoTitle}{ExplicitFlag}",
  "videoQuality": "P1080"
}
"""


class Tidal:
    def __init__(self, client_id: str, client_secret: str, tidal_dl="/usr/bin/tidal-dl"):

        self.client_id = client_id
        self.client_secret = client_secret
        self.session = requests.Session()
        self.login()
        self.expiration = datetime.datetime.now(
        )+datetime.timedelta(seconds=int(self.expires_in))

        token_filename = ".tidal-dl.token.json"
        self.token_path = os.path.join(
            self.__get_token_path(), token_filename)

        if not os.path.exists(self.token_path):
            subprocess.run([f"tidal-dl"])
        self.config_file_path = os.path.join(
            self.__get_token_path(), ".tidal-dl.json")

        if not os.path.exists(self.token_path):
            with open(self.config_file_path, 'w', encoding="utf-8") as f:
                f.write(config)

    def __get_token_path(self):
        if "XDG_CONFIG_HOME" in os.environ:
            return os.path.join(os.environ["XDG_CONFIG_HOME"])
        elif "HOME" in os.environ:
            return os.path.join(os.environ["HOME"])
        else:
            return os.path.join(os.path.abspath("./"))

    def login(self, token_url="https://auth.tidal.com/v1/oauth2/token") -> None:

        credentials = f"{self.client_id}:{self.client_secret}"
        b64creds = base64.b64encode(
            credentials.encode("utf-8")).decode("utf-8")
        payload = {"grant_type": "client_credentials"}
        headers = {"Authorization": f"Basic {b64creds}"}

        try:

            response = self.session.post(
                token_url, data=payload, headers=headers)
            self.access_token = response.json().get("access_token")
            self.expires_in = response.json().get("expires_in")
            self.expiration = datetime.datetime.now(
            )+datetime.timedelta(seconds=int(self.expires_in))

        except Exception as e:
            pass

    def link(self, upc: str, api_url="https://openapi.tidal.com", countryCode="US") -> str:

        if datetime.datetime.now() >= self.expiration:
            self.login()

        headers = {"accept": "application/vnd.tidal.v1+json",
                   "Authorization": f"Bearer {self.access_token}", "Content-Type": "application/vnd.tidal.v1+json"}
        response = self.session.get(
            f"{api_url}/albums/byBarcodeId?barcodeId={upc}&countryCode={countryCode}",  headers=headers)
        try:
            errors = response.json().get("errors")

            if errors is not None:
                for error in errors:
                    if error["detail"] == "Please refresh your token":
                        self.login()
                        break

            albums = response.json().get("data")

            if albums is None or len(albums) < 1:
                return ""
        except:
            return ""

        return albums[0].get("id")

    def enqueue(self, upc: str, path: str) -> tuple[bool, str, str]:
        id = self.link(upc)
        if id is None or id == "":
            return False, path, f"upc {upc} not found on Tidal"
        result = subprocess.run(
            ["tidal-dl", "--link", f"{id}", f"{path}"], stdout=subprocess.PIPE)

        if result.returncode == 1:
            return False, path, "tidal-dl exited with code 1"

        if "[ERR]" in result.stdout.decode("utf-8"):
            return False, path, "tidal-dl returned errors while downloading"

        return True, os.path.join(path, id), ""
