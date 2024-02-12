import os
import logging
import requests
import subprocess

config = """
{
  "downloadLocation": "/downloads",
  "tracknameTemplate": "%discnumber%-%tracknumber% %title%",
  "albumTracknameTemplate": "%discnumber%-%tracknumber% %title%",
  "playlistTracknameTemplate": "%discnumber%-%tracknumber% %title%",
  "createPlaylistFolder": false,
  "playlistNameTemplate": "%playlist%",
  "createArtistFolder": true,
  "artistNameTemplate": "%artist%",
  "createAlbumFolder": true,
  "albumNameTemplate": "%album_id%",
  "createCDFolder": false,
  "createStructurePlaylist": true,
  "createSingleFolder": true,
  "padTracks": true,
  "paddingSize": "0",
  "illegalCharacterReplacer": "_",
  "queueConcurrency": 5,
  "maxBitrate": "9",
  "fallbackBitrate": false,
  "fallbackSearch": true,
  "logErrors": true,
  "logSearched": false,
  "saveDownloadQueue": false,
  "overwriteFile": "t",
  "createM3U8File": false,
  "playlistFilenameTemplate": "playlist",
  "syncedLyrics": true,
  "embeddedArtworkSize": 800,
  "embeddedArtworkPNG": false,
  "localArtworkSize": 1200,
  "localArtworkFormat": "jpg",
  "saveArtwork": true,
  "coverImageTemplate": "cover",
  "saveArtworkArtist": true,
  "artistImageTemplate": "folder",
  "jpegImageQuality": 100,
  "dateFormat": "Y-M-D",
  "albumVariousArtists": true,
  "removeAlbumVersion": false,
  "removeDuplicateArtists": true,
  "tagsLanguage": "",
  "featuredToTitle": "0",
  "titleCasing": "nothing",
  "artistCasing": "nothing",
  "executeCommand": "",
  "tags": {
    "title": true,
    "artist": true,
    "album": true,
    "cover": true,
    "trackNumber": true,
    "trackTotal": true,
    "discNumber": true,
    "discTotal": true,
    "albumArtist": true,
    "genre": true,
    "year": true,
    "date": true,
    "explicit": true,
    "isrc": true,
    "length": true,
    "barcode": true,
    "bpm": true,
    "replayGain": false,
    "label": true,
    "lyrics": false,
    "syncedLyrics": false,
    "copyright": true,
    "composer": true,
    "involvedPeople": false,
    "source": true,
    "savePlaylistAsCompilation": false,
    "useNullSeparator": false,
    "saveID3v1": true,
    "multiArtistSeparator": "nothing",
    "singleAlbumArtist": false,
    "coverDescriptionUTF8": true,
    "rating": false,
    "artists": true
  },
  "feelingLucky": false,
  "fallbackISRC": true,
  "padSingleDigit": true
}
"""


class Deemix:

    def __init__(self, arl: str, deemix='/usr/bin/deemix'):
        self.arl = arl
        self.deemix = deemix
        self.session = requests.Session()
        arl_path = os.path.join(self.__get_config_path(), ".arl")
        with open(arl_path, 'w', encoding="utf-8") as f:
            f.write(arl)

        config_path = self.__get_config_path()
        if not os.path.exists(config_path):
            os.makedirs(config_path)

        config_file_path = os.path.join(config_path, "config.json")
        if not os.path.exists(config_file_path):
            with open(config_file_path, 'w', encoding="utf-8") as f:
                f.write(config)

    def __get_config_path(self) -> str:
        config_folder = ".config"
        if "XDG_CONFIG_HOME" in os.environ:
            return os.path.join(os.environ["XDG_CONFIG_HOME"], config_folder)
        elif "HOME" in os.environ:
            return os.path.join(os.environ["HOME"], config_folder)
        else:
            return os.path.join(os.path.abspath("./"), config_folder)

    def enqueue(self, upc: str, path: str, isrc=None) -> tuple[bool, str, str]:
        link = f"https://api.deezer.com/2.0/album/upc:{upc}"
        response = self.session.get(link)
        id = response.json().get("id")

        if id is None:
            if isrc is not None:
                try:
                    link = f"https://api.deezer.com/2.0/track/isrc:{isrc}"
                    response = self.session.get(link)
                    album = response.json().get("album")
                    if album is None:
                        return False, path, "upc and isrc not found on Deezer"
                    link = album["link"]
                    id = album["id"]

                except Exception as e:
                    return False, path, f"{e}"
            else:
                return False, path, "error upon Deezer API query"

        link = f"https:///api.deezer.com/2.0/album/{id}"

        result = subprocess.run(
            [f"{self.deemix}", "--path", f"{path}", f"{link}"], stdout=subprocess.PIPE)
        try:
            stdout = result.stdout.decode("utf-8")
        except Exception as e:
            return False, path, f"{e}"

        if result.returncode == 1:
            if result.stderr is not None:
                return False, path, result.stderr.decode("utf-8").replace("\n", " ")
            elif stdout != "":
                return False, path, stdout
            else:
                return False, path, f"deemix returned a non-zero exit code when processing {link} with upc={upc} and isrc={isrc}"

        if "DataException" in stdout:
            return False, path, stdout.replace("\n", " ")

        album_path = os.path.join(path, str(id))
        errors = os.path.join(album_path, "errors.txt")
        if os.path.exists(errors):
            return False, album_path, f"check {errors} for more details"

        return True, album_path, ""
