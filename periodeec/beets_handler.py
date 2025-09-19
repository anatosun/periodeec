import os
import random
import time
import logging
from typing import Dict, Any, List, Optional, Tuple
from urllib.parse import urlparse
from beets.library import Library
from beets import config
from beets import plugins
from beets.autotag import Recommendation
from beets.importer import ImportSession, ImportTask

# Handle beets version compatibility for action constants
try:
    from beets.importer import action
except ImportError:
    # In beets 2.4.0+, action constants were moved due to importer UI overhaul
    # Define the constants we need for compatibility
    class action:
        SKIP = 'skip'
        # Add other actions if needed in the future
        APPLY = 'apply'
        ASIS = 'asis'
from beets.dbcore.query import SubstringQuery, AndQuery, OrQuery
from beetsplug import plexupdate

logger = logging.getLogger(__name__)


class ImportResult:
    """Result of a Beets import operation."""
    
    def __init__(self, success: bool, message: str = "", 
                 imported_paths: List[str] = None, details: Dict[str, Any] = None):
        self.success = success
        self.message = message
        self.imported_paths = imported_paths or []
        self.details = details or {}
        self.timestamp = time.time()


class BeetsHandler:
    """Beets handler with import control, caching, and error handling."""
    
    def __init__(self, library: str, directory: str, plex_baseurl: str = "", 
                 plex_token: str = "", plex_section: str = 'Music',
                 spotify_client_id: str = "", spotify_client_secret: str = "",
                 beets_plugins: List[str] = None, fuzzy: bool = False,
                 auto_import: bool = True, strong_rec_thresh: float = 0.15,
                 timid: bool = False, duplicate_action: str = 'skip'):
        """
        Initialize the Beets handler.
        
        Args:
            library: Path to Beets library database
            directory: Music directory path
            plex_baseurl: Plex server URL for updates
            plex_token: Plex authentication token
            plex_section: Plex music section name
            spotify_client_id: Spotify client ID for metadata
            spotify_client_secret: Spotify client secret
            beets_plugins: List of plugins to load
            fuzzy: Enable fuzzy matching
            auto_import: Enable automatic import mode
            strong_rec_thresh: Threshold for strong recommendations
            timid: Enable timid mode (ask more questions)
            duplicate_action: Action for duplicates ('skip', 'keep', 'remove')
        """
        # Store configuration
        self.library_path = os.path.abspath(library)
        self.directory_path = os.path.abspath(directory)
        self.plex_baseurl = plex_baseurl
        self.plex_token = plex_token
        self.plex_section = plex_section
        self.fuzzy = fuzzy
        self.auto_import = auto_import
        
        # Plugin configuration
        if beets_plugins is None:
            beets_plugins = ["spotify", "plexupdate"] if plex_token else ["spotify"]
        
        # Setup Beets configuration
        self._setup_beets_config(
            beets_plugins, strong_rec_thresh, timid, duplicate_action,
            spotify_client_id, spotify_client_secret
        )
        
        # Initialize components
        self.lib = Library(path=self.library_path, directory=self.directory_path)
        self.plex_updater = self._setup_plex_updater() if plex_token else None
        
        # Caching and statistics
        self._track_cache = {}
        self._import_stats = {
            'total_imports': 0,
            'successful_imports': 0,
            'failed_imports': 0,
            'duplicate_skips': 0,
            'strong_matches': 0,
            'weak_matches': 0
        }
        
        logger.info(f"Beets handler initialized with library '{library}' and directory '{directory}'")
        
    def _setup_beets_config(self, beets_plugins: List[str], strong_rec_thresh: float,
                           timid: bool, duplicate_action: str, spotify_client_id: str,
                           spotify_client_secret: str):
        """Configure Beets settings."""
        # Basic paths
        config["directory"] = self.directory_path
        config["library"] = self.library_path
        
        # Plugin configuration
        config["plugins"] = beets_plugins
        plugins.load_plugins()
        loaded = [p.name for p in plugins.find_plugins()]
        logger.info(f"Loaded Beets plugins: {loaded}")
        
        # Import settings
        config['import']['flat'] = True
        config['import']['resume'] = False
        config['import']['quiet'] = not timid
        config['import']['timid'] = timid
        config['import']['duplicate_action'] = duplicate_action
        config["import"]["move"] = True
        config["import"]["copy"] = False
        config["import"]["link"] = False
        config["import"]["hardlink"] = False
        
        # Matching thresholds
        config["match"]["strong_rec_thresh"] = strong_rec_thresh
        config["match"]["medium_rec_thresh"] = min(0.25, strong_rec_thresh + 0.1)
        config["match"]["rec_gap_thresh"] = min(0.25, strong_rec_thresh + 0.1)
        
        # Match requirements and penalties
        config["match"]["max_rec"] = {
            "missing_tracks": "medium",
            "unmatched_tracks": "medium",
            "track_length": "medium",
            "track_index": "medium"
        }
        
        # Distance weights for matching
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
        
        # Match preferences
        config["match"]["preferred"] = {
            "countries": [],
            "media": [],
            "original_year": False
        }
        
        config["match"]["ignored"] = ["missing_tracks"]
        config["match"]["required"] = []
        config["match"]["ignored_media"] = []
        config["match"]["ignore_data_tracks"] = True
        config["match"]["ignore_video_tracks"] = True
        config["match"]["track_length_grace"] = 10
        config["match"]["track_length_max"] = 30
        
        # Disable unnecessary features
        config["chroma"]["auto"] = False
        config["musicbrainz"]["enabled"] = True
        config["musicbrainz"]["host"] = "musicbrainz.org"
        config["musicbrainz"]["rate_limit"] = 1.0
        
        # Spotify plugin configuration
        if spotify_client_id and spotify_client_secret:
            config["spotify"]["tiebreak"] = "popularity"
            config["spotify"]["source_weight"] = 0.9
            config["spotify"]["show_failures"] = True
            config["spotify"]["artist_field"] = "albumartist"
            config["spotify"]["track_field"] = "title"
            config["spotify"]["regex"] = []
            config["spotify"]["client_id"] = spotify_client_id
            config["spotify"]["client_secret"] = spotify_client_secret
            config["spotify"]["tokenfile"] = os.path.join(os.path.dirname(self.library_path), "spotify_token.json")
        
        # Plex plugin configuration
        if self.plex_baseurl and self.plex_token:
            parsed_url = urlparse(self.plex_baseurl)
            plex_host = parsed_url.hostname or "localhost"
            
            if parsed_url.port:
                plex_port = parsed_url.port
            elif "https" in self.plex_baseurl:
                plex_port = 443
            elif "http" in self.plex_baseurl:
                plex_port = 80
            else:
                plex_port = 32400
            
            config["plex"]["host"] = plex_host
            config["plex"]["port"] = plex_port
            config["plex"]["token"] = self.plex_token
            config["plex"]["library_name"] = self.plex_section
            config["plex"]["ignore_cert_errors"] = False
            config["plex"]["secure"] = "https" in self.plex_baseurl
            
            logger.info(f"Plex plugin configured for {plex_host}:{plex_port}")
    
    def _setup_plex_updater(self):
        """Initialize Plex updater plugin."""
        try:
            plex_updater = plexupdate.PlexUpdate()
            
            # Suppress verbose logging from Plex plugin
            for name in logging.root.manager.loggerDict:
                if name.startswith("beetsplug.plexupdate"):
                    plex_logger = logging.getLogger(name)
                    plex_logger.setLevel(logging.CRITICAL + 1)
                    plex_logger.propagate = False
                    plex_logger.handlers.clear()
            
            return plex_updater
        except Exception as e:
            logger.warning(f"Failed to initialize Plex updater: {e}")
            return None
    
    class SmartImportSession(ImportSession):
        """Smart import session with decision making."""
        
        def __init__(self, lib: Library, path: str, search_id: str = "", 
                     handler_ref=None, auto_mode: bool = True):
            super().__init__(lib, None, [os.fsencode(path)], None)
            self.handler_ref = handler_ref
            self.auto_mode = auto_mode
            self.search_id = search_id
            self.import_result = ImportResult(False, "Not started")
            self.imported_items = []
            
            if search_id:
                config["import"]["search_ids"] = [search_id]
            else:
                config["import"]["search_ids"] = []
            
            logger.info(f"Starting import session for: {path}")
        
        def prettify_candidate(self, candidate):
            """Format candidate information for logging."""
            try:
                # Handle None candidates
                if candidate is None:
                    return "<None Candidate>"

                # Handle string candidates first (simplest case)
                if isinstance(candidate, str):
                    return candidate

                # Handle different candidate object types (beets version compatibility)
                # Use getattr exclusively to avoid any potential attribute access issues
                info = getattr(candidate, 'info', None)
                if info is not None:
                    # Older beets versions with info attribute
                    artist = getattr(info, 'artist', 'Unknown Artist')
                    album = getattr(info, 'album', 'Unknown Album')
                    year = getattr(info, 'year', 'Unknown')
                    return f"{artist} - {album} ({year})"
                elif (getattr(candidate, 'artist', None) is not None and
                      getattr(candidate, 'album', None) is not None):
                    # Direct access for newer beets versions or different candidate types
                    artist = getattr(candidate, 'artist', 'Unknown Artist')
                    album = getattr(candidate, 'album', 'Unknown Album')
                    year = getattr(candidate, 'year', 'Unknown')
                    return f"{artist} - {album} ({year})"
                else:
                    # Fallback for any object - try to get meaningful representation
                    candidate_str = str(candidate)
                    if hasattr(candidate, '__dict__'):
                        logger.debug(f"Unknown candidate type with attributes: {list(candidate.__dict__.keys())}")
                    return candidate_str
            except AttributeError as ae:
                logger.error(f"AttributeError in prettify_candidate: {ae}, candidate type: {type(candidate)}")
                logger.error(f"Candidate value: {repr(candidate)}")
                return f"<AttributeError: {type(candidate).__name__}>"
            except Exception as e:
                logger.debug(f"Error formatting candidate: {e}, type: {type(candidate)}")
                return f"<Candidate: {type(candidate).__name__}>"
        
        def should_resume(self, path):
            """Don't resume interrupted imports."""
            logger.warning(f"Beets not resuming import at '{os.fsdecode(path)}'")
            return False
        
        def choose_match(self, task: ImportTask):
            """Choose the best match for an album."""
            self.current_task = task
            
            if not task.candidates:
                logger.warning("No candidates found for album import")
                self.import_result = ImportResult(False, "No candidates found")
                return action.SKIP
            
            if task.rec == Recommendation.strong:
                match = task.candidates[0]
                logger.info(f"Strong album match found: {self.prettify_candidate(match)}")
                
                if self.handler_ref:
                    self.handler_ref._import_stats['strong_matches'] += 1
                
                self.import_result = ImportResult(
                    True, 
                    f"Strong match found among {len(task.candidates)} candidates",
                    details={'match_strength': 'strong', 'candidate_count': len(task.candidates)}
                )
                return match
            
            elif task.rec == Recommendation.medium and self.auto_mode:
                match = task.candidates[0]
                logger.info(f"Medium album match found: {self.prettify_candidate(match)}")
                
                if self.handler_ref:
                    self.handler_ref._import_stats['weak_matches'] += 1
                
                self.import_result = ImportResult(
                    True, 
                    f"Medium match found among {len(task.candidates)} candidates",
                    details={'match_strength': 'medium', 'candidate_count': len(task.candidates)}
                )
                return match
            
            else:
                logger.warning(f"No suitable album match found (recommendation: {task.rec})")
                self.import_result = ImportResult(
                    False, 
                    f"No suitable match among {len(task.candidates)} candidates",
                    details={'match_strength': 'none', 'candidate_count': len(task.candidates)}
                )
                return action.SKIP
        
        def resolve_duplicate(self, task: ImportTask, found_duplicates):
            """Handle duplicate items in library."""
            self.current_task = task
            
            logger.warning(f"Found {len(found_duplicates)} duplicate items for: {os.fsdecode(self.paths[0])}")
            
            if self.handler_ref:
                self.handler_ref._import_stats['duplicate_skips'] += 1
            
            self.import_result = ImportResult(
                False, 
                f"Duplicate items found ({len(found_duplicates)} matches)",
                details={'duplicate_count': len(found_duplicates)}
            )
            return action.SKIP
        
        def choose_item(self, task: ImportTask):
            """Choose the best match for a single track."""
            self.current_task = task
            
            if not task.candidates:
                logger.warning("No candidates found for track import")
                self.import_result = ImportResult(False, "No track candidates found")
                return action.SKIP
            
            if task.rec == Recommendation.strong:
                match = task.candidates[0]
                logger.info(f"Strong track match found: {self.prettify_candidate(match)}")
                
                if self.handler_ref:
                    self.handler_ref._import_stats['strong_matches'] += 1
                
                self.import_result = ImportResult(
                    True, 
                    f"Strong track match found among {len(task.candidates)} candidates",
                    details={'match_strength': 'strong', 'candidate_count': len(task.candidates)}
                )
                return match
            
            elif task.rec == Recommendation.medium and self.auto_mode:
                match = task.candidates[0]
                logger.info(f"Medium track match found: {self.prettify_candidate(match)}")
                
                if self.handler_ref:
                    self.handler_ref._import_stats['weak_matches'] += 1
                
                self.import_result = ImportResult(
                    True, 
                    f"Medium track match found among {len(task.candidates)} candidates",
                    details={'match_strength': 'medium', 'candidate_count': len(task.candidates)}
                )
                return match
            
            else:
                logger.warning(f"No suitable track match found (recommendation: {task.rec})")
                self.import_result = ImportResult(
                    False, 
                    f"No suitable track match among {len(task.candidates)} candidates",
                    details={'match_strength': 'none', 'candidate_count': len(task.candidates)}
                )
                return action.SKIP
    
    def exists(self, isrc: str, artist: str = "", title: str = "", album: str = "") -> Tuple[bool, str]:
        """
        Check if a track exists in the library with search strategies.
        """
        # Check cache first
        cache_key = f"{isrc}:{artist}:{title}:{album}"
        if cache_key in self._track_cache:
            path = self._track_cache[cache_key]
            if os.path.exists(path):
                logger.debug(f"Found track in cache: {path}")
                return True, path
            else:
                # Remove stale cache entry
                del self._track_cache[cache_key]
        
        # Search strategies in order of preference
        search_strategies = [
            # Strategy 1: ISRC search (most reliable)
            lambda: self._search_by_isrc(isrc) if isrc else [],
            
            # Strategy 2: Artist + Title + Album
            lambda: self._search_by_metadata(artist, title, album) if all([artist, title, album]) else [],
            
            # Strategy 3: Artist + Title
            lambda: self._search_by_metadata(artist, title) if artist and title else [],
            
            # Strategy 4: Fuzzy search (if enabled)
            lambda: self._fuzzy_search(artist, title) if self.fuzzy and artist and title else []
        ]
        
        for i, strategy in enumerate(search_strategies):
            try:
                results = strategy()
                if results:
                    path = os.fsdecode(results[0])
                    logger.info(f"Found track using strategy {i+1}: {path}")
                    
                    # Cache the result
                    self._track_cache[cache_key] = path
                    return True, path
            except Exception as e:
                logger.debug(f"Search strategy {i+1} failed: {e}")
                continue
        
        logger.debug(f"Track not found in library: {artist} - {title}")
        return False, ""
    
    def _search_by_isrc(self, isrc: str) -> List[str]:
        """Search for tracks by ISRC."""
        if not isrc:
            return []
        
        query = SubstringQuery("isrc", isrc)
        return self._execute_query(query)
    
    def _search_by_metadata(self, artist: str, title: str, album: str = "") -> List[str]:
        """Search by artist, title, and optionally album."""
        queries = [SubstringQuery("artist", artist), SubstringQuery("title", title)]
        
        if album:
            queries.append(SubstringQuery("album", album))
        
        query = AndQuery(queries)
        return self._execute_query(query)
    
    def _fuzzy_search(self, artist: str, title: str) -> List[str]:
        """Perform fuzzy search for tracks."""
        # Try various combinations for fuzzy matching
        search_terms = [
            # Exact artist OR title
            OrQuery([SubstringQuery("artist", artist), SubstringQuery("title", title)]),
            # Partial matches
            SubstringQuery("artist", artist.split()[0] if artist.split() else artist),
            SubstringQuery("title", title.split()[0] if title.split() else title)
        ]
        
        for query in search_terms:
            results = self._execute_query(query)
            if results:
                return results
        
        return []
    
    def _execute_query(self, query) -> List[str]:
        """Execute a Beets query and return file paths."""
        try:
            results = []
            for item in self.lib.items(query):
                path = item.get("path", with_album=False)
                if path:
                    results.append(path)
            return results
        except Exception as e:
            logger.debug(f"Query execution failed: {e}")
            return []
    
    def add(self, path: str, search_id: str = "", force: bool = False) -> ImportResult:
        """
        Import music files with error handling and options.
        
        Args:
            path: Path to import
            search_id: Optional search ID for specific matching
            force: Force import even for duplicates
        """
        if not os.path.exists(path):
            return ImportResult(False, f"Path does not exist: {path}")
        
        # Update statistics
        self._import_stats['total_imports'] += 1
        
        # Rate limiting for external APIs
        if search_id:
            delay = random.uniform(1, 3)
            time.sleep(delay)
            logger.debug(f"API rate limiting delay: {delay:.1f}s")
        
        try:
            # Create import session
            session = self.SmartImportSession(
                lib=self.lib,
                path=path,
                search_id=search_id,
                handler_ref=self,
                auto_mode=self.auto_import
            )

            # Run import with detailed error tracking
            logger.info(f"Starting import: {path}")
            try:
                session.run()
            except AttributeError as ae:
                if "'str' object has no attribute 'info'" in str(ae):
                    logger.error(f"Beets library AttributeError during import: {ae}")
                    logger.error(f"This error is likely from the beets library itself, not our code")
                    # Try to provide more context
                    import traceback
                    logger.error(f"Full traceback: {traceback.format_exc()}")
                raise ae
            except Exception as e:
                logger.error(f"Import run failed with error: {e}")
                raise e
            
            # Process results
            if session.import_result.success:
                self._import_stats['successful_imports'] += 1
                
                # Get imported items
                if hasattr(session, 'current_task') and session.current_task:
                    try:
                        imported_items = session.current_task.imported_items()
                        imported_paths = []
                        
                        for item in imported_items:
                            item_path = os.fsdecode(item.destination())
                            imported_paths.append(item_path)
                            
                            # Update cache
                            isrc = item.get("isrc", "", with_album=False)
                            artist = item.get("artist", "", with_album=False)
                            title = item.get("title", "", with_album=False)
                            album = item.get("album", "", with_album=False)
                            
                            if isrc or (artist and title):
                                cache_key = f"{isrc}:{artist}:{title}:{album}"
                                self._track_cache[cache_key] = item_path
                        
                        session.import_result.imported_paths = imported_paths
                        logger.info(f"Successfully imported {len(imported_paths)} items")
                        
                    except Exception as e:
                        logger.warning(f"Error processing imported items: {e}")
                
                # Update Plex if configured
                if self.plex_updater:
                    try:
                        logger.info("Notifying Plex of library changes")
                        self.plex_updater.update(self.lib)
                    except Exception as e:
                        logger.warning(f"Plex update failed: {e}")
                
            else:
                self._import_stats['failed_imports'] += 1
                logger.warning(f"Import failed: {session.import_result.message}")
            
            return session.import_result
            
        except Exception as e:
            error_msg = f"Import session failed: {e}"
            logger.error(error_msg)
            self._import_stats['failed_imports'] += 1
            return ImportResult(False, error_msg)
    
    def batch_add(self, paths: List[str], search_ids: List[str] = None) -> List[ImportResult]:
        """
        Import multiple paths with batch processing.
        
        Args:
            paths: List of paths to import
            search_ids: Optional list of search IDs (must match paths length)
        """
        if search_ids and len(search_ids) != len(paths):
            raise ValueError("search_ids length must match paths length")
        
        results = []
        search_ids = search_ids or [""] * len(paths)
        
        logger.info(f"Starting batch import of {len(paths)} paths")
        
        for i, (path, search_id) in enumerate(zip(paths, search_ids)):
            logger.info(f"Batch import progress: {i+1}/{len(paths)}")
            
            result = self.add(path, search_id)
            results.append(result)
            
            # Inter-batch delay for API rate limiting
            if i < len(paths) - 1:
                time.sleep(random.uniform(0.5, 2.0))
        
        # Summary statistics
        successful = sum(1 for r in results if r.success)
        logger.info(f"Batch import complete: {successful}/{len(paths)} successful")
        
        return results
    
    # Replace the get_library_stats method in the Beets handler with this:

    def get_library_stats(self) -> Dict[str, Any]:
        """Get library statistics."""
        try:
            # Basic counts - handle both old and new Beets versions
            try:
                items_result = self.lib.items()
                albums_result = self.lib.albums()
                
                # Handle Results object (newer Beets) vs direct count (older Beets)
                if hasattr(items_result, '__len__'):
                    total_items = len(items_result)
                elif hasattr(items_result, 'count'):
                    total_items = items_result.count()
                else:
                    # Fallback: iterate and count
                    total_items = sum(1 for _ in items_result)
                
                if hasattr(albums_result, '__len__'):
                    total_albums = len(albums_result)
                elif hasattr(albums_result, 'count'):
                    total_albums = albums_result.count()
                else:
                    # Fallback: iterate and count
                    total_albums = sum(1 for _ in albums_result)
                    
            except Exception as e:
                logger.debug(f"Error getting basic counts: {e}")
                total_items = 0
                total_albums = 0
            
            # File system stats
            total_size = 0
            total_files = 0
            
            try:
                items = self.lib.items()
                for item in items:
                    try:
                        path = item.get("path", with_album=False)
                        if path and os.path.exists(os.fsdecode(path)):
                            total_size += os.path.getsize(os.fsdecode(path))
                            total_files += 1
                    except Exception as e:
                        logger.debug(f"Error processing item: {e}")
                        continue
            except Exception as e:
                logger.debug(f"Error calculating file stats: {e}")
            
            return {
                'total_tracks': total_items,
                'total_albums': total_albums,
                'total_files': total_files,
                'total_size_bytes': total_size,
                'total_size_gb': total_size / (1024**3) if total_size > 0 else 0,
                'library_path': self.library_path,
                'directory_path': self.directory_path,
                'cache_entries': len(self._track_cache),
                'import_stats': self._import_stats.copy()
            }
            
        except Exception as e:
            logger.error(f"Error getting library stats: {e}")
            return {'error': str(e), 'total_tracks': 0, 'total_albums': 0}

    # Also replace the validate_library method:

    def validate_library(self) -> ImportResult:
        """Validate library integrity and accessibility."""
        try:
            # Check library file
            if not os.path.exists(self.library_path):
                return ImportResult(False, f"Library database not found: {self.library_path}")
            
            # Check directory
            if not os.path.exists(self.directory_path):
                return ImportResult(False, f"Music directory not found: {self.directory_path}")
            
            # Test library access
            try:
                items_result = self.lib.items()
                albums_result = self.lib.albums()
                
                # Handle both old and new Beets API
                if hasattr(items_result, '__len__'):
                    item_count = len(items_result)
                elif hasattr(items_result, 'count'):
                    item_count = items_result.count()
                else:
                    item_count = sum(1 for _ in items_result)
                
                if hasattr(albums_result, '__len__'):
                    album_count = len(albums_result)
                elif hasattr(albums_result, 'count'):
                    album_count = albums_result.count()
                else:
                    album_count = sum(1 for _ in albums_result)
                    
            except Exception as e:
                return ImportResult(False, f"Cannot access library database: {e}")
            
            # Check write permissions
            try:
                test_file = os.path.join(self.directory_path, '.beets_test')
                with open(test_file, 'w') as f:
                    f.write('test')
                os.remove(test_file)
            except Exception as e:
                return ImportResult(False, f"No write permission to music directory: {e}")
            
            return ImportResult(
                True, 
                "Library validation successful",
                details={
                    'library_path': self.library_path,
                    'directory_path': self.directory_path,
                    'item_count': item_count,
                    'album_count': album_count
                }
            )
            
        except Exception as e:
            return ImportResult(False, f"Library validation failed: {e}")

    def print_stats(self):
            """Print formatted statistics."""
            stats = self.get_library_stats()
            
            print("\n=== Beets Library Statistics ===")
            print(f"Total tracks: {stats.get('total_tracks', 'Unknown')}")
            print(f"Total albums: {stats.get('total_albums', 'Unknown')}")
            print(f"Library size: {stats.get('total_size_gb', 0):.2f} GB")
            print(f"Cache entries: {stats.get('cache_entries', 0)}")
            
            import_stats = stats.get('import_stats', {})
            print(f"\n--- Import Statistics ---")
            print(f"Total imports: {import_stats.get('total_imports', 0)}")
            print(f"Successful: {import_stats.get('successful_imports', 0)}")
            print(f"Failed: {import_stats.get('failed_imports', 0)}")
            print(f"Strong matches: {import_stats.get('strong_matches', 0)}")
            print(f"Weak matches: {import_stats.get('weak_matches', 0)}")
            print(f"Duplicates skipped: {import_stats.get('duplicate_skips', 0)}")
            
            success_rate = 0
            if import_stats.get('total_imports', 0) > 0:
                success_rate = (import_stats.get('successful_imports', 0) / 
                              import_stats.get('total_imports', 1)) * 100
            print(f"Success rate: {success_rate:.1f}%")
            print("=" * 33)   

    def clear_cache(self):
        """Clear the track cache."""
        self._track_cache.clear()
        logger.info("Track cache cleared")
    
    def optimize_library(self):
        """Optimize the library database."""
        try:
            # This would run VACUUM on the SQLite database
            # Note: Beets doesn't expose this directly, so we'd need to access the DB
            logger.info("Library optimization not implemented (requires direct DB access)")
        except Exception as e:
            logger.error(f"Library optimization failed: {e}")
