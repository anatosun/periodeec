import os
from qobuz_dl.core import QobuzDL


class Qobuz:

    def __init__(self, email, password):
        self.qobuz = QobuzDL(quality=27, embed_art=True, cover_og_quality=False)
        self.qobuz.get_tokens()
        self.qobuz.initialize_client(
                str(email), str(password), self.qobuz.app_id, self.qobuz.secrets)

    def enqueue(self, path: str, isrc=None, link=None, fallback_album_query=None) -> tuple[bool, str, str]:

        results = self.qobuz.search_by_type(
            query=isrc, item_type="track", lucky=True)
        track_mode = True

        if results is None or len(results) == 0:
            results = self.qobuz.search_by_type(
                query=fallback_album_query, item_type="album", lucky=True)
            track_mode = False

        if results is None or len(results) == 0:
            return False, "", f"could not find {isrc} on qobuz nor with fallback query {fallback_album_query}"

        link = results[0]
        if track_mode:
            track_id = str(link).split("/")[-1]
            track = self.qobuz.client.get_track_meta(track_id)
            link = track["album"]['url']

        id = str(link).split("/")[-1]
        path = os.path.join(path, id+"_qobuz")
        if not os.path.exists(path):
            os.makedirs(path)

        try:
            self.qobuz.download_from_id(item_id=id, album=True, alt_path=path)
        except Exception as e:
            return False, path, f"qobuz returned a non-zero exit code when processing {link} with isrc={isrc}"

        return True, path, ""
