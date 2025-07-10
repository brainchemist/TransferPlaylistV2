from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from dotenv import load_dotenv
import os
import json
import requests

load_dotenv()
app = FastAPI()

# ENV config
CLIENT_ID = os.getenv("SCCLIENT_ID")
CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
REDIRECT_URI = os.getenv("SCREDIRECT_URI")
TOKEN_FILE = os.getenv("SCTOKEN_FILE", "soundcloud_token.json")

# Static & Templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/auth/soundcloud")
def auth_soundcloud():
    auth_url = (
        f"https://soundcloud.com/connect?"
        f"client_id={CLIENT_ID}&redirect_uri={REDIRECT_URI}"
        f"&response_type=code&scope=non-expiring"
    )
    return RedirectResponse(auth_url)

@app.get("/soundcloud/callback")
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

    token = get_saved_token()
    if not token:
        return RedirectResponse("/auth/soundcloud", status_code=302)

    txt_file, name = export_spotify_playlist(spotify_url)
    result = transfer_to_soundcloud(txt_file, token=token)

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
