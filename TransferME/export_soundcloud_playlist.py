import os

import requests
from PIL import Image
from io import BytesIO

from soundcloud import get_saved_token
from utils import sanitize_filename

CLIENT_ID = os.getenv("SCCLIENT_ID")
CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
REDIRECT_URI = os.getenv("SCREDIRECT_URI")
TOKEN_FILE = os.getenv("SCTOKEN_FILE", "soundcloud_token.json")


def resolve_playlist(url, token):
    headers = {"Authorization": f"OAuth {token}"}
    r = requests.get("https://api.soundcloud.com/resolve", params={"url": url}, headers=headers)
    if r.status_code != 200:
        print(f"❌ Failed to resolve URL: {r.status_code} - {r.text}")
        return None
    return r.json()

def export_soundcloud_playlist(playlist_url: str, access_token) -> tuple[str, str] | tuple[None, None]:

    playlist_data = resolve_playlist(playlist_url, access_token)
    if not playlist_data or playlist_data.get("kind") != "playlist":
        print("❌ Not a valid SoundCloud playlist.")
        return None, None

    title = playlist_data["title"]
    description = playlist_data.get("description", "")
    tracks = playlist_data["tracks"]
    artwork_url = playlist_data.get("artwork_url")
    safe_title = sanitize_filename(title)

    # Save track list
    txt_file = f"{safe_title}.txt"
    with open(txt_file, "w", encoding="utf-8") as f:
        for track in tracks:
            f.write(f"{track['title']} - {track['user']['username']}\n")

    # Save description
    if description:
        with open(f"{safe_title}.desc.txt", "w", encoding="utf-8") as f:
            f.write(description)
        print(f"📝 Description saved: {safe_title}.desc.txt")

    # Save artwork
    if artwork_url:
        image_url = artwork_url.replace("large.jpg", "t500x500.jpg")
        r = requests.get(image_url)
        if r.status_code == 200:
            try:
                img = Image.open(BytesIO(r.content)).convert("RGB")
                img.thumbnail((1000, 1000))
                img.save(f"{safe_title}.jpg", "JPEG", quality=85)
                print(f"🖼️ Cover image saved: {safe_title}.jpg")
            except Exception as e:
                print("⚠️ Failed to process image:", e)

    print(f"✅ Exported playlist: {safe_title}")
    print(f"🎵 Total tracks: {len(tracks)}")

    return txt_file, safe_title
