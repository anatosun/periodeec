import os
import logging
import sys
from qobuz_dl.core import QobuzDL
from periodeec.modules.downloader import Downloader
import contextlib
@contextlib.contextmanager
def suppress_stdout_stderr():
    with open(os.devnull, 'w') as devnull:
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = devnull
        sys.stderr = devnull
        try:
            yield
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class Qobuz(Downloader):

    def __init__(self,  email: str, password: str, quality=27, embed_art=True, cover_og_quality=False):
        super().__init__("Qobuz")
        if email == "" or password == "":
            raise ValueError("Email and password cannot be empty.")

        self.qobuz = QobuzDL(quality=quality, embed_art=embed_art,
                             cover_og_quality=cover_og_quality)
        self.qobuz.get_tokens()
        self.qobuz.initialize_client(
            email, password, self.qobuz.app_id, self.qobuz.secrets)

    def match(self, isrc: str, artist: str, title: str) -> str:
        query = isrc
        results = self.qobuz.search_by_type(
            query, item_type="track", lucky=True)
        if results is not None and len(results) > 0:
            track_id = str(results[0]).split("/")[-1]
            try:
                track = self.qobuz.client.get_track_meta(track_id)
                logger.info(
                    f"{self.name} successfully matched track with isrc '{isrc}'")
                return track['album']['url']
            except Exception as e:
                logger.error("{self.name} ran into an error: {e}")

        query = f"{artist} {title}"
        try:
            results = self.qobuz.search_by_type(
                query=query, item_type="album", lucky=True)
        except Exception as e:
            logger.error("{self.name} ran into an error: {e}")
            results = []

        if results is not None and len(results) > 0:
            logger.info(
                f"{self.name} successfully matched track with artist '{artist}' and title '{title}'")
            return results[0]

        logger.error(f"{self.name} could not match track with isrc '{isrc}'")
        return ""

    def enqueue(self, path: str, isrc: str, artist: str, title: str) -> tuple[bool, str]:

        link = self.match(isrc, artist, title)
        if link == "":
            return False, path

        album_id = link.split("/")[-1]

        if not os.path.exists(path):
            os.makedirs(path)

        try:
            with suppress_stdout_stderr():  # 👈 suppress tqdm here
                self.qobuz.download_from_id(
                    item_id=album_id, album=True, alt_path=path
                )
        except Exception as e:
            logger.error(f"{self.name} returned a non-zero exit code: {e}")
            return False, path

        return True, path
