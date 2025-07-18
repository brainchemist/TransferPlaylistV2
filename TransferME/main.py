from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import os
import json
import requests
from urllib.parse import urlencode
from uuid import uuid4
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
    session_id = str(uuid4())
    print(f"Received SP session_id: {session_id}")
    redirect_uri = f"{SPOTIFY_REDIRECT_URI}"
    params = urlencode({
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "scope": SPOTIFY_SCOPE,
        "state": session_id  # Ensuring state matches the session_id
    })
    return RedirectResponse(f"https://accounts.spotify.com/authorize?{params}")

@app.get("/auth/soundcloud")
def auth_soundcloud():
    session_id = str(uuid4())  # Generate session ID
    print(f"Received SC session_id: {session_id}")

    # Use the correct redirect URI for SoundCloud
    redirect_uri_with_session = f"{REDIRECT_URI}"  # No session_id in redirect_uri

    auth_url = (
        f"https://soundcloud.com/connect?"
        f"client_id={CLIENT_ID}&redirect_uri={redirect_uri_with_session}&response_type=code&scope=non-expiring&state={session_id}"
    )

    return RedirectResponse(auth_url)


@app.get("/callback")
async def soundcloud_callback(request: Request):
    # Get the code and session_id (from state)
    code = request.query_params.get("code")
    session_id = request.query_params.get("state")  # The session_id is now passed in the `state` parameter

    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ Authorization code not found in callback."
        })

    # Proceed to exchange the code for an access token
    token_response = requests.post("https://api.soundcloud.com/oauth2/token", data={
        'client_id': CLIENT_ID,
        'client_secret': CLIENT_SECRET,
        'redirect_uri': f"{REDIRECT_URI}",  # Same callback URL
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

    # Redirect back to the homepage with the session_id
    return RedirectResponse(f"/?session_id={session_id}")

@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    session_id = request.query_params.get("session_id", "default")
    print(f"Received session_id: {session_id}")
    return templates.TemplateResponse("index.html", {
        "request": request,
        "session_id": session_id
    })

@app.post("/transfer/spotify-to-soundcloud")
async def spotify_to_soundcloud(request: Request, spotify_url: str = Form(...), session_id: str = Form(...)):
    from export_spotify_playlist import export_spotify_playlist
    from soundcloud import transfer_to_soundcloud, get_saved_token

    print(f"Received session_id: {session_id}")

    sc_token = get_saved_token(session_id)
    spotify_token = get_saved_spotify_token(session_id)

    if not spotify_token:
        return RedirectResponse("/auth/spotify", status_code=302)
    if not sc_token:
        return RedirectResponse("/auth/soundcloud", status_code=302)

    result = export_spotify_playlist(spotify_url, token=spotify_token)
    print("Export result:", result)

    if result is None:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ Could not export playlist. Please check the Spotify link or token."
        })

    txt_file, name = result
    result = transfer_to_soundcloud(txt_file, token=sc_token)

    return templates.TemplateResponse("result.html", {"request": request, "message": result})


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

    return RedirectResponse(f"/?session_id={session_id}")  # Redirect with the session_id

