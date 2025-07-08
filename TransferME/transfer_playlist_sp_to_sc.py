import subprocess
import os
import glob

print("Exporting playlist from Spotify...")
subprocess.run(["python", "export_spotify_playlist.py"])

playlist_txts = sorted(
    [f for f in glob.glob("*.txt") if "skipped_tracks" not in f and not f.endswith(".desc.txt")],
    key=os.path.getmtime,
    reverse=True
)

if not playlist_txts:
    print("❌ No playlist .txt file found.")
    exit()

TEXT_FILE = playlist_txts[0]
BASE_NAME = os.path.splitext(TEXT_FILE)[0]
DESC_FILE = f"{BASE_NAME}.desc.txt"
COVER_FILE = f"{BASE_NAME}.jpg"

print(f"\n Transferring '{BASE_NAME}' to SoundCloud...")

env = os.environ.copy()
env["TEXT_FILE"] = TEXT_FILE
env["DESCRIPTION_FILE"] = DESC_FILE if os.path.exists(DESC_FILE) else ""
env["COVER_IMAGE_FILE"] = COVER_FILE if os.path.exists(COVER_FILE) else ""
env["TOKEN_FILE"] = "soundcloud_token.json"

subprocess.run(["python", "soundcloud.py"], env=env)

print("\n Cleaning up exported files...")
for file in [TEXT_FILE, DESC_FILE, COVER_FILE]:
    if os.path.exists(file):
        os.remove(file)
        print(f" Deleted {file}")

print("\n✅ All done!")
