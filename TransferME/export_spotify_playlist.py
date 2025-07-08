import spotipy
from spotipy.oauth2 import SpotifyOAuth
import requests
import os
import re
from PIL import Image

# ----------------- CONFIG -----------------
CLIENT_ID = '213b54fe34d54c15ac0307909e4e8d27'
CLIENT_SECRET = 'eee9bdd3e6c2416196d2465e1c3a89f0'
REDIRECT_URI = 'http://127.0.0.1:8000/callback'
SCOPE = 'playlist-read-private playlist-read-collaborative'

# ----------------- SPOTIPY AUTH -----------------
sp = spotipy.Spotify(auth_manager=SpotifyOAuth(
    client_id=CLIENT_ID,
    client_secret=CLIENT_SECRET,
    redirect_uri=REDIRECT_URI,
    scope=SCOPE
))

# ----------------- GET PLAYLIST -----------------
playlist_url = input("Enter your Spotify playlist URL or ID: ").strip()
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
    exit()

# Sanitize filename
safe_name = re.sub(r'[\\/*?:"<>|]', "_", playlist_name)

# ----------------- EXTRACT TRACKS -----------------
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

# ----------------- SAVE TRACK LIST -----------------
with open(f"{safe_name}.txt", "w", encoding="utf-8") as f:
    for line in track_titles:
        f.write(line + "\n")

# ----------------- SAVE DESCRIPTION -----------------
if playlist_description:
    with open(f"{safe_name}.desc.txt", "w", encoding="utf-8") as f:
        f.write(playlist_description)

# ----------------- DOWNLOAD AND RE-ENCODE IMAGE -----------------
def reencode_jpeg(image_path):
    try:
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1000, 1000))  # Resize to safe dimensions
        img.save(image_path, "JPEG", quality=85)
        print("🔄 Re-encoded cover image as valid JPEG.")
    except Exception as e:
        print(f"❌ Failed to re-encode image: {e}")

if playlist_image_url:
    img_path = f"{safe_name}.jpg"
    try:
        img_data = requests.get(playlist_image_url).content
        with open(img_path, "wb") as img_file:
            img_file.write(img_data)
        reencode_jpeg(img_path)
    except Exception as e:
        print(f"❌ Failed to download cover image: {e}")

# ----------------- DONE -----------------
print(f"✅ Saved {len(track_titles)} tracks to '{safe_name}.txt'")
if playlist_description:
    print(f"📝 Description saved to '{safe_name}.desc.txt'")
if playlist_image_url:
    print(f"🖼️ Cover image saved to '{safe_name}.jpg'")
