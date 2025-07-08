import requests
import webbrowser
import re
import time
import os
import json

# ----------------- CONFIG -----------------
CLIENT_ID = 'bmeOWPX1sHDLo6DATVC3EoQuEuF2u7Hf'
CLIENT_SECRET = 'pFYb7pOJAQMyjEPwS6m0tmXIXeMPzKOt'
REDIRECT_URI = 'http://localhost:8080/callback'
TEXT_FILE = os.getenv("TEXT_FILE")
TOKEN_FILE = os.getenv("TOKEN_FILE", "soundcloud_token.json")
NEW_PLAYLIST_NAME = os.path.splitext(os.path.basename(TEXT_FILE))[0]

desc_file = os.getenv("DESCRIPTION_FILE")
if desc_file and os.path.exists(desc_file):
    with open(desc_file, "r", encoding="utf-8") as f:
        PLAYLIST_DESCRIPTION = f.read().strip()
else:
    PLAYLIST_DESCRIPTION = "Imported from Spotify 🎵"

COVER_IMAGE_FILE = os.getenv("COVER_IMAGE_FILE", "")


# ----------------- AUTH + TOKEN REUSE -----------------
if os.path.exists(TOKEN_FILE):
    with open(TOKEN_FILE, "r") as f:
        token_data = json.load(f)
        access_token = token_data["access_token"]
        print("🔓 Reusing saved access token.")
else:
    auth_url = (
        f"https://soundcloud.com/connect?"
        f"client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}&response_type=code&scope=non-expiring"
    )
    print("🔗 Open this URL to authorize access:\n" + auth_url)
    webbrowser.open(auth_url)

    code = input("📋 Paste the `code` from the redirected URL: ").strip()

    token_response = requests.post("https://api.soundcloud.com/oauth2/token", data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
        'code': code
    })

    if token_response.status_code != 200:
        print("❌ Token exchange failed:", token_response.text)
        exit()

    token_data = token_response.json()
    access_token = token_data["access_token"]

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)
    print("💾 Access token saved for future use.")

# OAuth headers
headers = {
    'Authorization': f'OAuth {access_token}',
    'User-Agent': 'Mozilla/5.0'
}

# ----------------- SEARCH FUNCTION -----------------
def search_track(title_line):
    parts = re.split(r"\s*[-–]\s*", title_line)
    if len(parts) < 2:
        query = title_line.strip()
    else:
        title = parts[0].strip()
        artist = parts[1].strip()
        query = f"{title} {artist}"

    try:
        r = requests.get("https://api.soundcloud.com/tracks", params={
            'q': query,
            'limit': 5
        }, headers=headers)
    except Exception as e:
        print(f"⚠️  Connection error for '{query}': {e}")
        return None

    if r.status_code != 200:
        print(f"⚠️  API error {r.status_code} for '{query}': {r.text[:80]}")
        return None

    try:
        results = r.json()
    except Exception as e:
        print(f"⚠️  JSON parse error for '{query}': {e}")
        return None

    if not isinstance(results, list) or not results:
        return None

    for track in results:
        track_title = track['title'].lower()
        if all(word.lower() in track_title for word in query.lower().split()):
            return track['id']

    return results[0]['id']

# ----------------- LOAD TRACKS -----------------
try:
    with open(TEXT_FILE, "r", encoding="utf-8") as f:
        track_names = [line.strip() for line in f if line.strip()]
except FileNotFoundError:
    print(f"❌ File not found: {TEXT_FILE}")
    exit()

print(f"\n🎶 Found {len(track_names)} tracks to search.\n")

track_ids = []

# Clear skipped log
with open("skipped_tracks.txt", "w", encoding="utf-8") as logf:
    logf.write("")

for i, title in enumerate(track_names):
    percent = round((i + 1) / len(track_names) * 100)
    tid = search_track(title)

    if tid:
        print(f"[{percent}%] ✅ Found: {title}")
        track_ids.append(tid)
    else:
        print(f"[{percent}%] ❌ Not found: {title}")
        with open("skipped_tracks.txt", "a", encoding="utf-8") as logf:
            logf.write(title + "\n")

    time.sleep(0.6)

# ----------------- CREATE PLAYLIST -----------------
if not track_ids:
    print("⚠️ No valid tracks found. Playlist creation skipped.")
    exit()

playlist_payload = {
    'playlist': {
        'title': NEW_PLAYLIST_NAME,
        'sharing': 'public',
        'tracks': [{'id': tid} for tid in track_ids]
    }
}

create_r = requests.post("https://api.soundcloud.com/playlists", headers=headers, json=playlist_payload)

if create_r.status_code != 201:
    print(f"❌ Failed to create playlist: {create_r.status_code} - {create_r.text}")
    exit()

pl = create_r.json()
playlist_id = pl['id']
print(f"\n✅ Playlist created: {pl['title']}")
print(f"🔗 Playlist link: {pl['permalink_url']}")

# ----------------- SET DESCRIPTION AND IMAGE -----------------
def upload_cover_image_and_description(pid, image_path, description):
    if not os.path.exists(image_path):
        print("⚠️  Cover image not found, skipping upload.")
        return

    with open(image_path, "rb") as img_file:
        image_data = img_file.read()

    patch_url = f"https://api.soundcloud.com/playlists/{pid}"
    files = {
        'playlist[artwork_data]': ('cover.jpg', image_data, 'image/jpeg')
    }
    data = {
        'playlist[description]': description
    }

    r = requests.put(patch_url, headers=headers, data=data, files=files)
    if r.status_code == 200:
        print("🖼️  Cover image and description updated successfully.")
    else:
        print(f"❌ Failed to update image/description: {r.status_code} - {r.text}")

upload_cover_image_and_description(playlist_id, COVER_IMAGE_FILE, PLAYLIST_DESCRIPTION)
