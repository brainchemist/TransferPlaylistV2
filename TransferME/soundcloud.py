import os
import re
import json
import requests
from typing import Callable, Optional, Tuple, List, Dict
from dotenv import load_dotenv

load_dotenv()

SCCLIENT_ID = os.getenv("SCCLIENT_ID", "")
SCCLIENT_SECRET = os.getenv("SCCLIENT_SECRET", "")

TOKENS_DIR = "tokens"

# ---------- Token helpers ----------

def _sc_token_path(session_id: str) -> str:
    return os.path.join(TOKENS_DIR, f"{session_id}_sc.json")

def _load_sc_blob(session_id: str) -> Optional[dict]:
    p = _sc_token_path(session_id)
    if not os.path.exists(p):
        return None
    with open(p, "r") as f:
        return json.load(f)

def _save_sc_blob(session_id: str, blob: dict) -> None:
    os.makedirs(TOKENS_DIR, exist_ok=True)
    with open(_sc_token_path(session_id), "w") as f:
        json.dump(blob, f)

def get_saved_token(session_id: str) -> Optional[str]:
    data = _load_sc_blob(session_id)
    if not data:
        return None
    return data.get("access_token")

def refresh_soundcloud_token(session_id: str) -> Optional[str]:
    data = _load_sc_blob(session_id)
    if not data:
        return None
    rt = data.get("refresh_token")
    if not rt:
        return None
    r = requests.post("https://api.soundcloud.com/oauth2/token", data={
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": SCCLIENT_ID,
        "client_secret": SCCLIENT_SECRET,
    })
    if r.status_code != 200:
        print(f"⚠️ SC refresh failed: {r.status_code} {r.text}")
        return None
    new_tok = r.json()
    if "refresh_token" not in new_tok and "refresh_token" in data:
        new_tok["refresh_token"] = data["refresh_token"]
    _save_sc_blob(session_id, new_tok)
    return new_tok.get("access_token")

def _auth_headers(access_token: str) -> Dict[str, str]:
    return {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0",
        "Authorization": f"OAuth {access_token}",
    }

# ---------- Search (v2 with v1 fallback) + fuzzy matching ----------

def _norm(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = re.sub(r"\b(slowed|reverb|remix|edit|radio|version|feat|ft)\b", "", s)
    return s

def _score(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)

def search_soundcloud_track(session_id: str, title: str, artist: str) -> Optional[dict]:
    """
    Try v2 search, then fallback to v1. Auto-refresh on 401 once.
    Returns the best matching track object (dict) or None.
    """
    access = get_saved_token(session_id)
    if not access:
        return None
    headers = _auth_headers(access)

    query = f"{title} {artist}".strip()

    # v2
    v2_url = "https://api-v2.soundcloud.com/search/tracks"
    v2_params = {"q": query, "limit": 10}
    r = requests.get(v2_url, params=v2_params, headers=headers, timeout=20)

    if r.status_code == 401:
        new_access = refresh_soundcloud_token(session_id)
        if not new_access:
            return None
        headers = _auth_headers(new_access)
        r = requests.get(v2_url, params=v2_params, headers=headers, timeout=20)

    if r.status_code != 200:
        # v1 fallback
        v1_url = "https://api.soundcloud.com/tracks"
        v1_params = {"q": query, "limit": 10, "linked_partitioning": 1, "client_id": SCCLIENT_ID}
        r = requests.get(v1_url, params=v1_params, headers=headers, timeout=20)

    if r.status_code != 200:
        print(f"⚠️ SC search failed {r.status_code}: {r.text[:300]}")
        return None

    data = r.json()
    items = data.get("collection") if isinstance(data, dict) else data
    if not items:
        return None

    wanted = _norm(f"{title} {artist}")
    best = None
    for it in items:
        it_title = it.get("title", "")
        it_user = (it.get("user") or {}).get("username", "")
        cand = _norm(f"{it_title} {it_user}")
        score = _score(wanted, cand)
        if not best or score > best[0]:
            best = (score, it)

    if best and best[0] >= 0.5:
        return best[1]
    return None

# ---------- Transfer ----------

def _parse_export_file(text_file: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Very forgiving parser:
    - returns (playlist_title, [(title, artist), ...])
    export_spotify_playlist usually gives us a text with "Artist - Title" or "Title - Artist".
    We’ll try both patterns per line.
    """
    tracks: List[Tuple[str, str]] = []
    playlist_title = "Imported from Spotify"

    with open(text_file, "r", encoding="utf-8", errors="ignore") as f:
        for raw in f:
            line = raw.strip()
            if not line:
                continue
            # heuristics: prefer Title - Artist if obvious
            if " - " in line:
                left, right = line.split(" - ", 1)
                # crude guess: if right looks like an artist (few tokens), assume Title - Artist
                if len(right.split()) <= 5:
                    title, artist = left, right
                else:
                    title, artist = right, left
                tracks.append((title.strip(), artist.strip()))
            else:
                # fallback: treat the whole line as title with unknown artist
                tracks.append((line, ""))

    return playlist_title, tracks

def _create_playlist(session_id: str, title: str, track_ids: List[int]) -> Optional[dict]:
    """
    Create a SoundCloud playlist with the found track IDs.
    We try JSON POST to /playlists first; some deployments still prefer form-encoded shape.
    """
    access = get_saved_token(session_id)
    if not access:
        return None
    headers = _auth_headers(access)
    url = "https://api.soundcloud.com/playlists"

    payload_json = {"playlist": {"title": title, "sharing": "private", "tracks": [{"id": tid} for tid in track_ids]}}
    r = requests.post(url, json=payload_json, headers=headers, timeout=30)

    if r.status_code == 401:
        new_access = refresh_soundcloud_token(session_id)
        if not new_access:
            return None
        headers = _auth_headers(new_access)
        r = requests.post(url, json=payload_json, headers=headers, timeout=30)

    if r.status_code in (200, 201):
        return r.json()

    # fallback: form-encoded legacy format
    form = {
        "playlist[title]": title,
        "playlist[sharing]": "private",
    }
    # playlist[tracks][][id]=123 repeated
    files = []
    for i, tid in enumerate(track_ids):
        form[f"playlist[tracks][{i}][id]"] = str(tid)

    r2 = requests.post(url, data=form, headers=headers, timeout=30)
    if r2.status_code in (200, 201):
        return r2.json()

    print(f"⚠️ SC create playlist failed: {r.status_code} {r.text[:300]} | fallback {r2.status_code} {r2.text[:300]}")
    return None

def transfer_to_soundcloud(
    text_file: str,
    session_id: str,
    token: Optional[str] = None,
    playlist_title: Optional[str] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
) -> str:
    """
    - Reads exported text file
    - Searches tracks on SoundCloud with fuzzy matching
    - Creates a new private playlist with the matches
    - Returns a user-facing summary message
    """
    if not text_file or not os.path.exists(text_file):
        return "❌ Internal error: no export file to transfer."

    # Parse export file
    inferred_title, pairs = _parse_export_file(text_file)
    title = playlist_title or inferred_title
    total = len(pairs)
    found_ids: List[int] = []
    misses: List[str] = []

    for idx, (song, artist) in enumerate(pairs, start=1):
        if progress_cb:
            progress_cb(idx - 1, total, f"Searching {idx}/{total}: {song} – {artist}")
        hit = search_soundcloud_track(session_id, song, artist)
        if hit and "id" in hit:
            found_ids.append(int(hit["id"]))
            print(f"[{int(idx/total*100)}%] ✅ Found: {song} - {artist}")
        else:
            misses.append(f"{song} - {artist}")
            print(f"[{int(idx/total*100)}%] ❌ Not found: {song} - {artist}")

    if progress_cb:
        progress_cb(total, total, "Creating SoundCloud playlist…")

    if not found_ids:
        return "❌ No matching tracks were found on SoundCloud."

    created = _create_playlist(session_id, title, found_ids)
    if not created:
        return "❌ Failed to create SoundCloud playlist (auth or API error)."

    permalink = created.get("permalink_url") or "(no link returned)"
    summary = f"✅ Transferred {len(found_ids)}/{total} tracks to SoundCloud: {permalink}"
    if misses:
        summary += f" — {len(misses)} not found."
    return summary
