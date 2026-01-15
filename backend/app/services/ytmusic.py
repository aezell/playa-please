"""
YouTube Music API service - hybrid approach

Uses:
- YouTube Data API (official) for library access (liked videos, playlists)
- ytmusicapi (anonymous) for search and metadata
- yt-dlp for streaming
"""
import json
import logging
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy.orm import Session
from ytmusicapi import YTMusic
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from ..config import get_settings
from ..models import User, Song, UserSong
from ..database import get_db_session

logger = logging.getLogger(__name__)
settings = get_settings()

# Anonymous ytmusicapi client for search/metadata
_ytmusic_anon: Optional[YTMusic] = None


def get_ytmusic_anonymous() -> YTMusic:
    """Get anonymous YTMusic client for search and metadata"""
    global _ytmusic_anon
    if _ytmusic_anon is None:
        _ytmusic_anon = YTMusic()
    return _ytmusic_anon


def get_youtube_client(user: User):
    """
    Create YouTube Data API client from user's OAuth tokens.

    Args:
        user: User model with access_token and refresh_token

    Returns:
        YouTube API client, or None if tokens are missing
    """
    if not user.access_token or not user.refresh_token:
        logger.warning(f"User {user.id} has no OAuth tokens")
        return None

    try:
        creds = Credentials(
            token=user.access_token,
            refresh_token=user.refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=settings.google_client_id,
            client_secret=settings.google_client_secret,
        )

        return build('youtube', 'v3', credentials=creds)
    except Exception as e:
        logger.error(f"Failed to create YouTube client for user {user.id}: {e}")
        return None


async def sync_user_library(db: Session, user_id: str) -> Dict[str, Any]:
    """
    Fetch and cache user's YouTube Music library using YouTube Data API.

    Syncs:
    - Liked videos (music)
    - User's playlists

    Args:
        db: Database session
        user_id: User's ID

    Returns:
        Dict with sync statistics
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        logger.error(f"User {user_id} not found")
        return {"error": "User not found", "synced": 0}

    youtube = get_youtube_client(user)
    if not youtube:
        return {"error": "No valid OAuth tokens", "synced": 0}

    stats = {
        "liked_songs": 0,
        "playlists": 0,
        "playlist_songs": 0,
        "errors": [],
    }

    try:
        # Sync liked videos
        liked_count = await _sync_liked_videos(db, user_id, youtube)
        stats["liked_songs"] = liked_count
        logger.info(f"Synced {liked_count} liked videos for user {user_id}")
    except Exception as e:
        logger.error(f"Error syncing liked videos for user {user_id}: {e}")
        stats["errors"].append(f"Liked videos: {str(e)}")

    try:
        # Sync playlists
        playlist_count, songs_count = await _sync_playlists(db, user_id, youtube)
        stats["playlists"] = playlist_count
        stats["playlist_songs"] = songs_count
        logger.info(f"Synced {playlist_count} playlists with {songs_count} songs for user {user_id}")
    except Exception as e:
        logger.error(f"Error syncing playlists for user {user_id}: {e}")
        stats["errors"].append(f"Playlists: {str(e)}")

    stats["total_synced"] = stats["liked_songs"] + stats["playlist_songs"]
    return stats


async def _sync_liked_videos(db: Session, user_id: str, youtube) -> int:
    """Sync user's liked videos from YouTube"""
    count = 0
    next_page_token = None

    while True:
        try:
            request = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId="LL",  # Liked videos playlist
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                video_id = snippet.get('resourceId', {}).get('videoId')

                if not video_id:
                    continue

                # Create song from YouTube data
                song = await _upsert_song_from_youtube(db, video_id, snippet)
                if song:
                    await _upsert_user_song(db, user_id, song.video_id, "liked")
                    count += 1

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

        except Exception as e:
            logger.error(f"Error fetching liked videos page: {e}")
            break

    db.commit()
    return count


async def _sync_playlists(db: Session, user_id: str, youtube) -> tuple:
    """Sync user's playlists from YouTube"""
    playlist_count = 0
    total_songs = 0

    try:
        # Get user's playlists
        request = youtube.playlists().list(
            part="snippet",
            mine=True,
            maxResults=50
        )
        response = request.execute()

        for playlist in response.get('items', []):
            playlist_id = playlist['id']
            playlist_title = playlist['snippet']['title']

            # Skip auto-generated playlists
            if playlist_title.startswith('Liked') or playlist_id == 'LL':
                continue

            playlist_count += 1

            # Get playlist items
            songs_in_playlist = await _sync_playlist_items(db, user_id, youtube, playlist_id)
            total_songs += songs_in_playlist

    except Exception as e:
        logger.error(f"Error fetching playlists: {e}")

    db.commit()
    return playlist_count, total_songs


async def _sync_playlist_items(db: Session, user_id: str, youtube, playlist_id: str) -> int:
    """Sync items from a specific playlist"""
    count = 0
    next_page_token = None

    while True:
        try:
            request = youtube.playlistItems().list(
                part="snippet,contentDetails",
                playlistId=playlist_id,
                maxResults=50,
                pageToken=next_page_token
            )
            response = request.execute()

            for item in response.get('items', []):
                snippet = item.get('snippet', {})
                video_id = snippet.get('resourceId', {}).get('videoId')

                if not video_id:
                    continue

                song = await _upsert_song_from_youtube(db, video_id, snippet)
                if song:
                    await _upsert_user_song(db, user_id, song.video_id, "library")
                    count += 1

            next_page_token = response.get('nextPageToken')
            if not next_page_token:
                break

            # Limit to first 200 songs per playlist
            if count >= 200:
                break

        except Exception as e:
            logger.error(f"Error fetching playlist items: {e}")
            break

    return count


async def _upsert_song_from_youtube(db: Session, video_id: str, snippet: dict) -> Optional[Song]:
    """Create or update a Song record from YouTube Data API snippet"""
    if not video_id:
        return None

    title = snippet.get('title', 'Unknown Title')

    # Skip unavailable videos
    if title in ['Deleted video', 'Private video']:
        return None

    # Extract channel as artist (best we can do from YouTube Data API)
    artist = snippet.get('videoOwnerChannelTitle', snippet.get('channelTitle', 'Unknown Artist'))
    # Clean up " - Topic" suffix from auto-generated music channels
    if artist.endswith(' - Topic'):
        artist = artist[:-8]

    # Get thumbnail
    thumbnails = snippet.get('thumbnails', {})
    thumbnail_url = (
        thumbnails.get('high', {}).get('url') or
        thumbnails.get('medium', {}).get('url') or
        thumbnails.get('default', {}).get('url')
    )

    # Check if song exists
    song = db.query(Song).filter(Song.video_id == video_id).first()

    if song:
        # Update existing song
        song.title = title
        song.artist = artist
        song.thumbnail_url = thumbnail_url or song.thumbnail_url
        song.cached_at = datetime.utcnow()
    else:
        # Create new song
        song = Song(
            video_id=video_id,
            title=title,
            artist=artist,
            thumbnail_url=thumbnail_url,
            genres="[]",
            cached_at=datetime.utcnow(),
        )
        db.add(song)
        # Flush immediately to avoid duplicate key issues in batch
        try:
            db.flush()
        except Exception:
            db.rollback()
            # Song may have been added by concurrent request, try to fetch it
            song = db.query(Song).filter(Song.video_id == video_id).first()

    return song


async def _upsert_user_song(
    db: Session, user_id: str, video_id: str, source: str
) -> Optional[UserSong]:
    """Create or update a UserSong association"""
    user_song = db.query(UserSong).filter(
        UserSong.user_id == user_id,
        UserSong.video_id == video_id
    ).first()

    if user_song:
        # Update source if this is a "higher priority" source
        source_priority = {"liked": 3, "library": 2, "history": 1}
        if source_priority.get(source, 0) > source_priority.get(user_song.source, 0):
            user_song.source = source
    else:
        # Create new association
        user_song = UserSong(
            user_id=user_id,
            video_id=video_id,
            source=source,
            play_count=0,
            score=1.0,
        )
        db.add(user_song)

    return user_song


async def get_song_details(db: Session, user: User, video_id: str) -> Optional[Dict[str, Any]]:
    """
    Get detailed song metadata.

    First checks cache, then tries ytmusicapi anonymous search.

    Args:
        db: Database session
        user: User model
        video_id: YouTube video ID

    Returns:
        Song details dict, or None if not found
    """
    # Check cache first
    song = db.query(Song).filter(Song.video_id == video_id).first()

    if song and song.cached_at:
        age = (datetime.utcnow() - song.cached_at).days
        if age < 7:
            return {
                "video_id": song.video_id,
                "title": song.title,
                "artist": song.artist,
                "artist_id": song.artist_id,
                "album": song.album,
                "album_id": song.album_id,
                "duration_seconds": song.duration_seconds,
                "thumbnail_url": song.thumbnail_url,
                "genres": json.loads(song.genres) if song.genres else [],
            }

    # Try to get more details from ytmusicapi
    try:
        yt = get_ytmusic_anonymous()
        song_data = yt.get_song(video_id)

        if song_data:
            video_details = song_data.get("videoDetails", {})

            title = video_details.get("title", song.title if song else "Unknown")
            author = video_details.get("author", song.artist if song else "Unknown Artist")
            duration = int(video_details.get("lengthSeconds", 0))

            thumbnails = video_details.get("thumbnail", {}).get("thumbnails", [])
            thumbnail_url = thumbnails[-1]["url"] if thumbnails else None

            # Update or create song
            if song:
                song.title = title
                song.artist = author
                song.duration_seconds = duration or song.duration_seconds
                song.thumbnail_url = thumbnail_url or song.thumbnail_url
                song.cached_at = datetime.utcnow()
            else:
                song = Song(
                    video_id=video_id,
                    title=title,
                    artist=author,
                    duration_seconds=duration,
                    thumbnail_url=thumbnail_url,
                    cached_at=datetime.utcnow(),
                )
                db.add(song)

            db.commit()

            return {
                "video_id": video_id,
                "title": title,
                "artist": author,
                "duration_seconds": duration,
                "thumbnail_url": thumbnail_url,
                "genres": [],
            }

    except Exception as e:
        logger.warning(f"Could not get song details from ytmusicapi for {video_id}: {e}")

    # Return cached data if available
    if song:
        return {
            "video_id": song.video_id,
            "title": song.title,
            "artist": song.artist,
            "artist_id": song.artist_id,
            "album": song.album,
            "album_id": song.album_id,
            "duration_seconds": song.duration_seconds,
            "thumbnail_url": song.thumbnail_url,
            "genres": json.loads(song.genres) if song.genres else [],
        }

    return None


def search_songs(query: str, limit: int = 20) -> List[Dict[str, Any]]:
    """
    Search for songs using ytmusicapi (anonymous).

    Args:
        query: Search query
        limit: Maximum results

    Returns:
        List of song dicts
    """
    try:
        yt = get_ytmusic_anonymous()
        results = yt.search(query, filter="songs", limit=limit)

        songs = []
        for r in results:
            songs.append({
                "video_id": r.get("videoId"),
                "title": r.get("title"),
                "artist": r.get("artists", [{}])[0].get("name", "Unknown"),
                "album": r.get("album", {}).get("name") if r.get("album") else None,
                "duration_seconds": _parse_duration(r.get("duration")),
                "thumbnail_url": r.get("thumbnails", [{}])[-1].get("url") if r.get("thumbnails") else None,
            })

        return songs
    except Exception as e:
        logger.error(f"Search failed: {e}")
        return []


def _parse_duration(duration_str: str) -> int:
    """Parse duration string like '3:45' to seconds"""
    if not duration_str:
        return 0

    parts = duration_str.split(":")
    try:
        if len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
        elif len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
    except ValueError:
        pass
    return 0
