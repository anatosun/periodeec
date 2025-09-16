# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

Periodeec is an automated music synchronization system that bridges Spotify playlists with local Plex libraries. It uses Beets for metadata management and supports multiple music downloaders (Qobuz, Soulseek via slskd).

## Development Commands

### Running the Application
```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (main entry point)
python -m periodeec.main

# Alternative using setup.py entry point
periodeec

# Run with specific arguments
python -m periodeec.main --once           # One-time sync
python -m periodeec.main --run            # Continuous mode with scheduling
python -m periodeec.main --validate-config # Validate configuration only
python -m periodeec.main --status         # Status check
```

### Docker Commands
```bash
# Build locally
docker build -t periodeec:local .

# Run with Docker Compose
docker-compose up -d

# Build multi-architecture
docker buildx build --platform linux/amd64,linux/arm64 -t periodeec:multi .
```

### Development Setup
```bash
# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install in development mode
pip install -e .
```

## Git Commit Guidelines

- Use simple, concise commit messages without excessive detail
- Follow conventional commit format: `feat:`, `fix:`, `docs:`, `refactor:`, `ci:`, `chore:`
- Do not give credit to Claude or mention AI assistance in commit messages
- Examples:
  - `feat: add retry logic for slskd downloads`
  - `fix: resolve plex playlist creation issues`
  - `refactor: simplify download manager error handling`

## Code Architecture

### Core Components
- `main.py` - Application entrypoint, orchestration, scheduling, and monitoring
- `schema.py` - Unified data models (Track, User, metadata, enums for TrackStatus/AudioFormat)
- `config.py` - Configuration management with dataclasses for service configs
- `spotify_handler.py` - Spotify API integration with caching and rate limiting
- `plex_handler.py` - Plex Media Server integration for playlist/library management
- `beets_handler.py` - Metadata management and library matching via Beets
- `download_manager.py` - Download orchestration and retry logic
- `playlist.py` - Playlist management and synchronization logic

### Downloader Architecture
Located in `modules/` directory:
- `downloader.py` - Base downloader interface/abstract class
- `qobuz.py` - Qobuz high-quality downloads implementation
- `slskd.py` - Soulseek P2P integration via slskd daemon

### Data Flow
1. Spotify API → Track Extraction
2. Beets Library Check → Found/Not Found decision
3. If not found → Download Manager → Multi-source search (Qobuz, Soulseek)
4. Quality Scoring → Best Source Selection → Download & Import
5. Beets Processing → Plex Integration

## Configuration

The application uses YAML configuration files with schemas covering:
- Spotify API credentials and settings
- Plex server configuration
- Beets library settings
- Download source configurations (Qobuz, slskd)
- User profiles with sync preferences
- Scheduling and retry logic

Key config file: `config/config.yaml`

## Coding Conventions

- When refactoring or improving code, keep original class/function names (use `Class` not `ImprovedClass`)
- Use type hints and modern Python practices
- Follow existing error handling patterns from main.py
- Maintain consistency with existing logging and statistics tracking

## Key Features

### Multi-Source Downloads
- Qobuz: Hi-Res/Lossless quality downloads
- Soulseek (slskd): P2P network integration
- Extensible downloader architecture

### Metadata Management
- Beets integration with plugin support
- Audio analysis and quality scoring
- Multi-strategy matching (ISRC, fuzzy text, metadata)
- Cross-platform filename sanitization

### Synchronization
- Spotify to Plex sync with playlist support
- Automatic download of missing tracks
- Progress tracking and logging
- Caching system for performance

## Docker Integration

- Multi-architecture support (AMD64/ARM64)
- Branch-based image tags for development
- GitHub Container Registry with automated builds
- Environment variables for configuration

## Development Notes

- No test framework is currently implemented
- Uses conventional commit workflow
- Extensive error handling and logging in main.py
- Statistics tracking via ApplicationStats class