"""
Playlist router - Queue generation, library management, and feedback endpoints

Handles:
- Queue generation and regeneration
- Library statistics
- Library sync with YouTube Music
- User feedback (likes/dislikes)
"""
import json
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, status
from sqlalchemy.orm import Session
from sqlalchemy import func

from ..config import get_settings
from ..database import get_db
from ..models import User, Song, UserSong, PlaylistQueue
from ..schemas import (
    Song as SongSchema,
    SongWithFeedback,
    QueueResponse,
    LibraryStats,
    SyncStatus,
    FeedbackRequest,
    FeedbackResponse,
)
from ..services.algorithm import PlaylistAlgorithm
from ..services.feedback import FeedbackService
from ..services.ytmusic import sync_user_library
from .auth import require_current_user

router = APIRouter(tags=["playlist"])
settings = get_settings()
logger = logging.getLogger(__name__)

# Track sync status per user (in-memory for simplicity)
_sync_status: dict = {}


def _song_to_schema(song: Song) -> SongSchema:
    """Convert a Song model to a SongSchema"""
    genres = []
    if song.genres:
        try:
            genres = json.loads(song.genres)
        except (json.JSONDecodeError, TypeError):
            genres = []

    return SongSchema(
        video_id=song.video_id,
        title=song.title,
        artist=song.artist,
        artist_id=song.artist_id,
        album=song.album,
        album_id=song.album_id,
        duration_seconds=song.duration_seconds,
        thumbnail_url=song.thumbnail_url or "",
        genres=genres,
    )


def _song_with_feedback(song: Song, user_song: Optional[UserSong]) -> SongWithFeedback:
    """Convert a Song model to a SongWithFeedback schema"""
    genres = []
    if song.genres:
        try:
            genres = json.loads(song.genres)
        except (json.JSONDecodeError, TypeError):
            genres = []

    return SongWithFeedback(
        video_id=song.video_id,
        title=song.title,
        artist=song.artist,
        artist_id=song.artist_id,
        album=song.album,
        album_id=song.album_id,
        duration_seconds=song.duration_seconds,
        thumbnail_url=song.thumbnail_url or "",
        genres=genres,
        feedback=user_song.feedback if user_song else None,
        play_count=user_song.play_count if user_song else 0,
        last_played=user_song.last_played if user_song else None,
    )


# ============================================================================
# Queue Generation Endpoints
# ============================================================================


@router.get("/api/playlist/generate", response_model=QueueResponse)
async def generate_playlist(
    count: Optional[int] = None,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Force regenerate the playlist queue.

    This endpoint clears the current unplayed queue and generates a new one
    using the playlist algorithm. The algorithm considers:
    - User preferences (likes/dislikes)
    - Artist diversity (min_artist_gap)
    - Genre balance (max_genre_ratio)
    - Discovery ratio (discovery_ratio of new/rediscovered songs)

    Args:
        count: Optional number of songs to generate (defaults to queue_prefetch_size)

    Returns:
        QueueResponse with the newly generated queue
    """
    if count is None:
        count = settings.queue_prefetch_size

    # Limit count to reasonable bounds
    count = max(1, min(count, 100))

    logger.info(f"Generating playlist for user {user.id} with count={count}")

    try:
        algorithm = PlaylistAlgorithm(user.id, db)

        # Generate new songs
        songs = algorithm.generate_queue(count)

        if not songs:
            logger.warning(f"No songs generated for user {user.id}")
            return QueueResponse(current=None, upcoming=[], history=[])

        # Save to queue
        algorithm.update_queue(songs)

        # Get updated queue
        queue_songs = algorithm.get_queue(limit=count)

        # Convert to response format
        current = _song_to_schema(queue_songs[0]) if queue_songs else None
        upcoming = [_song_to_schema(s) for s in queue_songs[1:]] if len(queue_songs) > 1 else []

        # Get recent history
        history_songs = _get_play_history(db, user.id, limit=5)

        return QueueResponse(
            current=current,
            upcoming=upcoming,
            history=history_songs,
        )

    except Exception as e:
        logger.error(f"Error generating playlist for user {user.id}: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate playlist: {str(e)}"
        )


@router.get("/api/playlist/queue", response_model=QueueResponse)
async def get_queue(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the current playlist queue without regenerating.

    Returns the existing queue if available, or generates a new one if empty.

    Returns:
        QueueResponse with current, upcoming, and history songs
    """
    algorithm = PlaylistAlgorithm(user.id, db)
    queue_songs = algorithm.get_queue(limit=settings.queue_prefetch_size)

    # If queue is empty or too small, generate more
    if len(queue_songs) < 5:
        logger.info(f"Queue too small ({len(queue_songs)}), generating more for user {user.id}")
        songs = algorithm.generate_queue(settings.queue_prefetch_size)
        if songs:
            algorithm.update_queue(songs)
            queue_songs = algorithm.get_queue(limit=settings.queue_prefetch_size)

    current = _song_to_schema(queue_songs[0]) if queue_songs else None
    upcoming = [_song_to_schema(s) for s in queue_songs[1:]] if len(queue_songs) > 1 else []
    history_songs = _get_play_history(db, user.id, limit=5)

    return QueueResponse(
        current=current,
        upcoming=upcoming,
        history=history_songs,
    )


def _get_play_history(db: Session, user_id: str, limit: int = 5) -> List[SongSchema]:
    """Get recent play history for a user"""
    # Get recently played queue items
    recent_played = (
        db.query(PlaylistQueue)
        .filter(
            PlaylistQueue.user_id == user_id,
            PlaylistQueue.played == True
        )
        .order_by(PlaylistQueue.position.desc())
        .limit(limit)
        .all()
    )

    if not recent_played:
        return []

    # Get the songs
    video_ids = [entry.video_id for entry in recent_played]
    songs = db.query(Song).filter(Song.video_id.in_(video_ids)).all()
    song_map = {s.video_id: s for s in songs}

    return [_song_to_schema(song_map[entry.video_id]) for entry in recent_played if entry.video_id in song_map]


# ============================================================================
# Library Statistics Endpoint
# ============================================================================


@router.get("/api/library/stats", response_model=LibraryStats)
async def get_library_stats(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get library statistics for the current user.

    Returns counts for:
    - Total songs in library
    - Liked songs
    - Total unique artists
    - Total unique genres
    - Last sync timestamp

    Returns:
        LibraryStats with library statistics
    """
    # Total songs
    total_songs = db.query(func.count(UserSong.id)).filter(
        UserSong.user_id == user.id
    ).scalar() or 0

    # Liked songs
    liked_songs = db.query(func.count(UserSong.id)).filter(
        UserSong.user_id == user.id,
        UserSong.feedback == 'like'
    ).scalar() or 0

    # Get all user songs with their song data for artist/genre counts
    user_songs = (
        db.query(UserSong)
        .filter(UserSong.user_id == user.id)
        .all()
    )

    video_ids = [us.video_id for us in user_songs]

    if video_ids:
        songs = db.query(Song).filter(Song.video_id.in_(video_ids)).all()

        # Unique artists
        artists = set()
        genres = set()

        for song in songs:
            artist_key = song.artist_id or song.artist
            if artist_key:
                artists.add(artist_key)

            # Parse genres
            if song.genres:
                try:
                    song_genres = json.loads(song.genres)
                    genres.update(song_genres)
                except (json.JSONDecodeError, TypeError):
                    pass

        total_artists = len(artists)
        total_genres = len(genres)
    else:
        total_artists = 0
        total_genres = 0

    # Last synced (based on most recent song cache time)
    last_synced = None
    if video_ids:
        latest_song = (
            db.query(Song.cached_at)
            .filter(Song.video_id.in_(video_ids))
            .order_by(Song.cached_at.desc())
            .first()
        )
        if latest_song:
            last_synced = latest_song[0]

    return LibraryStats(
        total_songs=total_songs,
        liked_songs=liked_songs,
        total_artists=total_artists,
        total_genres=total_genres,
        last_synced=last_synced,
    )


# ============================================================================
# Library Sync Endpoint
# ============================================================================


async def _background_sync(user_id: str, db_url: str):
    """Background task to sync user library"""
    from ..database import get_db_session

    _sync_status[user_id] = {
        "status": "syncing",
        "progress": 0.0,
        "message": "Starting sync...",
    }

    try:
        with get_db_session() as db:
            _sync_status[user_id]["message"] = "Fetching from YouTube Music..."
            _sync_status[user_id]["progress"] = 0.1

            result = await sync_user_library(db, user_id)

            if "error" in result:
                _sync_status[user_id] = {
                    "status": "error",
                    "progress": 0.0,
                    "message": result["error"],
                }
            else:
                total = result.get("total_synced", 0)
                _sync_status[user_id] = {
                    "status": "complete",
                    "progress": 1.0,
                    "message": f"Synced {total} songs successfully",
                }

    except Exception as e:
        logger.error(f"Background sync error for user {user_id}: {e}")
        _sync_status[user_id] = {
            "status": "error",
            "progress": 0.0,
            "message": str(e),
        }


@router.post("/api/library/sync", response_model=SyncStatus)
async def trigger_library_sync(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Trigger a library sync with YouTube Music.

    This endpoint initiates a background sync of the user's YouTube Music
    library, including:
    - Liked songs
    - Recently played (history)
    - Saved library songs

    The sync runs in the background. Use GET /api/library/sync/status to
    check progress.

    Returns:
        SyncStatus indicating the sync has started
    """
    # Check if already syncing
    current_status = _sync_status.get(user.id, {})
    if current_status.get("status") == "syncing":
        return SyncStatus(
            status="syncing",
            progress=current_status.get("progress", 0.0),
            message=current_status.get("message", "Sync in progress..."),
        )

    # Start background sync
    _sync_status[user.id] = {
        "status": "syncing",
        "progress": 0.0,
        "message": "Starting sync...",
    }

    background_tasks.add_task(_background_sync, user.id, settings.database_url)

    return SyncStatus(
        status="syncing",
        progress=0.0,
        message="Library sync started",
    )


@router.get("/api/library/sync/status", response_model=SyncStatus)
async def get_sync_status(
    user: User = Depends(require_current_user),
):
    """
    Get the current library sync status.

    Returns:
        SyncStatus with current sync progress
    """
    status_info = _sync_status.get(user.id, {
        "status": "idle",
        "progress": 0.0,
        "message": "No sync in progress",
    })

    return SyncStatus(
        status=status_info.get("status", "idle"),
        progress=status_info.get("progress", 0.0),
        message=status_info.get("message", ""),
    )


# ============================================================================
# Feedback Endpoints
# ============================================================================


@router.post("/api/feedback", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Submit feedback (like/dislike) for a song.

    Feedback affects the playlist algorithm:
    - Liked songs get a 1.5x score boost
    - Disliked songs are excluded from the queue

    Args:
        request: FeedbackRequest with video_id and feedback type

    Returns:
        FeedbackResponse indicating success
    """
    if request.feedback not in ('like', 'dislike'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Feedback must be 'like' or 'dislike'"
        )

    try:
        feedback_service = FeedbackService(db)
        await feedback_service.record_feedback(
            user_id=user.id,
            video_id=request.video_id,
            feedback=request.feedback,
        )

        return FeedbackResponse(
            success=True,
            message=f"Song marked as {request.feedback}d",
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error recording feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to record feedback",
        )


@router.delete("/api/feedback/{video_id}", response_model=FeedbackResponse)
async def remove_feedback(
    video_id: str,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Remove feedback for a song (set to neutral).

    Args:
        video_id: The video ID to remove feedback for

    Returns:
        FeedbackResponse indicating success
    """
    try:
        feedback_service = FeedbackService(db)
        removed = await feedback_service.remove_feedback(
            user_id=user.id,
            video_id=video_id,
        )

        if removed:
            return FeedbackResponse(
                success=True,
                message="Feedback removed",
            )
        else:
            return FeedbackResponse(
                success=True,
                message="No feedback to remove",
            )

    except Exception as e:
        logger.error(f"Error removing feedback: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to remove feedback",
        )


@router.get("/api/feedback/{video_id}")
async def get_feedback(
    video_id: str,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get feedback for a specific song.

    Args:
        video_id: The video ID to get feedback for

    Returns:
        Dict with feedback value or null
    """
    feedback_service = FeedbackService(db)
    feedback = await feedback_service.get_feedback(user.id, video_id)

    return {"video_id": video_id, "feedback": feedback}


@router.get("/api/feedback")
async def get_all_feedback(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all feedback for the current user.

    Returns:
        Dict mapping video_id to feedback value
    """
    feedback_service = FeedbackService(db)
    all_feedback = await feedback_service.get_user_feedback(user.id)

    return {"feedback": all_feedback}


# ============================================================================
# Library Browsing Endpoints
# ============================================================================


@router.get("/api/library/liked", response_model=List[SongWithFeedback])
async def get_liked_songs(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all liked songs for the user.

    Args:
        limit: Maximum number of songs to return
        offset: Offset for pagination

    Returns:
        List of SongWithFeedback objects
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    feedback_service = FeedbackService(db)
    liked = await feedback_service.get_liked_songs(user.id, limit=limit + offset)

    # Apply offset manually since the service doesn't support it directly
    liked = liked[offset:offset + limit]

    # Get user song data for feedback info
    video_ids = [s.video_id for s in liked]
    user_songs = db.query(UserSong).filter(
        UserSong.user_id == user.id,
        UserSong.video_id.in_(video_ids)
    ).all()
    user_song_map = {us.video_id: us for us in user_songs}

    return [_song_with_feedback(song, user_song_map.get(song.video_id)) for song in liked]


@router.get("/api/library/songs", response_model=List[SongWithFeedback])
async def get_library_songs(
    limit: int = 50,
    offset: int = 0,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get all songs in the user's library.

    Args:
        limit: Maximum number of songs to return
        offset: Offset for pagination

    Returns:
        List of SongWithFeedback objects
    """
    limit = max(1, min(limit, 100))
    offset = max(0, offset)

    # Get user songs with pagination
    user_songs = (
        db.query(UserSong)
        .filter(UserSong.user_id == user.id)
        .order_by(UserSong.last_played.desc().nullslast())
        .offset(offset)
        .limit(limit)
        .all()
    )

    if not user_songs:
        return []

    # Get the songs
    video_ids = [us.video_id for us in user_songs]
    songs = db.query(Song).filter(Song.video_id.in_(video_ids)).all()
    song_map = {s.video_id: s for s in songs}
    user_song_map = {us.video_id: us for us in user_songs}

    result = []
    for us in user_songs:
        if us.video_id in song_map:
            result.append(_song_with_feedback(song_map[us.video_id], user_song_map.get(us.video_id)))

    return result
