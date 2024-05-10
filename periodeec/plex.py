import time
import click
from click.types import BOOL
from plexapi.audio import Playlist, Track
from plexapi.myplex import MyPlexPinLogin, MyPlexAccount
from plexapi.server import PlexServer

user = "adri.0"

baseurl = 'http://galak.internet-box.ch:32401'
token = '7yZzGaVTteBXi-Hipv3K'
source = PlexServer(baseurl, token)
source = source.switchUser(user)

baseurl = 'http://galak.internet-box.ch:32400'
token = '7yZzGaVTteBXi-Hipv3K'
destination = PlexServer(baseurl, token)
destination = destination.switchUser(user)


@click.command()
def match():

    playlist: Playlist
    for playlist in source.playlists(playlistType='audio'):

        playlist_title = str(playlist.title)
        if playlist.smart:
            click.echo(f"skipping {playlist_title} (smart playlist)")
            continue

        if not click.confirm(f"Match playlist '{playlist_title}'?"):
            continue

        matched_tracks = []
        track: Track
        for track in playlist.items():

            # .replace("(Original Mix)","").replace(" (", " - ").replace(")", "")
            title = str(track.title)
            artist = track.artist().title
            album = track.album().title
            unmatched = True
            query = title

            while unmatched:

                try:
                    results = destination.search(
                        f"{query}", mediatype="track", sectionId=11, limit=10)

                except Exception as e:
                    print(f"{e}")
                    results = []

                for result in results:
                    if result.title == title and result.artist().title == artist:
                        matched_tracks.append(result)
                        click.echo(
                            f"matched track {result.title} by {result.artist().title}")
                        unmatched = False
                        continue

                if len(results) < 1:
                    print(f"no match for {title} from {artist}")
                    query = click.prompt("Type query", type=click.STRING)
                    results = destination.search(
                        f"{query}", mediatype="track", sectionId=11)

                for i, result in enumerate(results):
                    click.echo(click.style(
                        f"{i}: {result.title} by {result.artist().title}", bold=True, blink=True), color=True)

                index = click.prompt(
                    f"Select matching track to {title} by {artist}", type=int, default=0)

                if index < 0 or index >= len(results):
                    query = click.prompt("Type query", type=click.STRING)
                    continue

                matched_tracks.append(results[index])
                unmatched = False

        if click.confirm("Commit tracks?"):
            destination.createPlaylist(
                title=playlist_title, items=matched_tracks)


if __name__ == '__main__':
    match()
