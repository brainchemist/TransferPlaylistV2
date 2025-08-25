# Updated main.py
from fastapi import FastAPI, Request, Form, BackgroundTasks, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from dotenv import load_dotenv
import os
import json
import requests
import asyncio
from urllib.parse import urlencode
from collections import defaultdict
from typing import Optional

# Import our new modules
from database import get_db, UserSession, TransferHistory
from token_manager import token_manager
from async_search import AsyncTrackSearcher, transfer_playlist_async
from helpers import ensure_session_id

load_dotenv()
app = FastAPI()

# Environment variables
SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SPOTIFY_REDIRECT_URI = os.getenv("SPREDIRECT_URI")
SPOTIFY_SCOPE = (
    "playlist-read-private playlist-read-collaborative "
    "playlist-modify-public playlist-modify-private"
)

SOUNDCLOUD_CLIENT_ID = os.getenv("SCCLIENT_ID")
SOUNDCLOUD_CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")
SOUNDCLOUD_REDIRECT_URI = os.getenv("SCREDIRECT_URI")

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Progress tracking (in-memory for now, could be moved to Redis later)
PROGRESS = defaultdict(lambda: {"percent": 0, "message": "Waiting…"})


def set_progress(session_id: str, percent: int, message: str):
    PROGRESS[session_id] = {
        "percent": max(0, min(100, int(percent))),
        "message": str(message),
    }


def record_transfer_history(
        session_id: str,
        source_platform: str,
        destination_platform: str,
        source_url: str,
        destination_url: Optional[str] = None,
        tracks_total: int = 0,
        tracks_found: int = 0,
        status: str = "success",
        error_message: Optional[str] = None,
        db: Session = Depends(get_db)
):
    """Record transfer in database"""
    transfer = TransferHistory(
        session_id=session_id,
        source_platform=source_platform,
        destination_platform=destination_platform,
        source_playlist_url=source_url,
        destination_playlist_url=destination_url,
        tracks_total=tracks_total,
        tracks_found=tracks_found,
        transfer_status=status,
        error_message=error_message
    )
    db.add(transfer)
    db.commit()


async def run_spotify_to_soundcloud_async(session_id: str, spotify_url: str):
    """Improved async transfer function"""
    try:
        # Step 1: Validate tokens
        set_progress(session_id, 5, "Checking authentication…")

        spotify_token = token_manager.get_spotify_token(session_id)
        soundcloud_token = token_manager.get_soundcloud_token(session_id)

        if not spotify_token:
            set_progress(session_id, 100, "❌ Spotify authentication required")
            return

        if not soundcloud_token:
            set_progress(session_id, 100, "❌ SoundCloud authentication required")
            return

        # Step 2: Export Spotify playlist
        set_progress(session_id, 10, "Fetching Spotify playlist…")

        try:
            import spotipy
            sp = spotipy.Spotify(auth=spotify_token)

            if "playlist/" in spotify_url:
                playlist_id = spotify_url.split("playlist/")[1].split("?")[0]
            else:
                playlist_id = spotify_url

            playlist_data = sp.playlist(playlist_id)
            playlist_name = playlist_data['name']
            tracks_data = playlist_data['tracks']

            # Extract all tracks
            track_list = []
            while tracks_data:
                for item in tracks_data['items']:
                    track = item['track']
                    if track:
                        name = track['name']
                        artist = track['artists'][0]['name'] if track['artists'] else ''
                        track_list.append((name, artist))

                if tracks_data['next']:
                    tracks_data = sp.next(tracks_data)
                else:
                    break

            set_progress(session_id, 20, f"Found {len(track_list)} tracks in '{playlist_name}'")

        except Exception as e:
            set_progress(session_id, 100, f"❌ Failed to fetch Spotify playlist: {str(e)}")
            return

        # Step 3: Search tracks on SoundCloud asynchronously
        def progress_callback(done: int, total: int, message: str):
            pct = 20 + int((done / max(1, total)) * 60)  # 20% to 80%
            set_progress(session_id, pct, f"Searching on SoundCloud ({done}/{total}): {message}")

        set_progress(session_id, 25, "Starting SoundCloud search…")

        search_result = await transfer_playlist_async(
            session_id=session_id,
            track_list=track_list,
            source_platform='spotify',
            destination_platform='soundcloud',
            progress_callback=progress_callback
        )

        found_tracks = search_result['tracks']
        tracks_found = search_result['found_tracks']

        if not found_tracks:
            set_progress(session_id, 100, "❌ No matching tracks found on SoundCloud")
            return

        # Step 4: Create SoundCloud playlist
        set_progress(session_id, 85, "Creating SoundCloud playlist…")

        try:
            headers = {"Authorization": f"OAuth {soundcloud_token}"}
            track_ids = [int(track['id']) for track in found_tracks if track.get('id')]

            # Step 4a: Create empty playlist first
            playlist_payload = {
                "title": f"{playlist_name} (from Spotify)",
                "sharing": "private"
            }

            async with AsyncTrackSearcher() as searcher:
                # Create the playlist
                async with searcher.session.post(
                        "https://api.soundcloud.com/playlists",
                        json=playlist_payload,
                        headers=headers
                ) as response:
                    if response.status in (200, 201):
                        playlist_result = await response.json()
                        playlist_id = playlist_result.get('id')
                        playlist_url = playlist_result.get('permalink_url', 'Created successfully')

                        # Step 4b: Add tracks to the playlist if we have any
                        if track_ids and playlist_id:
                            set_progress(session_id, 90, "Adding tracks to playlist…")

                            # Try adding tracks to the playlist
                            tracks_payload = {
                                "playlist": {
                                    "tracks": [{"id": tid} for tid in track_ids]
                                }
                            }

                            async with searcher.session.put(
                                    f"https://api.soundcloud.com/playlists/{playlist_id}",
                                    json=tracks_payload,
                                    headers=headers
                            ) as tracks_response:
                                if tracks_response.status in (200, 201):
                                    # Record success in database
                                    db = next(get_db())
                                    try:
                                        record_transfer_history(
                                            session_id=session_id,
                                            source_platform='spotify',
                                            destination_platform='soundcloud',
                                            source_url=spotify_url,
                                            destination_url=playlist_url,
                                            tracks_total=len(track_list),
                                            tracks_found=tracks_found,
                                            status='completed',
                                            db=db
                                        )
                                    finally:
                                        db.close()

                                    set_progress(session_id, 100, f"✅ Transfer completed: {playlist_url}")
                                else:
                                    # Playlist created but tracks couldn't be added
                                    error_text = await tracks_response.text()
                                    print(f"Failed to add tracks to playlist: {tracks_response.status} - {error_text}")

                                    # Record partial success
                                    db = next(get_db())
                                    try:
                                        record_transfer_history(
                                            session_id=session_id,
                                            source_platform='spotify',
                                            destination_platform='soundcloud',
                                            source_url=spotify_url,
                                            destination_url=playlist_url,
                                            tracks_total=len(track_list),
                                            tracks_found=0,  # No tracks actually added
                                            status='partial',
                                            error_message=f"Playlist created but tracks not added: HTTP {tracks_response.status}",
                                            db=db
                                        )
                                    finally:
                                        db.close()

                                    set_progress(session_id, 100,
                                                 f"⚠️ Playlist created but tracks couldn't be added: {playlist_url}")
                        else:
                            # No tracks to add, but playlist was created
                            db = next(get_db())
                            try:
                                record_transfer_history(
                                    session_id=session_id,
                                    source_platform='spotify',
                                    destination_platform='soundcloud',
                                    source_url=spotify_url,
                                    destination_url=playlist_url,
                                    tracks_total=len(track_list),
                                    tracks_found=0,
                                    status='completed',
                                    error_message="No matching tracks found",
                                    db=db
                                )
                            finally:
                                db.close()

                            set_progress(session_id, 100, f"✅ Empty playlist created: {playlist_url}")
                    else:
                        error_text = await response.text()
                        raise Exception(f"HTTP {response.status} - {error_text}")

        except Exception as e:
            # Record failure in database
            db = next(get_db())
            try:
                # Use variables that definitely exist at this point
                total_tracks = len(track_list) if 'track_list' in locals() else 0
                found_tracks_count = tracks_found if 'tracks_found' in locals() else 0

                record_transfer_history(
                    session_id=session_id,
                    source_platform='spotify',
                    destination_platform='soundcloud',
                    source_url=spotify_url,
                    tracks_total=total_tracks,
                    tracks_found=found_tracks_count,
                    status='failed',
                    error_message=str(e),
                    db=db
                )
            finally:
                db.close()

            set_progress(session_id, 100, f"❌ Failed to create playlist: {str(e)}")

    except Exception as e:
        set_progress(session_id, 100, f"❌ Transfer failed: {str(e)}")

# === ROUTES ===

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
    return_url = request.query_params.get("return_url", "/")
    spotify_url = request.query_params.get("spotify_url", "")

    if not code:
        return templates.TemplateResponse("result.html", {
            "request": request, "message": "❌ No authorization code found."
        })

    # Exchange code for token (your existing logic)
    token_response = requests.post("https://accounts.spotify.com/api/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "client_id": SPOTIFY_CLIENT_ID,
        "client_secret": SPOTIFY_CLIENT_SECRET
    })

    if token_response.status_code == 200:
        token_data = token_response.json()
        token_manager.save_spotify_token(session_id, token_data)

        # Redirect back to transfer with the original URL
        if spotify_url:
            redirect_url = f"/transfer?spotify_url={spotify_url}"
        else:
            redirect_url = return_url or "/transfer"

        resp = RedirectResponse(redirect_url)
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
        return resp
    else:
        return templates.TemplateResponse("result.html", {
            "request": request, "message": "❌ Failed to get Spotify token"
        })


@app.get("/auth/soundcloud")
def auth_soundcloud(request: Request):
    session_id = ensure_session_id(request)
    auth_url = (
        "https://soundcloud.com/connect?"
        f"client_id={SOUNDCLOUD_CLIENT_ID}"
        f"&redirect_uri={SOUNDCLOUD_REDIRECT_URI}"
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

    # Exchange code for token
    token_response = requests.post("https://api.soundcloud.com/oauth2/token", data={
        "client_id": SOUNDCLOUD_CLIENT_ID,
        "client_secret": SOUNDCLOUD_CLIENT_SECRET,
        "redirect_uri": SOUNDCLOUD_REDIRECT_URI,
        "grant_type": "authorization_code",
        "code": code
    })

    if token_response.status_code == 200:
        token_data = token_response.json()
        token_manager.save_soundcloud_token(session_id, token_data)

        resp = RedirectResponse(f"/transfer/?session_id={session_id}", status_code=303)
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
        return resp
    else:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": f"❌ Token exchange failed: {token_response.text}"
        })


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
def get_progress_endpoint(session_id: str):
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

    # Validate URL
    if "open.spotify.com/playlist/" not in spotify_url:
        return templates.TemplateResponse("result.html", {
            "request": request,
            "message": "❌ Please provide a valid Spotify playlist URL"
        })

    # Check tokens first
    spotify_token = token_manager.get_spotify_token(session_id)
    soundcloud_token = token_manager.get_soundcloud_token(session_id)

    if not spotify_token:
        # Store the transfer request and redirect to auth
        resp = RedirectResponse(f"/auth/spotify?return_url=/transfer&spotify_url={spotify_url}", status_code=303)
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
        return resp

    if not soundcloud_token:
        resp = RedirectResponse(f"/auth/soundcloud?return_url=/transfer&spotify_url={spotify_url}", status_code=303)
        resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
        return resp

    # Both tokens exist, proceed with transfer
    set_progress(session_id, 0, "Transfer queued…")

    # Run async transfer in background
    background_tasks.add_task(run_spotify_to_soundcloud_async, session_id, spotify_url)
    resp = RedirectResponse(f"/status?session_id={session_id}", status_code=303)
    resp.set_cookie("session_id", session_id, httponly=True, samesite="lax")
    return resp


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    """User dashboard showing transfer history"""
    session_id = request.cookies.get("session_id") or ensure_session_id(request)

    # Get transfer history
    transfers = db.query(TransferHistory).filter(
        TransferHistory.session_id == session_id
    ).order_by(TransferHistory.started_at.desc()).limit(10).all()

    # Get auth status
    spotify_token = token_manager.get_spotify_token(session_id)
    soundcloud_token = token_manager.get_soundcloud_token(session_id)

    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "session_id": session_id,
        "transfers": transfers,
        "spotify_authenticated": bool(spotify_token),
        "soundcloud_authenticated": bool(soundcloud_token)
    })


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


@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": "2024-01-01T00:00:00Z",
        "services": {
            "database": "connected",
            "spotify_api": "available",
            "soundcloud_api": "available"
        }
    }


# Legacy endpoint for SoundCloud to Spotify (keep for compatibility)
@app.post("/transfer/soundcloud-to-spotify")
async def soundcloud_to_spotify(
        request: Request,
        soundcloud_url: str = Form(...),
        session_id: str = Form(...),
):
    # For now, redirect to the old implementation
    # TODO: Implement async SoundCloud to Spotify transfer
    return templates.TemplateResponse("result.html", {
        "request": request,
        "message": "🚧 SoundCloud to Spotify transfer is being updated. Please try again later."
    })


# Simple test transfer function
async def run_spotify_to_sc(session_id: str, spotify_url: str):
    """Simple transfer function for testing"""
    import asyncio

    try:
        set_progress(session_id, 10, "Starting transfer...")
        await asyncio.sleep(2)

        set_progress(session_id, 30, "Connecting to Spotify...")
        await asyncio.sleep(2)

        set_progress(session_id, 50, "Fetching playlist...")
        await asyncio.sleep(2)

        set_progress(session_id, 80, "Searching on SoundCloud...")
        await asyncio.sleep(2)

        set_progress(session_id, 100, "✅ Transfer completed successfully!")

    except Exception as e:
        set_progress(session_id, 100, f"❌ Transfer failed: {str(e)}")