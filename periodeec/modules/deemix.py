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

    def __init__(self, arl: str):
        self.arl = arl
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

    def enqueue(self, path: str, isrc=None, link=None, fallback_album_query=None) -> tuple[bool, str, str]:

        id = str(link).split("/")[-1]
        path = os.path.join(path, id+"_deemix")
        if not os.path.exists(path):
            os.makedirs(path)
        try:
            link = f"https://api.deezer.com/2.0/track/isrc:{isrc}"
            response = self.session.get(link)
            album = response.json().get("album")
            artist = response.json().get("artist")

            if album is None or artist is None:
                return False, path, f"album not found for track with isrc {isrc}"

            id = album["id"]
            link = album.get("link")

            if link is None:
                return False, path, f"album link not found for track with isrc {isrc}"
            link = str(link)
            response = self.session.get(link)

            if response.history[-1].status_code == 302:
                link = response.history[-1].url

            id = link[link.find("album/")+6:]

        except Exception as e:
            return False, path, f"{e}"

        try:
            result = subprocess.run(
                [f"deemix", "--path", f"{path}", f"{link}"], stdout=subprocess.PIPE)
        except Exception as e:
            return False, path, f"deemix returned a non-zero exit code when processing {link} with isrc={isrc}"

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
                return False, path, f"deemix returned a non-zero exit code when processing {link} with isrc={isrc}"

        if "DataException" in stdout:
            return False, path, stdout.replace("\n", " ")

        album_path = os.path.join(path, str(id))
        errors = os.path.join(album_path, "errors.txt")
        if os.path.exists(errors):
            return False, path, f"check {errors} for more details"

        return True, path, ""
