#!/usr/bin/env python3
"""
Browser Login Script for Playa Please

This script launches a visible Chromium browser for you to log into
YouTube Music. Once logged in, the session is saved and the main
application will be able to play music.

Usage:
    python browser-login.py

Requirements:
    - A display (X11 or Wayland)
    - Or run via SSH with X forwarding: ssh -X user@host
"""
import asyncio
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from playwright.async_api import async_playwright

USER_DATA_DIR = Path(__file__).parent.parent / ".browser-data"


async def main():
    print("=" * 60)
    print("Playa Please - Browser Login")
    print("=" * 60)
    print()
    print("This will open a Chromium browser for you to log into")
    print("YouTube Music. Once logged in, close the browser and")
    print("the session will be saved for the main application.")
    print()
    print(f"Session data will be saved to: {USER_DATA_DIR}")
    print()

    # Ensure user data directory exists
    USER_DATA_DIR.mkdir(parents=True, exist_ok=True)

    # Check for display
    display = os.environ.get("DISPLAY")
    if not display:
        print("ERROR: No display found!")
        print()
        print("To run this script, you need either:")
        print("  1. A local display (run from desktop environment)")
        print("  2. SSH with X forwarding: ssh -X user@host")
        print("  3. VNC session")
        print()
        sys.exit(1)

    print(f"Using display: {display}")
    print()
    print("Starting browser...")
    print()

    async with async_playwright() as p:
        # Launch visible browser with persistent context
        context = await p.chromium.launch_persistent_context(
            user_data_dir=str(USER_DATA_DIR),
            headless=False,  # Visible browser
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-gpu",
            ],
            viewport={"width": 1280, "height": 800},
        )

        # Get or create page
        page = context.pages[0] if context.pages else await context.new_page()

        # Navigate to YouTube Music
        print("Navigating to YouTube Music...")
        await page.goto("https://music.youtube.com")

        print()
        print("=" * 60)
        print("INSTRUCTIONS:")
        print("=" * 60)
        print()
        print("1. If you see a 'Sign in' button, click it")
        print("2. Log in with your Google account")
        print("3. Wait for YouTube Music to fully load")
        print("4. Close the browser window when done")
        print()
        print("The session will be automatically saved.")
        print("=" * 60)
        print()

        # Wait for browser to close
        try:
            # Keep running until all pages are closed
            while context.pages:
                await asyncio.sleep(1)
        except Exception:
            pass

        await context.close()

    print()
    print("Browser closed. Session saved!")
    print()
    print("You can now start the main application:")
    print("  cd /home/sprite/playa-please/backend")
    print("  uvicorn app.main:app --host 0.0.0.0 --port 8000")
    print()


if __name__ == "__main__":
    asyncio.run(main())
