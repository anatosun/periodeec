# Periodeec

This is a simple script to periodically send your Spotify playlists to Deemix.

## Usage

To use the script, simply fill the `.env` and execute `python3 app.py`.

```
export EXECUTION_MODE=<albums|playlists|tracks>
export CONFIG_PATH=</config>
export DEEMIX_URL=<http://your_deemix_url:6595>
export DEEZER_EMAIL=<deezer email>
export DEEZER_PASSWORD=<deezer password>
export SPOTIFY_USERNAMES=<a list of spotify username from which you want to download playlists>
export SPOTIFY_CLIENT_ID=<spotify client id>
export SPOTIFY_CLIENT_SECRET=<spotify client secret>
export INTERVAL=<interval to run the script in seconds>
```

## Docker

Download the compose file, fill in the variables and execute `docker-compose up -d`.

```
version: '3.2'
services:
  periodeec:
    image: ghcr.io/anatosun/periodeec:latest
    container_name: periodeec
    environment:
        - EXECUTION_MODE=<albums>
        - CONFIG_PATH=</config>
        - DEEZER_EMAIL=<deezer email>
        - DEEZER_PASSWORD=<deezer password>
        - SPOTIFY_USERNAMES=<a list of spotify username from which you want to download playlists>
        - SPOTIFY_CLIENT_ID=<spotify client id>
        - SPOTIFY_CLIENT_SECRET=<spotify client secret>
        - INTERVAL=<interval to run the script in seconds>
    volumes:
        /config:/config # proper volume binding to make cache persistent
```
