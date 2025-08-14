# spotify_auth.py
import os, json, time, requests

SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SPOTIFY_TOKEN_DIR = "tokens"

def _token_path(session_id: str) -> str:
    os.makedirs(SPOTIFY_TOKEN_DIR, exist_ok=True)
    return os.path.join(SPOTIFY_TOKEN_DIR, f"{session_id}.json")

def load_spotify_token(session_id: str) -> dict | None:
    try:
        with open(_token_path(session_id), "r") as f:
            return json.load(f)
    except FileNotFoundError:
        return None

def save_spotify_token(session_id: str, data: dict) -> None:
    # Spotify returns expires_in (seconds). Track absolute expiry.
    now = int(time.time())
    data.setdefault("refresh_token", data.get("refresh_token"))  # keep old if missing
    data["obtained_at"] = now
    data["expires_at"] = now + int(data.get("expires_in", 3600)) - 60  # refresh 1 min early
    with open(_token_path(session_id), "w") as f:
        json.dump(data, f)

def ensure_spotify_token(session_id: str) -> dict | None:
    tok = load_spotify_token(session_id)
    if not tok:
        return None
    if int(time.time()) < int(tok.get("expires_at", 0)):
        return tok  # still valid

    # Need refresh
    refresh_token = tok.get("refresh_token")
    if not refresh_token:
        return None

    resp = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": SPOTIFY_CLIENT_ID,
            "client_secret": SPOTIFY_CLIENT_SECRET,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        return None

    new_tok = resp.json()
    # If Spotify omits refresh_token in refresh responses, reuse the old one
    if "refresh_token" not in new_tok:
        new_tok["refresh_token"] = refresh_token

    save_spotify_token(session_id, new_tok)
    return new_tok
