import os
import logging
import requests
import subprocess


class Freyr:

    def __init__(self):
        pass

    def enqueue(self, path: str, isrc=None, link=None) -> tuple[bool, str, str]:

        id = str(link).split("/")[-1]
        path = os.path.join(path, id)
        if not os.path.exists(path):
            os.makedirs(path)

        try:
            result = subprocess.run(
                [f"freyr", "--directory", f"{path}", f"{link}"], stdout=subprocess.PIPE)
        except Exception as e:
            return False, path, f"freyr returned a non-zero exit code when processing {link} with isrc={isrc}"

        return True, path, ""
