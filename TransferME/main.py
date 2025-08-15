from fastapi import FastAPI, Request, Form, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from dotenv import load_dotenv
import os
import json
import requests
from urllib.parse import urlencode
from collections import defaultdict

# local modules
from helpers import ensure_session_id
from export_spotify_playlist import get_saved_spotify_token, export_spotify_playlist
from spotify_auth import ensure_spotify_token  # already in your project
# NOTE: we call into soundcloud.py functions at runtime to avoid circular imports

load_dotenv()
app = FastAPI()

# ----- ENV -----
SCCLIENT_ID = os.getenv("SCCLIENT_ID")
SCCLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
SCREDIRECT_URI = os.getenv("SCREDIRECT_URI")

SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPREDIRECT_URI")
SPOTIFY_SCOPE = (
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private"
)

# ----- Static & Templates -----
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# ----- Progress store (in-memory) -----
PROGRESS = defaultdict(lambda: {"percent": 0, "message": "Waiting…"})


def set_progress(session_id: str, percent: int, message: str):
    PROGRESS[session_id] = {
        "percent": max(0, min(100, int(percent))),
        "message": str(message),
    }


# ===== Helpers =====

def refresh_spotify_token(session_id: str):
    """One-shot manual refresh if export fails with 401 (kept for compatibility)."""
    path = f"tokens/{session_id}.json"
    if not os.path.exists(path):
        return None
    with open(path, "r") as f:
        data = json.load(f)
    rt = data.get("refresh_token")
    if not rt:
        return None
    r = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "refresh_token",
        "refresh_token": rt,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET,
    })
    if r.status_code != 200:
        print(f"⚠️ Spotify refresh failed: {r.status_code} {r.text}")
        return None
    new_tok = r.json()
    if "refresh_token" not in new_tok and "refresh_token" in data:
        new_tok["refresh_token"] = data["refresh_token"]
    with open(path, "w") as f:
        json.dump(new_tok, f)
    return new_tok.get("access_token")


def run_spotify_to_sc(session_id: str, spotify_url: str):
    """
    Background worker:
    - Ensure Spotify token (refresh if needed).
    - Export playlist to a text file.
    - Hand off to SoundCloud transfer which searches & creates playlist.
    """
    # Import inside function to avoid circulars
    import soundcloud as scmod

    # 1) Ensure Spotify is valid
    set_progress(session_id, 5, "Refreshing Spotify token…")
    token_blob = ensure_spotify_token(session_id)  # may silently refresh & save
    if not token_blob or not token_blob.get("access_token"):
        set_progress(session_id, 100, "❌ Spotify auth required. Please re-auth and retry.")
        return

    # 2) Ensure SoundCloud token exists (the module will refresh on 401 later)
    sc_token = scmod.get_saved_token(session_id)
    if not sc_token:
        set_progress(session_id, 100, "❌ SoundCloud auth required. Please re-auth and retry.")
        return

    # 3) Validate Spotify URL early
    if "open.spotify.com/playlist/" not in spotify_url:
        set_progress(session_id, 100, "❌ That doesn’t look like a Spotify playlist URL.")
        return

    # 4) Export playlist from Spotify (retry once on 401)
    set_progress(session_id, 10, "Exporting playlist from Spotify…")
    try:
        result = export_spotify_playlist(spotify_url, token=get_saved_spotify_token(session_id))
    except Exception as e:
        print(f"⚠️ export_spotify_playlist error: {e}")
        result = None

    if not result:
        set_progress(session_id, 12, "Spotify token may have expired — refreshing…")
        if refresh_spotify_token(session_id):
            try:
                result = export_spotify_playlist(spotify_url, token=get_saved_spotify_token(session_id))
            except Exception as e:
                print(f"⚠️ export retry error: {e}")
                result = None

    if (not result) or (not result[0]):
        set_progress(session_id, 100, "❌ Couldn’t export playlist (after refresh). Re-auth Spotify.")
        return

    txt_file, playlist_name = result
    set_progress(session_id, 20, f"Found playlist “{playlist_name}”. Searching on SoundCloud…")

    # 5) Transfer to SoundCloud (auto-refresh on 401, fuzzy match, v2 search)
    def per_track_progress(done: int, total: int, msg: str):
        pct = 20 + int((done / max(1, total)) * 75)  # 20%..95%
        set_progress(session_id, pct, msg)

    result_msg = scmod.transfer_to_soundcloud(
        text_file=txt_file,
        session_id=session_id,
        playlist_title=playlist_name,
        progress_cb=per_track_progress,
    )

    set_progress(session_id, 100, result_msg or "✅ Done.")


# ===== Routes =====

@app.get("/auth/spotify")
def auth_spotify(request: Request):
    session_id = ensure_session_id(request)
    params = urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SPOTIFY_SCOPE,
        "state": session_id
    })
    resp = RedirectResponse(f"https://accounts.spotify.com/authorize?{params}")
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.get("/callback_spotify")
async def spotify_callback(request: Request):
    code = request.query_params.get("code")
    session_id = request.query_params.get("state")
    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request, "message": "❌ No authorization code found."
        })

    token_response = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    })
    token_data = token_response.json()
    os.makedirs("tokens", exist_ok=True)
    with open(f"tokens/{session_id}.json", "w") as f:
        json.dump(token_data, f)

    resp = RedirectResponse(f"/?session_id={session_id}")
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.get("/auth/soundcloud")
def auth_soundcloud(request: Request):
    session_id = ensure_session_id(request)
    auth_url = (
        "https://soundcloud.com/connect?"
        f"client_id={SCCLIENT_ID}"
        f"&redirect_uri={SCREDIRECT_URI}"
        f"&response_type=code&scope=non-expiring&state={session_id}"
    )
    resp = RedirectResponse(auth_url)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.get("/callback")
async def soundcloud_callback(request: Request):
    code = request.query_params.get("code")
    session_id = request.query_params.get("state")

    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request, "message": "❌ Authorization code not found in callback."
        })

    token_response = requests.post("https://api.soundcloud.com/oauth2/token", data={
        "client_id": SCCLIENT_ID,
        "client_secret": SCCLIENT_SECRET,
        "redirect_uri": SCREDIRECT_URI,
        "grant_type": "authorization_code",
        "code": code
    })
    if token_response.status_code != 200:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": f"❌ Token exchange failed: {token_response.text}"
        })

    token_data = token_response.json()
    os.makedirs("tokens", exist_ok=True)
    with open(f"tokens/{session_id}_sc.json", "w") as f:
        json.dump(token_data, f)

    # land the user on your transfer UI with the session cookie
    resp = RedirectResponse(f"/transfer/?session_id={session_id}", status_code=303)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    session_id = request.query_params.get("session_id", "default")
    return templates.TemplateResponse("index.html", {
        "request": request, "session_id": session_id
    })


@app.get("/transfer", response_class=HTMLResponse)
async def transfer_ui(request: Request):
    sid = request.query_params.get("session_id") or ensure_session_id(request)
    resp = templates.TemplateResponse("index.html", {"request": request, "session_id": sid})
    resp.set_cookie("session_id", sid, httponly=True, samesite="lax")
    return resp


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    session_id = request.query_params.get("session_id") or request.cookies.get("session_id") or "default"
    return templates.TemplateResponse("status.html", {"request": request, "session_id": session_id})


@app.get("/progress")
def get_progress(session_id: str):
    return JSONResponse(PROGRESS.get(session_id, {"percent": 0, "message": "Waiting…"}))


@app.post("/transfer/spotify-to-soundcloud")
async def spotify_to_soundcloud(
    request: Request,
    background_tasks: BackgroundTasks,
    spotify_url: str = Form(...),
    session_id: str = Form(""),
):
    if not session_id:
        session_id = request.cookies.get("session_id") or ensure_session_id(request)

    set_progress(session_id, 0, "Queued…")
    background_tasks.add_task(run_spotify_to_sc, session_id, spotify_url)

    resp = RedirectResponse(f"/status?session_id={session_id}", status_code=303)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.post("/transfer/soundcloud-to-spotify")
async def soundcloud_to_spotify(
    request: Request,
    soundcloud_url: str = Form(...),
    session_id: str = Form(...),
):
    # unchanged logic from your previous code path
    from export_soundcloud_playlist import export_soundcloud_playlist
    from spotify import transfer_to_spotify
    import soundcloud as scmod

    sc_token = scmod.get_saved_token(session_id)
    spotify_token = get_saved_spotify_token(session_id)

    if not spotify_token:
        return RedirectResponse("/auth/spotify", status_code=302)
    if not sc_token:
        return RedirectResponse("/auth/soundcloud", status_code=302)

    txt_file, name = export_soundcloud_playlist(soundcloud_url, sc_token)
    result = transfer_to_spotify(txt_file, session_id)
    return templates.TemplateResponse("result.html", {"request": request, "message": result})

@app.get("/result", response_class=HTMLResponse)
async def result_page(request: Request):
    session_id = (
        request.query_params.get("session_id")
        or request.cookies.get("session_id")
        or "default"
    )
    data = PROGRESS.get(session_id, {"percent": 0, "message": "Waiting…"})
    return templates.TemplateResponse(
        "result.html",
        {"request": request, "message": data.get("message", "Done.")}
    )