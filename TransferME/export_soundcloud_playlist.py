import requests
import re
import os
import json
import webbrowser
from PIL import Image
from io import BytesIO

# ---------------- CONFIG ----------------
CLIENT_ID = 'bmeOWPX1sHDLo6DATVC3EoQuEuF2u7Hf'
CLIENT_SECRET = 'pFYb7pOJAQMyjEPwS6m0tmXIXeMPzKOt'
REDIRECT_URI = 'http://localhost:8080/callback'
TOKEN_FILE = 'soundcloud_token.json'

# ------------- AUTH ----------------
def get_access_token():
    if os.path.exists(TOKEN_FILE):
        with open(TOKEN_FILE, "r") as f:
            token_data = json.load(f)
            if 'access_token' in token_data:
                print("🔓 Reusing saved access token.")
                return token_data['access_token']

    auth_url = (
        f"https://soundcloud.com/connect?client_id={CLIENT_ID}"
        f"&redirect_uri={REDIRECT_URI}&response_type=code&scope=non-expiring"
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
        print(f"❌ Token exchange failed ({token_response.status_code}):", token_response.text)
        return None

    token_data = token_response.json()
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

    print("✅ Token saved.")
    return token_data['access_token']

# ----------- HELPERS --------------
def sanitize_filename(name):
    return re.sub(r'[\\/*?:"<>|]', "_", name)

def resolve_playlist(url, token):
    headers = {"Authorization": f"OAuth {token}"}
    r = requests.get("https://api.soundcloud.com/resolve", params={"url": url}, headers=headers)
    if r.status_code != 200:
        print(f"❌ Failed to resolve URL: {r.status_code} - {r.text}")
        return None
    return r.json()

# ----------- MAIN ----------------
access_token = get_access_token()
if not access_token:
    exit()

playlist_url = input("🔗 Enter the SoundCloud playlist URL: ").strip()
playlist_data = resolve_playlist(playlist_url, access_token)

if not playlist_data or playlist_data.get("kind") != "playlist":
    print("❌ Not a valid SoundCloud playlist.")
    exit()

title = playlist_data["title"]
description = playlist_data.get("description", "")
tracks = playlist_data["tracks"]
artwork_url = playlist_data.get("artwork_url")
safe_title = sanitize_filename(title)

# Save track list
with open(f"{safe_title}.txt", "w", encoding="utf-8") as f:
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
