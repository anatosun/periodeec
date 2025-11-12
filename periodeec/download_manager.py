import os
import shutil
import logging
from periodeec.modules.downloader import Downloader, DownloadResult
from periodeec.track import Track

logger = logging.getLogger(__name__)


class DownloadManager:
    def __init__(self, downloaders: list[Downloader], download_path: str, failed_path: str):
        """
        Initializes the DownloadManager with a list of downloaders and necessary paths.

        :param downloaders: List of downloader instances with a .enqueue() method.
        :param download_path: Path where successful downloads will be stored.
        :param failed_path: Path where failed downloads will be logged or moved.
        """
        self.downloaders = downloaders
        self.download_path = download_path
        self.failed_path = failed_path

        os.makedirs(self.download_path, exist_ok=True)
        os.makedirs(self.failed_path, exist_ok=True)

    def enqueue(self, track: Track) -> tuple[bool, str]:
        """
        Calls the .enqueue() method on downloaders with the given track until it succeeds.

        :param track: A track object.
        :return: Tuple of (success, path)
        """
        for downloader in self.downloaders:

            logger.info(
                f"Using {downloader.name} to download track '{track.title}'")

            folder = f"{track.artist} - {track.album} ({track.release_year}) [{downloader.name}]"

            dl_path = os.path.join(self.download_path, folder)
            os.makedirs(dl_path, exist_ok=True)

            failed_file_path = os.path.join(self.failed_path, folder)

            if os.path.exists(failed_file_path):
                try:
                    shutil.move(failed_file_path, dl_path)
                except Exception as e:
                    logger.error(
                        f"Failed to move previously downloaded files at {failed_file_path}: {e}")

            result = downloader.enqueue(
                path=dl_path,
                isrc=track.isrc,
                artist=track.artist,
                title=track.title,
                album=track.album,
                release_year=track.release_year
            )

            if result.success:
                logger.info(
                    f"{downloader.name} successfully downloaded {len(result.downloaded_files or [])} file(s)"
                )
                return True, result.path

            # Log detailed error message
            error_message = (
                f"Downloader {downloader.name} failed for {track.title}: "
                f"{result.error_message}\n"
            )
            logger.warning(error_message)

            with open(os.path.join(self.failed_path, 'errors.log'), 'a') as f:
                f.write(error_message)

            try:
                shutil.move(dl_path, failed_file_path)
            except Exception as move_error:
                logger.error(
                    f"Failed to move file {result.path} to {failed_file_path}: {move_error}")

        return False, ""
