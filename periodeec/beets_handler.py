import subprocess
import os
import logging


class BeetsHandler():

    def __init__(self, library_path="/music"):
        config_path = os.path.join(os.environ["HOME"], "beets")
        if not os.path.exists(config_path):
            os.makedirs(config_path)

        self.config_file_path = os.path.join(config_path, "config.yaml")
        logging.debug(f"Beets library initialized at {library_path}")

    def exists(self, isrc: str, fuzzy=False, artist="", title="") -> tuple[bool, str]:
        """Checks if a track exists in the Beets library by ISRC or using a fuzzy search."""
        logging.debug(
            f"Checking existence of track: ISRC={isrc}, fuzzy={fuzzy}, artist={artist}, title={title}")

        if fuzzy:
            command = [
                "beet", "list", f"artist:{artist}", f"title:{title}", "--format", "'$path'"]
        else:
            command = ["beet", "list", f"isrc:{isrc}", "--format", "'$path'"]

        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode == 1:
            logging.warning(
                f"Beets command failed: {result.stderr.decode('utf-8')}")
            return False, ""

        output = result.stdout.decode("utf-8").strip()
        if not output:
            logging.debug("Track not found in Beets library.")
            return False, ""

        logging.debug(f"Track found: {output}")
        return True, output.split("\n")[0][1:-1]

    def add(self, path: str, search_id="") -> tuple[bool, str]:
        """Attempts to add a track to the Beets library."""
        logging.debug(
            f"Adding track to Beets: path={path}, search_id={search_id}")

        if search_id == "":
            command = ["beet", "import", "--quiet", path]
        else:
            command = ["beet", "import",
                       f"--search-id={search_id}", "--quiet", path]

        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        result_output = result.stdout.decode("utf-8")

        if "This album is already in the library!" in result_output:
            logging.warning("Album already exists in Beets library.")
            return False, "album already exists in beets library"

        if result.returncode == 1:
            logging.error(f"Beets import failed: {result_output.strip()}")
            if search_id == "":
                return False, result_output.strip()
            else:
                return self.add(path, "")

        if "Skipping." in result_output:
            logging.warning("Beets was unable to find a matching release.")
            if search_id == "":
                result_output = result_output.replace(
                    "\n", " ").replace("Skipping.", "")
                return False, f"beets was unable to find a matching release {result_output}"
            else:
                return self.add(path, "")

        logging.debug("Track successfully added to Beets library.")
        return True, ""
