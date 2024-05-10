import json
import os
import requests
import musicbrainzngs as mb

path = "./config/cache/albums"
lidarr_url = "https://lidarr.negrony.org"
lidarr_key = "b8a7f0a91b0f4762a5a022d52cc24b24"
headers = {"X-Api-Key": lidarr_key, "Content-Type": "application/json"}
mb.set_useragent(app="periodeec", version="0.0.1", contact="489un1b1@duck.com")
mb.auth("fixov", "EdzQmWr5KN6HqfF")


def match(album: dict) -> tuple[bool, str]:

    upc = album["external_ids"]["upc"]
    name = album["name"]
    results = mb.search_releases(query=f"{upc}", limit=1)
    if results.get("release-list") is None:
        return False, ""
    release = results["release-list"]

    # matched against upc
    if len(release) > 0 and release[0].get("id") is not None:
        return True, release[0]["id"]
    else:
        artists = [artist["name"] for artist in album["artists"]]
        artist = artists[0]
        query = f"{artist} {name}"
        results = mb.search_releases(query=query, limit=10)
        if results.get("release-list") is None:
            print(f"ERROR: no match for {query}")
            return False, ""
        releases = results["release-list"]
        if len(releases) < 1:
            print(f"ERROR: no match for {query}")
            return False, ""

        for release in releases:
            title = release["title"]
            credited_artist = release["artist-credit"][0]["name"]

            if str(title).capitalize() == str(name).capitalize():
                if str(credited_artist).capitalize() in [str(artist).capitalize() for artist in artists]:
                    if release.get("barcode") is None:
                        print(
                            f"submitting barcode for release {name} of {credited_artist}")
                        # mb.submit_barcodes({release["id"]: upc})
                    if release.get("id") is not None:
                        return True, release["id"]

    return False, ""


def add(mbid: str):

    album_endpoint = f"{lidarr_url}/api/v1/album"
    existing_album_response = requests.get(
        f"{album_endpoint}/{mbid}", headers=headers)
    if existing_album_response.status_code == 200:
        print("Album already exists in Lidarr. Skipping addition.")
    else:
        request_body = {"albumIds": [mbid]}

        add_album_response = requests.post(
            album_endpoint, headers=headers, data=json.dumps(request_body))

        if add_album_response.status_code == 200:
            print(f"Album added successfully.")
        else:
            print(
                f"Failed to add album. Status code: {add_album_response.status_code}, Response: {add_album_response.text}")


for file in os.listdir(path):
    file = os.path.join(path, file)
    matched = False
    with open(file, "r") as f:
        album = json.load(f)
        matched, mbid = match(album)
        if not matched:
            print(
                f"ERROR: failed to match {album['name']} with upc {album['external_ids']['upc']}")
        else:
            print(f"SUCCESS: matched {album['name']} with MBID {mbid}")
            add(mbid)
