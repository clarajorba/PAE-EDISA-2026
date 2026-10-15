#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# start_all.sh — Full Drone GCS stack (replaces 3-4 manual terminals)
#
# Starts:
#   1. rosbridge     WebSocket ↔ ROS2, port 9090
#   2. camera (ROS)  sensor_msgs/CompressedImage → /camera/forward/image_raw/compressed
#   3. MJPEG server  HTTP stream → :8080/cam1  (consumed by GCS dashboard)
#   4. SLAM          LiDAR driver + SLAM Toolbox  (--no-slam to skip)
#   5. MAVROS        Flight-controller bridge      (--mavros PORT to enable)
#   6. brain node    Autonomous mission planner    (--brain to enable)
#
# Usage:
#   ./start_all.sh [OPTIONS]
#
# Options:
#   -c | --cam    DEVICE     Camera device index        (default: 0)
#   -r | --res    WxH        Resolution e.g. 1280x720   (default: 640x480)
#   -f | --fps    FPS        Frame rate                 (default: 30)
#   -q | --qual   N          JPEG quality 1-100         (default: 80)
#   -l | --lidar  TYPE       unitree|rplidar|ydlidar|hokuyo  (default: unitree)
#   -p | --port   PORT       LiDAR serial port          (default: /dev/ttyUSB0)
#        --map    FILE       Existing map — SLAM runs in localization mode
#        --brain             Enable brain / mission-planner node
#        --mavros FCTL_PORT  Enable MAVROS  (e.g. /dev/ttyAMA0)
#        --no-slam           Skip SLAM entirely
#        --no-mjpeg          Skip MJPEG HTTP server
#        --no-cam            Skip camera publisher (ROS topic)
#        --ros-distro NAME   ROS2 distro name  (default: jazzy)
# ─────────────────────────────────────────────────────────────────────────────

set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ── Defaults ──────────────────────────────────────────────────────────────────
CAM_DEVICE=0
WIDTH=640
HEIGHT=480
FPS=30
QUALITY=80
LIDAR_TYPE="unitree"
LIDAR_PORT="/dev/ttyUSB0"
MAP_FILE=""
ENABLE_BRAIN=0
ENABLE_MAVROS=0
MAVROS_PORT="/dev/ttyAMA0"
ENABLE_SLAM=1
ENABLE_MJPEG=1
ENABLE_CAM=1
ROS_DISTRO_OVERRIDE="${ROS_DISTRO:-jazzy}"

# ── Argument parsing ──────────────────────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case "$1" in
    -c|--cam)        CAM_DEVICE="$2";                         shift 2 ;;
    -r|--res)        WIDTH="${2%x*}"; HEIGHT="${2#*x}";        shift 2 ;;
    -f|--fps)        FPS="$2";                                shift 2 ;;
    -q|--qual)       QUALITY="$2";                            shift 2 ;;
    -l|--lidar)      LIDAR_TYPE="$2";                         shift 2 ;;
    -p|--port)       LIDAR_PORT="$2";                         shift 2 ;;
    --map)           MAP_FILE="$2";                           shift 2 ;;
    --brain)         ENABLE_BRAIN=1;                          shift   ;;
    --mavros)        ENABLE_MAVROS=1; MAVROS_PORT="$2";       shift 2 ;;
    --no-slam)       ENABLE_SLAM=0;                           shift   ;;
    --no-mjpeg)      ENABLE_MJPEG=0;                          shift   ;;
    --no-cam)        ENABLE_CAM=0;                            shift   ;;
    --ros-distro)    ROS_DISTRO_OVERRIDE="$2";                shift 2 ;;
    *) echo "[GCS] Unknown option: $1"; shift ;;
  esac
done

# ── Source ROS2 ───────────────────────────────────────────────────────────────
source "/opt/ros/$ROS_DISTRO_OVERRIDE/setup.bash"
# Optional workspaces (non-fatal if absent)
source "$HOME/rosbridge_ws/install/setup.bash"      2>/dev/null || true
source "$HOME/unitree_lidar_ros2/install/setup.bash" 2>/dev/null || true
source "$HOME/ros2_ws/install/setup.bash"            2>/dev/null || true
source "$HOME/slam_ws/install/setup.bash"            2>/dev/null || true   # paquetes del repo (deploy.sh)

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_DIR="$HOME/gcs_logs/$(date +%Y%m%d_%H%M%S)"
mkdir -p "$LOG_DIR"

log()  { echo "[GCS $(date +%H:%M:%S)] $*"; }
loge() { echo "[GCS $(date +%H:%M:%S)] ERROR: $*" >&2; }

log "Logging to $LOG_DIR"

# ── PID tracking & cleanup ───────────────────────────────────────────────────
declare -A PIDS

cleanup() {
  log "Shutting down all processes..."
  for name in "${!PIDS[@]}"; do
    pid="${PIDS[$name]}"
    if kill -0 "$pid" 2>/dev/null; then
      log "  Stopping $name (PID $pid)"
      kill "$pid" 2>/dev/null
    fi
  done
  wait 2>/dev/null || true
  log "All stopped. Logs at $LOG_DIR"
}
trap cleanup EXIT INT TERM

# ─────────────────────────────────────────────────────────────────────────────
# 1. rosbridge — WebSocket ↔ ROS2 on port 9090
# ─────────────────────────────────────────────────────────────────────────────
log "Starting rosbridge on :9090 ..."
ros2 launch rosbridge_server rosbridge_websocket_launch.xml \
  > "$LOG_DIR/rosbridge.log" 2>&1 &
PIDS[rosbridge]=$!
sleep 2   # give rosbridge time to bind before other nodes publish

# ─────────────────────────────────────────────────────────────────────────────
# 2. Camera publisher — ROS topic (Pi Camera via picamera2)
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$ENABLE_CAM" == "1" ]]; then
  log "Starting camera publisher (ROS) — /dev/video$CAM_DEVICE  ${WIDTH}x${HEIGHT} @ ${FPS}fps"
  ros2 run dron_percepcion camera_publisher \
    --ros-args \
    -p device:=$CAM_DEVICE \
    -p topic:=/camera/forward/image_raw/compressed \
    -p width:=$WIDTH \
    -p height:=$HEIGHT \
    -p fps:=$FPS \
    -p jpeg_quality:=$QUALITY \
    > "$LOG_DIR/camera_ros.log" 2>&1 &
  PIDS[camera_ros]=$!
fi

# ─────────────────────────────────────────────────────────────────────────────
# 3. MJPEG server — HTTP stream on :8080/cam1  (consumed by GCS dashboard)
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$ENABLE_MJPEG" == "1" ]]; then
  log "Starting MJPEG server on :8080/cam1"
  python3 "$SCRIPT_DIR/mjpeg_server.py" \
    $CAM_DEVICE 8080 $WIDTH $HEIGHT $QUALITY \
    > "$LOG_DIR/mjpeg.log" 2>&1 &
  PIDS[mjpeg]=$!
fi

# ─────────────────────────────────────────────────────────────────────────────
# 4. SLAM — LiDAR driver + SLAM Toolbox
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$ENABLE_SLAM" == "1" ]]; then
  SLAM_ARGS=(--lidar "$LIDAR_TYPE" --port "$LIDAR_PORT")
  [[ -n "$MAP_FILE" ]] && SLAM_ARGS+=(--map "$MAP_FILE")
  log "Starting SLAM — lidar=$LIDAR_TYPE  port=$LIDAR_PORT"
  bash "$SCRIPT_DIR/slam_launch.sh" "${SLAM_ARGS[@]}" \
    > "$LOG_DIR/slam.log" 2>&1 &
  PIDS[slam]=$!
fi

# ─────────────────────────────────────────────────────────────────────────────
# 5. MAVROS — flight-controller bridge (disabled unless --mavros PORT given)
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$ENABLE_MAVROS" == "1" ]]; then
  log "Starting MAVROS on $MAVROS_PORT"
  ros2 launch mavros apm.launch \
    fcu_url:="$MAVROS_PORT:57600" \
    gcs_url:="" \
    > "$LOG_DIR/mavros.log" 2>&1 &
  PIDS[mavros]=$!
fi

# ─────────────────────────────────────────────────────────────────────────────
# 6. Brain node — autonomous mission planner (disabled unless --brain given)
# ─────────────────────────────────────────────────────────────────────────────
if [[ "$ENABLE_BRAIN" == "1" ]]; then
  log "Starting brain node  (DB: ~/brain_data.db)"
  ros2 run dron_gcs_bridge brain_node \
    > "$LOG_DIR/brain.log" 2>&1 &
  PIDS[brain]=$!
fi

# ─────────────────────────────────────────────────────────────────────────────
# Status banner
# ─────────────────────────────────────────────────────────────────────────────
PI_IP=$(hostname -I | awk '{print $1}')
echo ""
log "══════════════════════════════════════════════════"
log "  Drone GCS — all systems running"
log "  rosbridge  ws://$PI_IP:9090"
log "  MJPEG      http://$PI_IP:8080/cam1"
log "  Logs       $LOG_DIR"
log "  Processes:"
for name in "${!PIDS[@]}"; do
  log "    %-14s PID %s" "$name" "${PIDS[$name]}"
done
log "  Press Ctrl+C to stop everything."
log "══════════════════════════════════════════════════"
echo ""

wait
