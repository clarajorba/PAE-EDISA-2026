#!/usr/bin/env bash
# Launch LiDAR driver + SLAM Toolbox on Raspberry Pi.
# Tested with ROS2 Jazzy + rplidar_ros / ydlidar_ros2_driver.
#
# Usage:
#   ./slam_launch.sh                        # RPLiDAR on /dev/ttyUSB0
#   ./slam_launch.sh --port /dev/ttyUSB1    # different port
#   ./slam_launch.sh --lidar ydlidar        # YDLIDAR X4/G4
#   ./slam_launch.sh --map /tmp/my_map      # load existing map (localization mode)

LIDAR="rplidar"
PORT="/dev/ttyUSB0"
BAUD=115200
FRAME="laser"
MAP_FILE=""
PARAMS_DIR="$(dirname "$(realpath "$0")")"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --lidar) LIDAR="$2";    shift 2 ;;
    --port)  PORT="$2";     shift 2 ;;
    --baud)  BAUD="$2";     shift 2 ;;
    --map)   MAP_FILE="$2"; shift 2 ;;
    *) echo "Unknown arg: $1"; shift ;;
  esac
done

source /opt/ros/jazzy/setup.bash
source ~/rosbridge_ws/install/setup.bash 2>/dev/null || true

# Give serial port access without sudo each time
sudo chmod 666 "$PORT" 2>/dev/null || true

echo "[SLAM] driver=$LIDAR  port=$PORT  baud=$BAUD"

# ── LiDAR driver ──────────────────────────────────────────────────────────────
if [ "$LIDAR" = "rplidar" ]; then
  ros2 run rplidar_ros rplidar_composition \
    --ros-args \
    -p serial_port:="$PORT" \
    -p serial_baudrate:=$BAUD \
    -p frame_id:="$FRAME" \
    -p angle_compensate:=true \
    -p scan_mode:=Standard &
  LIDAR_PID=$!

elif [ "$LIDAR" = "ydlidar" ]; then
  ros2 run ydlidar_ros2_driver ydlidar_ros2_driver_node \
    --ros-args \
    -p port:="$PORT" \
    -p baudrate:=$BAUD \
    -p frame_id:="$FRAME" \
    -p lidar_type:=1 \
    -p device_type:=6 &
  LIDAR_PID=$!

elif [ "$LIDAR" = "hokuyo" ]; then
  ros2 run urg_node urg_node_driver \
    --ros-args -p serial_port:="$PORT" -p frame_id:="$FRAME" &
  LIDAR_PID=$!

else
  echo "[SLAM] Unknown lidar type '$LIDAR'. Start it manually."
  LIDAR_PID=""
fi

sleep 2

# ── SLAM Toolbox ──────────────────────────────────────────────────────────────
if [ -n "$MAP_FILE" ]; then
  # Localization mode: load existing map
  echo "[SLAM] Localization mode — map: $MAP_FILE"
  ros2 launch slam_toolbox localization_launch.py \
    slam_params_file:="$PARAMS_DIR/slam_params.yaml" \
    map_file_name:="$MAP_FILE" \
    use_sim_time:=false &
else
  # Mapping mode: build new map
  echo "[SLAM] Mapping mode"
  ros2 launch slam_toolbox online_async_launch.py \
    slam_params_file:="$PARAMS_DIR/slam_params.yaml" \
    use_sim_time:=false &
fi
SLAM_PID=$!

echo "[SLAM] Running — lidar PID=$LIDAR_PID  slam PID=$SLAM_PID"
echo "       Topics: /scan → SLAM Toolbox → /map + /slam_toolbox/pose"
echo "       GCS subscribes automatically when connected to rosbridge."
echo "       Press Ctrl+C to stop."

trap "kill $LIDAR_PID $SLAM_PID 2>/dev/null" EXIT INT TERM
wait
