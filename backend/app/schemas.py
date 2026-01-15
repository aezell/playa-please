"""
Shared Pydantic schemas - API contracts between frontend and backend
"""
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


# === Auth Schemas ===

class User(BaseModel):
    id: str
    email: str
    name: str
    picture: Optional[str] = None


class AuthStatus(BaseModel):
    authenticated: bool
    user: Optional[User] = None


# === Song Schemas ===

class Artist(BaseModel):
    id: str
    name: str


class Song(BaseModel):
    video_id: str
    title: str
    artist: str
    artist_id: Optional[str] = None
    album: Optional[str] = None
    album_id: Optional[str] = None
    duration_seconds: int
    thumbnail_url: str
    genres: List[str] = []


class SongWithFeedback(Song):
    feedback: Optional[str] = None  # 'like', 'dislike', or None
    play_count: int = 0
    last_played: Optional[datetime] = None


# === Player Schemas ===

class StreamResponse(BaseModel):
    url: str
    expires_at: datetime


class QueueResponse(BaseModel):
    current: Optional[Song] = None
    upcoming: List[Song] = []
    history: List[Song] = []  # Last 5 played


class NowPlayingResponse(BaseModel):
    song: Optional[Song] = None
    is_playing: bool = False
    progress_seconds: float = 0
    queue_position: int = 0


# === Feedback Schemas ===

class FeedbackRequest(BaseModel):
    video_id: str
    feedback: str  # 'like' or 'dislike'


class FeedbackResponse(BaseModel):
    success: bool
    message: str


# === Library Schemas ===

class LibraryStats(BaseModel):
    total_songs: int
    liked_songs: int
    total_artists: int
    total_genres: int
    last_synced: Optional[datetime] = None


class SyncStatus(BaseModel):
    status: str  # 'idle', 'syncing', 'complete', 'error'
    progress: float  # 0.0 to 1.0
    message: str
