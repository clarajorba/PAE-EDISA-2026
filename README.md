# PAE-EDISA 2026

> **Autonomous UAV system for warehouse inventory and 3D mapping** — built for EDISA as part of the UPC PAE programme (2025–2026).

A drone equipped with a LiDAR sensor, camera, and onboard computer flies autonomously through a warehouse, builds a real-time 3D map, detects barcodes and packages, and generates a geolocated inventory report — all without manual operation.

---

## Work Packages

| Folder | Work Package | Description |
|---|---|---|
| [`WP2/`](WP2/README.md) | **GCS & Drone Control** | Electron ground control app + ROS2 onboard stack + MAVLink bridge |
| [`WP3/`](WP3/README.md) | **Computer Vision** | Box detection, volumetry estimation, unified pipeline |
| [`WP1/`](WP1/mockup_aruco/planos_aruco/README.md) | **ArUco Localisation** | Marker-based pose estimation mockup |
| [`src/`](src/) | **SLAM Libraries** | Point-LIO and Unitree LiDAR ROS2 driver (submodules) |

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
  <a href="WP2/gcs/docs/assets/demo.mp4">
    <img src="WP2/gcs/docs/assets/slam.png" width="80%" alt="▶ Click to watch demo"/>
  </a>
  <br/><em>▶ Click to watch the demo video</em>
</p>

---

## Screenshots

<p align="center">
  <img src="WP2/gcs/docs/assets/dashboard.png" width="48%"/>
  <img src="WP2/gcs/docs/assets/slam.png" width="48%"/>
</p>
<p align="center">
  <img src="WP2/gcs/docs/assets/navigation.png" width="48%"/>
  <img src="WP2/gcs/docs/assets/barcode.png" width="48%"/>
</p>

---

## Quick Start

```bash
# 1 — Deploy onboard software to the Raspberry Pi
scp WP2/gcs/raspberry/* raspi5@<PI_IP>:~/
ssh raspi5@<PI_IP> "pip3 install --break-system-packages flask opencv-python pyzbar pymavlink"
ssh raspi5@<PI_IP> "sudo systemctl enable --now rosbridge.service"

# 2 — Launch the GCS app (laptop)
cd WP2/gcs
npm install
npm start
```

---

## Tech Stack

**Onboard (Raspberry Pi 5):** ROS2 Jazzy · Point-LIO SLAM · pymavlink · picamera2 · OpenCV · pyzbar · Flask · rosbridge  
**Ground app:** Electron · Node.js · ROSLIB.js · Chart.js · Leaflet · SQLite3  
**Comms:** MAVLink v2 (UART) · rosbridge WebSocket · MJPEG HTTP  
**Vision:** YOLOv8 · OpenCV · pyzbar · ArUco

---

## Team

UPC — Universitat Politècnica de Catalunya  
PAE (Projecte d'Aplicació a l'Empresa) 2025–2026  
Client: EDISA

---

## Contributors

**Students**

Aaron Noguera · Aitor Pitarch · Alejandro de Alvarado · Alejandro Jové · Clara Jorba · Ignacio Blasi · Ignasi Fernández · Jaqueline Khalioulline · Lluís Estapé · Diego Rivas · Marc Elvira · Pablo Sánchez · Patricia Ballester · Samantha Wroblewski

**Professors**

Elisa Sayrol · Javier Ruiz-Hidalgo
