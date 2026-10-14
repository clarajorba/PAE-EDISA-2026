# raspberry/ — Onboard Software Stack

All Python nodes and shell scripts that run on the **Raspberry Pi 5** aboard the drone. They form a complete ROS2 stack — no cloud, no external services needed.

---

## Deployment

```bash
# From your dev machine
scp raspberry/* raspi5@<PI_IP>:~/

# On the Pi — install Python dependencies
pip3 install --break-system-packages flask opencv-python pyzbar pymavlink

# Install systemd services
sudo cp ~/rosbridge.service  /etc/systemd/system/
sudo cp ~/drone-gcs.service  /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now rosbridge.service

# Launch everything manually (optional — systemd handles it on boot)
bash ~/start_all.sh
```

---

## Files

### `gcs_control.py` — Service Manager
ROS2 node that subscribes to `/gcs/cmd` and manages the lifecycle of every other node.  
The GCS app sends `{"action":"start","service":"slam"}` — this node starts or stops the corresponding process and streams its status back on `/gcs/status` at 1 Hz.

**Topics:**
- Sub: `/gcs/cmd` — `std_msgs/String` JSON commands
- Pub: `/gcs/status` — `std_msgs/String` JSON status map

---

### `camera_publisher.py` — Pi Camera → ROS
Uses **picamera2** to capture frames from the Raspberry Pi Camera Module and publish them as `sensor_msgs/CompressedImage` at up to 30 fps.

**Key details:**
- Format: `BGR888` → JPEG encoded, quality configurable
- QoS: `BEST_EFFORT / VOLATILE / KEEP_LAST(1)` — matches what barcode_detector expects
- Topic: `/camera/forward/image_raw/compressed`

**Parameters** (via `--ros-args -p name:=value`):

| Parameter | Default | Description |
|---|---|---|
| `fps` | 30 | Capture frame rate |
| `width` / `height` | 640 × 480 | Resolution |
| `jpeg_quality` | 80 | JPEG quality (1–100) |
| `frame_id` | `camera_forward` | TF frame |

---

### `mjpeg_server.py` — MJPEG HTTP Stream
A minimal Flask server that captures from V4L2 (`cv2.VideoCapture`) and serves an MJPEG stream on `:8080/cam1`. This is what the **Dashboard camera** panel in the GCS app displays.

Uses a different capture path from `camera_publisher.py` (V4L2 vs picamera2), which is why a `BGR→RGB` colour conversion is applied — V4L2 on the RPi Camera returns RGB-ordered data that OpenCV treats as BGR.

```bash
python3 mjpeg_server.py [device] [port] [width] [height] [quality]
# Default: device=0  port=8080  640x480  quality=80
```

---

### `barcode_detector.py` — Vision + Inventory
Subscribes to the Pi Camera ROS topic, runs **pyzbar** barcode/QR detection on every frame (throttled to 4 fps to save CPU), and for each new detection:

1. Draws a green polygon + label overlay on the frame
2. Stamps the detection with the current **SLAM position** (x, y, z, θ) from `/Odometry` or `/tf`
3. Publishes a JSON detection event on `/barcode/detection`
4. Publishes the annotated image on `/barcode/roi/image/compressed`

**Dedup:** the same code is suppressed for 3 seconds to avoid duplicate log entries.

**SLAM overlay:** x / y / z / heading rendered on every frame in the top-left corner so operators can visually confirm position data.

**Topics:**
- Sub: `/camera/forward/image_raw/compressed` (BEST_EFFORT QoS — must match publisher)
- Sub: `/Odometry` (Point-LIO pose)
- Sub: `/tf` (fallback: `camera_init → aft_mapped` transform)
- Pub: `/barcode/roi/image/compressed`
- Pub: `/barcode/detection` — `{"barcode":"P003GUA","slam_x":1.2,"slam_y":-0.5,"slam_z":1.1,"slam_theta":-116.8}`

---

### `brain_node.py` — Autonomous Mission Planner
Reads a waypoint mission from a **SQLite database** (`~/brain_data.db`), tracks the drone's position via SLAM odometry, and streams `geometry_msgs/PoseStamped` setpoints to the flight controller at 10 Hz.

When the drone comes within `1.5 m` of a waypoint it advances to the next one. Mission progress is published to `/brain/planned_path` at 1 Hz for the GCS map to display.

On first run, seeds the DB with a default 5 × 5 m square mission. Edit with any SQLite client to define custom missions.

**Control loop:** 10 Hz setpoint → flight controller  
**Map update:** 1 Hz path publish → GCS

---

### `mavlink_bridge.py` — MAVLink ↔ ROS2
Replaces MAVROS with a lightweight **pymavlink** bridge. Connects to the Pixhawk over serial (auto-detects `/dev/serial0 → ttyAMA10 → ttyUSB0 → ttyACM0`), requests telemetry streams, and republishes as standard ROS2 messages.

**Why not MAVROS?** MAVROS requires binary ROS packages not easily available on RPi5, adds heavy overhead, and had sysid=0 detection issues with the RPi5 RP1 UART chip. This custom bridge handles reconnection, heartbeat parsing, and command sending with ~250 lines of Python.

**Published topics:**

| Topic | Type | Source MAVLink message |
|---|---|---|
| `/drone/vfr` | String (JSON) | `VFR_HUD` |
| `/drone/state` | String (JSON) | `HEARTBEAT` |
| `/drone/motors` | String (JSON) | `SERVO_OUTPUT_RAW` / `RC_CHANNELS` |
| `/drone/gps_status` | String (JSON) | `GPS_RAW_INT` |
| `/mavros/battery` | `BatteryState` | `SYS_STATUS` |
| `/mavros/imu/data` | `Imu` | `ATTITUDE` |
| `/mavros/global_position/global` | `NavSatFix` | `GLOBAL_POSITION_INT` |
| `/mavros/local_position/velocity_body` | `TwistStamped` | `GLOBAL_POSITION_INT` |

**Commands** (send JSON to `/drone/cmd`):
```json
{"action":"arm"}
{"action":"disarm"}
{"action":"mode","mode":"GUIDED"}
{"action":"takeoff","alt":5.0}
{"action":"land"}
```

**Serial configuration:**
```bash
# Required for RPi5 GPIO UART (add to /boot/firmware/config.txt)
enable_uart=1

# Environment overrides
MAV_PORT=/dev/ttyAMA10   # serial port
MAV_BAUD=57600           # baud rate
```

---

### `slam_launch.sh` — LiDAR + SLAM Launcher
Orchestrates the three-terminal manual sequence as a single automated script:

1. Sets Ethernet interface (`eth0`) static IP for the LiDAR
2. Launches `unitree_lidar_ros2` driver (LiDAR → `/unilidar/cloud`)
3. Waits for LiDAR topics to appear
4. Launches **Point-LIO** SLAM (`/cloud_registered`, `/Odometry`, `/tf`)

```bash
bash slam_launch.sh [--lidar unitree|rplidar|ydlidar] [--port /dev/ttyUSB0] [--map existing.map]
```

---

### `start_all.sh` — Full Stack Launcher
One-command startup for all components. Accepts CLI flags to enable/disable individual modules:

```bash
bash start_all.sh [--no-slam] [--no-mjpeg] [--no-cam] [--brain] [--mavros PORT]
```

Starts: rosbridge → camera (ROS) → MJPEG server → SLAM → (optionally) MAVROS + Brain.  
All logs go to `~/gcs_logs/<timestamp>/`.

---

### `rosbridge.service` / `drone-gcs.service` — systemd Services
Enable rosbridge WebSocket server and gcs_control to start automatically on boot:

```bash
sudo systemctl enable rosbridge.service
sudo systemctl status rosbridge.service
```
