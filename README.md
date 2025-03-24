# 🌀 Periodeec

**Periodeec** is an automated system to sync Spotify playlists and collections to Plex, enriched with intelligent autotagging via [Beets](https://beets.io/) and optional music downloading. This tool is ideal for music enthusiasts who want to maintain a local, organized, and Plex-friendly library in sync with their Spotify ecosystem.

---

## ✨ Features

- 🎵 Sync Spotify playlists to Plex as M3U playlists or collections
- 🧠 Automatic metadata tagging via Beets with plugin support
- 🚀 Integrates with external music downloaders (e.g. Qobuz, Deezer, YouTube Music)
- 📁 Generates M3U files for Plex compatibility
- ⏱️ Schedule-based synchronization (per-user frequency)
- ⚡ Fast, pluggable architecture with cache and fuzzy matching
- 🧹 Modular design (handlers for Spotify, Plex, Beets, downloaders, etc.)

---

## 📦 Requirements

- Python 3.10+
- Spotify developer credentials
- Plex Media Server with a "Music" library
- Beets with relevant plugins
- (Optional) Supported downloaders with CLI or API

---

## 🛠️ Installation

Clone the repo:

```bash
git clone https://github.com/yourusername/periodeec.git
cd periodeec
```

Install dependencies:

```bash
pip install -r requirements.txt
```

---

## ⚙️ Configuration

Create a config directory with a `config.yaml` file inside. A minimal example:

```yaml
settings:
  beets:
    library: /data/music/library.blb
    directory: /data/music
  downloads: /data/music/downloads
  unmatched: /data/music/unmatched
  failed: /data/music/failed
  spotify:
    client_id: YOUR_SPOTIFY_CLIENT_ID
    client_secret: YOUR_SPOTIFY_CLIENT_SECRET
  clients:
    qobuz:
      email: YOUR_QOBUZ_EMAIL
      password: YOUR_QOBUZ_PASSWORD
  plex:
    baseurl: http://localhost
    port: 32400
    token: YOUR_PLEX_TOKEN
    section: Music

usernames:
  alice:
    spotify_username: alice_spotify_id
    sync_mode: playlist
    sync_to_plex_users:
      - alice@example.com
    download_missing: true
    schedule: 1440 # in minutes
```

Place this under `/config/config.yaml` (or set `PD_CONFIG=/path/to/config` as an env var).

---

## 🚀 Running

To run it immediately:

```bash
python -m periodeec
```

To run it continuously (with scheduled syncing):

```bash
PD_RUN=true python -m periodeec
```

You can also containerize it using the provided `Dockerfile` and `docker-compose.yaml`.

---

## 🧱 Architecture

- `periodeec/main.py` – entrypoint
- `beets_handler.py` – handles autotagging and matching
- `spotify_handler.py` – fetches playlists and tracks
- `plex_handler.py` – creates playlists and collections on Plex
- `modules/` – downloader modules
- `track.py`, `playlist.py`, `user.py` – data models

---

## 📌 Roadmap

- [ ] Add support for smart playlist filters
- [ ] Add GUI (streamlit or web-based)
- [ ] Better handling of missing metadata

---

## 🧠 Credits

- [Beets](https://beets.io/)
- [Spotipy](https://spotipy.readthedocs.io/)
- [PlexAPI](https://python-plexapi.readthedocs.io/)
- Your favorite music downloader CLI tools

---

## 📄 License

MIT License. See `LICENSE` for details.

---

## 🙌 Contributing

Pull requests are welcome! Please open an issue first to discuss changes.
