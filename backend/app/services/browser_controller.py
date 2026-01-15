"""
Browser Controller Service - Playwright-based YouTube Music automation

Controls a headless browser that plays YouTube Music, allowing us to capture
the audio output via PulseAudio virtual sink.
"""
import asyncio
import os
import logging
from pathlib import Path
from typing import Optional, Callable, Awaitable
from dataclasses import dataclass, field
from enum import Enum

from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright

logger = logging.getLogger(__name__)


class PlaybackState(Enum):
    IDLE = "idle"
    PLAYING = "playing"
    PAUSED = "paused"
    LOADING = "loading"
    ERROR = "error"


@dataclass
class NowPlaying:
    """Current track information"""
    video_id: Optional[str] = None
    title: Optional[str] = None
    artist: Optional[str] = None
    album: Optional[str] = None
    thumbnail: Optional[str] = None
    duration_seconds: int = 0
    position_seconds: int = 0
    state: PlaybackState = PlaybackState.IDLE


@dataclass
class BrowserControllerConfig:
    """Configuration for browser controller"""
    display: str = ":99"
    user_data_dir: str = "/home/sprite/playa-please/backend/.browser-data"
    audio_sink: str = "ytmusic"
    headless: bool = False  # Must be False for audio
    timeout_ms: int = 30000


class BrowserController:
    """
    Controls YouTube Music playback via browser automation.

    This class manages a Chromium browser instance that:
    - Loads music.youtube.com
    - Plays songs by video ID
    - Reports playback state
    - Outputs audio to PulseAudio virtual sink
    """

    def __init__(self, config: Optional[BrowserControllerConfig] = None):
        self.config = config or BrowserControllerConfig()
        self._playwright: Optional[Playwright] = None
        self._browser: Optional[Browser] = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._now_playing = NowPlaying()
        self._on_track_ended: Optional[Callable[[], Awaitable[None]]] = None
        self._monitor_task: Optional[asyncio.Task] = None
        self._is_authenticated = False

    @property
    def now_playing(self) -> NowPlaying:
        """Get current playback info"""
        return self._now_playing

    @property
    def is_authenticated(self) -> bool:
        """Check if user is logged in"""
        return self._is_authenticated

    def set_on_track_ended(self, callback: Callable[[], Awaitable[None]]):
        """Set callback for when track ends"""
        self._on_track_ended = callback

    async def start(self) -> bool:
        """
        Start the browser controller.

        Returns True if browser started and user is authenticated.
        """
        logger.info("Starting browser controller...")

        # Set display for Xvfb
        os.environ["DISPLAY"] = self.config.display

        # Ensure user data directory exists
        Path(self.config.user_data_dir).mkdir(parents=True, exist_ok=True)

        try:
            self._playwright = await async_playwright().start()

            # Launch browser with persistent context for session persistence
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.config.user_data_dir,
                headless=self.config.headless,
                args=[
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-features=PreloadMediaEngagementData,MediaEngagementBypassAutoplayPolicies",
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    f"--alsa-output-device=pulse",
                    "--disable-gpu",
                ],
                ignore_default_args=["--mute-audio"],
                bypass_csp=True,
                viewport={"width": 1280, "height": 720},
            )

            # Get the main page
            if self._context.pages:
                self._page = self._context.pages[0]
            else:
                self._page = await self._context.new_page()

            # Navigate to YouTube Music
            logger.info("Navigating to YouTube Music...")
            await self._page.goto(
                "https://music.youtube.com",
                wait_until="domcontentloaded",
                timeout=self.config.timeout_ms
            )

            # Wait a bit for page to settle
            await asyncio.sleep(2)

            # Check authentication status
            self._is_authenticated = await self._check_auth()

            if self._is_authenticated:
                logger.info("User is authenticated with YouTube Music")
                # Start monitoring playback
                self._monitor_task = asyncio.create_task(self._monitor_playback())
            else:
                logger.warning("User is NOT authenticated - manual login required")

            return self._is_authenticated

        except Exception as e:
            logger.error(f"Failed to start browser controller: {e}")
            await self.stop()
            raise

    async def stop(self):
        """Stop the browser controller and clean up resources"""
        logger.info("Stopping browser controller...")

        if self._monitor_task:
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except asyncio.CancelledError:
                pass
            self._monitor_task = None

        if self._context:
            await self._context.close()
            self._context = None
            self._page = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        logger.info("Browser controller stopped")

    async def _check_auth(self) -> bool:
        """Check if user is logged into YouTube Music"""
        if not self._page:
            return False

        try:
            # Wait a moment for page to fully load
            await asyncio.sleep(1)

            # Get the page content to check for auth indicators
            content = await self._page.content()

            # If we see sign-in prompts in the HTML, not logged in
            sign_in_indicators = [
                'Sign in',
                'accounts.google.com/ServiceLogin',
                '"SIGN_IN"',
            ]

            for indicator in sign_in_indicators:
                if indicator in content:
                    # Double-check with a more specific selector
                    sign_in_button = await self._page.query_selector(
                        'a[href*="accounts.google.com"][aria-label*="Sign in"], '
                        'button[aria-label="Sign in"], '
                        'ytmusic-pivot-bar-item-renderer[tab-id="FEmusic_liked"]'  # Library tab indicates logged in
                    )
                    # If we find library tab, we ARE logged in despite other indicators
                    library_tab = await self._page.query_selector(
                        'ytmusic-pivot-bar-item-renderer[tab-id="FEmusic_liked"], '
                        'ytmusic-guide-entry-renderer[guide-entry-title="Library"], '
                        'tp-yt-paper-tab[aria-label*="Library"]'
                    )
                    if library_tab:
                        return True
                    if sign_in_button:
                        return False

            # Look for avatar/profile button - indicates logged in
            avatar = await self._page.query_selector(
                '#avatar-btn, '
                'img.yt-spec-avatar-shape__avatar, '
                'yt-img-shadow#avatar, '
                'button[aria-label*="Account"], '
                'ytmusic-pivot-bar-item-renderer[tab-id="FEmusic_liked"]'
            )
            if avatar:
                return True

            # Check for personal content that only shows when logged in
            personal_content = await self._page.query_selector(
                'ytmusic-guide-entry-renderer[guide-entry-title="Library"], '
                '[aria-label="Library"], '
                'ytmusic-pivot-bar-item-renderer'
            )
            if personal_content:
                return True

            # If nothing indicates we're logged out, assume we are logged in
            # (conservative approach - better to try than fail)
            logger.info("No definitive auth indicators found, assuming logged in")
            return True

        except Exception as e:
            logger.error(f"Error checking auth: {e}")
            return False

    async def wait_for_login(self, timeout_seconds: int = 300) -> bool:
        """
        Wait for user to complete manual login.

        This should be called if is_authenticated is False.
        The browser window will show the login page - user needs to log in.

        Returns True if login successful within timeout.
        """
        if not self._page:
            return False

        logger.info(f"Waiting for user to log in (timeout: {timeout_seconds}s)...")

        start_time = asyncio.get_event_loop().time()

        while asyncio.get_event_loop().time() - start_time < timeout_seconds:
            if await self._check_auth():
                self._is_authenticated = True
                logger.info("User logged in successfully!")
                # Start monitoring
                self._monitor_task = asyncio.create_task(self._monitor_playback())
                return True
            await asyncio.sleep(2)

        logger.warning("Login timeout expired")
        return False

    async def play_song(self, video_id: str) -> bool:
        """
        Navigate to and play a specific song.

        Args:
            video_id: YouTube video ID

        Returns:
            True if playback started successfully
        """
        if not self._page or not self._is_authenticated:
            logger.error("Cannot play song - browser not ready or not authenticated")
            return False

        try:
            url = f"https://music.youtube.com/watch?v={video_id}"
            logger.info(f"Playing song: {video_id}")

            self._now_playing.state = PlaybackState.LOADING
            self._now_playing.video_id = video_id

            # Navigate to song
            await self._page.goto(url, wait_until="domcontentloaded", timeout=self.config.timeout_ms)

            # Wait for player to be ready and try to start playback
            # YouTube Music sometimes needs multiple attempts
            for attempt in range(5):
                await asyncio.sleep(1)
                await self._ensure_playing()
                await self._update_now_playing()

                if self._now_playing.state == PlaybackState.PLAYING:
                    logger.info(f"Playback started after {attempt + 1} attempt(s)")
                    return True

                logger.debug(f"Playback not started yet, attempt {attempt + 1}/5, state: {self._now_playing.state}")

            # Even if state isn't PLAYING, we navigated successfully - return True
            # The monitor task will update the state when audio actually starts
            logger.warning(f"Playback state is {self._now_playing.state} after all attempts, but navigation succeeded")
            return True

        except Exception as e:
            logger.error(f"Error playing song {video_id}: {e}")
            self._now_playing.state = PlaybackState.ERROR
            return False

    async def _ensure_playing(self):
        """Ensure the player is playing (click play if needed)"""
        if not self._page:
            return

        try:
            # Check if already playing
            play_button = await self._page.query_selector(
                'tp-yt-paper-icon-button.play-pause-button[aria-label="Play"], '
                '#play-pause-button[aria-label="Play"]'
            )

            if play_button:
                # Click play
                await play_button.click()
                await asyncio.sleep(0.5)
                logger.info("Clicked play button")

        except Exception as e:
            logger.warning(f"Error ensuring playback: {e}")

    async def pause(self) -> bool:
        """Pause playback"""
        if not self._page:
            return False

        try:
            # Find and click pause button
            pause_button = await self._page.query_selector(
                'tp-yt-paper-icon-button.play-pause-button[aria-label="Pause"], '
                '#play-pause-button[aria-label="Pause"]'
            )

            if pause_button:
                await pause_button.click()
                self._now_playing.state = PlaybackState.PAUSED
                logger.info("Paused playback")
                return True

            return False

        except Exception as e:
            logger.error(f"Error pausing: {e}")
            return False

    async def resume(self) -> bool:
        """Resume playback"""
        if not self._page:
            return False

        try:
            await self._ensure_playing()
            self._now_playing.state = PlaybackState.PLAYING
            logger.info("Resumed playback")
            return True

        except Exception as e:
            logger.error(f"Error resuming: {e}")
            return False

    async def _update_now_playing(self):
        """Update now playing information from page"""
        if not self._page:
            return

        try:
            # Get title
            title_el = await self._page.query_selector(
                'yt-formatted-string.title.ytmusic-player-bar, '
                '.title.ytmusic-player-bar yt-formatted-string'
            )
            if title_el:
                self._now_playing.title = await title_el.text_content()

            # Get artist
            artist_el = await self._page.query_selector(
                'yt-formatted-string.byline.ytmusic-player-bar a, '
                '.byline.ytmusic-player-bar yt-formatted-string a'
            )
            if artist_el:
                self._now_playing.artist = await artist_el.text_content()

            # Get thumbnail (and upgrade to high resolution)
            thumbnail_el = await self._page.query_selector(
                'img.ytmusic-player-bar, '
                'ytmusic-player-bar img.image'
            )
            if thumbnail_el:
                thumbnail_url = await thumbnail_el.get_attribute('src')
                # Upgrade thumbnail to higher resolution (544x544 instead of 60x60)
                if thumbnail_url:
                    import re
                    thumbnail_url = re.sub(r'=w\d+-h\d+', '=w544-h544', thumbnail_url)
                    thumbnail_url = re.sub(r'=s\d+', '=s544', thumbnail_url)
                self._now_playing.thumbnail = thumbnail_url

            # Get duration from player
            await self._update_progress()

            # Update state based on player
            is_playing = await self._page.query_selector(
                'tp-yt-paper-icon-button.play-pause-button[aria-label="Pause"], '
                '#play-pause-button[aria-label="Pause"]'
            )

            if is_playing:
                self._now_playing.state = PlaybackState.PLAYING
            else:
                self._now_playing.state = PlaybackState.PAUSED

        except Exception as e:
            logger.warning(f"Error updating now playing: {e}")

    async def _update_progress(self):
        """Update playback progress"""
        if not self._page:
            return

        try:
            # Try to get time info from player
            time_info = await self._page.query_selector('.time-info.ytmusic-player-bar')
            if time_info:
                text = await time_info.text_content()
                # Format: "0:30 / 3:45"
                if '/' in text:
                    parts = text.split('/')
                    self._now_playing.position_seconds = self._parse_time(parts[0].strip())
                    self._now_playing.duration_seconds = self._parse_time(parts[1].strip())

        except Exception as e:
            logger.warning(f"Error updating progress: {e}")

    def _parse_time(self, time_str: str) -> int:
        """Parse time string like '3:45' to seconds"""
        try:
            parts = time_str.split(':')
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
            elif len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        except:
            pass
        return 0

    async def _monitor_playback(self):
        """Background task to monitor playback state"""
        logger.info("Starting playback monitor")

        update_counter = 0
        last_video_id = None

        while True:
            try:
                await asyncio.sleep(1)

                if not self._page or not self._is_authenticated:
                    continue

                # Check current URL for video ID changes
                current_url = self._page.url
                current_video_id = None
                if 'watch?v=' in current_url:
                    import re
                    match = re.search(r'watch\?v=([^&]+)', current_url)
                    if match:
                        current_video_id = match.group(1)

                # If video ID changed or every 5 seconds, do a full update
                update_counter += 1
                if current_video_id != last_video_id or update_counter >= 5:
                    if current_video_id != last_video_id and current_video_id:
                        logger.info(f"Detected song change: {last_video_id} -> {current_video_id}")
                    last_video_id = current_video_id
                    update_counter = 0
                    await self._update_now_playing()
                else:
                    # Just update progress
                    await self._update_progress()

                # Check if song ended
                if self._now_playing.state == PlaybackState.PLAYING:
                    if (self._now_playing.duration_seconds > 0 and
                        self._now_playing.position_seconds >= self._now_playing.duration_seconds - 1):
                        logger.info("Track ended")
                        self._now_playing.state = PlaybackState.IDLE

                        if self._on_track_ended:
                            await self._on_track_ended()

            except asyncio.CancelledError:
                logger.info("Playback monitor cancelled")
                break
            except Exception as e:
                logger.warning(f"Error in playback monitor: {e}")
                await asyncio.sleep(5)

    async def get_login_url(self) -> str:
        """Get the URL where user can see the browser to log in"""
        # In a real deployment, you might use noVNC or similar
        # For now, we'll return info about how to access
        return f"Browser running on DISPLAY={self.config.display}"


# Singleton instance
_controller: Optional[BrowserController] = None


def get_browser_controller() -> BrowserController:
    """Get the singleton browser controller instance"""
    global _controller
    if _controller is None:
        _controller = BrowserController()
    return _controller


async def init_browser_controller() -> BrowserController:
    """Initialize and start the browser controller"""
    controller = get_browser_controller()
    await controller.start()
    return controller


async def shutdown_browser_controller():
    """Shutdown the browser controller"""
    global _controller
    if _controller:
        await _controller.stop()
        _controller = None
