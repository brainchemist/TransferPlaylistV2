from sqlalchemy import create_engine, Column, String, DateTime, Integer, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
import os

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./transferme.db")

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class UserSession(Base):
    __tablename__ = "user_sessions"
    
    session_id = Column(String, primary_key=True)
    spotify_access_token = Column(Text)
    spotify_refresh_token = Column(Text)
    spotify_expires_at = Column(DateTime)
    soundcloud_access_token = Column(Text)
    soundcloud_refresh_token = Column(Text)
    soundcloud_expires_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow)

class TransferHistory(Base):
    __tablename__ = "transfer_history"
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(String)
    source_platform = Column(String)
    destination_platform = Column(String)
    source_playlist_url = Column(String)
    destination_playlist_url = Column(String)
    tracks_total = Column(Integer)
    tracks_found = Column(Integer)
    transfer_status = Column(String)
    error_message = Column(Text)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
