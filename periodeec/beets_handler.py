import os
import logging
from beets.library import Library
from beets.library import plugins
from beets import config
from beets.autotag import Recommendation
from beets.importer import ImportSession, action, ImportTask
from beets.dbcore.query import SubstringQuery, AndQuery
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class BeetsHandler:
    class AutoImportSession(ImportSession):
        def __init__(self, lib: Library, path: str):
            super().__init__(lib, None, [os.fsencode(path)], None)
            logger.info(f"Importing {path}")
            self.success = False
            self.msg = ""

        def prettify(self, candidate):
            artist = candidate.info.artist
            album = candidate.info.album
            year = candidate.info.year
            return f"{artist} - {album} ({year})"

        def should_resume(self, path):
            logger.warning(f"Beets not resuming import at '{path}'")
            return False

        def choose_match(self, task: ImportTask):
            if task.rec == Recommendation.strong:
                self.match = task.candidates[0]
                logger.info(f"Found strong match: {self.prettify(self.match)}")
                self.success = True
                self.task = task
                self.msg = f"Beets found strong match among {len(task.candidates)} candidates"
                return self.match
            else:
                logger.warning("No strong match for item, skipping.")
                self.msg = f"Beets could not find strong match among {len(task.candidates)} candidates"
                return action.SKIP

        def resolve_duplicate(self, task: ImportTask, found_duplicates):
            self.match = task.candidates[0]
            logger.error(
                f"Beets found {len(found_duplicates)} duplicate items in library for path '{self.paths[0]}'")
            return action.SKIP

        def choose_item(self, task):
            if task.rec == Recommendation.strong:
                self.match = task.candidates[0]
                logger.info(f"Found strong match: {self.prettify(self.match)}")
                self.success = True
                self.task = task
                self.msg = f"Beets found strong match among {len(task.candidates)} candidates"
                return self.match
            else:
                logger.warning("No strong match for item, skipping.")
                self.msg = f"Beets could not find strong match among {len(task.candidates)} candidates"
                return action.SKIP

    def __init__(self, library: str, directory: str, baseurl: str, token: str, client_id: str, client_secret: str, port=32400, section='Music', beets_plugins=["spotify", "plexupdate"], fuzzy=False):

        config["directory"] = os.path.abspath(directory)
        config["library"] = os.path.abspath(library)
        config["plugins"] = beets_plugins
        plugins.load_plugins(config["plugins"].as_str_seq())
        loaded = [p.name for p in plugins.find_plugins()]
        logger.info(f"Loaded Beets plugins: {loaded}")

        config['import']['flat'] = True
        config['import']['resume'] = False
        config['import']['quiet'] = True
        config['import']['timid'] = False
        config['import']['duplicate_action'] = 'skip'
        config["import"]["move"] = True

        config["match"]["strong_rec_thresh"] = 0.15
        config["match"]["medium_rec_thresh"] = 0.25
        config["match"]["rec_gap_thresh"] = 0.25

        config["match"]["max_rec"]["missing_tracks"] = "medium"
        config["match"]["max_rec"]["unmatched_tracks"] = "medium"
        config["match"]["max_rec"]["track_length"] = "medium"
        config["match"]["max_rec"]["track_index"] = "medium"

        config["match"]["distance_weights"] = {
            "source": 0.0,
            "artist": 1.0,
            "album": 3.0,
            "media": 1.0,
            "mediums": 1.0,
            "year": 1.0,
            "country": 0.5,
            "label": 0.5,
            "catalognum": 0.5,
            "albumdisambig": 0.5,
            "album_id": 5.0,
            "tracks": 2.0,
            "missing_tracks": 0.9,
            "unmatched_tracks": 0.6,
            "track_title": 1.5,
            "track_artist": 2.0,
            "track_index": 0.0,
            "track_length": 2.0,
            "track_id": 5.0
        }

        config["match"]["preferred"]["countries"] = []
        config["match"]["preferred"]["media"] = []
        config["match"]["preferred"]["original_year"] = False

        config["match"]["ignored"] = ["missing_tracks"]
        config["match"]["required"] = []
        config["match"]["ignored_media"] = []
        config["match"]["ignore_data_tracks"] = True
        config["match"]["ignore_video_tracks"] = True
        config["match"]["track_length_grace"] = 10
        config["match"]["track_length_max"] = 30

        config["plex"]["host"] = baseurl
        config["plex"]["port"] = port
        config["plex"]["token"] = token
        config["plex"]["library_name"] = section

        config["chroma"]["auto"] = False
        config["musicbrainz"]["enabled"] = False

        config["spotify"]["tiebreak"] = "popularity"
        config["spotify"]["source_weight"] = 0.9
        config["spotify"]["show_failures"] = True
        config["spotify"]["artist_field"] = "albumartist"
        config["spotify"]["track_field"] = "title"
        config["spotify"]["regex"] = []
        config["spotify"]["client_id"] = client_id
        config["spotify"]["client_secret"] = client_secret
        config["spotify"]["tokenfile"] = "spotify_token.json"

        self.lib = Library(path=library, directory=directory)
        self.fuzzy = fuzzy
        self.cache = {}

        logger.info(
            f"Beets initialized with library '{library}' and music directory '{directory}'")

    def _query(self, beet_query) -> list[str]:

        results = []
        for item in self.lib.items(beet_query):
            results.append(item.get("path", with_album=False))
        return results

    def exists(self, isrc: str, artist: str = "", title: str = "") -> tuple[bool, str]:

        if isrc != "" and self.cache.get(isrc) is not None:
            path = self.cache[isrc]
            logger.info(f"Found match from cache at '{path}'")
            return True, path

        query = SubstringQuery("isrc", isrc)

        paths = self._query(query)

        if paths:
            path = os.fsdecode(paths[0])
            logger.info(f"Found perfect match at '{path}'")
            self.cache['isrc'] = path
            return True, path

        if self.fuzzy:

            query = AndQuery([
                SubstringQuery("artist", artist),
                SubstringQuery("title", title)
            ])

        else:
            logger.info(f"Could not match item with isrc '{isrc}'")
            return False, ""

        paths = self._query(query)

        if paths:
            path = os.fsdecode(paths[0])
            logger.info(f"Found fuzzy match at '{path}'")
            if isrc != "":
                self.cache['isrc'] = path
            return True, path

        logger.info(
            f"Could not match item with isrc '{isrc}', artist '{artist}' and title '{title}'")
        return False, ""

    def add(self, path: str, search_id="") -> bool:
        """Use a custom non-interactive import session."""

        success = False
        imported = []

        try:

            if search_id != "":
                logger.info(
                    f"Attempting to autotag '{path}' with search_id '{search_id}'")
                config["import"]["search_ids"] = [search_id]

                session = self.AutoImportSession(
                    lib=self.lib,
                    path=path
                )
                session.run()
                success = session.success
                imported = session.task.imported_items()

            if self.fuzzy and not success:

                logger.info(
                    f"Attempting to autotag '{path}' without search_id")
                config["import"]["search_ids"] = []

                session = self.AutoImportSession(
                    lib=self.lib,
                    path=path
                )
                session.run()
                success = session.success
                imported = session.task.imported_items()

        except Exception as e:
            logger.error(f"Beets import failed: {e}")
            return False

        if success:
            try:
                for item in imported:
                    path = os.fsdecode(item.destination())
                    isrc = item.get("isrc", "", with_album=False)
                    title = item.get("title", "", with_album=False)
                    logger.info(
                        f"Beets imported track '{title}' at path '{path}'")
                    if isrc != "":
                        self.cache[isrc] = path
            except Exception as e:
                logger.error("Beets failed to cache paths after import")

        return success
