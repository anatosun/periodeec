import subprocess
import os


class Beets():

    def __init__(self, library_path="/music", beet="/usr/bin/beet"):
        config = f"""
plugins: spotify filetote
directory: {library_path}
library: /config/beets/library.db
import:
  move: yes
match:
  strong_rec_thresh: 0.10 # 0.04
  medium_rec_thresh: 0.25 # 0.25
  rec_gap_thresh: 0.25 # 0.25
  max_rec:
    missing_tracks: medium # medium
    unmatched_tracks: medium # medium
    track_length: medium
    track_index: medium
  distance_weights:
    source: 0.0 # 2.0
    artist: 3.0 # 3.0
    album: 3.0 # 3.0
    media: 1.0 # 1.0
    mediums: 1.0 # 1.0
    year: 1.0 # 1.0
    country: 0.5 # 0.5
    label: 0.5 # 0.5
    catalognum: 0.5 # 0.5
    albumdisambig: 0.5 # 0.5
    album_id: 5.0 # 5.0
    tracks: 2.0 # 2.0
    missing_tracks: 0.9 # 0.9
    unmatched_tracks: 0.6 # 0.6
    track_title: 3.0 # 3.0
    track_artist: 2.0 # 2.0
    track_index: 1.0 # 1.0
    track_length: 2.0 # 2.0
    track_id: 5.0 # 5.0
  preferred:
    countries: [] # []
    media: [] # []
    original_year: no # no
  ignored: ["missing_tracks", "track_length", "unmatched_tracks", "track_index"] # []
  required: [] # []
  ignored_media: [] # []
  ignore_data_tracks: yes # yes
  ignore_video_tracks: yes # yes
  track_length_grace: 10 # 10
  track_length_max: 30 # 30
filetote:
  extensions: .cue .log .json .png .jpg .jpeg .lrc
        """
        self.beet = beet
        config_path = os.path.join(os.environ["HOME"], "beets")
        if not os.path.exists(config_path):
            os.makedirs(config_path)

        self.config_file_path = os.path.join(config_path, "config.yaml")
        if not os.path.exists(self.config_file_path):
            with open(self.config_file_path, 'w', encoding="utf-8") as f:
                f.write(config)

    def exists(self, isrc: str) -> tuple[bool, str]:

        result = subprocess.run(
            [f"{self.beet}", "list", f"isrc:{isrc}", "--format", "'$path'"], stdout=subprocess.PIPE)

        path = result.stdout.decode("utf-8")
        if result.returncode == 1:
            return False, path

        if result.stdout.decode("utf-8") == "":
            return False, path

        return True, path[:-2]

    def add(self, path: str, search_id: str) -> tuple[bool, str]:

        result = subprocess.run(
            [f"{self.beet}", "import", f"--search-id={search_id}", "--quiet", f"{path}"], stdout=subprocess.PIPE)

        # beet import failed
        if result.returncode == 1:
            return False, result.stdout.decode("utf-8").replace("\n", "")

        if "Skipping." in result.stdout.decode("utf-8"):
            return False, "beets was unable to find a matching release"

        return True, ""
