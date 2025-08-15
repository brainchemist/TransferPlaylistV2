import os
import re
import json
import time
import requests

from utils import sanitize_filename

CLIENT_ID = os.getenv("SCCLIENT_ID")
CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
REDIRECT_URI = os.getenv("SCREDIRECT_URI")

def get_saved_token(session_id: str = "default") -> str | None:
    path = f"tokens/{session_id}_sc.json"
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)["access_token"]
    return None

def search_track(title_line, headers):
    parts = re.split(r"\s*[-–]\s*", title_line)
    query = title_line.strip() if len(parts) < 2 else f"{parts[0].strip()} {parts[1].strip()}"

    try:
        r = requests.get("https://api.soundcloud.com/tracks", params={
            'q': query,
            'limit': 5
        }, headers=headers)
        r.raise_for_status()
        results = r.json()
    except Exception:
        return None

    if not isinstance(results, list) or not results:
        return None

    for track in results:
        track_title = track['title'].lower()
        if all(word.lower() in track_title for word in query.lower().split()):
            return track['id']
    return results[0]['id']

def upload_cover_and_description(headers, pid, image_path, description):
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

def transfer_to_soundcloud(text_file, token):
    headers = {
        'Authorization': f'OAuth {token}',
        'User-Agent': 'Mozilla/5.0'
    }
    if not os.path.exists(text_file):
        return f"❌ File not found: {text_file}"

    playlist_name = os.path.splitext(os.path.basename(text_file))[0]
    description = "Imported from Spotify 🎵"

    description_file = f"{playlist_name}.desc.txt"
    if description_file and os.path.exists(description_file):
        with open(description_file, "r", encoding="utf-8") as f:
            description = f.read().strip()

    # Read tracks
    with open(text_file, "r", encoding="utf-8") as f:
        track_lines = [line.strip() for line in f if line.strip()]

    print(f"\n🎶 Found {len(track_lines)} tracks to search.\n")
    track_ids = []

    skipped_log = "skipped_tracks.txt"
    open(skipped_log, "w").close()

    for i, title in enumerate(track_lines):
        percent = round((i + 1) / len(track_lines) * 100)
        tid = search_track(title, headers)

        if tid:
            print(f"[{percent}%] ✅ Found: {title}")
            track_ids.append(tid)
        else:
            print(f"[{percent}%] ❌ Not found: {title}")
            with open(skipped_log, "a", encoding="utf-8") as logf:
                logf.write(title + "\n")

        time.sleep(0.6)

    if not track_ids:
        return "⚠️ No valid tracks found. Playlist creation skipped."

    payload = {
        'playlist': {
            'title': playlist_name,
            'sharing': 'public',
            'tracks': [{'id': tid} for tid in track_ids]
        }
    }

    r = requests.post("https://api.soundcloud.com/playlists", headers=headers, json=payload)
    if r.status_code != 201:
        return f"❌ Failed to create playlist: {r.status_code} - {r.text}"

    pl = r.json()
    playlist_url = pl['permalink_url']
    print(f"\n✅ Playlist created: {pl['title']}")
    print(f"🔗 Playlist link: {playlist_url}")

    safe_title = sanitize_filename(pl['title'])
    cover_image_file = f"{safe_title}.jpg"

    if cover_image_file:
        upload_cover_and_description(headers, pl['id'], cover_image_file, description)

    for file in [f"{safe_title}.txt", f"{safe_title}.jpg", f"{safe_title}.desc.txt", "skipped_tracks.txt"]:
        if os.path.exists(file):
            os.remove(file)
            print(f" Deleted {file}")

    return f"✅ Playlist '{playlist_name}' transferred to SoundCloud.\n🔗 {playlist_url}"

def _sc_auth_header(token):
    # token may be a string or a dict saved from /oauth2/token
    if isinstance(token, dict):
        token = token.get("access_token") or token.get("oauth_token") or token.get("token")
    if not token:
        raise RuntimeError("No SoundCloud access token available.")
    return {"Authorization": f"OAuth {token}"}
