import os
import re
import time
import base64
import json
import spotipy

def get_saved_spotify_token():
    token_file = "spotify_token.json"
    if os.path.exists(token_file):
        with open(token_file) as f:
            return json.load(f)["access_token"]
    return None

def transfer_to_spotify(text_file: str, desc_file: str = "") -> str:
    if not text_file or not os.path.exists(text_file):
        return "❌ Playlist text file not found."

    base_name = os.path.splitext(os.path.basename(text_file))[0]
    token = get_saved_spotify_token()
    if not token:
        return "❌ Spotify token not found. Please authenticate first."

    sp = spotipy.Spotify(auth=token)

    try:
        user_id = sp.current_user()["id"]
    except Exception as e:
        return f"❌ Failed to fetch current user: {e}"

    with open(text_file, "r", encoding="utf-8") as f:
        track_lines = [line.strip() for line in f if line.strip()]

    playlist_desc = ""
    desc_file = f"{base_name}.desc.txt"
    if os.path.exists(desc_file):
        with open(desc_file, "r", encoding="utf-8") as f:
            playlist_desc = f.read().strip()

    new_playlist = sp.user_playlist_create(user=user_id, name=base_name, public=True, description=playlist_desc)
    playlist_id = new_playlist["id"]
    print(f"🎵 Created Spotify playlist: {base_name}")

    image_file = f"{base_name}.jpg"
    if os.path.exists(image_file):
        try:
            with open(image_file, "rb") as f:
                b64_img = base64.b64encode(f.read()).decode("utf-8")
            sp.playlist_upload_cover_image(playlist_id, b64_img)
            print("🖼️ Uploaded playlist image.")
        except Exception as e:
            print("⚠️ Could not upload image:", e)

    found, not_found = [], []

    for i, line in enumerate(track_lines):
        parts = re.split(r"\s*-\s*", line)
        query = line if len(parts) < 2 else f"{parts[0]} {parts[1]}"
        try:
            result = sp.search(q=query, type="track", limit=1)
            items = result["tracks"]["items"]
            if items:
                found.append(items[0]["id"])
                print(f"[{int((i + 1) / len(track_lines) * 100)}%] ✅ Found: {line}")
            else:
                not_found.append(line)
                print(f"[{int((i + 1) / len(track_lines) * 100)}%] ❌ Not found: {line}")
        except Exception as e:
            not_found.append(line)
            print(f"⚠️ Error searching for: {line} – {e}")

        time.sleep(0.5)

    for i in range(0, len(found), 100):
        sp.playlist_add_items(playlist_id, found[i:i + 100])

    if not_found:
        skipped_file = "spotify_skipped_tracks.txt"
        with open(skipped_file, "w", encoding="utf-8") as f:
            f.write("\n".join(not_found))
        print(f"⚠️ {len(not_found)} not found. Saved to {skipped_file}")

    for file in [f"{base_name}.txt", f"{base_name}.jpg", f"{base_name}.desc.txt"]:
        if os.path.exists(file):
            os.remove(file)
            print(f"🗑️ Deleted {file}")

    return f"✅ Transfer complete! {len(found)} tracks added to '{base_name}' playlist."
