# token_manager.py
import os
import time
import requests
from datetime import datetime, timedelta
from sqlalchemy.orm import Session
from database import get_db, UserSession
from typing import Optional, Dict

SPOTIFY_CLIENT_ID = os.getenv("SPCLIENT_ID")
SPOTIFY_CLIENT_SECRET = os.getenv("SPCLIENT_SECRET")
SOUNDCLOUD_CLIENT_ID = os.getenv("SCCLIENT_ID")
SOUNDCLOUD_CLIENT_SECRET = os.getenv("SCCLIENT_SECRET")

class TokenManager:
    def __init__(self):
        pass

    def save_spotify_token(self, session_id: str, token_data: Dict) -> None:
        """Save Spotify token to database"""
        db = next(get_db())
        try:
            now = datetime.utcnow()
            expires_in = token_data.get("expires_in", 3600)
            expires_at = now + timedelta(seconds=expires_in - 60)  # Refresh 1 min early
            
            user_session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
            if not user_session:
                user_session = UserSession(session_id=session_id)
                db.add(user_session)
            
            user_session.spotify_access_token = token_data.get("access_token")
            user_session.spotify_refresh_token = token_data.get("refresh_token")
            user_session.spotify_expires_at = expires_at
            user_session.last_activity = now
            
            db.commit()
        finally:
            db.close()

    def save_soundcloud_token(self, session_id: str, token_data: Dict) -> None:
        """Save SoundCloud token to database"""
        db = next(get_db())
        try:
            now = datetime.utcnow()
            expires_in = token_data.get("expires_in", 3600)
            expires_at = now + timedelta(seconds=expires_in - 60) if expires_in else None
            
            user_session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
            if not user_session:
                user_session = UserSession(session_id=session_id)
                db.add(user_session)
            
            user_session.soundcloud_access_token = token_data.get("access_token")
            user_session.soundcloud_refresh_token = token_data.get("refresh_token")
            user_session.soundcloud_expires_at = expires_at
            user_session.last_activity = now
            
            db.commit()
        finally:
            db.close()

    def get_spotify_token(self, session_id: str) -> Optional[str]:
        """Get valid Spotify token, refresh if needed"""
        db = next(get_db())
        try:
            user_session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
            if not user_session or not user_session.spotify_access_token:
                return None
            
            # Check if token is still valid
            if user_session.spotify_expires_at and datetime.utcnow() < user_session.spotify_expires_at:
                return user_session.spotify_access_token
            
            # Try to refresh
            if user_session.spotify_refresh_token:
                new_token = self._refresh_spotify_token(user_session.spotify_refresh_token)
                if new_token:
                    self.save_spotify_token(session_id, new_token)
                    return new_token.get("access_token")
            
            return None
        finally:
            db.close()

    def get_soundcloud_token(self, session_id: str) -> Optional[str]:
        """Get valid SoundCloud token, refresh if needed"""
        db = next(get_db())
        try:
            user_session = db.query(UserSession).filter(UserSession.session_id == session_id).first()
            if not user_session or not user_session.soundcloud_access_token:
                return None
            
            # Check if token is still valid (if we have expiry info)
            if user_session.soundcloud_expires_at and datetime.utcnow() < user_session.soundcloud_expires_at:
                return user_session.soundcloud_access_token
            
            # Try to refresh if we have refresh token
            if user_session.soundcloud_refresh_token:
                new_token = self._refresh_soundcloud_token(user_session.soundcloud_refresh_token)
                if new_token:
                    self.save_soundcloud_token(session_id, new_token)
                    return new_token.get("access_token")
            
            # If no expiry info or refresh failed, return existing token
            return user_session.soundcloud_access_token
        finally:
            db.close()

    def _refresh_spotify_token(self, refresh_token: str) -> Optional[Dict]:
        """Refresh Spotify token"""
        try:
            response = requests.post(
                "https://accounts.spotify.com/api/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": SPOTIFY_CLIENT_ID,
                    "client_secret": SPOTIFY_CLIENT_SECRET,
                },
                timeout=20,
            )
            if response.status_code == 200:
                data = response.json()
                # Keep old refresh token if not provided
                if "refresh_token" not in data:
                    data["refresh_token"] = refresh_token
                return data
        except Exception as e:
            print(f"Failed to refresh Spotify token: {e}")
        return None

    def _refresh_soundcloud_token(self, refresh_token: str) -> Optional[Dict]:
        """Refresh SoundCloud token"""
        try:
            response = requests.post(
                "https://api.soundcloud.com/oauth2/token",
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": SOUNDCLOUD_CLIENT_ID,
                    "client_secret": SOUNDCLOUD_CLIENT_SECRET,
                },
                timeout=20,
            )
            if response.status_code == 200:
                data = response.json()
                if "refresh_token" not in data:
                    data["refresh_token"] = refresh_token
                return data
        except Exception as e:
            print(f"Failed to refresh SoundCloud token: {e}")
        return None

# Global instance
token_manager = TokenManager()