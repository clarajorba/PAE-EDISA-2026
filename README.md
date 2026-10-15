# PAE-EDISA 2026

> **Autonomous UAV system for warehouse inventory and 3D mapping** — built for EDISA as part of the UPC PAE programme (2025–2026).

A drone equipped with a LiDAR sensor, camera, and onboard computer flies autonomously through a warehouse, builds a real-time 3D map, detects barcodes and packages, and generates a geolocated inventory report — all without manual operation.

---

## Repository Layout

Organised by what each part is and where it runs (until Oct 2026 it was split into `WP2/`, `WP3/` and `src/` — see [`docs/estado/REORGANIZACION.md`](docs/estado/REORGANIZACION.md) for the old → new map).

| Folder | Runs on | Description |
|---|---|---|
| [`ros2/`](ros2/) | Raspberry Pi / simulator | All ROS 2 packages, built with colcon |
| ├ `dron_control/` | | Package `dron_control_sistema`: PX4 control via MAVROS, mission (`cerebro_node`, `mision.json`), SLAM→PX4 bridge |
| ├ `dron_percepcion/` | | Pi camera, barcode detector, image+pose sync |
| ├ `dron_gcs_bridge/` | | Nodes serving the GCS app: service manager, MAVLink bridge, mission planner |
| ├ `dron_bringup/` | | Launch files and config (MAVROS for PX4, TFs, PX4 params) — empty for now |
| └ `third_party/` | | Point-LIO (with local changes) and the Unitree L2 driver (copied, not submodules) |
| [`raspberry/`](raspberry/) | Raspberry Pi | Start scripts, systemd services, MJPEG server, `deploy.sh` |
| [`gcs/`](gcs/README.md) | Laptop | Electron ground control app |
| [`vision/`](vision/README.md) | Laptop | Computer vision: box detection, volumetry, barcodes (formerly WP3) |
| [`sim/`](sim/README.md) | Laptop | Simulation (PX4 SITL setup, Monte Carlo results) |
| [`tools/`](tools/README.md) | Any | Debugging and network test scripts |
| [`docs/`](docs/) | — | `setup/`, `arquitectura/`, `estado/`, `entregables/` |
| [`data/`](data/README.md) | — | Large data kept out of git (rosbags, maps, weights) |

---

## System Overview

```mermaid
flowchart TD
    subgraph DRONE["🚁  DRONE"]
        direction LR

        subgraph SENSORS["Sensors"]
            direction TB
            LiDAR["📡 Unitree 4D LiDAR"]
            CAM["📷 Pi Camera Module"]
            PX["🎮 Pixhawk FC · ArduCopter"]
        end

        subgraph PI["🍓  Raspberry Pi 5  ·  ROS2 Jazzy"]
            direction LR
            SLAM["🗺️ Point-LIO SLAM"]
            MAV["🔌 MAVLink bridge"]
            BAR["📦 Barcode detector"]
            BRAIN["🧠 Brain node"]
            RB["🌐 rosbridge :9090"]
        end

        LiDAR -- "eth0"  --> PI
        CAM   -- "CSI"   --> PI
        PX    -- "UART"  --> PI
    end

    subgraph GCS["💻  GCS Laptop  ·  Electron"]
        direction LR
        DASH["🖥️ Dashboard\nARM · Camera · Map"]
        NAV["🧭 Navigation\nHorizon · GPS · IMU"]
        SLAMV["🗺️ SLAM Viewer\n3D Point Cloud"]
        IMGP["📦 Image Processing\nInventory · Barcodes"]
    end

    RB  -- "Wi-Fi · WebSocket :9090" --> GCS
    CAM -. "MJPEG HTTP :8080" .-> DASH

    style DRONE  fill:#1B3D6F18,stroke:#1B3D6F,stroke-width:2px,color:#ccc
    style SENSORS fill:#ffffff08,stroke:#555,stroke-dasharray:4,color:#aaa
    style PI     fill:#0D1B2Aaa,stroke:#4FC3F7,stroke-width:1.5px,color:#fff
    style GCS    fill:#0D2A1Aaa,stroke:#64D2A4,stroke-width:2px,color:#fff
    style SLAM   fill:#1B3D6F,stroke:#4FC3F7,color:#fff
    style MAV    fill:#1B3D6F,stroke:#4FC3F7,color:#fff
    style BAR    fill:#1B3D6F,stroke:#4FC3F7,color:#fff
    style BRAIN  fill:#1B3D6F,stroke:#4FC3F7,color:#fff
    style RB     fill:#0A4A6E,stroke:#4FC3F7,stroke-width:2px,color:#fff
    style DASH   fill:#0E4A1A,stroke:#64D2A4,color:#fff
    style NAV    fill:#0E4A1A,stroke:#64D2A4,color:#fff
    style SLAMV  fill:#0E4A1A,stroke:#64D2A4,color:#fff
    style IMGP   fill:#0E4A1A,stroke:#64D2A4,color:#fff
    style LiDAR  fill:#2C3E50,stroke:#7F8C8D,color:#ddd
    style CAM    fill:#2C3E50,stroke:#7F8C8D,color:#ddd
    style PX     fill:#2C3E50,stroke:#7F8C8D,color:#ddd
```

---

## Key Results

- **Live 3D mapping** at 800,000 LiDAR points per scan using Point-LIO SLAM
- **Real-time barcode detection** with SLAM-tagged x/y/z position per scan
- **Autonomous waypoint navigation** driven by brain_node + Pixhawk MAVLink
- **Cross-platform desktop app** (Windows / Linux / macOS) — zero ROS needed on the laptop
- **SQLite inventory database** with CSV/Excel export

---

## Video Demo

<p align="center">
  <a href="gcs/docs/assets/demo.mp4">
    <img src="gcs/docs/assets/dashboard.png" width="80%" alt="▶ Click to watch demo"/>
  </a>
  <br/><em>▶ Click to watch the demo video</em>
</p>

---

## Screenshots

<p align="center">
  <img src="gcs/docs/assets/dashboard.png" width="48%"/>
  <img src="gcs/docs/assets/slam.png" width="48%"/>
</p>
<p align="center">
  <img src="gcs/docs/assets/navigation.png" width="48%"/>
  <img src="gcs/docs/assets/barcode.png" width="48%"/>
</p>

---

## Quick Start

```bash
# 1 — Deploy onboard software to the Raspberry Pi
./raspberry/deploy.sh raspi5@<PI_IP>          # ROS 2 packages → ~/slam_ws on the Pi
scp raspberry/* raspi5@<PI_IP>:~/
ssh raspi5@<PI_IP> "pip3 install --break-system-packages flask opencv-python pyzbar pymavlink"
ssh raspi5@<PI_IP> "sudo systemctl enable --now rosbridge.service"

# 2 — Launch the GCS app (laptop)
cd gcs
npm install
npm start
```

---

## Tech Stack

**Onboard (Raspberry Pi 5):** ROS2 Jazzy · Point-LIO SLAM · pymavlink · picamera2 · OpenCV · pyzbar · Flask · rosbridge  
**Ground app:** Electron · Node.js · ROSLIB.js · Chart.js · Leaflet · SQLite3  
**Comms:** MAVLink v2 (UART) · rosbridge WebSocket · MJPEG HTTP  
**Vision:** YOLOv8 · OpenCV · pyzbar

---

## Team

UPC — Universitat Politècnica de Catalunya  
PAE (Projecte d'Aplicació a l'Empresa) 2025–2026  
Client: EDISA

---

## Contributors

<p align="center">
  <img src="gcs/docs/assets/team.jpg" width="80%" alt="The Team"/>
  <br/><em>The Team</em>
</p>

**Students**

Aaron Noguera · Aitor Pitarch · Alejandro de Alvarado · Alejandro Jové · Clara Jorba · Ignacio Blasi · Ignasi Fernández · Jaqueline Khalioulline · Lluís Estapé · Diego Rivas · Marc Elvira · Pablo Sánchez · Patricia Ballester · Samantha Wroblewski

**Professors**

Elisa Sayrol · Javier Ruiz-Hidalgo
