"""
Audio Streamer Service - ffmpeg-based audio capture and streaming

Captures audio from PulseAudio virtual sink and streams it via HTTP.
"""
import asyncio
import subprocess
import logging
from typing import AsyncGenerator, Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class AudioStreamerConfig:
    """Configuration for audio streamer"""
    pulse_source: str = "ytmusic.monitor"
    bitrate: str = "128k"  # Lower bitrate for faster initial buffering
    sample_rate: int = 44100
    channels: int = 2
    format: str = "mp3"
    chunk_size: int = 1024  # Bytes per chunk (smaller for lower latency)


class AudioStreamer:
    """
    Streams audio from PulseAudio virtual sink via ffmpeg.

    This captures the browser's audio output and encodes it to MP3
    for streaming to the frontend.
    """

    def __init__(self, config: Optional[AudioStreamerConfig] = None):
        self.config = config or AudioStreamerConfig()
        self._process: Optional[subprocess.Popen] = None
        self._is_running = False
        self._active_connections = 0

    @property
    def is_running(self) -> bool:
        return self._is_running and self._process is not None

    @property
    def active_connections(self) -> int:
        return self._active_connections

    async def start(self) -> bool:
        """Start the ffmpeg capture process"""
        if self._is_running:
            logger.warning("Audio streamer already running")
            return True

        try:
            # Build ffmpeg command with minimal latency
            cmd = [
                "ffmpeg",
                "-probesize", "32",  # Minimal probe size
                "-analyzeduration", "0",  # No analysis duration
                "-fflags", "+nobuffer+flush_packets",  # Reduce buffering
                "-flags", "low_delay",  # Low delay mode
                "-f", "pulse",  # Input format: PulseAudio
                "-i", self.config.pulse_source,  # Input source
                "-acodec", "libmp3lame",  # MP3 encoder
                "-compression_level", "0",  # Fastest encoding
                "-ab", self.config.bitrate,  # Bitrate
                "-ar", str(self.config.sample_rate),  # Sample rate
                "-ac", str(self.config.channels),  # Channels
                "-f", self.config.format,  # Output format
                "-flush_packets", "1",  # Flush packets immediately
                "-"  # Output to stdout
            ]

            logger.info(f"Starting ffmpeg: {' '.join(cmd)}")

            # Start ffmpeg process
            self._process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,  # Suppress ffmpeg stderr
                bufsize=0  # Unbuffered
            )

            self._is_running = True
            logger.info("Audio streamer started")
            return True

        except Exception as e:
            logger.error(f"Failed to start audio streamer: {e}")
            self._is_running = False
            return False

    async def stop(self):
        """Stop the ffmpeg capture process"""
        if self._process:
            logger.info("Stopping audio streamer...")
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None
            self._is_running = False
            logger.info("Audio streamer stopped")

    async def get_audio_stream(self) -> AsyncGenerator[bytes, None]:
        """
        Get async generator that yields audio chunks.

        This should be used by the streaming endpoint to send audio
        to connected clients.
        """
        if not self._process or not self._process.stdout:
            logger.error("Audio streamer not running")
            return

        self._active_connections += 1
        logger.info(f"New audio stream connection (total: {self._active_connections})")

        try:
            loop = asyncio.get_event_loop()

            while self._is_running:
                try:
                    # Read chunk in thread pool to avoid blocking
                    chunk = await loop.run_in_executor(
                        None,
                        self._process.stdout.read,
                        self.config.chunk_size
                    )

                    if not chunk:
                        # EOF - process may have died
                        if self._process.poll() is not None:
                            logger.warning("ffmpeg process ended unexpectedly")
                            break
                        continue

                    yield chunk

                except Exception as e:
                    logger.error(f"Error reading audio chunk: {e}")
                    break

        finally:
            self._active_connections -= 1
            logger.info(f"Audio stream disconnected (remaining: {self._active_connections})")

    async def restart(self):
        """Restart the audio streamer"""
        await self.stop()
        await asyncio.sleep(0.5)
        await self.start()


# Singleton instance
_streamer: Optional[AudioStreamer] = None


def get_audio_streamer() -> AudioStreamer:
    """Get the singleton audio streamer instance"""
    global _streamer
    if _streamer is None:
        _streamer = AudioStreamer()
    return _streamer


async def init_audio_streamer() -> AudioStreamer:
    """Initialize and start the audio streamer"""
    streamer = get_audio_streamer()
    await streamer.start()
    return streamer


async def shutdown_audio_streamer():
    """Shutdown the audio streamer"""
    global _streamer
    if _streamer:
        await _streamer.stop()
        _streamer = None
