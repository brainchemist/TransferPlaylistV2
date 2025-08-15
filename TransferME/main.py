from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import os
import json
import requests
from urllib.parse import urlencode
from export_spotify_playlist import get_saved_spotify_token
from helpers import ensure_session_id
from collections import defaultdict
from fastapi import BackgroundTasks
import time

from spotify_auth import ensure_spotify_token

load_dotenv()
app = FastAPI()

# ENV config
SCCLIENT_ID = os.getenv("SCCLIENT_ID")
SCCLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
SCREDIRECT_URI = os.getenv("SCREDIRECT_URI")
TOKEN_FILE = os.getenv("SCTOKEN_FILE", "soundcloud_token.json")
SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_REDIRECT_URI = os.getenv("SPREDIRECT_URI")
SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SPOTIFY_TOKEN_FILE = "spotify_token.json"

# Static & Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")


PROGRESS = defaultdict(lambda: {"percent": 0, "message": "Waiting…"})

def set_progress(session_id: str, percent: int, message: str):
    PROGRESS[session_id] = {"percent": max(0, min(100, percent)), "message": message}


def run_spotify_to_sc(session_id: str, spotify_url: str):
    from export_spotify_playlist import export_spotify_playlist, get_saved_spotify_token
    from soundcloud import transfer_to_soundcloud, get_saved_token
    # add this import
    from main import refresh_soundcloud_token  # or wherever you placed it

    set_progress(session_id, 5, "Refreshing Spotify token…")
    token = ensure_spotify_token(session_id)
    if not token:
        set_progress(session_id, 100, "❌ Spotify auth required (token expired). Please re-auth and retry.")
        return

    # —— SoundCloud token handling ——
    sc_token = get_saved_token(session_id)
    if not sc_token:
        set_progress(session_id, 100, "❌ SoundCloud auth needed. Please re-auth.")
        return

    # If we have a refresh_token, refresh proactively
    try:
        with open(f"tokens/{session_id}_sc.json") as f:
            sc_data = json.load(f)
    except Exception:
        sc_data = {}

    if sc_data.get("refresh_token"):
        set_progress(session_id, 6, "Refreshing SoundCloud token…")
        new_sc = refresh_soundcloud_token(session_id)
        if new_sc:  # replace the bearer we’ll pass down
            sc_token = new_sc

    # (optional) quick sanity check against /me; if 401, ask for re-auth
    # resp = requests.get("https://api.soundcloud.com/me", headers={"Authorization": f"OAuth {sc_token}"})
    # if resp.status_code == 401:
    #     set_progress(session_id, 100, "❌ SoundCloud session expired. Please re-auth.")
    #     return

    sp_token = get_saved_spotify_token(session_id)

    set_progress(session_id, 10, "Exporting playlist from Spotify…")
    try:
        result = export_spotify_playlist(spotify_url, token=sp_token)
    except Exception:
        result = None

    if not result:
        set_progress(session_id, 12, "Spotify token may have expired — refreshing…")
        if refresh_spotify_token(session_id):
            sp_token = get_saved_spotify_token(session_id)
            try:
                result = export_spotify_playlist(spotify_url, token=sp_token)
            except Exception:
                result = None

    if not result:
        set_progress(session_id, 100, "❌ Couldn’t export playlist (after refresh). Re-auth Spotify.")
        return

    txt_file, name = result
    set_progress(session_id, 20, f"Found playlist “{name}”. Searching tracks on SoundCloud…")

    result_msg = transfer_to_soundcloud(txt_file, token=sc_token)
    set_progress(session_id, 100, result_msg or "✅ Done.")




@app.get("/auth/spotify")
def auth_spotify(request: Request):
    session_id = ensure_session_id(request)
    print(f"Auth SP using session_id: {session_id}")

    redirect_uri = SPOTIFY_REDIRECT_URI
    params = urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SPOTIFY_SCOPE,
        "state": session_id
    })
    resp = RedirectResponse(f"https://accounts.spotify.com/authorize?{params}")
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp

@app.get("/auth/soundcloud")
def auth_soundcloud(request: Request):
    session_id = ensure_session_id(request)
    print(f"Auth SC using session_id: {session_id}")

    redirect_uri_with_session = SCREDIRECT_URI
    auth_url = (
        "https://soundcloud.com/connect?"
        f"client_id={SCCLIENT_ID}&redirect_uri={redirect_uri_with_session}"
        f"&response_type=code&scope=non-expiring&state={session_id}"
    )
    resp = RedirectResponse(auth_url)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp

@app.get("/callback")
async def soundcloud_callback(request: Request):
    # Get the code and session_id (from state)
    code = request.query_params.get("code")
    session_id = request.query_params.get("state")

    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ Authorization code not found in callback."
        })

    # Proceed to exchange the code for an access token
    token_response = requests.post("https://api.soundcloud.com/oauth2/token", data={
        'client_id': SCCLIENT_ID,
        'client_secret': SCCLIENT_SECRET,
        'redirect_uri': f"{SCREDIRECT_URI}",  # Same callback URL
        'grant_type': 'authorization_code',
        'code': code
    })

    if token_response.status_code != 200:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": f"❌ Token exchange failed: {token_response.text}"
        })

    # Save the token to the session-based file
    token_data = token_response.json()
    os.makedirs("tokens", exist_ok=True)
    with open(f"tokens/{session_id}_sc.json", "w") as f:
        json.dump(token_data, f)

    resp = RedirectResponse(f"/transfer/?session_id={session_id}", status_code=303)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    session_id = request.query_params.get("session_id", "default")
    print(f"Received session_id: {session_id}")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "session_id": session_id
    })

from fastapi.responses import JSONResponse

@app.get("/progress")
def get_progress(session_id: str):
    return JSONResponse(PROGRESS.get(session_id, {"percent": 0, "message": "Waiting…"}))

@app.get("/transfer", response_class=HTMLResponse)
async def transfer_ui(request: Request):
    sid = request.query_params.get("session_id") or ensure_session_id(request)
    resp = templates.TemplateResponse("index.html", {"request": request, "session_id": sid})
    resp.set_cookie("session_id", sid, httponly=True, samesite="lax")
    return resp


@app.post("/transfer/spotify-to-soundcloud")
async def spotify_to_soundcloud(request: Request,
                                background_tasks: BackgroundTasks,
                                spotify_url: str = Form(...),
                                session_id: str = Form("")):
    if not session_id:
        session_id = request.cookies.get("session_id") or ensure_session_id(request)

    # kick the job to the background and bounce user to the status page
    set_progress(session_id, 0, "Queued…")
    background_tasks.add_task(run_spotify_to_sc, session_id, spotify_url)

    resp = RedirectResponse(f"/transfer/status?session_id={session_id}", status_code=303)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.get("/status", response_class=HTMLResponse)
async def status_page(request: Request):
    session_id = request.query_params.get("session_id") or request.cookies.get("session_id") or "default"
    return templates.TemplateResponse("status.html", {"request": request, "session_id": session_id})


@app.post("/transfer/soundcloud-to-spotify")
async def soundcloud_to_spotify(request: Request, soundcloud_url: str = Form(...), session_id: str = Form(...)):
    from export_soundcloud_playlist import export_soundcloud_playlist
    from spotify import transfer_to_spotify
    from soundcloud import get_saved_token

    print(f"Received session_id: {session_id}")
    try:
        current_directory = os.getcwd()
        files_in_directory = os.listdir(f"{current_directory}/tokens")
        print(f"Current directory: {current_directory}")
        print(f"Files in directory: {files_in_directory}")

    except FileNotFoundError:
        print(f"Not yet.")

    sc_token = get_saved_token(session_id)
    spotify_token = get_saved_spotify_token(session_id)

    if not spotify_token:
        return RedirectResponse("/auth/spotify", status_code=302)
    if not sc_token:
        return RedirectResponse("/auth/soundcloud", status_code=302)

    txt_file, name = export_soundcloud_playlist(soundcloud_url, sc_token)
    print("Export result:", txt_file, name)
    result = transfer_to_spotify(txt_file, session_id)

    return templates.TemplateResponse("result.html", {"request": request, "message": result})


@app.get("/callback_spotify")
async def spotify_callback(request: Request):
    code = request.query_params.get("code")
    session_id = request.query_params.get("state")  # Get session_id from state parameter

    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ No authorization code found."
        })

    token_response = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": f"{SPOTIFY_REDIRECT_URI}",
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


def refresh_spotify_token(session_id: str):
    path = f"tokens/{session_id}.json"
    if not os.path.exists(path):
        return None
    with open(path) as f:
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
        return None
    new_tok = r.json()
    # keep old refresh_token if Spotify doesn’t return a new one
    if "refresh_token" not in new_tok and "refresh_token" in data:
        new_tok["refresh_token"] = data["refresh_token"]
    with open(path, "w") as f:
        json.dump(new_tok, f)
    return new_tok.get("access_token")

def refresh_soundcloud_token(session_id: str):
    path = f"tokens/{session_id}_sc.json"
    if not os.path.exists(path):
        return None

    with open(path) as f:
        data = json.load(f)

    rt = data.get("refresh_token")
    if not rt:
        return None

    r = requests.post(
        "https://api.soundcloud.com/oauth2/token",
        data={
            "grant_type": "refresh_token",
            "refresh_token": rt,
            "client_id": SCCLIENT_ID,
            "client_secret": SCCLIENT_SECRET,
        },
    )

    if r.status_code != 200:
        print(f"⚠️ Failed to refresh SoundCloud token: {r.status_code} {r.text}")
        return None

    new_tok = r.json()

    # Keep the old refresh_token if SoundCloud doesn't send a new one
    if "refresh_token" not in new_tok and "refresh_token" in data:
        new_tok["refresh_token"] = data["refresh_token"]

    with open(path, "w") as f:
        json.dump(new_tok, f)

    return new_tok.get("access_token")