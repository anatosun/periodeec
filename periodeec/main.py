#!/usr/bin/env python3
"""
Periodeec - Music Synchronization Tool
Main application entry point with comprehensive error handling, scheduling, and monitoring.
"""

import argparse
import asyncio
import logging
import logging.handlers
import os
import signal
import sys
import time
import importlib
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from pathlib import Path
import schedule
import threading
from concurrent.futures import ThreadPoolExecutor
import json

# Imports
from periodeec.config import load_config, ConfigurationError, Config
from periodeec.beets_handler import BeetsHandler
from periodeec.plex_handler import PlexHandler
from periodeec.importers.spotify_importer import SpotifyImporter
from periodeec.importers.lastfm_importer import LastFMImporter
from periodeec.importers.listenbrainz_importer import ListenBrainzImporter
from periodeec.download_manager import DownloadManager
from periodeec.schema import Track
from periodeec.schema import User
from periodeec.playlist import Playlist
from periodeec.modules.downloader import Downloader


class ApplicationStats:
    """Application-wide statistics tracking."""
    
    def __init__(self):
        self.start_time = datetime.now()
        self.total_sync_operations = 0
        self.successful_syncs = 0
        self.failed_syncs = 0
        self.total_tracks_processed = 0
        self.total_tracks_downloaded = 0
        self.total_playlists_synced = 0
        self.downloader_usage = {}
        self.last_sync_times = {}
        self.error_counts = {}
    
    def record_sync(self, sync_type: str, success: bool, track_count: int = 0, 
                   downloaded_count: int = 0):
        """Record sync operation statistics."""
        self.total_sync_operations += 1
        self.total_tracks_processed += track_count
        self.total_tracks_downloaded += downloaded_count
        
        if success:
            self.successful_syncs += 1
            if sync_type == 'playlist':
                self.total_playlists_synced += 1
        else:
            self.failed_syncs += 1
        
        self.last_sync_times[sync_type] = datetime.now()
    
    def record_downloader_usage(self, downloader_name: str):
        """Record downloader usage."""
        self.downloader_usage[downloader_name] = self.downloader_usage.get(downloader_name, 0) + 1
    
    def record_error(self, error_type: str):
        """Record error occurrence."""
        self.error_counts[error_type] = self.error_counts.get(error_type, 0) + 1
    
    @property
    def uptime_hours(self) -> float:
        """Get application uptime in hours."""
        return (datetime.now() - self.start_time).total_seconds() / 3600
    
    @property
    def success_rate(self) -> float:
        """Get sync success rate percentage."""
        if self.total_sync_operations == 0:
            return 0.0
        return (self.successful_syncs / self.total_sync_operations) * 100
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert stats to dictionary."""
        return {
            'start_time': self.start_time.isoformat(),
            'uptime_hours': self.uptime_hours,
            'total_sync_operations': self.total_sync_operations,
            'successful_syncs': self.successful_syncs,
            'failed_syncs': self.failed_syncs,
            'success_rate': self.success_rate,
            'total_tracks_processed': self.total_tracks_processed,
            'total_tracks_downloaded': self.total_tracks_downloaded,
            'total_playlists_synced': self.total_playlists_synced,
            'downloader_usage': self.downloader_usage,
            'last_sync_times': {k: v.isoformat() for k, v in self.last_sync_times.items()},
            'error_counts': self.error_counts
        }


class ColorFormatter(logging.Formatter):
    """Colored logging formatter for console output."""
    
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Green
        'WARNING': '\033[33m',    # Yellow
        'ERROR': '\033[31m',      # Red
        'CRITICAL': '\033[35m'    # Magenta
    }
    RESET = '\033[0m'
    
    def format(self, record):
        if hasattr(self, '_use_color') and self._use_color:
            color = self.COLORS.get(record.levelname, '')
            record.levelname = f"{color}{record.levelname}{self.RESET}"
        return super().format(record)


class PeriodeecApplication:
    """Main application class with comprehensive functionality."""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """Initialize the application."""
        self.config_path = config_path
        self.config: Optional[Config] = None
        self.shutdown_event = threading.Event()
        self.stats = ApplicationStats()
        self.executor = ThreadPoolExecutor(max_workers=4)
        
        # Component instances
        self.spotify_importer: Optional[SpotifyImporter] = None
        self.lastfm_importer: Optional[LastFMImporter] = None
        self.listenbrainz_importer: Optional[ListenBrainzImporter] = None
        self.plex_handler: Optional[PlexHandler] = None
        self.beets_handler: Optional[BeetsHandler] = None
        self.download_manager: Optional[DownloadManager] = None
        
        # Setup signal handlers
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
        
        # Logger will be setup in initialize()
        self.logger: Optional[logging.Logger] = None
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully."""
        if self.logger:
            self.logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        self.shutdown_event.set()
    
    def setup_logging(self):
        """Setup logging configuration."""
        # Clear any existing handlers
        logging.getLogger().handlers.clear()
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, self.config.logging.level.upper()))
        
        # Console handler
        if self.config.logging.console:
            console_handler = logging.StreamHandler(sys.stdout)
            
            if self.config.logging.color:
                formatter = ColorFormatter(fmt=self.config.logging.format)
                formatter._use_color = True
            else:
                formatter = logging.Formatter(fmt=self.config.logging.format)
            
            console_handler.setFormatter(formatter)
            root_logger.addHandler(console_handler)
        
        # File handler
        if self.config.logging.file:
            file_handler = logging.handlers.RotatingFileHandler(
                self.config.logging.file,
                maxBytes=self.config.logging.max_size_mb * 1024 * 1024,
                backupCount=self.config.logging.backup_count,
                encoding='utf-8'
            )
            
            file_formatter = logging.Formatter(fmt=self.config.logging.format)
            file_handler.setFormatter(file_formatter)
            root_logger.addHandler(file_handler)
        
        self.logger = logging.getLogger(__name__)
        self.logger.info("Logging system initialized")
    
    async def initialize(self) -> bool:
        """Initialize the application components."""
        try:
            # Load configuration
            self.logger = logging.getLogger(__name__)  # Temporary logger
            self.logger.info(f"Loading configuration from {self.config_path}")
            
            self.config = load_config(self.config_path)

            # Log configuration paths for debugging
            self.logger.info("Configuration paths resolved:")
            self.logger.info(f"  Working directory: {os.getcwd()}")
            self.logger.info(f"  Config directory: {self.config.config_dir}")
            self.logger.info(f"  Downloads: {self.config.paths.downloads}")
            self.logger.info(f"  Failed: {self.config.paths.failed}")
            self.logger.info(f"  Playlists: {self.config.paths.playlists}")
            self.logger.info(f"  M3U: {self.config.paths.m3u}")
            self.logger.info(f"  Cache: {self.config.paths.cache}")
            self.logger.info(f"  Beets library: {self.config.beets.library}")
            self.logger.info(f"  Beets directory: {self.config.beets.directory}")

            # Setup proper logging
            self.setup_logging()
            self.logger.info("Configuration loaded successfully")
            
            # Initialize components
            if not self._initialize_downloaders():
                return False
            
            if not await self._initialize_handlers():
                return False
            
            # Validate connections
            if not await self._validate_connections():
                return False
            
            self.logger.info("Application initialized successfully")
            return True
            
        except ConfigurationError as e:
            print(f"Configuration error: {e}", file=sys.stderr)
            return False
        except Exception as e:
            print(f"Initialization failed: {e}", file=sys.stderr)
            return False
    
    def _initialize_downloaders(self) -> bool:
        """Initialize download components."""
        try:
            downloaders = []
            
            for name, downloader_config in self.config.get_enabled_downloaders().items():
                self.logger.info(f"Initializing downloader: {name}")
                
                try:
                    # Import downloader module
                    module = importlib.import_module(f"periodeec.modules.{name}")
                    downloader_class = getattr(module, name.capitalize())
                    
                    # Create downloader instance
                    downloader_params = downloader_config.__dict__.copy()
                    downloader_params.pop('name', None)
                    downloader_params.pop('enabled', None)
                    
                    downloader = downloader_class(**downloader_params)
                    
                    # Validate downloader
                    if downloader.validate_credentials():
                        downloaders.append(downloader)
                        self.logger.info(f"Downloader {name} initialized successfully")
                    else:
                        self.logger.error(f"Downloader {name} credential validation failed")
                        
                except Exception as e:
                    self.logger.error(f"Failed to initialize downloader {name}: {e}")
                    self.stats.record_error(f"downloader_init_{name}")
            
            if not downloaders:
                self.logger.error("No valid downloaders available")
                return False
            
            # Initialize download manager
            self.download_manager = DownloadManager(
                downloaders=downloaders,
                download_path=self.config.paths.downloads,
                failed_path=self.config.paths.failed,
                enable_retry=True,
                max_retries=2,
                stats_file=os.path.join(self.config.paths.cache, "download_stats.json")
            )
            
            self.logger.info(f"Download manager initialized with {len(downloaders)} downloaders")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize downloaders: {e}")
            return False
    
    async def _initialize_handlers(self) -> bool:
        """Initialize service handlers."""
        try:
            # Initialize Beets handler
            self.beets_handler = BeetsHandler(
                library=self.config.beets.library,
                directory=self.config.beets.directory,
                failed_path=self.config.paths.failed,
                plex_baseurl=self.config.plex.baseurl,
                plex_token=self.config.plex.token,
                plex_section=self.config.plex.section,
                spotify_client_id=self.config.importers.spotify.client_id,
                spotify_client_secret=self.config.importers.spotify.client_secret,
                beets_plugins=self.config.beets.plugins,
                fuzzy=self.config.beets.fuzzy,
                auto_import=self.config.beets.auto_import,
                strong_rec_thresh=self.config.beets.strong_rec_thresh,
                timid=self.config.beets.timid,
                duplicate_action=self.config.beets.duplicate_action
            )
            
            # Initialize Spotify importer
            spotify_config = self.config.importers.spotify
            spotify_importer_config = {
                'client_id': spotify_config.client_id,
                'client_secret': spotify_config.client_secret,
                'anonymous': spotify_config.anonymous,
                'cache_enabled': spotify_config.cache_enabled,
                'cache_ttl_hours': spotify_config.cache_ttl_hours,
                'rate_limit_rpm': int(spotify_config.rate_limit_rpm * self.config.advanced.rate_limit_buffer),
                'retry_attempts': spotify_config.retry_attempts,
                'request_timeout': spotify_config.request_timeout,
                'add_source_to_titles': getattr(spotify_config, 'add_source_to_titles', False),
                'include_collaborative': getattr(spotify_config, 'include_collaborative', True),
                'include_followed': getattr(spotify_config, 'include_followed', False)
            }
            self.spotify_importer = SpotifyImporter(spotify_importer_config)
            # Authenticate the importer
            await self.spotify_importer.authenticate()

            # Initialize Last.fm importer if enabled
            lastfm_config = self.config.importers.lastfm
            if lastfm_config.enabled:
                lastfm_importer_config = {
                    'api_key': lastfm_config.api_key,
                    'api_secret': lastfm_config.api_secret,
                    'username': lastfm_config.username,
                    'password': lastfm_config.password
                }
                self.lastfm_importer = LastFMImporter(lastfm_importer_config)
                await self.lastfm_importer.authenticate()

            # Initialize ListenBrainz importer if enabled
            listenbrainz_config = self.config.importers.listenbrainz
            if listenbrainz_config.enabled:
                listenbrainz_importer_config = {
                    'user_token': listenbrainz_config.user_token,
                    'username': listenbrainz_config.username
                }
                self.listenbrainz_importer = ListenBrainzImporter(listenbrainz_importer_config)
                await self.listenbrainz_importer.authenticate()

            # Initialize Plex handler
            plex_config = self.config.plex
            self.plex_handler = PlexHandler(
                baseurl=plex_config.baseurl,
                token=plex_config.token,
                section=plex_config.section,
                m3u_path=self.config.paths.m3u,
                verify_ssl=plex_config.verify_ssl,
                timeout=plex_config.timeout,
                retry_attempts=plex_config.retry_attempts,
                music_directory=self.config.beets.directory
            )
            
            self.logger.info("All handlers initialized successfully")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to initialize handlers: {e}")
            return False
    
    async def _validate_connections(self) -> bool:
        """Validate connections to external services."""
        validation_results = []
        
        # Validate Spotify
        if await self.spotify_importer.validate_connection():
            self.logger.info("Spotify connection validated")
            validation_results.append(True)
        else:
            self.logger.error("Spotify connection validation failed")
            validation_results.append(False)
        
        # Validate Plex
        plex_result = self.plex_handler.validate_connection()
        if plex_result.success:
            self.logger.info("Plex connection validated")
            validation_results.append(True)
        else:
            self.logger.error(f"Plex validation failed: {plex_result.message}")
            validation_results.append(False)
        
        # Validate Last.fm if enabled
        if self.lastfm_importer:
            if await self.lastfm_importer.validate_connection():
                self.logger.info("Last.fm connection validated")
                validation_results.append(True)
            else:
                self.logger.error("Last.fm connection validation failed")
                validation_results.append(False)

        # Validate ListenBrainz if enabled
        if self.listenbrainz_importer:
            if await self.listenbrainz_importer.validate_connection():
                self.logger.info("ListenBrainz connection validated")
                validation_results.append(True)
            else:
                self.logger.error("ListenBrainz connection validation failed")
                validation_results.append(False)

        # Validate Beets
        beets_result = self.beets_handler.validate_library()
        if beets_result.success:
            self.logger.info("Beets library validated")
            validation_results.append(True)
        else:
            self.logger.error(f"Beets validation failed: {beets_result.message}")
            validation_results.append(False)

        return all(validation_results)
    
    async def sync_playlist(self, playlist_config, playlist_name: str, original_title: str = None) -> bool:
        """Sync a single playlist."""
        try:
            display_title = original_title or playlist_config.title or playlist_name
            self.logger.info(f"Starting sync for playlist: {display_title}")
            start_time = time.time()

            # Create playlist object from config (we'll get tracks to determine count)
            playlist_title = original_title or playlist_config.title or playlist_name
            playlist_path = os.path.join(self.config.paths.playlists, f"{playlist_name}.json")

            # Get tracks first to determine actual count
            tracks = await self.spotify_importer.get_playlist_tracks(playlist_config.url)

            if not tracks:
                self.logger.warning(f"No tracks found for playlist: {playlist_title}")
                return False

            playlist = Playlist(
                title=playlist_title,
                tracks=[],
                id=self.spotify_importer._extract_playlist_id(playlist_config.url) or playlist_name,
                path=playlist_path,
                number_of_tracks=len(tracks),
                description=playlist_config.summary or '',
                snapshot_id='',
                poster=playlist_config.poster or '',
                summary=playlist_config.summary or '',
                url=playlist_config.url
            )
            
            # Check if update needed
            if playlist.is_up_to_date() and not getattr(playlist_config, 'force_update', False):
                self.logger.info(f"Playlist '{playlist_title}' is up to date")
                
                # Still sync to Plex users if needed
                success = True
                for username in playlist_config.sync_to_plex_users:
                    if not playlist.is_up_to_date_for(username):
                        plex_result = self._sync_to_plex(playlist, playlist_config, username)
                        if plex_result:
                            playlist.update_for(username)
                            playlist.save()
                        else:
                            success = False
                
                return success
            
            # Use tracks already fetched above
            self.logger.info(f"Processing {len(tracks)} tracks for playlist: {playlist_title}")
            
            # Update tracklist
            playlist.tracks = playlist.update_tracklist(tracks, playlist.tracks)
            
            # Process tracks (find in library or download)
            processed_count = 0
            downloaded_count = 0
            
            for track in playlist.tracks:
                if self.shutdown_event.is_set():
                    self.logger.info("Shutdown requested, stopping track processing")
                    break
                
                if not track.path:
                    # Check if exists in library
                    exists, path = self.beets_handler.exists(
                        isrc=track.isrc,
                        artist=track.artist,
                        title=track.title,
                        album=track.album
                    )
                    
                    if exists:
                        track.mark_found_in_library(path)
                        self.logger.debug(f"Found in library: {track.title}")
                    elif playlist_config.download_missing:
                        # Download track
                        self.logger.info(f"Downloading: {track.artist} - {track.title}")
                        
                        download_result = self.download_manager.enqueue(track)
                        self.stats.record_downloader_usage(
                            download_result.metadata.get('downloader_used', 'unknown')
                        )
                        
                        if download_result.success:
                            # Import to Beets
                            import_result = self.beets_handler.add(
                                download_result.path,
                                track.album_url
                            )
                            
                            if import_result.success:
                                # Find imported track
                                exists, path = self.beets_handler.exists(
                                    isrc=track.isrc,
                                    artist=track.artist,
                                    title=track.title
                                )
                                if exists:
                                    track.mark_found_in_library(path)
                                    downloaded_count += 1
                            
                            track.mark_download_attempt(
                                downloader_name=download_result.metadata.get('downloader_used', 'unknown'),
                                success=import_result.success,
                                error_message=import_result.message if not import_result.success else "",
                                match_quality=download_result.match_quality.value if download_result.match_quality else "",
                                download_time=download_result.metadata.get('download_time', 0.0)
                            )
                
                processed_count += 1
            
            # Save playlist
            playlist.save()
            
            # Sync to Plex
            for username in playlist_config.sync_to_plex_users:
                if self._sync_to_plex(playlist, playlist_config, username):
                    playlist.update_for(username)
                    playlist.save()
            
            # Record statistics
            sync_time = time.time() - start_time
            self.stats.record_sync('playlist', True, processed_count, downloaded_count)
            
            self.logger.info(
                f"Playlist sync completed: {playlist_title} "
                f"({processed_count} tracks, {downloaded_count} downloaded) "
                f"in {sync_time:.1f}s"
            )
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to sync playlist {playlist_name}: {e}")
            self.stats.record_sync('playlist', False)
            self.stats.record_error('playlist_sync')
            return False
    
    def _sync_to_plex(self, playlist: Playlist, playlist_config, username: str) -> bool:
        """Sync playlist to Plex for a specific user."""
        try:
            sync_mode = getattr(playlist_config, 'sync_mode', 'playlist')
            create_m3u = getattr(playlist_config, 'create_m3u', True)
            
            if sync_mode in ['playlist', 'both']:
                result = self.plex_handler.create(
                    playlist=playlist,
                    username=username,
                    collection=False,
                    create_m3u=create_m3u
                )
                
                if not result.success:
                    self.logger.error(f"Failed to create Plex playlist for {username}: {result.message}")
                    return False
            
            if sync_mode in ['collection', 'both']:
                result = self.plex_handler.create(
                    playlist=playlist,
                    username="",  # Collections are server-wide
                    collection=True,
                    create_m3u=False
                )
                
                if not result.success:
                    self.logger.error(f"Failed to create Plex collection: {result.message}")
                    return False
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to sync to Plex: {e}")
            return False
    
    async def sync_user(self, user_config, username: str) -> bool:
        """Sync all playlists for a user."""
        try:
            self.logger.info(f"Starting user sync: {username}")
            start_time = time.time()
            
            # Get user info
            spotify_username = user_config.service_connections.spotify_username
            spotify_user = await self.spotify_importer.get_user_info(spotify_username)

            # Get playlists
            spotify_prefs = user_config.import_preferences.spotify
            playlists = await self.spotify_importer.get_user_playlists(
                user_id=spotify_username,
                include_collaborative=spotify_prefs.get('include_collaborative', True),
                include_followed=spotify_prefs.get('include_followed', False)
            )
            
            if not playlists:
                self.logger.warning(f"No playlists found for user: {username}")
                return False
            
            success_count = 0
            
            for playlist in playlists:
                if self.shutdown_event.is_set():
                    break
                
                # Create temporary playlist config
                temp_config = type('PlaylistConfig', (), {
                    'url': playlist.url,
                    'title': None,
                    'sync_mode': 'playlist',
                    'sync_to_plex_users': user_config.sync_to_plex_users,
                    'download_missing': user_config.download_missing,
                    'create_m3u': user_config.create_m3u,
                    'summary': playlist.description or playlist.summary,
                    'poster': playlist.poster
                })()
                
                # Use original playlist title for display, but unique name for tracking
                unique_name = f"{username}_{playlist.title}"
                if await self.sync_playlist(temp_config, unique_name, original_title=playlist.title):
                    success_count += 1
            
            sync_time = time.time() - start_time
            self.logger.info(
                f"User sync completed: {username} "
                f"({success_count}/{len(playlists)} playlists) "
                f"in {sync_time:.1f}s"
            )
            
            return success_count > 0
            
        except Exception as e:
            self.logger.error(f"Failed to sync user {username}: {e}")
            self.stats.record_error('user_sync')
            return False
    
    def _sync_user_wrapper(self, user_config, username: str):
        """Synchronous wrapper for async sync_user method."""
        return asyncio.run(self.sync_user(user_config, username))

    def _health_check_wrapper(self):
        """Synchronous wrapper for async _health_check method."""
        return asyncio.run(self._health_check())

    def setup_scheduler(self):
        """Setup scheduled tasks."""
        self.logger.info("Setting up scheduler")

        # Schedule playlist syncs
        for name, playlist_config in self.config.get_enabled_playlists().items():
            schedule.every(playlist_config.schedule_minutes).minutes.do(
                self.sync_playlist, playlist_config, name
            )
            self.logger.info(f"Scheduled playlist '{name}' every {playlist_config.schedule_minutes} minutes")

        # Schedule user syncs
        for name, user_config in self.config.get_enabled_users().items():
            schedule.every(user_config.schedule_minutes).minutes.do(
                self._sync_user_wrapper, user_config, name
            )
            self.logger.info(f"Scheduled user '{name}' every {user_config.schedule_minutes} minutes")

        # Schedule statistics save
        if self.config.advanced.enable_statistics:
            schedule.every(10).minutes.do(self._save_statistics)

        # Schedule health check
        if self.config.advanced.health_check_interval_minutes > 0:
            schedule.every(self.config.advanced.health_check_interval_minutes).minutes.do(
                self._health_check_wrapper
            )
    
    def _save_statistics(self):
        """Save application statistics."""
        try:
            if self.config and self.config.advanced.statistics_file:
                stats_data = {
                    'application': self.stats.to_dict(),
                    'spotify': self.spotify_importer.get_service_stats() if self.spotify_importer else {},
                    'downloads': self.download_manager.get_stats().to_dict() if self.download_manager else {},
                    'beets': self.beets_handler.get_library_stats() if self.beets_handler else {}
                }
                
                with open(self.config.advanced.statistics_file, 'w') as f:
                    json.dump(stats_data, f, indent=2, default=str)
                
                self.logger.debug("Statistics saved")
        except Exception as e:
            self.logger.error(f"Failed to save statistics: {e}")
    
    async def _health_check(self):
        """Perform health check on all components."""
        try:
            self.logger.info("Performing health check")
            
            # Check Spotify connection
            if not await self.spotify_importer.validate_connection():
                self.logger.warning("Spotify connection health check failed")
                self.stats.record_error('health_check_spotify')
            
            # Check Plex connection
            plex_result = self.plex_handler.validate_connection()
            if not plex_result.success:
                self.logger.warning(f"Plex connection health check failed: {plex_result.message}")
                self.stats.record_error('health_check_plex')
            
            # Check Last.fm connection if enabled
            if self.lastfm_importer:
                if not await self.lastfm_importer.validate_connection():
                    self.logger.warning("Last.fm connection health check failed")
                    self.stats.record_error('health_check_lastfm')

            # Check ListenBrainz connection if enabled
            if self.listenbrainz_importer:
                if not await self.listenbrainz_importer.validate_connection():
                    self.logger.warning("ListenBrainz connection health check failed")
                    self.stats.record_error('health_check_listenbrainz')

            # Check Beets library
            beets_result = self.beets_handler.validate_library()
            if not beets_result.success:
                self.logger.warning(f"Beets library health check failed: {beets_result.message}")
                self.stats.record_error('health_check_beets')

            self.logger.info("Health check completed")
            
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
    
    async def run_once(self) -> bool:
        """Run all sync operations once."""
        self.logger.info("Running one-time sync")
        
        success = True
        
        # Sync playlists
        for name, playlist_config in self.config.get_enabled_playlists().items():
            if not await self.sync_playlist(playlist_config, name):
                success = False
        
        # Sync users
        for name, user_config in self.config.get_enabled_users().items():
            if not await self.sync_user(user_config, name):
                success = False
        
        return success
    
    def run_scheduler(self):
        """Run the scheduler loop."""
        self.logger.info("Starting scheduler")
        
        # Run initial sync
        schedule.run_all()
        
        # Main scheduler loop
        while not self.shutdown_event.is_set():
            try:
                schedule.run_pending()
                time.sleep(1)
            except Exception as e:
                self.logger.error(f"Scheduler error: {e}")
                time.sleep(5)
        
        self.logger.info("Scheduler stopped")
    
    def print_status(self):
        """Print current application status."""
        print("\n=== Periodeec Status ===")
        print(f"Uptime: {self.stats.uptime_hours:.1f} hours")
        print(f"Total sync operations: {self.stats.total_sync_operations}")
        print(f"Success rate: {self.stats.success_rate:.1f}%")
        print(f"Tracks processed: {self.stats.total_tracks_processed}")
        print(f"Tracks downloaded: {self.stats.total_tracks_downloaded}")
        print(f"Playlists synced: {self.stats.total_playlists_synced}")
        
        if self.spotify_importer:
            self.spotify_importer.print_stats()
        
        if self.download_manager:
            self.download_manager.print_stats()
        
        if self.beets_handler:
            self.beets_handler.print_stats()
        
        print("=" * 24)
    
    def cleanup(self):
        """Cleanup application resources."""
        self.logger.info("Cleaning up application resources")
        
        try:
            # Save final statistics
            self._save_statistics()
            
            # Cleanup download manager
            if self.download_manager:
                self.download_manager.cleanup()
            
            # Cleanup executor
            self.executor.shutdown(wait=True)
            
            self.logger.info("Cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Periodeec - Music Synchronization Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --config /path/to/config.yaml --run
  %(prog)s --once --status
  %(prog)s --config-example > example-config.yaml
        """
    )
    
    parser.add_argument(
        '--config', '-c',
        type=str,
        default=os.getenv("PERIODEEC_CONFIG", "config/config.yaml"),
        help='Path to configuration file (default: config/config.yaml)'
    )
    
    parser.add_argument(
        '--run', '-r',
        action='store_true',
        help='Run in scheduled mode (continuous operation)'
    )
    
    parser.add_argument(
        '--once', '-o',
        action='store_true',
        help='Run sync operations once and exit'
    )
    
    parser.add_argument(
        '--status', '-s',
        action='store_true',
        help='Show status information and exit'
    )
    
    parser.add_argument(
        '--config-example',
        action='store_true',
        help='Generate example configuration and exit'
    )
    
    parser.add_argument(
        '--validate-config',
        action='store_true',
        help='Validate configuration and exit'
    )
    
    parser.add_argument(
        '--log-level',
        choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'],
        help='Override log level from config file'
    )
    
    parser.add_argument(
        '--version',
        action='version',
        version='Periodeec 2.0.0'
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    try:
        # Parse arguments
        args = parse_args()
        
        # Handle special cases
        if args.config_example:
            from periodeec.config import create_example_config
            create_example_config()
            return 0
        
        # Initialize application
        app = PeriodeecApplication(args.config)
        
        if not asyncio.run(app.initialize()):
            print("Failed to initialize application", file=sys.stderr)
            return 1
        
        # Override log level if specified
        if args.log_level:
            logging.getLogger().setLevel(getattr(logging, args.log_level))
            app.logger.info(f"Log level overridden to {args.log_level}")
        
        # Handle validation
        if args.validate_config:
            issues = app.config.validate_configuration()
            if issues:
                print("Configuration validation failed:")
                for issue in issues:
                    print(f"  - {issue}")
                return 1
            else:
                print("Configuration is valid")
                return 0
        
        # Handle status display
        if args.status:
            app.print_status()
            return 0
        
        # Handle run modes
        if args.once:
            app.logger.info("Running in one-time sync mode")
            success = asyncio.run(app.run_once())
            app.print_status()
            return 0 if success else 1
        
        elif args.run or os.getenv("PERIODEEC_RUN", "").lower() == "true":
            app.logger.info("Running in scheduled mode")
            app.setup_scheduler()
            
            try:
                app.run_scheduler()
            except KeyboardInterrupt:
                app.logger.info("Received interrupt signal")
            
            return 0
        
        else:
            # Default: show help
            print("No operation specified. Use --help for available options.")
            print("Common usage:")
            print("  --once    : Run sync once and exit")
            print("  --run     : Run continuously with scheduler")
            print("  --status  : Show current status")
            return 1
    
    except Exception as e:
        print(f"Fatal error: {e}", file=sys.stderr)
        return 1
    
    finally:
        # Cleanup
        try:
            if 'app' in locals():
                app.cleanup()
        except:
            pass


if __name__ == "__main__":
    sys.exit(main())
