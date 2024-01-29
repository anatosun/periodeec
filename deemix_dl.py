import os
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
  "albumNameTemplate": "%upc%",
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
        arl_path = os.path.join(self.__get_config_path(), ".arl")
        with open(arl_path, 'w', encoding="utf-8") as f:
            f.write(arl)
        config_path = os.path.join(self.__get_config_path(), "config.json")
        if not os.path.exists(config_path):
            with open(config_path, 'w', encoding="utf-8") as f:
                f.write(config)

    def __get_config_path(self) -> str:
        config_folder = ".config"
        if "XDG_CONFIG_HOME" in os.environ:
            return os.path.join(os.environ["XDG_CONFIG_HOME"], config_folder)
        elif "HOME" in os.environ:
            return os.path.join(os.environ["HOME"], config_folder)
        else:
            return os.path.join(os.path.abspath("./"), config_folder)

    def enqueue(self, upc: str, path: str) -> tuple[bool, str, str]:
        link = f"https://deezer/album/upc:{upc}"
        result = subprocess.run(
            [f"{self.deemix}", "--path", f"{path}", f"{link}"], stdout=subprocess.PIPE)

        if result.returncode == 1:
            return False, path, "tidal-dl exited with code 1"

        if "DataException" in result.stdout.decode("utf-8"):
            return False, path, result.stdout.decode("utf-8")[:-2]

        return True, os.path.join(path, upc.lstrip("0")), ""
