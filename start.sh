#!/bin/bash
# Playa Please - Startup Script
#
# This starts the music player server with browser-based audio streaming.
#
# First-time setup:
#   If you haven't logged into YouTube Music yet, run:
#     python /home/sprite/playa-please/backend/scripts/browser-login.py
#
#   This requires a display (X11/VNC). Once logged in, the session persists.

cd /home/sprite/playa-please/backend

echo "Starting Playa Please..."
echo ""
echo "The server will:"
echo "  1. Set up audio environment (Xvfb, PulseAudio)"
echo "  2. Launch a headless browser for YouTube Music"
echo "  3. Check if browser is authenticated"
echo ""
echo "If browser is not authenticated, you'll need to run:"
echo "  python scripts/browser-login.py"
echo ""

exec python -m uvicorn app.main:app --host 0.0.0.0 --port 8000
