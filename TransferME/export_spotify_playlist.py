import json

import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import os
import re
from PIL import Image
from spotipy import Spotify

# ----------------- CONFIG -----------------
CLIENT_ID = os.getenv("SPCLIENT_ID")
CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
REDIRECT_URI = os.getenv("SPREDIRECT_URI")
SCOPE = 'playlist-read-private playlist-read-collaborative'
SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_REDIRECT_URI = os.getenv("SPREDIRECT_URI")
SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SPOTIFY_TOKEN_FILE = "spotify_token.json"

def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def reencode_jpeg(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1000, 1000))
        img.save(image_path, "JPEG", quality=85)
        print("🔄 Re-encoded cover image as valid JPEG.")
    except Exception as e:
        print(f"❌ Failed to re-encode image: {e}")

def export_spotify_playlist(playlist_url: str) -> tuple[str, str]:
    sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPE
    ))

    if "playlist/" in playlist_url:
        playlist_id = playlist_url.split("playlist/")[1].split("?")[0]
    else:
        playlist_id = playlist_url

    try:
        playlist_data = sp.playlist(playlist_id)
        playlist_name = playlist_data['name']
        playlist_description = playlist_data['description']
        playlist_image_url = playlist_data['images'][0]['url'] if playlist_data['images'] else None
        tracks = playlist_data['tracks']
    except Exception as e:
        print("❌ Failed to fetch playlist:", e)
        return None, None

    safe_name = sanitize_filename(playlist_name)

    # Extract tracks
    track_titles = []
    while tracks:
        for item in tracks['items']:
            track = item['track']
            if track:
                name = track['name']
                artist = track['artists'][0]['name']
                track_titles.append(f"{name} - {artist}")
        if tracks['next']:
            tracks = sp.next(tracks)
        else:
            break

    # Write tracks
    txt_file = f"{safe_name}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        for line in track_titles:
            f.write(line + "\n")

    # Write description
    desc_file = f"{safe_name}.desc.txt"
    if playlist_description:
        with open(desc_file, "w", encoding="utf-8") as f:
            f.write(playlist_description)

    # Write image
    img_path = f"{safe_name}.jpg"
    if playlist_image_url:
        try:
            img_data = requests.get(playlist_image_url).content
            with open(img_path, "wb") as img_file:
                img_file.write(img_data)
            reencode_jpeg(img_path)
        except Exception as e:
            print(f"❌ Failed to download cover image: {e}")

    print(f"✅ Exported '{playlist_name}' ({len(track_titles)} tracks)")
    return txt_file, safe_name  # text file and base name (without extension)

def get_saved_spotify_token():
    if os.path.exists(SPOTIFY_TOKEN_FILE):
        with open(SPOTIFY_TOKEN_FILE) as f:
            return json.load(f)["access_token"]
    return None

def export_spotify_playlist(url, token):
    sp = Spotify(auth=token)