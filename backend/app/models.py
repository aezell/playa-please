"""
SQLAlchemy database models
"""
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship
from datetime import datetime

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True)
    email = Column(String, unique=True, nullable=False)
    name = Column(String, nullable=False)
    picture = Column(String, nullable=True)
    access_token = Column(Text, nullable=True)
    refresh_token = Column(Text, nullable=True)
    token_expiry = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    songs = relationship("UserSong", back_populates="user")
    queue = relationship("PlaylistQueue", back_populates="user")


class Song(Base):
    __tablename__ = "songs"

    video_id = Column(String, primary_key=True)
    title = Column(String, nullable=False)
    artist = Column(String, nullable=False)
    artist_id = Column(String, nullable=True)
    album = Column(String, nullable=True)
    album_id = Column(String, nullable=True)
    duration_seconds = Column(Integer, default=0)
    thumbnail_url = Column(String, nullable=True)
    genres = Column(Text, default="[]")  # JSON array
    cached_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user_songs = relationship("UserSong", back_populates="song")


class UserSong(Base):
    __tablename__ = "user_songs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    video_id = Column(String, ForeignKey("songs.video_id"), nullable=False)
    source = Column(String, nullable=False)  # 'history', 'liked', 'library'
    play_count = Column(Integer, default=0)
    last_played = Column(DateTime, nullable=True)
    feedback = Column(String, nullable=True)  # 'like', 'dislike', None
    feedback_at = Column(DateTime, nullable=True)
    score = Column(Float, default=1.0)  # Algorithm score

    __table_args__ = (
        UniqueConstraint('user_id', 'video_id', name='uq_user_song'),
    )

    # Relationships
    user = relationship("User", back_populates="songs")
    song = relationship("Song", back_populates="user_songs")


class PlaylistQueue(Base):
    __tablename__ = "playlist_queue"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String, ForeignKey("users.id"), nullable=False)
    video_id = Column(String, ForeignKey("songs.video_id"), nullable=False)
    position = Column(Integer, nullable=False)
    played = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="queue")


class StreamCache(Base):
    __tablename__ = "stream_cache"

    video_id = Column(String, primary_key=True)
    stream_url = Column(Text, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    cached_at = Column(DateTime, default=datetime.utcnow)


class UnavailableVideo(Base):
    """Track videos that failed to stream (unavailable, bot detection, etc)"""
    __tablename__ = "unavailable_videos"

    video_id = Column(String, primary_key=True)
    error_type = Column(String, nullable=False)  # 'unavailable', 'bot_detection', 'other'
    error_message = Column(Text, nullable=True)
    failed_at = Column(DateTime, default=datetime.utcnow)
    retry_after = Column(DateTime, nullable=True)  # When to retry (for rate limits)
