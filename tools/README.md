# tools/

Scripts sueltos de depuración y pruebas (antes en `WP2/telemetria/`). No forman paquete ROS:
se ejecutan con `python3 tools/<script>.py` después de `source /opt/ros/jazzy/setup.bash`.

| Script | Qué hace |
|---|---|
| `sim_slam.py` | Publica una pose falsa en `/slam/pose` a 10 Hz (probar sin LiDAR) |
| `slam_monitor.py` | Muestra por terminal la pose de `/slam/pose` |
| `telemetry_viewer.py` | Muestra lo que se envía a `/mavros/setpoint_velocity/cmd_vel_unstamped` y `/mavros/vision_pose/pose` |
| `receptordron.py` | (portátil) Recibe imagen + pose de `telemetry_publisher` y las guarda en `~/PAE/demo_output` |
| `monitor_node.py` | (portátil) Escucha `camera/image/compressed` y `telemetry/pose_sync` |
| `network_test.py`, `streamerdron.py`, `artificial_camera_node.py` | Pruebas de red: mensajes de prueba, imagen artificial |

`spy_mavros` (espía ENU→NED→MAVLink) sigue dentro del paquete: `ros2 run dron_control_sistema spy_mavros`.
