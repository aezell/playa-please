"""
Stream service - Get audio stream URLs using yt-dlp or Piped API fallback
"""
import asyncio
import logging
import httpx
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Tuple, List

import yt_dlp
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import StreamCache, UnavailableVideo

logger = logging.getLogger(__name__)
settings = get_settings()

# Cookie file path - user can place cookies.txt here
COOKIE_FILE = Path(__file__).parent.parent.parent / "cookies.txt"

# Piped instances to try as fallback (public instances)
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://pipedapi.adminforge.de",
    "https://api.piped.yt",
    "https://pipedapi.in.projectsegfau.lt",
]


class StreamService:
    """Service for managing audio stream URLs"""

    @staticmethod
    def _get_ydl_opts() -> dict:
        """Get yt-dlp options, including cookies if available."""
        opts = {
            # Don't specify format - we'll select from available formats manually
            'quiet': True,
            'no_warnings': True,
            'extract_flat': False,
            'skip_download': True,
            'noplaylist': True,
            # Enable remote JS solver for YouTube signature challenges
            'remote_components': ['ejs:github'],
        }

        # Use cookies if file exists
        if COOKIE_FILE.exists():
            opts['cookiefile'] = str(COOKIE_FILE)
            logger.info(f"Using cookies from {COOKIE_FILE}")
        else:
            # Without cookies, try mediaconnect client as fallback
            opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['mediaconnect', 'android', 'web'],
                }
            }

        return opts

    # Rate limiting - track last request time
    _last_request_time: Optional[datetime] = None
    _min_request_interval = 2.0  # seconds between requests

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

    def _rate_limit(self) -> None:
        """Apply rate limiting between requests to avoid bot detection."""
        import time
        now = datetime.utcnow()
        if StreamService._last_request_time is not None:
            elapsed = (now - StreamService._last_request_time).total_seconds()
            if elapsed < StreamService._min_request_interval:
                sleep_time = StreamService._min_request_interval - elapsed
                logger.debug(f"Rate limiting: sleeping {sleep_time:.2f}s")
                time.sleep(sleep_time)
        StreamService._last_request_time = datetime.utcnow()

    def _try_piped_api(self, video_id: str) -> Optional[Tuple[str, datetime]]:
        """
        Try to get stream URL from Piped API instances.

        Piped is a privacy-friendly YouTube frontend that can provide
        stream URLs without triggering bot detection.
        """
        for instance in PIPED_INSTANCES:
            try:
                url = f"{instance}/streams/{video_id}"
                logger.debug(f"Trying Piped instance: {instance}")

                with httpx.Client(timeout=10.0) as client:
                    response = client.get(url)

                    if response.status_code == 200:
                        data = response.json()

                        # Get audio streams
                        audio_streams = data.get('audioStreams', [])
                        if audio_streams:
                            # Sort by bitrate, get highest quality
                            audio_streams.sort(key=lambda x: x.get('bitrate', 0), reverse=True)
                            best_audio = audio_streams[0]
                            stream_url = best_audio.get('url')

                            if stream_url:
                                logger.info(f"Got stream URL from Piped ({instance}) for {video_id}")
                                # Piped URLs typically last a few hours
                                expires_at = datetime.utcnow() + timedelta(hours=2)
                                return (stream_url, expires_at)

                        # Fallback to adaptive formats if no audio streams
                        hls = data.get('hls')
                        if hls:
                            logger.info(f"Got HLS stream from Piped ({instance}) for {video_id}")
                            expires_at = datetime.utcnow() + timedelta(hours=2)
                            return (hls, expires_at)

                    elif response.status_code == 500:
                        # Video might be unavailable
                        error_msg = response.json().get('message', '')
                        if 'unavailable' in error_msg.lower():
                            logger.warning(f"Video {video_id} unavailable on Piped")
                            return None

            except Exception as e:
                logger.warning(f"Piped instance {instance} failed for {video_id}: {e}")
                continue

        return None

    def _extract_stream_url(self, video_id: str) -> Tuple[str, datetime]:
        """
        Extract audio stream URL, trying Piped API first then yt-dlp as fallback.

        Args:
            video_id: YouTube video ID

        Returns:
            Tuple of (stream_url, expires_at)

        Raises:
            ValueError: If extraction fails
        """
        # Try Piped API first (avoids bot detection)
        piped_result = self._try_piped_api(video_id)
        if piped_result:
            return piped_result

        logger.debug(f"Piped failed, falling back to yt-dlp for {video_id}")

        # Apply rate limiting for yt-dlp
        self._rate_limit()

        url = f"https://www.youtube.com/watch?v={video_id}"

        try:
            with yt_dlp.YoutubeDL(self._get_ydl_opts()) as ydl:
                info = ydl.extract_info(url, download=False)

                if not info:
                    raise ValueError(f"No info extracted for video {video_id}")

                # Get the best audio format URL
                formats = info.get('formats', [])

                # Try audio-only formats first (no video codec)
                audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('vcodec') == 'none' and f.get('url')]

                if audio_formats:
                    # Prefer browser-compatible formats: m4a (aac), webm (opus), mp3
                    # Sort by: 1) browser compatibility, 2) bitrate
                    def format_score(f):
                        ext = f.get('ext', '')
                        acodec = f.get('acodec', '')
                        abr = f.get('abr', 0) or 0

                        # Prefer m4a/mp4 (aac) and webm (opus) - widely supported
                        if ext in ('m4a', 'mp4') or 'aac' in acodec:
                            compat = 3
                        elif ext == 'webm' or 'opus' in acodec:
                            compat = 2
                        elif ext == 'mp3':
                            compat = 3
                        else:
                            compat = 1

                        return (compat, abr)

                    audio_formats.sort(key=format_score, reverse=True)
                    best_audio = audio_formats[0]
                else:
                    # Fallback to any format with audio and a URL
                    audio_formats = [f for f in formats if f.get('acodec') != 'none' and f.get('url')]
                    if audio_formats:
                        # Prefer formats without video to save bandwidth
                        audio_formats.sort(key=lambda x: (x.get('vcodec') == 'none', x.get('abr', 0) or 0), reverse=True)
                        best_audio = audio_formats[0]
                    else:
                        # Last resort: use the direct URL if available
                        direct_url = info.get('url')
                        if direct_url:
                            logger.info(f"Using direct URL for {video_id}")
                            expires_at = datetime.utcnow() + timedelta(hours=settings.stream_cache_hours)
                            return (direct_url, expires_at)
                        raise ValueError(f"No audio formats found for video {video_id}")

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
