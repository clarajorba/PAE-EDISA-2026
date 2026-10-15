# renderer/ — GCS Frontend (Electron)

The Drone GCS user interface — a single-page Electron renderer that connects to the Raspberry Pi over a rosbridge WebSocket and visualises all telemetry, video, and sensor data in real time.

No ROS installation is required on the operator's laptop. The app runs on **Windows, Linux, and macOS**.

---

## Files

### `index.html` — UI Shell
Defines the four-tab layout, all panel structure, and global styles. Tabs:

| Tab | Content |
|---|---|
| **DASHBOARD** | Live camera, NAV map, ARM/DISARM, service controls, battery, motors |
| **NAVIGATION** | Artificial horizon, compass, altitude/speed/vspeed charts, flight data table |
| **SLAM** | Live 3D LiDAR point cloud (Canvas), pose, Point-LIO status, loop closures |
| **IMAGE PROCESSING** | Barcode camera stream, detection inventory list, DB log, volumetry panel |

---

### `app.js` — Application Logic

All runtime behaviour: ROS connections, subscriptions, UI updates, and user interactions.

#### Connection
Connects to `ws://<host>:9090` via **ROSLIB.js**. The host is read from the top-bar input field. Reconnects automatically on disconnect.

#### Dashboard
- **ARM / DISARM / mode buttons** → publish JSON to `/drone/cmd`
- **TAKEOFF / LAND / RTL** → publish JSON to `/drone/cmd`
- **Live camera (`CAM 1`)** → `<img>` tag pointing to `http://<host>:8080/cam1` (MJPEG)
- **NAV map** → Canvas drawn at 20 Hz from `/brain/planned_path`; shows real path (blue), planned waypoints (dashed yellow), drone arrow
- **Service panel** → subscribes to `/gcs/status`, publishes to `/gcs/cmd` on button click. Auto-starts camera and MJPEG when barcode service starts
- **Battery ring** → updates from `/mavros/battery`
- **Motor circles** → 5-motor layout, thrust derived from `/drone/motors` PWM values

#### Navigation
- **Artificial horizon** → Canvas redrawn on each `/mavros/imu/data` message; pitch shifts horizon line, roll rotates the disc
- **Compass rose** → SVG-style Canvas, heading from `/drone/vfr`
- **Charts** → Chart.js rolling 60-sample window for altitude, airspeed, vertical speed

#### SLAM
- **Point cloud** → subscribes to `/slam/cloud_2d` (downsampled top-down projection published by a relay node). Points coloured by height using a red→yellow→green→blue gradient
- **Status panel** → `/slam/status` JSON: active/inactive, pose X/Y, orientation, points/scan, TF frames, save path

#### Image Processing
- **Barcode camera** → ROS topic `/barcode/roi/image/compressed` decoded from base64 JPEG
- **Detection list** → builds a live table from `/barcode/detection` events (time, code, product, position)
- **DB log** → shows the last 5 INSERT confirmations
- **Export** → `Exportar CSV / Excel` button serialises the in-memory detection list

#### Auto-start behaviour
When the **CODIS** (barcode) service is started from the Dashboard, `app.js` automatically starts the Camera, Camera2, and MJPEG services if they are not already running — ensuring the barcode feed has a source.

---

### `lib/roslib.js` — ROSLIB.js
Vendored copy of [roslibjs](https://github.com/RobotWebTools/roslibjs). Provides `ROSLIB.Ros`, `ROSLIB.Topic`, and `ROSLIB.Message` — the WebSocket client that bridges JavaScript to the ROS2 topic graph.

---

## ROS Topics Consumed

| Topic | Type | Used in |
|---|---|---|
| `/drone/vfr` | `std_msgs/String` (JSON) | Navigation — heading, speed, altitude |
| `/drone/state` | `std_msgs/String` (JSON) | Status bar — armed/mode/connected |
| `/drone/motors` | `std_msgs/String` (JSON) | Dashboard — motor thrust rings |
| `/drone/gps_status` | `std_msgs/String` (JSON) | Navigation — GPS fix/sats |
| `/mavros/battery` | `sensor_msgs/BatteryState` | Dashboard — battery ring |
| `/mavros/imu/data` | `sensor_msgs/Imu` | Navigation — horizon, attitude |
| `/mavros/global_position/global` | `sensor_msgs/NavSatFix` | Dashboard — lat/lon/alt abs |
| `/mavros/local_position/velocity_body` | `geometry_msgs/TwistStamped` | Navigation — Vx/Vy/Vz |
| `/brain/planned_path` | `std_msgs/String` (JSON) | Dashboard — NAV map |
| `/slam/status` | `std_msgs/String` (JSON) | SLAM tab — status panel |
| `/barcode/detection` | `std_msgs/String` (JSON) | Image Processing — inventory |
| `/barcode/roi/image/compressed` | `sensor_msgs/CompressedImage` | Image Processing — camera |
| `/gcs/status` | `std_msgs/String` (JSON) | Dashboard — service indicators |

## ROS Topics Published

| Topic | Type | Trigger |
|---|---|---|
| `/drone/cmd` | `std_msgs/String` (JSON) | ARM, DISARM, mode, takeoff, land, RTL |
| `/gcs/cmd` | `std_msgs/String` (JSON) | Start/stop service buttons |
