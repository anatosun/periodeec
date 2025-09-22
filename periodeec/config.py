import os
import yaml
import logging
from typing import Dict, Any, List, Optional, Union
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SpotifyConfig:
    """Spotify service configuration."""
    enabled: bool = True
    client_id: str = ""
    client_secret: str = ""
    cache_enabled: bool = True
    cache_ttl_hours: int = 24
    rate_limit_rpm: int = 100
    retry_attempts: int = 3
    request_timeout: int = 30
    include_collaborative: bool = True
    include_followed: bool = False
    add_source_to_titles: bool = False
    source_tag_format: str = "({service})"


@dataclass
class PlexConfig:
    """Plex service configuration."""
    baseurl: str = ""
    token: str = ""
    section: str = "Music"
    verify_ssl: bool = True
    timeout: int = 30
    retry_attempts: int = 3


@dataclass
class BeetsConfig:
    """Beets configuration."""
    library: str = "./library.db"
    directory: str = "./music"
    plugins: List[str] = field(default_factory=lambda: ["spotify", "plexupdate"])
    fuzzy: bool = False
    auto_import: bool = True
    strong_rec_thresh: float = 0.15
    timid: bool = False
    duplicate_action: str = "skip"  # skip, keep, remove


@dataclass
class DownloaderConfig:
    """Base downloader configuration."""
    name: str = ""
    priority: int = 50
    timeout: int = 300
    enabled: bool = True


@dataclass
class QobuzConfig(DownloaderConfig):
    """Qobuz downloader configuration."""
    name: str = "qobuz"
    email: str = ""
    password: str = ""
    quality: int = 27  # 27=Hi-Res, 7=Lossless, 6=CD, 5=MP3 320
    embed_art: bool = True
    cover_og_quality: bool = False
    priority: int = 10


@dataclass
class SlskdConfig(DownloaderConfig):
    """Soulseek (slskd) downloader configuration."""
    name: str = "slskd"
    host: str = "localhost"
    port: int = 5030
    api_key: str = ""
    username: str = ""
    password: str = ""
    use_https: bool = False
    max_results: int = 100
    min_bitrate: int = 320
    preferred_formats: List[str] = field(default_factory=lambda: ['flac', 'alac', 'mp3', 'm4a'])
    priority: int = 30


@dataclass
class LastFMConfig:
    """Last.FM importer configuration."""
    enabled: bool = False
    api_key: str = ""
    api_secret: str = ""
    rate_limit_rpm: int = 200
    add_source_to_titles: bool = False
    source_tag_format: str = "({service})"
    default_limit: int = 50
    max_retries: int = 3
    include_top_tracks: bool = True
    include_loved_tracks: bool = True
    top_tracks_periods: List[str] = field(default_factory=lambda: ["overall", "12month", "6month", "3month"])


@dataclass
class ListenBrainzConfig:
    """ListenBrainz importer configuration."""
    enabled: bool = False
    user_token: str = ""
    server_url: str = "https://listenbrainz.org"
    rate_limit_rpm: int = 60
    add_source_to_titles: bool = False
    source_tag_format: str = "({service})"
    default_limit: int = 100
    max_retries: int = 3
    include_top_artists: bool = True
    include_recent_listens: bool = True


@dataclass
class ImportersConfig:
    """Multi-service importers configuration."""
    spotify: SpotifyConfig = field(default_factory=SpotifyConfig)
    lastfm: LastFMConfig = field(default_factory=LastFMConfig)
    listenbrainz: ListenBrainzConfig = field(default_factory=ListenBrainzConfig)


@dataclass
class PathConfig:
    """File path configuration."""
    config: str = "./config"
    downloads: str = "./downloads"
    failed: str = "./failed"
    playlists: str = "./playlists"
    m3u: str = "./m3u"
    cache: str = "./cache"


@dataclass
class PlaylistConfig:
    """Individual playlist configuration."""
    url: str = ""
    title: Optional[str] = None
    sync_mode: str = "playlist"  # playlist, collection, both
    sync_to_plex_users: List[str] = field(default_factory=list)
    download_missing: bool = True
    create_m3u: bool = True
    summary: Optional[str] = None
    poster: Optional[str] = None
    schedule_minutes: int = 1440  # 24 hours
    enabled: bool = True
    overwrite: bool = True


@dataclass
class CollectionConfig:
    """Collection configuration."""
    url: str = ""
    title: Optional[str] = None
    download_missing: bool = True
    summary: Optional[str] = None
    poster: Optional[str] = None
    schedule_minutes: int = 1440
    enabled: bool = True
    overwrite: bool = True


@dataclass
class ServiceConnections:
    """User connections to different music services."""
    spotify_username: str = ""
    lastfm_username: str = ""
    listenbrainz_username: str = ""


@dataclass
class ImportPreferences:
    """User preferences for importing from services."""
    primary_service: str = "spotify"
    enabled_services: List[str] = field(default_factory=lambda: ["spotify"])
    spotify: Dict[str, Any] = field(default_factory=lambda: {
        "include_collaborative": True,
        "include_followed": False
    })
    lastfm: Dict[str, Any] = field(default_factory=lambda: {
        "include_top_tracks": True,
        "include_loved_tracks": True,
        "top_tracks_periods": ["overall", "12month"]
    })
    listenbrainz: Dict[str, Any] = field(default_factory=lambda: {
        "include_top_artists": True,
        "include_recent_listens": True
    })


@dataclass
class UserConfig:
    """Enhanced user sync configuration with multi-service support."""
    # Service connections
    service_connections: ServiceConnections = field(default_factory=ServiceConnections)

    # Import preferences
    import_preferences: ImportPreferences = field(default_factory=ImportPreferences)

    # Plex sync settings
    sync_to_plex_users: List[str] = field(default_factory=list)
    download_missing: bool = True
    create_m3u: bool = True

    # Scheduling
    schedule_minutes: int = 1440  # 24 hours
    enabled: bool = True
    overwrite: bool = True


@dataclass
class LoggingConfig:
    """Logging configuration."""
    level: str = "INFO"
    format: str = "%(asctime)s - %(levelname)s - %(name)s - %(message)s"
    file: Optional[str] = None
    max_size_mb: int = 100
    backup_count: int = 5
    console: bool = True
    color: bool = True


@dataclass
class AdvancedConfig:
    """Advanced configuration options."""
    enable_statistics: bool = True
    statistics_file: Optional[str] = "stats.json"
    enable_caching: bool = True
    cache_cleanup_days: int = 30
    max_concurrent_downloads: int = 3
    rate_limit_buffer: float = 1.2  # Multiply rate limits by this factor for safety
    retry_failed_after_hours: int = 24
    health_check_interval_minutes: int = 60


class ConfigurationError(Exception):
    """Configuration-related error."""
    pass


class Config:
    """Configuration system for periodeec application."""
    
    def __init__(self, config_path: str = "config/config.yaml"):
        """
        Initialize configuration from file.
        
        Args:
            config_path: Path to the configuration YAML file
        """
        self.config_path = Path(config_path)
        self.config_dir = self.config_path.parent
        
        # Default configurations
        self.plex = PlexConfig()
        self.beets = BeetsConfig()
        self.paths = PathConfig()
        self.logging = LoggingConfig()
        self.advanced = AdvancedConfig()

        # Multi-service importers configuration
        self.importers = ImportersConfig()

        # Collections
        self.downloaders: Dict[str, Union[QobuzConfig, SlskdConfig]] = {}
        self.playlists: Dict[str, PlaylistConfig] = {}
        self.collections: Dict[str, CollectionConfig] = {}
        self.users: Dict[str, UserConfig] = {}
        
        # Load configuration
        if self.config_path.exists():
            self.load_config()
        else:
            logger.warning(f"Configuration file not found: {config_path}")
            self.create_default_config()
    
    def load_config(self):
        """Load configuration from YAML file."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                config_data = yaml.safe_load(f)
            
            if not config_data:
                raise ConfigurationError("Configuration file is empty")
            
            # Validate against schema
            self._validate_config(config_data)
            
            # Load main configurations using consistent structure
            # Priority: settings.* (new format) -> root level.* (legacy format)
            settings_data = config_data.get('settings', {})

            # Load core service configurations
            self._load_plex_config(
                settings_data.get('plex', {})
            )
            self._load_beets_config(
                settings_data.get('beets', config_data.get('beets', {}))
            )

            # Load path configurations (extract from settings or use legacy paths section)
            paths_config = {}
            if settings_data:
                # Extract path-related settings from settings section
                path_fields = ['downloads', 'failed', 'playlists', 'm3u', 'cache']
                for field in path_fields:
                    if field in settings_data:
                        paths_config[field] = settings_data[field]
            if not paths_config:  # Fallback to legacy paths section
                paths_config = config_data.get('paths', {})

            self._load_paths_config(paths_config)

            # Load logging configuration
            self._load_logging_config(
                settings_data.get('logging', config_data.get('logging', {}))
            )

            # Load advanced configuration
            self._load_advanced_config(
                config_data.get('advanced', {})
            )

            # Load importers configuration
            importers_config = config_data.get('importers', {})
            self._load_importers_config(importers_config)
            
            # Load downloader configurations
            self._load_downloader_configs(config_data.get('downloaders', {}))
            
            # Load playlist/collection/user configurations
            self._load_playlists_config(config_data.get('playlists', {}))
            self._load_collections_config(config_data.get('collections', {}))
            self._load_users_config(config_data.get('users', {}))
            
            # Resolve relative paths
            self._resolve_paths()
            
            logger.info(f"Configuration loaded successfully from {self.config_path}")
            
        except Exception as e:
            raise ConfigurationError(f"Failed to load configuration: {e}")
    
    def _validate_config(self, config_data: Dict[str, Any]):
        """Validate essential configuration requirements."""
        # Check for plex config under settings only
        settings_data = config_data.get('settings', {})

        if 'plex' not in settings_data:
            raise ConfigurationError("Required configuration section missing: plex must be under 'settings'")

        # Validate Plex configuration
        plex_config = settings_data.get('plex', {})
        if not plex_config.get('baseurl') or not plex_config.get('token'):
            raise ConfigurationError("Plex baseurl and token are required")
    
    def _load_plex_config(self, config: Dict[str, Any]):
        """Load Plex configuration."""
        self.plex = PlexConfig(**config)
    
    def _load_beets_config(self, config: Dict[str, Any]):
        """Load Beets configuration."""
        self.beets = BeetsConfig(**config)
    
    def _load_paths_config(self, config: Dict[str, Any]):
        """Load path configuration."""
        self.paths = PathConfig(**config)
    
    def _load_logging_config(self, config: Dict[str, Any]):
        """Load logging configuration."""
        self.logging = LoggingConfig(**config)
    
    def _load_advanced_config(self, config: Dict[str, Any]):
        """Load advanced configuration."""
        self.advanced = AdvancedConfig(**config)

    def _load_importers_config(self, config: Dict[str, Any]):
        """Load multi-service importers configuration."""
        # Load Spotify configuration
        spotify_config = config.get('spotify', {})
        # Remove legacy 'anonymous' field if present for backward compatibility
        spotify_config = {k: v for k, v in spotify_config.items() if k != 'anonymous'}
        self.importers.spotify = SpotifyConfig(**spotify_config)

        # Load Last.FM configuration
        lastfm_config = config.get('lastfm', {})
        self.importers.lastfm = LastFMConfig(**lastfm_config)

        # Load ListenBrainz configuration
        listenbrainz_config = config.get('listenbrainz', {})
        self.importers.listenbrainz = ListenBrainzConfig(**listenbrainz_config)
    
    def _load_downloader_configs(self, config: Dict[str, Any]):
        """Load downloader configurations."""
        for name, downloader_config in config.items():
            if not downloader_config.get('enabled', True):
                continue
            
            if name == 'qobuz':
                self.downloaders[name] = QobuzConfig(**downloader_config)
            elif name == 'slskd':
                self.downloaders[name] = SlskdConfig(**downloader_config)
            else:
                logger.warning(f"Unknown downloader type: {name}")
    
    def _load_playlists_config(self, config: Dict[str, Any]):
        """Load playlist configurations."""
        for name, playlist_config in config.items():
            if playlist_config.get('enabled', True):
                self.playlists[name] = PlaylistConfig(**playlist_config)
    
    def _load_collections_config(self, config: Dict[str, Any]):
        """Load collection configurations."""
        for name, collection_config in config.items():
            if collection_config.get('enabled', True):
                self.collections[name] = CollectionConfig(**collection_config)
    
    def _load_users_config(self, config: Dict[str, Any]):
        """Load user configurations."""
        for name, user_config in config.items():
            if user_config.get('enabled', True):
                # Handle nested objects properly
                user_dict = user_config.copy()

                # Extract and instantiate service_connections if present
                if 'service_connections' in user_dict:
                    service_connections_data = user_dict.pop('service_connections')
                    user_dict['service_connections'] = ServiceConnections(**service_connections_data)

                # Extract and instantiate import_preferences if present
                if 'import_preferences' in user_dict:
                    import_preferences_data = user_dict.pop('import_preferences')
                    user_dict['import_preferences'] = ImportPreferences(**import_preferences_data)

                self.users[name] = UserConfig(**user_dict)
    
    def _resolve_paths(self):
        """Resolve relative paths to absolute paths."""
        base_path = self.config_dir
        
        # Resolve path configurations
        for attr in ['config', 'downloads', 'failed', 'playlists', 'm3u', 'cache']:
            current_path = getattr(self.paths, attr)
            if not os.path.isabs(current_path):
                resolved_path = os.path.abspath(os.path.join(base_path, current_path))
                setattr(self.paths, attr, resolved_path)
        
        # Resolve beets paths
        if not os.path.isabs(self.beets.library):
            self.beets.library = os.path.abspath(os.path.join(base_path, self.beets.library))
        
        if not os.path.isabs(self.beets.directory):
            self.beets.directory = os.path.abspath(os.path.join(base_path, self.beets.directory))
        
        # Resolve logging file path if specified
        if self.logging.file and not os.path.isabs(self.logging.file):
            self.logging.file = os.path.abspath(os.path.join(base_path, self.logging.file))
        
        # Resolve statistics file path if specified
        if self.advanced.statistics_file and not os.path.isabs(self.advanced.statistics_file):
            self.advanced.statistics_file = os.path.abspath(
                os.path.join(base_path, self.advanced.statistics_file)
            )
    
    def create_default_config(self):
        """Create a default configuration file."""
        default_config = {
            'spotify': {
                'client_id': '',
                'client_secret': '',
                'cache_enabled': True,
                'cache_ttl_hours': 24,
                'rate_limit_rpm': 100
            },
            'plex': {
                'baseurl': 'http://localhost:32400',
                'token': '',
                'section': 'Music',
                'verify_ssl': True,
                'timeout': 30
            },
            'beets': {
                'library': './music/library.db',
                'directory': './music',
                'plugins': ['spotify', 'plexupdate'],
                'fuzzy': False,
                'auto_import': True,
                'strong_rec_thresh': 0.15
            },
            'paths': {
                'config': './config',
                'downloads': './downloads',
                'failed': './failed',
                'playlists': './playlists',
                'm3u': './m3u',
                'cache': './cache'
            },
            'downloaders': {
                'qobuz': {
                    'enabled': False,
                    'email': '',
                    'password': '',
                    'quality': 27,
                    'priority': 10
                },
                'slskd': {
                    'enabled': False,
                    'host': 'localhost',
                    'port': 5030,
                    'api_key': '',
                    'priority': 30
                }
            },
            'logging': {
                'level': 'INFO',
                'console': True,
                'color': True,
                'file': None
            },
            'advanced': {
                'enable_statistics': True,
                'enable_caching': True,
                'max_concurrent_downloads': 3,
                'retry_failed_after_hours': 24
            },
            'playlists': {},
            'collections': {},
            'users': {}
        }
        
        # Create config directory
        self.config_dir.mkdir(parents=True, exist_ok=True)
        
        # Write default config
        with open(self.config_path, 'w', encoding='utf-8') as f:
            yaml.dump(default_config, f, default_flow_style=False, indent=2)
        
        logger.info(f"Created default configuration at {self.config_path}")
    
    def create_directories(self):
        """Create necessary directories."""
        directories = [
            self.paths.config,
            self.paths.downloads,
            self.paths.failed,
            self.paths.playlists,
            self.paths.m3u,
            self.paths.cache,
            os.path.dirname(self.beets.library),
            self.beets.directory
        ]
        
        for directory in directories:
            if directory:
                Path(directory).mkdir(parents=True, exist_ok=True)
                logger.debug(f"Created directory: {directory}")
    
    def validate_configuration(self) -> List[str]:
        """
        Validate the loaded configuration and return list of issues.
        
        Returns:
            List of validation error messages
        """
        issues = []
        
        # Validate Plex configuration
        if not self.plex.baseurl:
            issues.append("Plex baseurl is required")
        if not self.plex.token:
            issues.append("Plex token is required")
        
        # Validate importer configurations
        if self.importers.spotify.enabled:
            if not self.importers.spotify.client_id:
                issues.append("Spotify client_id is required")
            if not self.importers.spotify.client_secret:
                issues.append("Spotify client_secret is required")

        if self.importers.lastfm.enabled:
            if not self.importers.lastfm.api_key:
                issues.append("Last.FM api_key is required when Last.FM is enabled")
            if not self.importers.lastfm.api_secret:
                issues.append("Last.FM api_secret is required when Last.FM is enabled")

        # ListenBrainz doesn't require validation as it can work without token for public data
        
        # Validate downloader configurations
        for name, downloader in self.downloaders.items():
            if isinstance(downloader, QobuzConfig):
                if not downloader.email or not downloader.password:
                    issues.append(f"Qobuz email and password are required")
            elif isinstance(downloader, SlskdConfig):
                if not downloader.api_key and not (downloader.username and downloader.password):
                    issues.append(f"Slskd requires either api_key or username/password")
        
        # Validate paths exist or can be created
        critical_paths = [
            (self.beets.directory, "Beets music directory"),
            (os.path.dirname(self.beets.library), "Beets library directory")
        ]
        
        for path, description in critical_paths:
            try:
                Path(path).mkdir(parents=True, exist_ok=True)
            except Exception as e:
                issues.append(f"Cannot create {description} at {path}: {e}")
        
        # Validate playlist/collection/user configurations
        for name, playlist in self.playlists.items():
            if not playlist.url:
                issues.append(f"Playlist '{name}' missing URL")
        
        for name, collection in self.collections.items():
            if not collection.url:
                issues.append(f"Collection '{name}' missing URL")
        
        for name, user in self.users.items():
            # Check if user has spotify connection
            if not user.service_connections.spotify_username:
                issues.append(f"User '{name}' missing spotify connection (service_connections.spotify_username required)")
        
        return issues
    
    def get_enabled_downloaders(self) -> Dict[str, Union[QobuzConfig, SlskdConfig]]:
        """Get only enabled downloader configurations."""
        return {name: config for name, config in self.downloaders.items() if config.enabled}
    
    def get_enabled_playlists(self) -> Dict[str, PlaylistConfig]:
        """Get only enabled playlist configurations."""
        return {name: config for name, config in self.playlists.items() if config.enabled}
    
    def get_enabled_collections(self) -> Dict[str, CollectionConfig]:
        """Get only enabled collection configurations."""
        return {name: config for name, config in self.collections.items() if config.enabled}
    
    def get_enabled_users(self) -> Dict[str, UserConfig]:
        """Get only enabled user configurations."""
        return {name: config for name, config in self.users.items() if config.enabled}
    
    def save_config(self):
        """Save current configuration to file."""
        try:
            config_data = {
                'settings': {
                    'plex': {
                        'baseurl': self.plex.baseurl,
                        'token': self.plex.token,
                        'section': self.plex.section,
                        'verify_ssl': self.plex.verify_ssl,
                        'timeout': self.plex.timeout,
                        'retry_attempts': self.plex.retry_attempts
                    },
                    'beets': {
                        'library': self.beets.library,
                        'directory': self.beets.directory,
                        'plugins': self.beets.plugins,
                        'fuzzy': self.beets.fuzzy,
                        'auto_import': self.beets.auto_import,
                        'strong_rec_thresh': self.beets.strong_rec_thresh,
                        'timid': self.beets.timid,
                        'duplicate_action': self.beets.duplicate_action
                    },
                    'downloads': self.paths.downloads,
                    'failed': self.paths.failed,
                    'playlists': self.paths.playlists,
                    'm3u': self.paths.m3u,
                    'cache': self.paths.cache,
                    'logging': {
                        'level': self.logging.level,
                        'format': self.logging.format,
                        'file': self.logging.file,
                        'max_size_mb': self.logging.max_size_mb,
                        'backup_count': self.logging.backup_count,
                        'console': self.logging.console,
                        'color': self.logging.color
                    }
                },
                'importers': {
                    'spotify': {
                        'client_id': self.importers.spotify.client_id,
                        'client_secret': self.importers.spotify.client_secret,
                        'cache_enabled': self.importers.spotify.cache_enabled,
                        'cache_ttl_hours': self.importers.spotify.cache_ttl_hours,
                        'rate_limit_rpm': self.importers.spotify.rate_limit_rpm,
                        'retry_attempts': self.importers.spotify.retry_attempts,
                        'request_timeout': self.importers.spotify.request_timeout
                    }
                },
                'advanced': {
                    'enable_statistics': self.advanced.enable_statistics,
                    'statistics_file': self.advanced.statistics_file,
                    'enable_caching': self.advanced.enable_caching,
                    'cache_cleanup_days': self.advanced.cache_cleanup_days,
                    'max_concurrent_downloads': self.advanced.max_concurrent_downloads,
                    'rate_limit_buffer': self.advanced.rate_limit_buffer,
                    'retry_failed_after_hours': self.advanced.retry_failed_after_hours
                }
            }
            
            # Add downloader configurations
            downloaders_data = {}
            for name, downloader in self.downloaders.items():
                if isinstance(downloader, QobuzConfig):
                    downloaders_data[name] = {
                        'enabled': downloader.enabled,
                        'email': downloader.email,
                        'password': downloader.password,
                        'quality': downloader.quality,
                        'embed_art': downloader.embed_art,
                        'cover_og_quality': downloader.cover_og_quality,
                        'priority': downloader.priority,
                        'timeout': downloader.timeout
                    }
                elif isinstance(downloader, SlskdConfig):
                    downloaders_data[name] = {
                        'enabled': downloader.enabled,
                        'host': downloader.host,
                        'port': downloader.port,
                        'api_key': downloader.api_key,
                        'username': downloader.username,
                        'password': downloader.password,
                        'use_https': downloader.use_https,
                        'max_results': downloader.max_results,
                        'min_bitrate': downloader.min_bitrate,
                        'preferred_formats': downloader.preferred_formats,
                        'priority': downloader.priority,
                        'timeout': downloader.timeout
                    }
            config_data['downloaders'] = downloaders_data
            
            # Add playlist/collection/user configurations
            config_data['playlists'] = {
                name: {
                    'url': playlist.url,
                    'title': playlist.title,
                    'sync_mode': playlist.sync_mode,
                    'sync_to_plex_users': playlist.sync_to_plex_users,
                    'download_missing': playlist.download_missing,
                    'create_m3u': playlist.create_m3u,
                    'summary': playlist.summary,
                    'poster': playlist.poster,
                    'schedule_minutes': playlist.schedule_minutes,
                    'enabled': playlist.enabled,
                    'overwrite': playlist.overwrite
                }
                for name, playlist in self.playlists.items()
            }
            
            config_data['collections'] = {
                name: {
                    'url': collection.url,
                    'title': collection.title,
                    'download_missing': collection.download_missing,
                    'summary': collection.summary,
                    'poster': collection.poster,
                    'schedule_minutes': collection.schedule_minutes,
                    'enabled': collection.enabled,
                    'overwrite': collection.overwrite
                }
                for name, collection in self.collections.items()
            }
            
            config_data['users'] = {
                name: {
                    'service_connections': {
                        'spotify_username': user.service_connections.spotify_username,
                        'lastfm_username': user.service_connections.lastfm_username,
                        'listenbrainz_username': user.service_connections.listenbrainz_username
                    },
                    'import_preferences': {
                        'primary_service': user.import_preferences.primary_service,
                        'enabled_services': user.import_preferences.enabled_services,
                        'spotify': user.import_preferences.spotify,
                        'lastfm': user.import_preferences.lastfm,
                        'listenbrainz': user.import_preferences.listenbrainz
                    },
                    'sync_to_plex_users': user.sync_to_plex_users,
                    'download_missing': user.download_missing,
                    'create_m3u': user.create_m3u,
                    'schedule_minutes': user.schedule_minutes,
                    'enabled': user.enabled,
                    'overwrite': user.overwrite
                }
                for name, user in self.users.items()
            }
            
            # Write configuration
            with open(self.config_path, 'w', encoding='utf-8') as f:
                yaml.dump(config_data, f, default_flow_style=False, indent=2)
            
            logger.info(f"Configuration saved to {self.config_path}")
            
        except Exception as e:
            raise ConfigurationError(f"Failed to save configuration: {e}")
    
    def print_summary(self):
        """Print a summary of the current configuration."""
        print("\n=== Configuration Summary ===")
        print(f"Config file: {self.config_path}")
        print(f"Spotify: Authenticated")
        print(f"Plex: {self.plex.baseurl} (section: {self.plex.section})")
        print(f"Beets library: {self.beets.library}")
        print(f"Music directory: {self.beets.directory}")
        
        print(f"\nDownloaders ({len(self.get_enabled_downloaders())} enabled):")
        for name, downloader in self.get_enabled_downloaders().items():
            print(f"  - {name} (priority: {downloader.priority})")
        
        print(f"\nPlaylists: {len(self.get_enabled_playlists())} enabled")
        print(f"Collections: {len(self.get_enabled_collections())} enabled")
        print(f"Users: {len(self.get_enabled_users())} enabled")
        
        print(f"\nAdvanced:")
        print(f"  - Statistics: {'Enabled' if self.advanced.enable_statistics else 'Disabled'}")
        print(f"  - Caching: {'Enabled' if self.advanced.enable_caching else 'Disabled'}")
        print(f"  - Max concurrent downloads: {self.advanced.max_concurrent_downloads}")
        print("=" * 30)


def load_config(config_path: str = "config/config.yaml") -> Config:
    """
    Load configuration from file with error handling.
    
    Args:
        config_path: Path to configuration file
        
    Returns:
        Config instance
        
    Raises:
        ConfigurationError: If configuration cannot be loaded or is invalid
    """
    try:
        config = Config(config_path)
        
        # Validate configuration
        issues = config.validate_configuration()
        if issues:
            error_msg = "Configuration validation failed:\n" + "\n".join(f"  - {issue}" for issue in issues)
            raise ConfigurationError(error_msg)
        
        # Create necessary directories
        config.create_directories()
        
        return config
        
    except Exception as e:
        if isinstance(e, ConfigurationError):
            raise
        else:
            raise ConfigurationError(f"Failed to load configuration: {e}")


def create_example_config(output_path: str = "config/example-config.yaml"):
    """Create an example configuration file with documentation."""
    example_config = {
        '# Periodeec Configuration File': None,
        '# This file contains all configuration options for the periodeec music sync tool': None,
        '': None,
        
        'spotify': {
            '# Spotify API credentials (get from https://developer.spotify.com)': None,
            'client_id': 'your_spotify_client_id',
            'client_secret': 'your_spotify_client_secret',
            '# Cache settings': None,
            'cache_enabled': True,
            'cache_ttl_hours': 24,
            '# Rate limiting (requests per minute)': None,
            'rate_limit_rpm': 100,
            'retry_attempts': 3,
            'request_timeout': 30
        },
        
        'plex': {
            '# Plex server configuration': None,
            'baseurl': 'http://localhost:32400',
            'token': 'your_plex_token',
            'section': 'Music',
            'verify_ssl': True,
            'timeout': 30,
            'retry_attempts': 3
        },
        
        'beets': {
            '# Beets music library configuration': None,
            'library': './music/library.db',
            'directory': './music',
            'plugins': ['spotify', 'plexupdate'],
            'fuzzy': False,
            'auto_import': True,
            'strong_rec_thresh': 0.15,
            'timid': False,
            'duplicate_action': 'skip'  # skip, keep, remove
        },
        
        'paths': {
            '# Directory paths (relative to config file)': None,
            'config': './config',
            'downloads': './downloads',
            'failed': './failed',
            'playlists': './playlists',
            'm3u': './m3u',
            'cache': './cache'
        },
        
        'downloaders': {
            'qobuz': {
                'enabled': False,
                'email': 'your_qobuz_email',
                'password': 'your_qobuz_password',
                'quality': 27,  # 27=Hi-Res, 7=Lossless, 6=CD, 5=MP3 320
                'embed_art': True,
                'cover_og_quality': False,
                'priority': 10,
                'timeout': 300
            },
            'slskd': {
                'enabled': False,
                'host': 'localhost',
                'port': 5030,
                'api_key': 'your_slskd_api_key',
                'username': '',  # Alternative to api_key
                'password': '',  # Alternative to api_key
                'use_https': False,
                'max_results': 100,
                'min_bitrate': 320,
                'preferred_formats': ['flac', 'alac', 'mp3', 'm4a'],
                'priority': 30,
                'timeout': 600
            }
        },
        
        'logging': {
            'level': 'INFO',  # DEBUG, INFO, WARNING, ERROR, CRITICAL
            'console': True,
            'color': True,
            'file': None,  # Optional log file path
            'max_size_mb': 100,
            'backup_count': 5
        },
        
        'advanced': {
            'enable_statistics': True,
            'statistics_file': 'stats.json',
            'enable_caching': True,
            'cache_cleanup_days': 30,
            'max_concurrent_downloads': 3,
            'rate_limit_buffer': 1.2,
            'retry_failed_after_hours': 24,
            'health_check_interval_minutes': 60
        },
        
        '# Playlist configurations': None,
        'playlists': {
            'example_playlist': {
                'url': 'https://open.spotify.com/playlist/your_playlist_id',
                'title': None,  # Override playlist title
                'sync_mode': 'playlist',  # playlist, collection, both
                'sync_to_plex_users': ['username1', 'username2'],
                'download_missing': True,
                'create_m3u': True,
                'summary': None,  # Override description
                'poster': None,  # Override poster URL
                'schedule_minutes': 1440,  # Check every 24 hours
                'enabled': True,
                'overwrite': True
            }
        },
        
        '# Collection configurations': None,
        'collections': {
            'example_collection': {
                'url': 'https://open.spotify.com/playlist/your_playlist_id',
                'title': None,
                'download_missing': True,
                'summary': None,
                'poster': None,
                'schedule_minutes': 1440,
                'enabled': True,
                'overwrite': True
            }
        },
        
        '# User sync configurations': None,
        'users': {
            'example_user': {
                'service_connections': {
                    'spotify_username': 'your_spotify_username',
                    'lastfm_username': 'your_lastfm_username',
                    'listenbrainz_username': 'your_listenbrainz_username'
                },
                'import_preferences': {
                    'primary_service': 'spotify',
                    'enabled_services': ['spotify'],
                    'spotify': {
                        'include_collaborative': True,
                        'include_followed': False
                    },
                    'lastfm': {
                        'include_top_tracks': True,
                        'include_loved_tracks': True,
                        'top_tracks_periods': ['overall', '12month']
                    },
                    'listenbrainz': {
                        'include_top_artists': True,
                        'include_recent_listens': True
                    }
                },
                'sync_to_plex_users': ['plex_username'],
                'download_missing': True,
                'create_m3u': True,
                'schedule_minutes': 1440,
                'enabled': True,
                'overwrite': True
            }
        }
    }
    
    # Create output directory
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Write example config (filtering out comment keys)
    clean_config = {k: v for k, v in example_config.items() if not k.startswith('#') and k != ''}
    
    with open(output_path, 'w', encoding='utf-8') as f:
        yaml.dump(clean_config, f, default_flow_style=False, indent=2)
    
    logger.info(f"Example configuration created at {output_path}")


if __name__ == "__main__":
    # Example usage
    try:
        config = load_config()
        config.print_summary()
    except ConfigurationError as e:
        print(f"Configuration error: {e}")
    except Exception as e:
        print(f"Unexpected error: {e}")
