#!/bin/bash
# Setup script for audio pipeline: Xvfb + PulseAudio virtual sink
# This creates the infrastructure for capturing browser audio

set -e

DISPLAY_NUM="${DISPLAY_NUM:-99}"
SINK_NAME="${SINK_NAME:-ytmusic}"

echo "=== Playa Please Audio Setup ==="

# 1. Start Xvfb (virtual display) if not running
if ! pgrep -f "Xvfb :${DISPLAY_NUM}" > /dev/null; then
    echo "Starting Xvfb on display :${DISPLAY_NUM}..."
    Xvfb :${DISPLAY_NUM} -screen 0 1920x1080x24 &
    sleep 1
    echo "Xvfb started with PID $!"
else
    echo "Xvfb already running on :${DISPLAY_NUM}"
fi

export DISPLAY=:${DISPLAY_NUM}

# 2. Start PulseAudio if not running
if ! pgrep -x pulseaudio > /dev/null; then
    echo "Starting PulseAudio..."
    pulseaudio --start --exit-idle-time=-1 2>/dev/null || true
    sleep 1
    echo "PulseAudio started"
else
    echo "PulseAudio already running"
fi

# 3. Create virtual sink for browser audio capture
# Check if sink already exists
if ! pactl list sinks short 2>/dev/null | grep -q "${SINK_NAME}"; then
    echo "Creating virtual audio sink '${SINK_NAME}'..."
    pactl load-module module-null-sink sink_name=${SINK_NAME} sink_properties=device.description="${SINK_NAME}_output"
    echo "Virtual sink created"
else
    echo "Virtual sink '${SINK_NAME}' already exists"
fi

# 4. Set the virtual sink as default
echo "Setting ${SINK_NAME} as default sink..."
pactl set-default-sink ${SINK_NAME} 2>/dev/null || true

# 5. Verify setup
echo ""
echo "=== Setup Complete ==="
echo "DISPLAY=:${DISPLAY_NUM}"
echo "Audio sink: ${SINK_NAME}"
echo "Monitor source: ${SINK_NAME}.monitor (use this for ffmpeg capture)"
echo ""
echo "To capture audio:"
echo "  ffmpeg -f pulse -i ${SINK_NAME}.monitor -acodec libmp3lame -ab 192k -f mp3 pipe:1"
