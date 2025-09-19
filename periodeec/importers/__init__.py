# Periodeec Music Importers
"""
Multi-service music importer system for Periodeec.

This package provides a unified interface for importing playlists and tracks
from various music services (Spotify, LastFM, ListenBrainz) into the Periodeec
system for synchronization with Plex libraries.
"""

from .base_importer import MusicServiceImporter, ImporterError, AuthenticationError
from .importer_manager import ImporterManager

__all__ = [
    'MusicServiceImporter',
    'ImporterError',
    'AuthenticationError',
    'ImporterManager'
]