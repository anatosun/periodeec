import subprocess


class Beets():

    def __init__(self, beet="/usr/bin/beet"):
        self.beet = beet

    def exists(self, isrc: str) -> tuple[bool, str]:

        result = subprocess.run(
            [f"{self.beet}", "list", f"isrc:{isrc}", "--format", "'$path'"], stdout=subprocess.PIPE)

        path = result.stdout.decode("utf-8")
        if result.returncode == 1:
            return False, path

        if result.stdout.decode("utf-8") == "":
            return False, path

        return True, path[:-2]

    def add(self, path: str, search_id: str,  force=False) -> bool:

        result = subprocess.run(
            [f"{self.beet}", "import", f"--search-id={search_id}", "--quiet", f"{path}"], stdout=subprocess.PIPE)

        # beet import failed
        if result.returncode == 1:
            return False

        if "Skipping." in result.stdout.decode("utf-8"):
            return False

        return True
