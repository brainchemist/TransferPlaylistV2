import subprocess
import os
import glob

# Step 1: Export playlist from SoundCloud
print("🔄 Exporting playlist from SoundCloud...")
subprocess.run(["python", "export_soundcloud_playlist.py"])

# Step 2: Detect the most recently created .txt playlist (not skipped list)
playlist_txts = sorted(
    [f for f in glob.glob("*.txt") if "skipped" not in f and not f.endswith(".desc.txt")],
    key=os.path.getmtime,
    reverse=True
)

if not playlist_txts:
    print("❌ No exported playlist found.")
    exit()

TEXT_FILE = playlist_txts[0]
BASE_NAME = os.path.splitext(TEXT_FILE)[0]
DESC_FILE = f"{BASE_NAME}.desc.txt"
COVER_FILE = f"{BASE_NAME}.jpg"

print(f"\n🚀 Transferring '{BASE_NAME}' to Spotify...")

# Step 3: Pass environment vars to spotify.py
env = os.environ.copy()
env["TEXT_FILE"] = TEXT_FILE
env["DESCRIPTION_FILE"] = DESC_FILE if os.path.exists(DESC_FILE) else ""
env["COVER_IMAGE_FILE"] = COVER_FILE if os.path.exists(COVER_FILE) else ""

subprocess.run(["python", "spotify.py"], env=env)

# Step 4: Optional cleanup
print("\n🧹 Cleaning up temporary files...")
for f in [TEXT_FILE, DESC_FILE, COVER_FILE]:
    if os.path.exists(f):
        os.remove(f)
        print(f"🗑️ Deleted {f}")

print("\n✅ SoundCloud ➜ Spotify transfer complete.")
