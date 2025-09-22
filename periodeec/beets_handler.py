import os
import random
import time
from urllib import parse
from urllib.parse import urlparse
import logging
from beets.library import Library
from beets import config
from beets import plugins
from beets.autotag import Recommendation
from beets.importer import ImportSession, ImportTask
from beets.dbcore.query import SubstringQuery, AndQuery

# Handle beets version compatibility for action constants
try:
    from beets.importer import action
except ImportError:
    # In beets 2.4.0+, action constants were moved due to importer UI overhaul
    # Define the constants we need for compatibility
    class action:
        SKIP = 'skip'
        APPLY = 'apply'
        ASIS = 'asis'

from beetsplug import plexupdate

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class ImportResult:
    """Result of a Beets operation."""

    def __init__(self, success: bool, message: str = ""):
        self.success = success
        self.message = message


class BeetsHandler:
    class AutoImportSession(ImportSession):
        def __init__(self, lib: Library, path: str):
            super().__init__(lib, None, [os.fsencode(path)], None)
            logger.info(f"Importing {path}")
            self.success = False
            self.msg = ""

        def prettify(self, candidate):
            # Handle different candidate object types (beets version compatibility)
            try:
                if hasattr(candidate, 'info'):
                    # Older beets versions with info attribute
                    artist = candidate.info.artist
                    album = candidate.info.album
                    year = candidate.info.year
                    return f"{artist} - {album} ({year})"
                else:
                    # Newer beets versions with direct access
                    artist = getattr(candidate, 'artist', 'Unknown Artist')
                    album = getattr(candidate, 'album', 'Unknown Album')
                    year = getattr(candidate, 'year', 'Unknown')
                    return f"{artist} - {album} ({year})"
            except AttributeError:
                return str(candidate)

        def should_resume(self, path):
            logger.error(f"Beets not resuming import at '{path}'")
            return False

        def choose_match(self, task: ImportTask):
            self.task = task
            if task.rec == Recommendation.strong:
                self.match = task.candidates[0]
                logger.info(f"Found strong match: {self.prettify(self.match)}")
                self.success = True
                self.msg = f"Beets found strong match among {len(task.candidates)} candidates"
                return self.match
            else:
                logger.error("No strong match for item, skipping.")
                self.msg = f"Beets could not find strong match among {len(task.candidates)} candidates"
                return action.SKIP

        def resolve_duplicate(self, task: ImportTask, found_duplicates):
            self.match = task.candidates[0]
            self.task = task
            logger.error(
                f"Beets found {len(found_duplicates)} duplicate items in library for path '{self.paths[0]}'")
            return action.SKIP

        def choose_item(self, task):
            self.task = task
            if task.rec == Recommendation.strong:
                self.match = task.candidates[0]
                logger.info(f"Found strong match: {self.prettify(self.match)}")
                self.success = True
                self.msg = f"Beets found strong match among {len(task.candidates)} candidates"
                return self.match
            else:
                logger.error("No strong match for item, skipping.")
                self.msg = f"Beets could not find strong match among {len(task.candidates)} candidates"
                return action.SKIP

    def __init__(self, library: str, directory: str, failed_path: str = "./failed",
                 plex_baseurl: str = "", plex_token: str = "", plex_section: str = 'Music',
                 spotify_client_id: str = "", spotify_client_secret: str = "",
                 beets_plugins=None, fuzzy: bool = False,
                 auto_import: bool = True, strong_rec_thresh: float = 0.15,
                 timid: bool = False, duplicate_action: str = 'skip'):

        # Handle default beets_plugins
        if beets_plugins is None:
            beets_plugins = ["spotify", "plexupdate"] if plex_token else ["spotify"]

        # Store instance variables
        self.auto_import = auto_import
        self.failed_path = os.path.abspath(failed_path)

        config["directory"] = os.path.abspath(directory)
        config["library"] = os.path.abspath(library)
        config["plugins"] = beets_plugins
        plugins.load_plugins()
        loaded = [p.name for p in plugins.find_plugins()]
        logger.info(f"Loaded Beets plugins: {loaded}")

        config['import']['flat'] = True
        config['import']['resume'] = False
        config['import']['quiet'] = not timid
        config['import']['timid'] = timid
        config['import']['duplicate_action'] = duplicate_action
        config["import"]["move"] = True

        config["match"]["strong_rec_thresh"] = strong_rec_thresh
        config["match"]["medium_rec_thresh"] = min(0.25, strong_rec_thresh + 0.1)
        config["match"]["rec_gap_thresh"] = min(0.25, strong_rec_thresh + 0.1)

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

        parsed_url = urlparse(plex_baseurl)
        plex_host = parsed_url.hostname
        if parsed_url.port:
            plex_port = parsed_url.port
        else:
            if "https" in plex_baseurl:
                plex_port = 443
            elif "http" in plex_baseurl:
                plex_port = 80
            else:
                plex_port = 32400

        logger.info(
            f"Plex plugin initialized with host '{plex_host}' and port '{plex_port}'")

        self.plex = plexupdate.PlexUpdate()
        for name in logging.root.manager.loggerDict:
            if name.startswith("beetsplug.plexupdate"):
                qlogger = logging.getLogger(name)
                qlogger.setLevel(logging.CRITICAL + 1)
                qlogger.propagate = False
                qlogger.handlers.clear()

        config["plex"]["host"] = plex_host
        config["plex"]["port"] = plex_port
        config["plex"]["token"] = plex_token
        config["plex"]["library_name"] = plex_section
        config["plex"]["ignore_cert_errors"] = False
        config["plex"]["secure"] = "https" in plex_baseurl

        config["chroma"]["auto"] = False
        config["musicbrainz"]["enabled"] = False

        config["spotify"]["tiebreak"] = "popularity"
        config["spotify"]["source_weight"] = 0.9
        config["spotify"]["show_failures"] = True
        config["spotify"]["artist_field"] = "albumartist"
        config["spotify"]["track_field"] = "title"
        config["spotify"]["regex"] = []
        config["spotify"]["client_id"] = spotify_client_id
        config["spotify"]["client_secret"] = spotify_client_secret
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

    def exists(self, isrc: str, artist: str = "", title: str = "", album: str = "") -> tuple[bool, str]:

        if isrc != "" and self.cache.get(isrc) is not None:
            path = self.cache[isrc]
            logger.info(f"Found match from cache at '{path}'")
            return True, path

        query = SubstringQuery("isrc", isrc)

        paths = self._query(query)

        if paths:
            path = os.fsdecode(paths[0])
            logger.info(f"Found perfect match at '{path}'")
            self.cache[isrc] = path
            return True, path

        if self.fuzzy:
            # Build fuzzy search query with available fields
            queries = []
            if artist:
                queries.append(SubstringQuery("artist", artist))
            if title:
                queries.append(SubstringQuery("title", title))
            if album:
                queries.append(SubstringQuery("album", album))

            if queries:
                query = AndQuery(queries)
            else:
                logger.info(f"No search terms available for fuzzy matching")
                return False, ""

        else:
            logger.info(
                f"Could not match track with isrc '{isrc}', artist '{artist}', title '{title}', album '{album}'")
            return False, ""

        paths = self._query(query)

        if paths:
            path = os.fsdecode(paths[0])
            logger.info(f"Found fuzzy match at '{path}'")
            if isrc != "":
                self.cache[isrc] = path
            return True, path

        logger.info(
            f"Could not match track with isrc '{isrc}', artist '{artist}', title '{title}', album '{album}'")
        return False, ""

    def _move_to_failed(self, path: str) -> bool:
        """Move a file or directory to the failed directory."""
        try:
            import shutil

            # Ensure failed directory exists
            os.makedirs(self.failed_path, exist_ok=True)

            # Get filename/dirname for destination
            basename = os.path.basename(path)
            dest_path = os.path.join(self.failed_path, basename)

            # Handle conflicts by adding a timestamp
            if os.path.exists(dest_path):
                import time
                timestamp = int(time.time())
                name, ext = os.path.splitext(basename)
                dest_path = os.path.join(self.failed_path, f"{name}_{timestamp}{ext}")

            # Move the file/directory
            shutil.move(path, dest_path)
            logger.info(f"Moved failed import to: {dest_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to move {path} to failed directory: {e}")
            return False

    def add(self, path: str, search_id="") -> bool:
        """Use a custom non-interactive import session."""

        success = False
        imported = []

        if search_id != "":
            timeout = int(random.uniform(1, 3))
            time.sleep(timeout)
            logger.info(f"Sleeping for {timeout}s to prevent rate limiting")
            try:
                logger.info(
                    f"Attempting to autotag '{path}' with search_id '{search_id}'")
                config["import"]["search_ids"] = [search_id]

                session = self.AutoImportSession(
                    lib=self.lib,
                    path=path
                )
                session.run()
                success = session.success
                if hasattr(session, 'task') and session.task:
                    imported = session.task.imported_items()
            except Exception as e:
                logger.error(f"Beets import failed: {e}")
                success = False

        if self.fuzzy and not success:

            timeout = int(random.uniform(1, 3))
            time.sleep(timeout)
            logger.info(f"Sleeping for {timeout}s to prevent rate limiting")
            try:
                logger.info(
                    f"Attempting to autotag '{path}' without search_id")
                config["import"]["search_ids"] = []

                session = self.AutoImportSession(
                    lib=self.lib,
                    path=path
                )
                session.run()
                success = session.success
                if hasattr(session, 'task') and session.task:
                    imported = session.task.imported_items()
            except Exception as e:
                logger.error(f"Beets import failed: {e}")
                success = False

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

        if success and config["plex"]["token"] != "":
            logger.info(
                f"Notifying Plex of newly imported tracks at '{config['plex']['host']}'")
            self.plex.update(self.lib)

        # Move failed imports to failed directory
        if not success and os.path.exists(path):
            self._move_to_failed(path)

        return success

    def get_library_stats(self):
        """Get library statistics."""
        try:
            # Basic counts
            total_items = 0
            total_albums = 0
            total_size = 0
            total_files = 0

            try:
                # Count items and albums
                for item in self.lib.items():
                    total_items += 1
                    try:
                        path = item.get("path", with_album=False)
                        if path and os.path.exists(os.fsdecode(path)):
                            total_size += os.path.getsize(os.fsdecode(path))
                            total_files += 1
                    except Exception:
                        continue

                for album in self.lib.albums():
                    total_albums += 1

            except Exception as e:
                logger.debug(f"Error getting library counts: {e}")

            return {
                'total_tracks': total_items,
                'total_albums': total_albums,
                'total_files': total_files,
                'total_size_bytes': total_size,
                'total_size_gb': total_size / (1024**3) if total_size > 0 else 0,
                'cache_entries': len(self.cache)
            }

        except Exception as e:
            logger.error(f"Error getting library stats: {e}")
            return {'error': str(e), 'total_tracks': 0, 'total_albums': 0}

    def validate_library(self) -> ImportResult:
        """Validate library integrity and accessibility."""
        try:
            # Get proper paths (handle bytes/string encoding)
            library_path = self.lib.path
            if isinstance(library_path, bytes):
                library_path = os.fsdecode(library_path)

            directory_path = self.lib.directory
            if isinstance(directory_path, bytes):
                directory_path = os.fsdecode(directory_path)

            # Check library file
            if not os.path.exists(os.path.abspath(library_path)):
                error_msg = f"Library database not found: {library_path}"
                logger.error(error_msg)
                return ImportResult(False, error_msg)

            # Check directory
            if not os.path.exists(directory_path):
                error_msg = f"Music directory not found: {directory_path}"
                logger.error(error_msg)
                return ImportResult(False, error_msg)

            # Test library access
            try:
                # Try to access the library
                list(self.lib.items())
                list(self.lib.albums())
            except Exception as e:
                error_msg = f"Cannot access library database: {e}"
                logger.error(error_msg)
                return ImportResult(False, error_msg)

            # Check write permissions
            try:
                test_file = os.path.join(directory_path, '.beets_test')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
            except Exception as e:
                error_msg = f"No write permission to music directory: {e}"
                logger.error(error_msg)
                return ImportResult(False, error_msg)

            logger.info("Library validation successful")
            return ImportResult(True, "Library validation successful")

        except Exception as e:
            error_msg = f"Library validation failed: {e}"
            logger.error(error_msg)
            return ImportResult(False, error_msg)