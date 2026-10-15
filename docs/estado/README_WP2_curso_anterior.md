# WP2 — Ground Control Station & Drone Control

This work package covers everything needed to fly the drone and visualise its data in real time.

## Structure

```
WP2/
├── gcs/        ← Electron desktop app + Raspberry Pi onboard stack
└── ros2/       ← ROS2 control nodes (cerebro, lidar bridge, MAVLink)
```

## Sub-modules

### [`gcs/`](gcs/README.md) — Drone GCS App
The main deliverable of WP2. A full-stack UAV ground control station:
- **Electron frontend** — Dashboard, Navigation, SLAM, Image Processing tabs
- **Raspberry Pi onboard stack** — ROS2 nodes for camera, SLAM, barcode detection, mission planning, and MAVLink bridge
- Real-time 3D LiDAR map, live camera, autonomous waypoints, barcode inventory

→ **[Full documentation](gcs/README.md)**

### [`ros2/`](ros2/) — ROS2 Control Package
The `dron_control_sistema` ROS2 package with higher-level nodes:

| File | Description |
|---|---|
| `cerebro_node.py` | Mission coordinator — state machine for autonomous ops |
| `lidar_bridge_node.py` | Bridge between LiDAR driver and ROS2 topic graph |
| `mavros_node.py` | MAVROS-based flight controller interface |
| `simulador_dron.py` | Physics-based drone flight simulator |
| `simulacion_montecarlo.py` | Monte Carlo mission simulation |
| `mision.json` | Mission definition file |

See [`COMUNICACION_ROS2_PIXHAWK.md`](ros2/dron_control_sistema/COMUNICACION_ROS2_PIXHAWK.md) for the full ROS2 ↔ Pixhawk communication design.
