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

load_dotenv()
app = FastAPI()

# ENV config
CLIENT_ID = os.getenv("SCCLIENT_ID")
CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
REDIRECT_URI = os.getenv("SCREDIRECT_URI")
TOKEN_FILE = os.getenv("SCTOKEN_FILE", "soundcloud_token.json")
SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_REDIRECT_URI = os.getenv("SPREDIRECT_URI")
SPOTIFY_SCOPE = "playlist-read-private playlist-read-collaborative playlist-modify-public playlist-modify-private"
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SPOTIFY_TOKEN_FILE = "spotify_token.json"

# Static & Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/auth/spotify")
def auth_spotify():
    params = urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": SPOTIFY_SCOPE,
    })
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{params}")

@app.get("/auth/soundcloud")
def auth_soundcloud():
    auth_url = (
        f"https://soundcloud.com/connect?"
        f"client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        f"&response_type=code&scope=non-expiring"
    )
    return RedirectResponse(auth_url)

@app.get("/callback")
async def soundcloud_callback(request: Request):
    code = request.query_params.get("code")
    redirect_to = request.query_params.get("redirect_to", "/")
    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ Authorization code not found in callback."
        })

    token_response = requests.post("https://api.soundcloud.com/oauth2/token", data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': REDIRECT_URI,
        'grant_type': 'authorization_code',
        'code': code
    })

    if token_response.status_code != 200:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": f"❌ Token exchange failed: {token_response.text}"
        })

    # ✅ Save token to file
    token_data = token_response.json()
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f)

    return RedirectResponse(redirect_to)

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/transfer/spotify-to-soundcloud")
async def spotify_to_soundcloud(request: Request, spotify_url: str = Form(...)):
    from export_spotify_playlist import export_spotify_playlist
    from soundcloud import transfer_to_soundcloud, get_saved_token

    sc_token = get_saved_token()
    spotify_token = get_saved_spotify_token()

    if not spotify_token:
        return RedirectResponse("/auth/spotify", status_code=302)
    if not sc_token:
        return RedirectResponse("/auth/soundcloud", status_code=302)

    txt_file, name = export_spotify_playlist(spotify_url, token=spotify_token)
    result = transfer_to_soundcloud(txt_file, token=sc_token)

    return templates.TemplateResponse("result.html", {"request": request, "message": result})


@app.post("/transfer/soundcloud-to-spotify")
async def soundcloud_to_spotify(request: Request, soundcloud_url: str = Form(...)):
    from export_soundcloud_playlist import export_soundcloud_playlist
    from spotify import transfer_to_spotify
    from soundcloud import get_saved_token

    token = get_saved_token()
    if not token:
        return RedirectResponse("/auth/soundcloud", status_code=302)

    txt_file, name = export_soundcloud_playlist(soundcloud_url, token)
    result = transfer_to_spotify(txt_file)

    return templates.TemplateResponse("result.html", {"request": request, "message": result})


@app.get("/callback_spotify")
async def spotify_callback(request: Request):
    code = request.query_params.get("code")
    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ No code provided in callback."
        })

    token_response = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    })

    if token_response.status_code != 200:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": f"❌ Failed to get token: {token_response.text}"
        })

    with open(SPOTIFY_TOKEN_FILE, "w") as f:
        json.dump(token_response.json(), f)

    return RedirectResponse("/")