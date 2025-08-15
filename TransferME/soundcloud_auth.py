# soundcloud_auth.py
import os, json, time, requests
from dotenv import load_dotenv
load_dotenv()

SCCLIENT_ID = os.getenv("SCCLIENT_ID")
SCCLIENT_SECRET = os.getenv("SCCLIENT_SECRET")

TOKEN_FMT = "tokens/{session_id}_sc.json"

def _load(session_id):
    p = TOKEN_FMT.format(session_id=session_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)

def _save(session_id, data):
    os.makedirs("tokens", exist_ok=True)
    with open(TOKEN_FMT.format(session_id=session_id), "w") as f:
        json.dump(data, f)

def ensure_soundcloud_token(session_id):
    """
    Return a valid SC token blob (dict). If expired and refresh_token exists,
    refresh it and persist the new blob. Returns None if we cannot refresh.
    """
    data = _load(session_id)
    if not data:
        return None

    now = int(time.time())
    created = int(data.get("created_at") or 0)
    expires_in = int(data.get("expires_in") or 0)

    # If SC gave us expiry data, proactively refresh 60s early
    if expires_in and created and now > (created + expires_in - 60):
        rt = data.get("refresh_token")
        if not rt:
            return None  # can’t refresh; user must re-auth SC

        r = requests.post("https://api.soundcloud.com/oauth2/token", data={
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": SCCLIENT_ID,
            "client_secret": SCCLIENT_SECRET,
        })
        if r.status_code != 200:
            return None

        new_tok = r.json()
        # keep old refresh_token if SC doesn’t return a new one
        if "refresh_token" not in new_tok and "refresh_token" in data:
            new_tok["refresh_token"] = data["refresh_token"]
        new_tok.setdefault("created_at", now)
        _save(session_id, new_tok)
        return new_tok

    # No expiry info? Just return what we have.
    return data
