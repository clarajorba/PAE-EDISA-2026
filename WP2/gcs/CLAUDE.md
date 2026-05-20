# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
npm start          # run the app in development (Electron window)
npm run build      # package for distribution → dist/
```

No linter or test suite is configured. There is no transpile step — all JS is vanilla ES2020+ loaded directly by Electron/Chromium.

To install dependencies after a fresh clone:
```bash
npm install
```

## Architecture

This is a single-window **Electron** desktop app. The stack has three layers:

### 1. Electron shell (`main.js`)
Opens a `BrowserWindow` (1400×820 min) loading `renderer/index.html` with `contextIsolation: true` and `nodeIntegration: false`. The preload (`preload.js`) is currently empty — nothing is bridged from Node; all communication happens inside the renderer over WebSocket.

### 2. Renderer (`renderer/`)
A single-page app with **no framework, no bundler**. Everything is vanilla JS and Canvas 2D API.

- `renderer/index.html` — all CSS (inline `<style>`) + HTML structure. Four tab sections: `#view-dashboard`, `#view-navigation`, `#view-slam`, `#view-image`.
- `renderer/app.js` — all application logic (~1100 lines). Single file.
- `renderer/lib/roslib.js` — bundled roslibjs, loaded before `app.js`.

**`app.js` internal structure:**
- `S` object — single shared state for all telemetry, updated by ROS subscriptions, consumed by canvas draw functions.
- `connect()` / `subscribe()` — establish ROSLIB.Ros WebSocket connection, then create all topic subscriptions. The URL is stored in `localStorage('ros_url')` (default `ws://localhost:9090`). On connect, automatically attempts MJPEG camera at `http://<same-host>:8080/cam1`.
- `initConnPopover()` — topbar URL popover with subnet scanner (`scanSubnet` probes 40 IPs in parallel via WebSocket, 400 ms timeout; `getLocalIP` uses WebRTC ICE to find local subnet).
- `frame()` — `requestAnimationFrame` loop calling all canvas draw functions every frame.
- `resizeCanvases()` — `ResizeObserver` on layout containers keeps canvas pixel dimensions matched to CSS layout.

**Camera flow (dual path):**
- Dashboard `#cam1`: MJPEG via native `<img>` element → `connectMJPEG()` points it to `http://<pi>:8080/cam1`. Falls back to Canvas test pattern on error, retries every 3 s.
- Image Processing `#icam1` / `#icam2`: ROS `sensor_msgs/CompressedImage` → base64 → `Uint8Array` → `Blob` → `createImageBitmap()` → drawn to canvas by `subCamImage()`.
- Dashboard `#cam1` canvas also subscribes via `subCamImage` (same `/camera/forward/image_raw/compressed` topic) as a secondary path.

**ROS topics subscribed:**

| Topic | Message type | Purpose |
|---|---|---|
| `/mavros/vfr_hud` | `mavros_msgs/VFR_HUD` | Speed, climb rate, heading |
| `/mavros/altitude` | `mavros_msgs/Altitude` | Relative altitude |
| `/mavros/battery` | `sensor_msgs/BatteryState` | Battery % and voltage |
| `/mavros/imu/data` | `sensor_msgs/Imu` | Attitude quaternion → roll/pitch/yaw |
| `/mavros/local_position/velocity_body` | `geometry_msgs/TwistStamped` | Body-frame velocity |
| `/mavros/global_position/global` | `sensor_msgs/NavSatFix` | GPS position + trail |
| `/mavros/gpsstatus` | `mavros_msgs/GPSRAW` | Fix type, satellites |
| `/mavros/state` | `mavros_msgs/State` | Armed state, flight mode |
| `/mavros/rc/out` | `mavros_msgs/RCOut` | Motor PWM (ch 1–6) |
| `/scan` | `sensor_msgs/LaserScan` | LiDAR point cloud |
| `/map` | `nav_msgs/OccupancyGrid` | SLAM occupancy map |
| `/slam_toolbox/pose` | `geometry_msgs/PoseWithCovarianceStamped` | SLAM robot pose |
| `/barcode/detection` | `std_msgs/String` (JSON or plain) | Barcode scan results |
| `/detection/volume` | `std_msgs/String` (JSON) | Volumetry measurements |
| `/camera/forward/image_raw/compressed` | `sensor_msgs/CompressedImage` | Forward camera |
| `/camera/down/image_raw/compressed` | `sensor_msgs/CompressedImage` | Downward camera |

### 3. Raspberry Pi scripts (`raspberry/`)

These run on the Pi (ROS2 Jazzy) and are independent of the Electron app:

- `camera_publisher.py` — picamera2 node publishing `sensor_msgs/CompressedImage`. Uses `BGR888` format (no cv2 color conversion needed). Key params: `device` (camera index), `topic`, `fps`, `width`, `height`, `jpeg_quality`.
- `mjpeg_server.py` — Flask MJPEG server on port 8080, `/cam1` endpoint. Used by the dashboard img element.
- `start_gcs.sh` — launches rosbridge (port 9090) + camera_publisher together.

**Rosbridge** was built from source at Release 2.3.0 (`~/rosbridge_ws`) on the Pi because `ros-jazzy-rosbridge-suite` is not available via apt. Source: `~/rosbridge_ws`.

## Key constraints

- **roslib loaded from `renderer/lib/roslib.js`** (bundled copy), not from `node_modules`, so it works after `electron-builder` packages the app.
- **No Node APIs in renderer** — roslib communicates over browser WebSocket; nothing requires nodeIntegration.
- **Motor layout** — hexacopter, 6 motors. PWM range 1000–2000 µs mapped to 0–100%. Motor positions in `drawHexDiagram()` match PX4/QGC actuator layout (M1–M6 with CW/CCW assignments).
- **SLAM canvas** — occupancy grid rendered cell-by-cell with `fillRect`; LiDAR overlay rendered in SLAM pose coordinate frame (60 px/m scale). Both drawn in `drawSLAM()`, called only when `S.activeView === 'slam'`.
