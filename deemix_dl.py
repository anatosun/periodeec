import os
import subprocess


class Deemix:

    def __init__(self, arl: str, deemix='/usr/bin/deemix'):
        self.arl = arl
        self.deemix = deemix
        filepath = os.path.join(self.__get_config_path(), ".arl")
        with open(filepath, 'w', encoding="utf-8") as f:
            f.write(arl)

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
