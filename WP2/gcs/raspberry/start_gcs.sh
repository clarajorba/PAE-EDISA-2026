#!/usr/bin/env bash
# Start rosbridge (WebSocket ↔ ROS2) + camera publisher on the Raspberry Pi.
# Usage:  ./start_gcs.sh [camera_device] [width] [height] [fps]
# Example: ./start_gcs.sh 0 640 480 30

DEVICE=${1:-0}
WIDTH=${2:-640}
HEIGHT=${3:-480}
FPS=${4:-30}
TOPIC="/camera/forward/image_raw/compressed"

# Source ROS2 (adjust distro name if needed: humble / iron / jazzy)
source /opt/ros/humble/setup.bash

echo "[GCS] Starting rosbridge on port 9090..."
ros2 launch rosbridge_server rosbridge_websocket_launch.xml &
BRIDGE_PID=$!

# Give rosbridge a moment to bind
sleep 2

echo "[GCS] Starting camera publisher: device=$DEVICE ${WIDTH}x${HEIGHT} @ ${FPS}fps"
python3 "$(dirname "$0")/camera_publisher.py" \
  --ros-args \
  -p device:=$DEVICE \
  -p topic:=$TOPIC \
  -p width:=$WIDTH \
  -p height:=$HEIGHT \
  -p fps:=$FPS \
  -p jpeg_quality:=80 &
CAM_PID=$!

echo "[GCS] Running — bridge PID=$BRIDGE_PID  cam PID=$CAM_PID"
echo "      Connect GCS to ws://$(hostname -I | awk '{print $1}'):9090"
echo "      Press Ctrl+C to stop."

trap "kill $BRIDGE_PID $CAM_PID 2>/dev/null" EXIT INT TERM
wait
