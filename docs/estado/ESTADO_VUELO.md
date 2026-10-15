# Estado — Vuelo (Pixhawk / PX4 / MAVROS / simulador)
Última actualización: 15/10/2026

<!-- Lo rellena el chat de vuelo. -->

## Hecho
- **14/10 · Simulador en el portátil de Alex.** ROS 2 Jazzy, MAVROS 2.16.0 + datasets
  GeographicLib, PX4 **v1.17.0** (SITL) + Gazebo Harmonic, QGroundControl **v5.1.5**
  (AppImage) y ModemManager desactivado. Guía paso a paso en `docs/setup/SETUP_SIMULADOR.md`.
  URL de MAVROS para el SITL: `udp://:14540@127.0.0.1:14580`.
- **14/10 · `dron_control_sistema` compila en Jazzy.** Workspace `~/ros2_ws` (enlace a `ros2/`,
  `--symlink-install`); los 6 nodos cargan sin errores.
- **14/10 · Primer vuelo OFFBOARD en SITL** con `pixhawk_menu_node`: ROS 2 → MAVROS → PX4
  funciona (despegue con QGC, OFFBOARD, movimiento por velocidad y aterrizaje).
- **15/10 · Despegue en OFFBOARD arreglado (`dbe2e1a`).** `[4]` ya no usa `/mavros/cmd/takeoff`:
  sube a 0,5 m/s de forma continua hasta +1,5 m sobre el punto actual. Se cancela solo si sale
  de OFFBOARD, si se desarma o a los 15 s. Filtro de `NaN` en el ACK. Verificado en SITL y en el
  log de PX4 (sin orden NAV_TAKEOFF; llega a 1,4 m 3,3 s después de despegar).
  Secuencia: `3` → `1` → `4` (antes de 10 s) → `w/a/s/d` → `5`.
- **15/10 · Causas del fallo anterior** (comprobadas en el código de PX4 1.17 y en logs `.ulg`):
  la rampa de despegue suave (`COM_SPOOLUP_TIME` 1 s + `MPC_TKO_RAMP_T` 3 s) necesita una orden
  de subida continua de ~1,4 s; y `CommandTOL` con `lat/lon = 0` fija el destino en 0°,0° y el
  dron no despega nunca. No usar la orden de despegue de MAVLink en interiores.

## Pendiente (en orden)
1. **`package.xml` de `dron_control_sistema`:** declarar `rclpy`, `std_msgs`, `geometry_msgs`,
   `tf2_ros`, `ament_index_python`, `python3-numpy`, `python3-matplotlib`, `python3-scipy`
   (necesario para que `rosdep` las instale en la Pi). **Humble → Jazzy** en
   `pixhawk_menu_node.py`, `mavros_node.py`, `raspberry/deploy.sh` y `raspberry/start_gcs.sh`.
2. **Confirmar el hardware de vuelo (antes de F1):** mando RC + receptor (modelo), versión del
   firmware de la Pixhawk 6X (objetivo: PX4 v1.17.0, la misma del SITL) y radio SiK.
3. **F1 · Puesta a punto del dron real con QGC (hasta 30/10):** firmware, airframe X500 V2,
   calibración de sensores y del mando, modos de vuelo en los interruptores (OFFBOARD,
   posición/altitud, *kill*), *failsafes* y batería. Después, vuelo manual.
4. **MAVROS en la Pi:** comprobar si está instalado (lo apunta el chat SLAM en su inventario) y
   crear un launch propio para PX4 por USB (`/dev/ttyACM0`). Hoy `raspberry/start_all.sh` lanza
   `apm.launch` (ArduPilot).
5. **Puente SLAM → PX4 (riesgo principal, F3):** partir de `logic_bridge.py` (ahora en
   `ros2/dron_control/`): cambio de ejes LiDAR → `base_link` (ENU/FLU), frecuencia fija, y elegir
   `/mavros/vision_pose/pose` o `/mavros/odometry/out` (`/slam/odom` trae velocidad y
   covarianza). Parámetros EKF2 (`EKF2_EV_CTRL`, `EKF2_HGT_REF`, retardo, sin GPS). Probarlo
   primero en SITL. **Prueba de mesa a finales de octubre** (depende de que el chat SLAM entregue
   odometría + extrínseca).
6. **Controlador OFFBOARD por posición (F4):** `/mavros/setpoint_position/local` en lugar de
   velocidad. `mavros_node` solo publica al cambiar de waypoint (PX4 saldría de OFFBOARD).
   Regenerar `mision.json` (la altura de la estantería está en el eje Y y Z fija a 1 m) con
   `simulacion_montecarlo.py` corregido.

## Abierto / dudas
- **¿Tenemos mando RC?** Es el control de emergencia (recuperar el control y *kill*); QGC no lo
  sustituye. Sin mando, PX4 no deja armar fuera del simulador con la configuración por defecto.
- **Puerto serie de la Pixhawk en la Pi:** `mavlink_bridge.py` (pymavlink, ArduPilot) y MAVROS no
  pueden abrir el mismo puerto a la vez. Revisar qué arranca `drone-gcs.service`
  (`start_all.sh --mavros /dev/ttyAMA0`) antes de lanzar MAVROS.
- El control por velocidad del menú deriva y no mueve distancias exactas: válido para pruebas,
  no para volar delante de la estantería.
- `r` (subir) del menú sigue siendo un pulso de 1 s: no sirve para despegar, solo en el aire.
- Al cerrar el SITL, el servidor de Gazebo a veces queda abierto (Ctrl+C; documentado).
- Portátil de Marc con Windows: tiene que instalar Ubuntu 24.04 nativo (arranque dual, no WSL)
  antes de seguir `SETUP_SIMULADOR.md`.
