"""
Audio Router - Browser-based audio streaming endpoints

Provides:
- Audio stream from browser (via PulseAudio capture)
- Playback controls (play, pause, skip)
- Now playing information
"""
import logging
from typing import Optional
from enum import Enum

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..database import get_db
from ..models import User, Song as SongModel
from ..schemas import Song
from ..routers.auth import require_current_user
from ..services.browser_controller import (
    get_browser_controller,
    BrowserController,
    PlaybackState,
)
from ..services.audio_streamer import get_audio_streamer, AudioStreamer
from ..services.algorithm import PlaylistAlgorithm

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/audio", tags=["audio"])


# === Schemas ===

class AudioStatus(BaseModel):
    """Overall audio system status"""
    browser_running: bool
    browser_authenticated: bool
    stream_running: bool
    active_listeners: int


class NowPlaying(BaseModel):
    """Current playback info"""
    video_id: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    thumbnail: Optional[str] = None
    duration_seconds: int = 0
    position_seconds: int = 0
    state: str = "idle"  # idle, playing, paused, loading, error


class ControlAction(str, Enum):
    PLAY = "play"
    PAUSE = "pause"
    SKIP = "skip"


class ControlRequest(BaseModel):
    action: ControlAction


class ControlResponse(BaseModel):
    success: bool
    message: str
    now_playing: Optional[NowPlaying] = None


# === Dependencies ===

def get_controller() -> BrowserController:
    """Get browser controller instance"""
    return get_browser_controller()


def get_streamer() -> AudioStreamer:
    """Get audio streamer instance"""
    return get_audio_streamer()


# === Endpoints ===

@router.get("/status", response_model=AudioStatus)
async def get_status(
    controller: BrowserController = Depends(get_controller),
    streamer: AudioStreamer = Depends(get_streamer),
):
    """
    Get audio system status.

    Returns information about browser state, authentication, and streaming.
    """
    return AudioStatus(
        browser_running=controller._page is not None,
        browser_authenticated=controller.is_authenticated,
        stream_running=streamer.is_running,
        active_listeners=streamer.active_connections,
    )


@router.get("/now-playing", response_model=NowPlaying)
async def get_now_playing(
    controller: BrowserController = Depends(get_controller),
):
    """
    Get current playback information.

    Returns the currently playing track, progress, and state.
    """
    np = controller.now_playing
    return NowPlaying(
        video_id=np.video_id,
        title=np.title,
        artist=np.artist,
        thumbnail=np.thumbnail,
        duration_seconds=np.duration_seconds,
        position_seconds=np.position_seconds,
        state=np.state.value,
    )


@router.get("/stream")
async def stream_audio(
    streamer: AudioStreamer = Depends(get_streamer),
):
    """
    Stream audio from the browser.

    This endpoint returns a continuous MP3 audio stream captured
    from the browser's audio output. Connect to this URL with an
    audio player to listen.

    Note: This is a long-lived connection that streams until
    the client disconnects.
    """
    if not streamer.is_running:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Audio stream not available"
        )

    return StreamingResponse(
        streamer.get_audio_stream(),
        media_type="audio/mpeg",
        headers={
            "Cache-Control": "no-cache, no-store",
            "Connection": "keep-alive",
            "Transfer-Encoding": "chunked",
        }
    )


@router.post("/control", response_model=ControlResponse)
async def control_playback(
    request: ControlRequest,
    user: User = Depends(require_current_user),
    controller: BrowserController = Depends(get_controller),
    db: Session = Depends(get_db),
):
    """
    Control playback.

    Actions:
    - play: Resume playback or start playing next song
    - pause: Pause playback
    - skip: Skip to next song in queue
    """
    if not controller.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser not authenticated"
        )

    try:
        if request.action == ControlAction.PLAY:
            # If nothing playing, get next song from queue
            if controller.now_playing.state == PlaybackState.IDLE:
                success = await _play_next_song(user, controller, db)
                message = "Started playback" if success else "Failed to start playback"
            else:
                success = await controller.resume()
                message = "Resumed playback" if success else "Failed to resume"

        elif request.action == ControlAction.PAUSE:
            success = await controller.pause()
            message = "Paused playback" if success else "Failed to pause"

        elif request.action == ControlAction.SKIP:
            success = await _play_next_song(user, controller, db)
            message = "Skipped to next song" if success else "Failed to skip"

        else:
            success = False
            message = f"Unknown action: {request.action}"

        np = controller.now_playing
        return ControlResponse(
            success=success,
            message=message,
            now_playing=NowPlaying(
                video_id=np.video_id,
                title=np.title,
                artist=np.artist,
                thumbnail=np.thumbnail,
                duration_seconds=np.duration_seconds,
                position_seconds=np.position_seconds,
                state=np.state.value,
            )
        )

    except Exception as e:
        logger.error(f"Control error: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=str(e)
        )


@router.post("/play/{video_id}", response_model=ControlResponse)
async def play_specific_song(
    video_id: str,
    user: User = Depends(require_current_user),
    controller: BrowserController = Depends(get_controller),
    db: Session = Depends(get_db),
):
    """
    Play a specific song by video ID.

    This bypasses the queue and plays the requested song immediately.
    """
    if not controller.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Browser not authenticated"
        )

    success = await controller.play_song(video_id)

    np = controller.now_playing
    return ControlResponse(
        success=success,
        message="Playing song" if success else "Failed to play song",
        now_playing=NowPlaying(
            video_id=np.video_id,
            title=np.title,
            artist=np.artist,
            thumbnail=np.thumbnail,
            duration_seconds=np.duration_seconds,
            position_seconds=np.position_seconds,
            state=np.state.value,
        )
    )


# === Helper Functions ===

async def _play_next_song(
    user: User,
    controller: BrowserController,
    db: Session
) -> bool:
    """Get next song from playlist algorithm and play it"""
    try:
        algorithm = PlaylistAlgorithm(user.id, db)

        # Get or generate queue
        queue = algorithm.get_queue(limit=10)

        if not queue:
            # Generate new queue
            queue = algorithm.generate_queue(count=20)
            algorithm.update_queue(queue)

        if not queue:
            logger.warning("No songs in queue")
            return False

        # Get next unplayed song
        next_song = queue[0]

        # Play it
        success = await controller.play_song(next_song.video_id)

        if success:
            # Mark as played and remove from queue head
            algorithm.mark_song_played(next_song.video_id)
            db.commit()

        return success

    except Exception as e:
        logger.error(f"Error playing next song: {e}")
        return False


async def setup_auto_advance(user_id: str, db_session_maker):
    """
    Set up automatic advancement to next song when current ends.

    This should be called during startup to enable radio mode.
    """
    controller = get_browser_controller()

    async def on_track_ended():
        logger.info("Track ended - auto-advancing to next song")
        # Get a fresh DB session
        from ..database import SessionLocal
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.id == user_id).first()
            if user:
                await _play_next_song(user, controller, db)
        finally:
            db.close()

    controller.set_on_track_ended(on_track_ended)


# === Admin Endpoints ===

class BrowserLoginStatus(BaseModel):
    """Browser login status and instructions"""
    is_authenticated: bool
    browser_running: bool
    instructions: str
    display: str


@router.get("/admin/browser-status", response_model=BrowserLoginStatus)
async def get_browser_login_status(
    controller: BrowserController = Depends(get_controller),
):
    """
    Get browser login status and instructions for manual authentication.

    If the browser is not authenticated, provides instructions for
    how to log in manually.
    """
    is_auth = controller.is_authenticated
    is_running = controller._page is not None

    if is_auth:
        instructions = "Browser is authenticated and ready to play music."
    elif is_running:
        instructions = (
            "Browser is running but NOT authenticated. "
            "To log in, you need to access the browser via VNC or run the login script. "
            "The browser session is saved in /home/sprite/playa-please/backend/.browser-data "
            "Once logged in, the session will persist across restarts."
        )
    else:
        instructions = "Browser is not running. Restart the server to launch the browser."

    return BrowserLoginStatus(
        is_authenticated=is_auth,
        browser_running=is_running,
        instructions=instructions,
        display=controller.config.display if is_running else "",
    )


@router.post("/admin/start-stream")
async def start_audio_stream(
    controller: BrowserController = Depends(get_controller),
    streamer: AudioStreamer = Depends(get_streamer),
):
    """
    Manually start the audio stream.

    Use this after browser authentication to start the audio capture.
    """
    if not controller.is_authenticated:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Browser not authenticated - cannot start stream"
        )

    if streamer.is_running:
        return {"success": True, "message": "Stream already running"}

    success = await streamer.start()
    return {
        "success": success,
        "message": "Stream started" if success else "Failed to start stream"
    }
