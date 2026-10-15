#!/usr/bin/env bash
# rosbridge_boot.sh — started by systemd on every boot.
# Brings up rosbridge (port 9090) + the GCS control node (receives dashboard commands).
# Everything else (SLAM, camera, MAVROS, brain) is started on-demand from the app.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

source /opt/ros/${ROS_DISTRO:-jazzy}/setup.bash
source "$HOME/rosbridge_ws/install/setup.bash" 2>/dev/null || true
source "$HOME/slam_ws/install/setup.bash"     2>/dev/null || true

echo "[boot] Starting rosbridge on :9090 ..."
ros2 launch rosbridge_server rosbridge_websocket_launch.xml &
BRIDGE_PID=$!

# Kill rosbridge when this script exits (systemd stop / reboot / crash)
trap "kill $BRIDGE_PID 2>/dev/null; wait" EXIT INT TERM

# Give rosbridge a moment to bind before the control node tries to publish
sleep 3

echo "[boot] Starting GCS control node ..."
# gcs_control busca aquí slam_launch.sh y mjpeg_server.py
export PAE_RASPBERRY_DIR="$SCRIPT_DIR"
exec ros2 run dron_gcs_bridge gcs_control
