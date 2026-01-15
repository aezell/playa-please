"""
Stream service - Get audio stream URLs using yt-dlp
"""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple

import yt_dlp
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import StreamCache, UnavailableVideo

logger = logging.getLogger(__name__)
settings = get_settings()


class StreamService:
    """Service for managing audio stream URLs"""

    # yt-dlp options for extracting audio URLs
    YDL_OPTS = {
        'format': 'bestaudio/best',
        'quiet': True,
        'no_warnings': True,
        'extract_flat': False,
        'skip_download': True,
        'noplaylist': True,
    }

    def __init__(self, db: Session):
        self.db = db

    def is_video_unavailable(self, video_id: str) -> bool:
        """
        Check if a video is marked as unavailable.

        For bot detection errors, check if retry_after has passed.
        For permanent errors (unavailable), always return True.
        """
        entry = self.db.query(UnavailableVideo).filter(
            UnavailableVideo.video_id == video_id
        ).first()

        if entry is None:
            return False

        # For bot detection, allow retry after the specified time
        if entry.error_type == 'bot_detection' and entry.retry_after:
            if datetime.utcnow() >= entry.retry_after:
                # Time to retry - remove the entry
                self.db.delete(entry)
                self.db.commit()
                return False

        return True

    def mark_video_unavailable(
        self, video_id: str, error_type: str, error_message: str = None
    ) -> None:
        """
        Mark a video as unavailable.

        Args:
            video_id: YouTube video ID
            error_type: 'unavailable', 'bot_detection', 'other'
            error_message: Optional error details
        """
        # Set retry_after for bot detection (retry in 1 hour)
        retry_after = None
        if error_type == 'bot_detection':
            retry_after = datetime.utcnow() + timedelta(hours=1)

        existing = self.db.query(UnavailableVideo).filter(
            UnavailableVideo.video_id == video_id
        ).first()

        if existing:
            existing.error_type = error_type
            existing.error_message = error_message
            existing.failed_at = datetime.utcnow()
            existing.retry_after = retry_after
        else:
            entry = UnavailableVideo(
                video_id=video_id,
                error_type=error_type,
                error_message=error_message,
                failed_at=datetime.utcnow(),
                retry_after=retry_after
            )
            self.db.add(entry)

        self.db.commit()

    def get_cached_url(self, video_id: str) -> Optional[Tuple[str, datetime]]:
        """
        Get stream URL from cache if it exists and hasn't expired.

        Args:
            video_id: YouTube video ID

        Returns:
            Tuple of (stream_url, expires_at) or None if not cached/expired
        """
        cache_entry = self.db.query(StreamCache).filter(
            StreamCache.video_id == video_id
        ).first()

        if cache_entry is None:
            return None

        # Check if expired (with 5 minute buffer)
        if cache_entry.expires_at <= datetime.utcnow() + timedelta(minutes=5):
            # Delete expired entry
            self.db.delete(cache_entry)
            self.db.commit()
            return None

        return (cache_entry.stream_url, cache_entry.expires_at)

    def cache_url(self, video_id: str, stream_url: str, expires_at: datetime) -> None:
        """
        Store stream URL in cache.

        Args:
            video_id: YouTube video ID
            stream_url: The audio stream URL
            expires_at: When the URL expires
        """
        # Upsert the cache entry
        cache_entry = self.db.query(StreamCache).filter(
            StreamCache.video_id == video_id
        ).first()

        if cache_entry:
            cache_entry.stream_url = stream_url
            cache_entry.expires_at = expires_at
            cache_entry.cached_at = datetime.utcnow()
        else:
            cache_entry = StreamCache(
                video_id=video_id,
                stream_url=stream_url,
                expires_at=expires_at,
                cached_at=datetime.utcnow()
            )
            self.db.add(cache_entry)

        self.db.commit()

    def _extract_stream_url(self, video_id: str) -> Tuple[str, datetime]:
        """
        Extract audio stream URL using yt-dlp (synchronous).

        Args:
            video_id: YouTube video ID

        Returns:
            Tuple of (stream_url, expires_at)

        Raises:
            ValueError: If extraction fails
        """
        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            with yt_dlp.YoutubeDL(self.YDL_OPTS) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    raise ValueError(f"No info extracted for video {video_id}")

                # Get the best audio format URL
                formats = info.get('formats', [])
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none']

                if audio_formats:
                    # Sort by quality (abr = audio bitrate)
                    audio_formats.sort(key=lambda x: x.get('abr', 0) or 0, reverse=True)
                    best_audio = audio_formats[0]
                else:
                    # Fallback to any format with audio
                    audio_formats = [f for f in formats if f.get('acodec') != 'none']
                    if not audio_formats:
                        raise ValueError(f"No audio formats found for video {video_id}")
                    best_audio = audio_formats[0]

                stream_url = best_audio.get('url')
                if not stream_url:
                    raise ValueError(f"No URL in format for video {video_id}")

                # Calculate expiration (URLs typically last ~2 hours)
                expires_at = datetime.utcnow() + timedelta(hours=settings.stream_cache_hours)

                return (stream_url, expires_at)

        except yt_dlp.utils.DownloadError as e:
            error_str = str(e)
            logger.error(f"yt-dlp download error for {video_id}: {e}")

            # Categorize the error
            if "Video unavailable" in error_str or "Private video" in error_str:
                self.mark_video_unavailable(video_id, 'unavailable', error_str)
                raise ValueError(f"Video unavailable: {video_id}")
            elif "Sign in to confirm" in error_str or "bot" in error_str.lower():
                self.mark_video_unavailable(video_id, 'bot_detection', error_str)
                raise ValueError(f"Bot detection triggered: {video_id}")
            else:
                self.mark_video_unavailable(video_id, 'other', error_str)
                raise ValueError(f"Failed to extract stream URL: {e}")
        except Exception as e:
            logger.error(f"Unexpected error extracting stream for {video_id}: {e}")
            self.mark_video_unavailable(video_id, 'other', str(e))
            raise ValueError(f"Stream extraction failed: {e}")

    async def get_stream_url_async(self, video_id: str) -> Tuple[str, datetime]:
        """
        Get audio stream URL for a video (async version).

        First checks cache, then extracts fresh URL if needed.

        Args:
            video_id: YouTube video ID

        Returns:
            Tuple of (stream_url, expires_at)

        Raises:
            ValueError: If video is unavailable or extraction fails
        """
        # Check if video is marked unavailable
        if self.is_video_unavailable(video_id):
            raise ValueError(f"Video {video_id} is marked as unavailable")

        # Check cache first
        cached = self.get_cached_url(video_id)
        if cached:
            logger.debug(f"Cache hit for video {video_id}")
            return cached

        logger.debug(f"Cache miss for video {video_id}, extracting...")

        # Run extraction in thread pool to not block
        loop = asyncio.get_event_loop()
        stream_url, expires_at = await loop.run_in_executor(
            None, self._extract_stream_url, video_id
        )

        # Cache the result
        self.cache_url(video_id, stream_url, expires_at)

        return (stream_url, expires_at)

    def get_stream_url_sync(self, video_id: str) -> Tuple[str, datetime]:
        """
        Get audio stream URL for a video (sync version).

        First checks cache, then extracts fresh URL if needed.

        Args:
            video_id: YouTube video ID

        Returns:
            Tuple of (stream_url, expires_at)
        """
        # Check cache first
        cached = self.get_cached_url(video_id)
        if cached:
            logger.debug(f"Cache hit for video {video_id}")
            return cached

        logger.debug(f"Cache miss for video {video_id}, extracting...")

        # Extract fresh URL
        stream_url, expires_at = self._extract_stream_url(video_id)

        # Cache the result
        self.cache_url(video_id, stream_url, expires_at)

        return (stream_url, expires_at)

    def cleanup_expired(self) -> int:
        """
        Remove all expired cache entries.

        Returns:
            Number of entries removed
        """
        result = self.db.query(StreamCache).filter(
            StreamCache.expires_at <= datetime.utcnow()
        ).delete()
        self.db.commit()
        return result


async def get_stream_url(video_id: str, db: Session) -> Tuple[str, datetime]:
    """
    Convenience function to get stream URL.

    Args:
        video_id: YouTube video ID
        db: Database session

    Returns:
        Tuple of (stream_url, expires_at)
    """
    service = StreamService(db)
    return await service.get_stream_url_async(video_id)
