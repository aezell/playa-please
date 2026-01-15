"""
Player router - handles playback queue and streaming

Endpoints:
- GET /api/queue - Get current queue
- POST /api/queue/next - Advance to next song
- GET /api/stream/{video_id} - Get stream URL
"""
from typing import Optional
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from ..config import get_settings
from ..database import get_db
from ..models import User, Song, PlaylistQueue, UserSong
from ..schemas import QueueResponse, Song as SongSchema, StreamResponse
from .auth import require_current_user
from ..services.stream import get_stream_url
from ..services.algorithm import generate_playlist

router = APIRouter(prefix="/api", tags=["player"])
settings = get_settings()


def _song_to_schema(song: Song) -> SongSchema:
    """Convert Song model to Pydantic schema."""
    import json
    return SongSchema(
        video_id=song.video_id,
        title=song.title,
        artist=song.artist,
        artist_id=song.artist_id,
        album=song.album,
        album_id=song.album_id,
        duration_seconds=song.duration_seconds,
        thumbnail_url=song.thumbnail_url or "",
        genres=json.loads(song.genres) if song.genres else [],
    )


@router.get("/queue", response_model=QueueResponse)
async def get_queue(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the current playback queue for the user.

    Returns:
        - current: The currently playing song (first unplayed in queue)
        - upcoming: Next songs in the queue
        - history: Last 5 played songs
    """
    # Get queue items ordered by position
    queue_items = db.query(PlaylistQueue).filter(
        PlaylistQueue.user_id == user.id
    ).order_by(PlaylistQueue.position).all()

    if not queue_items:
        # No queue exists, try to generate one
        try:
            await generate_playlist(db, user.id, settings.queue_prefetch_size)
            # Re-fetch queue
            queue_items = db.query(PlaylistQueue).filter(
                PlaylistQueue.user_id == user.id
            ).order_by(PlaylistQueue.position).all()
        except Exception:
            # Return empty queue if generation fails
            return QueueResponse(current=None, upcoming=[], history=[])

    # Separate played and unplayed
    played_items = [q for q in queue_items if q.played]
    unplayed_items = [q for q in queue_items if not q.played]

    # Get current song (first unplayed)
    current_song = None
    if unplayed_items:
        current_video_id = unplayed_items[0].video_id
        song = db.query(Song).filter(Song.video_id == current_video_id).first()
        if song:
            current_song = _song_to_schema(song)

    # Get upcoming songs (skip the current one)
    upcoming = []
    for queue_item in unplayed_items[1:10]:  # Next 9 songs
        song = db.query(Song).filter(Song.video_id == queue_item.video_id).first()
        if song:
            upcoming.append(_song_to_schema(song))

    # Get history (last 5 played, most recent first)
    history = []
    for queue_item in reversed(played_items[-5:]):
        song = db.query(Song).filter(Song.video_id == queue_item.video_id).first()
        if song:
            history.append(_song_to_schema(song))

    return QueueResponse(
        current=current_song,
        upcoming=upcoming,
        history=history,
    )


@router.post("/queue/next", response_model=QueueResponse)
async def next_song(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Advance to the next song in the queue.

    Marks the current song as played and returns the updated queue.
    Also triggers prefetch if queue is running low.
    """
    # Get current (first unplayed) queue item
    current_item = db.query(PlaylistQueue).filter(
        PlaylistQueue.user_id == user.id,
        PlaylistQueue.played == False
    ).order_by(PlaylistQueue.position).first()

    if current_item:
        # Mark as played
        current_item.played = True

        # Update UserSong play count and last_played
        user_song = db.query(UserSong).filter(
            UserSong.user_id == user.id,
            UserSong.video_id == current_item.video_id
        ).first()

        if user_song:
            user_song.play_count = (user_song.play_count or 0) + 1
            user_song.last_played = datetime.utcnow()

        db.commit()

    # Check if we need to prefetch more songs
    unplayed_count = db.query(PlaylistQueue).filter(
        PlaylistQueue.user_id == user.id,
        PlaylistQueue.played == False
    ).count()

    if unplayed_count < 5:
        # Generate more songs
        try:
            await generate_playlist(db, user.id, settings.queue_prefetch_size)
        except Exception:
            pass  # Continue with what we have

    # Return updated queue
    return await get_queue(user=user, db=db)


@router.post("/queue/skip")
async def skip_song(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Skip the current song (same as next, but may affect algorithm differently).

    This can be used by the algorithm to detect skipped songs and adjust scores.
    """
    # Get current song before skipping
    current_item = db.query(PlaylistQueue).filter(
        PlaylistQueue.user_id == user.id,
        PlaylistQueue.played == False
    ).order_by(PlaylistQueue.position).first()

    if current_item:
        # TODO: Record skip event for algorithm
        # from ..services.algorithm import PlaylistAlgorithm
        # algorithm = PlaylistAlgorithm(db, user.id)
        # await algorithm.update_song_score(current_item.video_id, 'skipped')
        pass

    # Advance to next song
    return await next_song(user=user, db=db)


@router.get("/stream/{video_id}", response_model=StreamResponse)
async def get_stream(
    video_id: str,
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Get the stream URL for a specific video.

    This returns a direct audio stream URL that the frontend can use
    to play the song. URLs are cached and have an expiry time.
    """
    try:
        stream_url, expires_at = await get_stream_url(video_id, db)

        return StreamResponse(
            url=stream_url,
            expires_at=expires_at,
        )
    except NotImplementedError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="Stream service not yet implemented"
        )
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to get stream URL: {str(e)}"
        )


@router.post("/queue/regenerate", response_model=QueueResponse)
async def regenerate_queue(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Regenerate the entire queue using the playlist algorithm.

    This clears unplayed items and generates a fresh queue.
    """
    # Clear unplayed queue items
    db.query(PlaylistQueue).filter(
        PlaylistQueue.user_id == user.id,
        PlaylistQueue.played == False
    ).delete()
    db.commit()

    # Generate new queue
    try:
        await generate_playlist(db, user.id, settings.queue_prefetch_size)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate queue: {str(e)}"
        )

    return await get_queue(user=user, db=db)


@router.delete("/queue")
async def clear_queue(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Clear the entire queue (both played and unplayed).
    """
    db.query(PlaylistQueue).filter(
        PlaylistQueue.user_id == user.id
    ).delete()
    db.commit()

    return {"success": True, "message": "Queue cleared"}
