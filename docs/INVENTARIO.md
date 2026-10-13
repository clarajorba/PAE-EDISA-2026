# Inventario del repositorio PAE-EDISA-2026

> Revisión hecha el 13/10/2026 sobre la rama `feature/AiM` (comparada con `main`, `origin/WP2` y `origin/unificacio-WP3`).
> Solo se ha **leído** código: no se ha ejecutado nada ni se ha tocado la Raspberry. Donde digo "funciona" o "roto" me baso en lo que hace el código, no en pruebas.

---

## 0. Resumen en 10 puntos

1. **Hay tres "líneas" de control distintas y ninguna está terminada**:
   - (a) `WP2/ros2/` → paquete ROS 2 que usa **MAVROS + PX4** (la que os interesa).
   - (b) `WP2/gcs/raspberry/` → scripts que usan **pymavlink + ArduCopter** (sin MAVROS). Es la que usa la app de escritorio (GCS).
   - (c) `WP1/.../planos_aruco/` → usa **MAVSDK** contra un simulador PX4 (puerto UDP 14540). Es un experimento antiguo con marcadores ArUco.
2. **Los archivos que "faltaban" existen todos**: `pixhawk_menu_node.py` y `simulador_dron.py` están en `WP2/ros2/dron_control_sistema/`; `brain_node.py` y `camera_publisher.py` están en `WP2/gcs/raspberry/`.
3. **Sí hay nodos que publican en los topics de MAVROS que necesitáis**, pero son prototipos:
   - `/mavros/vision_pose/pose` → solo `WP2/telemetria/logic_bridge.py` (copia la pose del SLAM tal cual, sin cambiar ejes ni frecuencia).
   - `/mavros/setpoint_position/local` → solo `WP2/gcs/raspberry/brain_node.py` (tiene varios fallos, ver §5).
4. **Por qué no veis `/Odometry`**: el Point-LIO de este repo **está modificado**. Publica la odometría en **`/slam/odom`** (antes de mayo 2026 era `/aft_mapped_to_init`) y además una pose en **`/slam/pose`**. Nunca publica `/Odometry`. Pero `brain_node.py`, `barcode_detector.py` y la GCS escuchan `/Odometry`.
5. **El `mavros_node.py` actual sí habla con MAVROS** (publica velocidad en `/mavros/setpoint_velocity/cmd_vel_unstamped`), no solo en `/drone/cmd_vel` como decía la revisión parcial. Pero publica solo cuando cambia el waypoint (no de forma continua) y sin límite de velocidad, así que OFFBOARD no aguantaría.
6. **La misión `mision.json` vuela siempre a 1 m de altura**: el "alto" de la estantería (4 m) está puesto en el eje Y (horizontal), no en Z. Tal y como está, no recorre la cara de una estantería de arriba abajo.
7. **La app de escritorio (GCS) está pensada para ArduPilot** (botones GUIDED/LOITER/AUTO/STABILIZE, despegue a 5 m por defecto, dibujo de 6 motores) y para SLAM Toolbox 2D (botones que llaman a servicios `/slam_toolbox/...` que nunca están en marcha).
8. **La visión (WP3) no está conectada a ROS**: lee vídeo por TCP desde la Pi (`rpicam-vid`) y usa una distancia fija de 120 cm en lugar de la medida del LiDAR. Hay dos versiones paralelas del pipeline (YOLO-World y GroundingDINO).
9. **Hay mucha duplicación**: los mismos modelos `.pt` copiados 2–3 veces, el PDF de la presentación dos veces en la raíz, dos interfaces gráficas ROS que nadie usa (`gcs_node.py`, `gui_node.py`), etc.
10. **Hay IPs, usuarios y rutas fijas en el código** (192.168.1.x, 172.20.10.2, `raspi5`, `pi`, `~/slam_ws`...). Ver §6.

---

## 1. Ramas

| Rama | Qué tiene |
|---|---|
| `main` | Estado final del curso anterior, tras la "reorganización/limpieza" (PR #4). |
| `feature/AiM` (actual) | `main` + **un solo commit** ("Canvis inicials", 13/10/2026) que añade otra vez `Presentación final PAE.pdf`. El archivo es **idéntico** al que ya había: solo cambia cómo está escrita la "ó" en el nombre (dos formas Unicode), así que ahora hay dos copias. |
| `origin/WP2`, `origin/unificacio-WP3` | Ramas antiguas, **ya incluidas en `main`**. Lo único que tienen y `main` no son cosas que la limpieza borró a propósito (`error_ignasi/`, `MOCKUP_ARUCO/`, `.DS_Store`, una nota de conexión). Nada que recuperar. |

---

## 2. Mapa del repo

```
PAE-EDISA-2026/
├── README.md                     Presentación del proyecto (en inglés). Describe ArduCopter y "navegación autónoma" (ver §6).
├── Presentación final PAE.pdf    Presentación final del curso pasado (×2, duplicada).
├── .gitignore                    Ignora *.pt, *.pth, build/, install/, log/... (pero hay .pt subidos de antes).
├── .gitmodules                   VACÍO. src/ no son submódulos aunque el README lo diga: el código está copiado dentro.
│
├── src/                          ── LiDAR + SLAM (se compila con colcon en la Raspberry, en ~/slam_ws)
│   ├── unilidar_sdk2/            Driver oficial de Unitree para el L2 (SDK en C++ + nodo ROS 2).
│   ├── point_lio_ros2/           Point-LIO (SLAM LiDAR-inercial), MODIFICADO: publica /slam/odom y /slam/pose.
│   └── .claude/settings.local.json  Permisos de Claude Code del PC de otro alumno. Basura.
│
├── WP1/mockup_aruco/             ── Experimento de localización con marcadores ArUco (curso pasado). No se usa en la nueva arquitectura.
│   ├── stream_dron.py / monitor_dron.py   Pi detecta ArUco y envía vídeo+pose al PC por TCP.
│   ├── calibration/, config/     Calibración de cámara y posiciones de marcadores.
│   ├── medir_error_estatico*.py, mediciones/  Medidas de error (108 archivos CSV/JSON/TXT).
│   ├── planos_aruco/             Generador de marcadores + controlador PX4 con MAVSDK (simulación).
│   ├── antiguos/, error_nacho/   Versiones viejas.
│   └── src/ed3ed                 Archivo suelto sin uso aparente.
│
├── WP2/                          ── Control del dron, comunicación y GCS
│   ├── README.md                 Índice de WP2 (enlaza a un .md que no está donde dice).
│   ├── docs/
│   │   ├── COMUNICACION_ROS2_PIXHAWK.md/.pdf   MUY ÚTIL: explica MAVLink, MAVROS, ENU/NED y OFFBOARD con PX4.
│   │   ├── CONTEXTO_PROYECTO.md   Contexto de la simulación (ROS 2 Humble en Docker).
│   │   ├── generar_pdf.py         Convierte el .md anterior a PDF.
│   │   └── simulation_results/    Gráficos e HTML de la simulación Monte Carlo.
│   ├── ros2/                     Paquete ROS 2 "dron_control_sistema" (línea MAVROS + PX4).
│   │   ├── setup.py, package.xml, resource/, test/   Esqueleto del paquete ament_python.
│   │   ├── deploy.sh             Copia el paquete por SSH a la Pi y lo compila (¡usa ROS Humble!).
│   │   ├── CLAUDE.md             Notas de la versión de simulación (desactualizadas en parte).
│   │   └── dron_control_sistema/ Los nodos (cerebro, mavros, lidar_bridge, pixhawk_menu, simulador...) + mision.json.
│   ├── telemetria/               Prototipos sueltos (no forman paquete): puente a vision_pose, cámara+pose, pruebas de red.
│   └── gcs/                      App de escritorio + scripts de la Raspberry (línea pymavlink + ArduCopter).
│       ├── main.js, preload.js, package.json   App Electron.
│       ├── renderer/             Interfaz (index.html, app.js de 1745 líneas, roslib.js).
│       ├── raspberry/            Scripts que corren en la Pi: gcs_control, mavlink_bridge, brain_node, cámara, barcode, arranque.
│       ├── docs/                 Manual PDF, informe técnico (LaTeX/PDF/HTML), capturas, vídeo demo, foto del equipo.
│       ├── README.md             Documentación de la GCS.
│       └── CLAUDE.md             Notas para Claude (desactualizadas: dice ~1100 líneas, topics /mavros/vfr_hud...).
│
└── WP3/                          ── Visión (se ejecuta en el portátil)
    ├── programa_unificado.py     Atajo que llama a app/programa_unificado.py.
    ├── app/programa_unificado.py Lanzador con 3 modos: volumetria, detectar-imagenes, detectar-video.
    ├── config/requirements_unificado.txt
    ├── docs/                     README_UNIFICADO.md + nota de conexión a la Pi (IPs de un iPhone).
    ├── volumetria/               Pipeline "BLOC0..3" con YOLO-World + MobileSAM + lector de códigos (versión A).
    │   └── barcode/deteccio_qr_codi/  Detector de códigos independiente (detect_CB.py) + capturas de prueba.
    ├── UNIFICACIO_FINAL/         Mismo pipeline BLOC0..3 pero con GroundingDINO (versión B) + 51 fotos de resultados.
    ├── deteccion_cajas/          Detector de cajas con GroundingDINO (copia del repo oficial de GroundingDINO + scripts propios).
    ├── modelos/yolo/, models/    Pesos de modelos (.pt), repetidos.
    └── datos/fotos_caixa/        29 fotos de cajas de prueba.
```

---

## 3. Subsistemas

### 3.1 Control del dron / PX4

**Qué hace, en sencillo.** La Pixhawk es el "piloto": mantiene el dron estable y sabe moverse a una posición o velocidad si alguien se la pide. La Raspberry es el "copiloto": decide adónde ir y se lo dice a la Pixhawk. Para que se entiendan hace falta un traductor: **MAVROS** (convierte mensajes de ROS 2 en mensajes MAVLink, el idioma de la Pixhawk, y cambia los ejes de ENU a NED). El modo en el que la Pixhawk obedece a la Raspberry se llama **OFFBOARD**.

En el repo hay **tres** formas distintas de hacer esto:

#### (a) Línea MAVROS + PX4 — `WP2/ros2/dron_control_sistema/` (Raspberry)

| Archivo | Qué hace | Estado |
|---|---|---|
| `pixhawk_menu_node.py` | Menú de teclado para probar la Pixhawk: [3] OFFBOARD, [1] armar, [4] despegar 1,5 m, [5] aterrizar (`AUTO.LAND`), w/a/s/d/r/f mueve a 0,3 m/s durante 1 s, [0] parada. Publica velocidad a 10 Hz de forma continua (ceros cuando no hay orden), que es lo que PX4 necesita. | **Prototipo útil.** Es lo más cercano a lo que necesitáis. Pero: sin posición del SLAM en el EKF2, PX4 rechazará OFFBOARD/despegue. Usa velocidad, no posición. |
| `mavros_node.py` | Recibe el siguiente waypoint (`/cerebro/target`) y calcula una velocidad = destino − posición actual. La publica en MAVROS **y** en `/drone/cmd_vel` (para el simulador). Lee la posición de `/mavros/local_position/pose` o, si no hay, de `/drone/pose`. | **Incompleto.** Solo publica cuando llega un waypoint nuevo (no a ≥10 Hz) → PX4 saldría de OFFBOARD a los 0,5 s. No limita la velocidad. No arma, no cambia de modo, no despega. |
| `spy_mavros.py` | "Espía" de depuración: muestra en colores cómo un comando ENU se convierte a NED y a la trama MAVLink. También tiene teclas para enviar velocidades. | Herramienta de depuración. |
| `simulador_dron.py` | Simulador de juguete: suma la velocidad recibida a la posición y la dibuja en 3D (matplotlib). | Funciona solo como demo; no tiene física real. |
| `simulacion_montecarlo.py`, `simulacion_interactiva.py` | Scripts sueltos (sin ROS) que simulan la misión con ruido y **regeneran `mision.json`**. | Funcionan (offline). |

Cómo se arranca (en la Pi, tras compilar el paquete con colcon; MAVROS tiene que estar arrancado aparte):
```bash
# MAVROS no tiene launch en el repo. Habría que lanzarlo a mano, p. ej.:
ros2 launch mavros px4.launch fcu_url:=/dev/ttyACM0:921600
ros2 run dron_control_sistema pixhawk_menu_node
```
`deploy.sh` copia el paquete a `~/slam_ws/src` por SSH y lo compila, **pero hace `source /opt/ros/humble`** (en la Pi hay Jazzy).

#### (b) Línea pymavlink + ArduCopter — `WP2/gcs/raspberry/mavlink_bridge.py` (Raspberry)

Sustituye a MAVROS con un script propio en Python. Lee telemetría de la Pixhawk (batería, actitud, GPS, velocidad) y la publica con nombres que **imitan** a MAVROS (`/mavros/battery`, `/mavros/imu/data`...) para que la GCS los muestre. Acepta órdenes JSON en `/drone/cmd`: arm, disarm, mode, takeoff, land.

- **Está escrito para ArduCopter**: la tabla de modos (GUIDED=4, LOITER=5...) es de ArduPilot. Con PX4 el modo se mostrará como un número sin sentido y los cambios de modo enviarán códigos equivocados.
- Puerto por defecto 57600 baudios y busca primero los UART GPIO (`/dev/serial0`, `ttyAMA10`...); vuestro cableado es USB `/dev/ttyACM0` a 921600.
- No envía setpoints ni pose de visión: no sirve para vuelo autónomo.
- La GCS envía también `goto` y `vel_stop`, que este script **ignora** en silencio.
- Estado: **funcionaba para telemetría con el dron anterior (ArduPilot)**. Para PX4 hay que sustituirlo por MAVROS.

#### (c) Línea MAVSDK — `WP1/mockup_aruco/planos_aruco/scripts/px4_aruco_controller.py`

Usa la librería MAVSDK (no ROS) contra `udp://:14540`, que es la dirección del **simulador** PX4 SITL. Misión de 196 waypoints (28 estanterías × 7 pisos) guiada por ArUco. **Solo simulación; fuera de la arquitectura actual.**

---

### 3.2 LiDAR / SLAM

**Qué hace.** El LiDAR Unitree L2 lanza láseres y devuelve una nube de puntos del entorno + datos de su IMU interna. Point-LIO junta esas dos cosas y calcula **dónde está el LiDAR** en cada momento (y de paso construye un mapa 3D). Esa posición es la que tendrá que llegar a la Pixhawk para sustituir al GPS.

| Archivo | Qué hace |
|---|---|
| `src/unilidar_sdk2/.../launch/launch.py` | Arranca el driver del L2 por red (`initialize_type: 2` = UDP; Pi 192.168.1.2:6201, L2 192.168.1.62:6101). Publica `/unilidar/cloud` y `/unilidar/imu`. **También abre RViz siempre** (no se puede desactivar con un argumento). El parámetro `serial_port: /dev/ttyACM0` no se usa en modo UDP, pero confunde porque es el mismo puerto que la Pixhawk. |
| `src/point_lio_ros2/launch/mapping_unilidar_l2.launch.py` | Arranca Point-LIO con `config/unilidar_l2.yaml` y `use_imu_as_input: True`. RViz opcional (`rviz:=false`). |
| `src/point_lio_ros2/config/unilidar_l2.yaml` | Parámetros. Ojo: `pcd_save_en: true` con `interval: -1` → guarda **todo** el mapa en memoria hasta cerrar; en vuelos largos puede llenar la RAM de la Pi. |
| `src/point_lio_ros2/src/laserMapping.cpp` | Código de Point-LIO. **Modificado por el equipo** (ver abajo). |
| `WP2/gcs/raspberry/slam_launch.sh` | Script que hace las 3 terminales de golpe: pone IP fija a `eth0`, arranca el driver, espera a que salgan los topics y arranca Point-LIO sin RViz. |
| `WP2/ros2/dron_control_sistema/lidar_bridge_node.py` | Lee la TF `camera_init → aft_mapped` a 10 Hz y publica `[x, y, z, yaw]` en `/drone/pose` (formato propio `Float32MultiArray`). Guarda un CSV por sesión. |
| `WP2/telemetria/slam_monitor.py` | Muestra por terminal la pose de `/slam/pose` (posición + ángulos). Útil para comprobar el SLAM. |

**Topics que publica Point-LIO (según el código de este repo):**

| Topic | Tipo | Comentario |
|---|---|---|
| `/slam/odom` | `nav_msgs/Odometry` | Antes del commit del 20/05/2026 se llamaba `/aft_mapped_to_init` (nombre original de Point-LIO). **Ojo**: si se arranca con `correct_odom_unilidar_l2.launch.py` (que pone `odom_only: True`), este topic pasa a llamarse `/odom_corrected`. Con `mapping_unilidar_l2.launch.py` es `/slam/odom`. |
| `/slam/pose` | `geometry_msgs/PoseStamped` | Añadido por el equipo el 20/05/2026. |
| TF `camera_init → aft_mapped` | TF | La que usa `lidar_bridge_node`. |
| `/cloud_registered`, `/cloud_registered_body`, `/cloud_effected`, `/Laser_map`, `/path` | nubes y trayectoria | La GCS dibuja `/cloud_registered`. |

> **Para comprobar en la Pi**: con Point-LIO en marcha, `ros2 topic list | grep -E "slam|aft_mapped"`. Si sale `/aft_mapped_to_init` y no `/slam/pose`, la Pi tiene compilada la versión anterior al commit del 20/05 (el commit original lo subió el usuario `raspi5` el 18/05).

Cómo se arranca (en la Pi):
```bash
bash ~/slam_launch.sh           # o a mano:
ros2 launch unitree_lidar_ros2 launch.py
ros2 launch point_lio mapping_unilidar_l2.launch.py rviz:=false
ros2 run dron_control_sistema lidar_bridge_node
```

**Estado: funciona en mano** (según vuestro documento). En el repo no hay nada que convierta los ejes del LiDAR a los del dron (el LiDAR no estará montado justo en el centro del dron ni necesariamente con la misma orientación).

---

### 3.3 Comunicación (puentes y telemetría)

Hay dos "carreteras" de datos:

1. **Pi ↔ Pixhawk**: MAVROS (línea a) o `mavlink_bridge.py` (línea b). Ver §3.1.
2. **Pi ↔ portátil**: **rosbridge** en el puerto 9090. Es un servidor que deja que un programa que no es ROS (la app Electron) lea y escriba topics de ROS a través de WebSocket por Wi-Fi. Además hay un servidor de vídeo MJPEG en el puerto 8080.

| Archivo | Dónde | Qué hace | Estado |
|---|---|---|---|
| `WP2/telemetria/logic_bridge.py` | Pi | Lee `/slam/pose` y la reenvía **tal cual** a `/mavros/vision_pose/pose`. Además manda velocidades de prueba (avanza a 0,5 m/s hasta x=5 y "gira"). | **Prototipo.** Es la semilla del puente SLAM→PX4, pero: no convierte ejes del LiDAR al dron, no controla la frecuencia (reenvía al ritmo que llegue), deja el `frame_id` de Point-LIO (`camera_init`)... y mezcla lógica de movimiento que no debería estar ahí. |
| `WP2/telemetria/sim_slam.py` | Pi/PC | Publica una pose falsa en `/slam/pose` a 10 Hz para probar sin LiDAR. | Funciona (prueba). |
| `WP2/telemetria/telemetry_publisher.py` | Pi | Captura cámara (`cv2.VideoCapture(0)`) a 15 fps, publica imagen comprimida + la última pose del SLAM con la misma marca de tiempo (`camera/image/compressed`, `telemetry/pose_sync`). | Prototipo. Empareja con "la última pose", no con la del instante exacto. |
| `WP2/telemetria/receptordron.py` | Portátil | Recibe esas imágenes+poses y las guarda en `~/PAE/demo_output` (solo las 20 últimas). | Prototipo. |
| `WP2/telemetria/telemetry_publisher_cdr.py` / `receptordron_cdr.py` | Pi / servidor | Envío de imágenes por socket TCP a través de un túnel SSH a un servidor de la UPC. | **`receptordron_cdr.py` está roto**: en la línea 10 hay un comando `scp` pegado dentro del código (error de sintaxis). |
| `monitor_node.py`, `telemetry_viewer.py`, `network_test.py`, `test_comms.py`, `streamerdron.py`, `artificial_camera_node.py` | — | Pruebas de red/visualización (mensajes de prueba, imagen azul con texto, etc.). | Pruebas sueltas. |
| `WP2/gcs/raspberry/rosbridge_boot.sh` + `rosbridge.service` | Pi | Al encender la Pi (systemd) arranca rosbridge y `gcs_control.py`. | Funcionaba con la Pi anterior (usuario `raspi5`). |
| `WP2/gcs/raspberry/gcs_control.py` | Pi | "Interruptor remoto": la app manda `{"action":"start","service":"slam"}` a `/gcs/cmd` y este nodo arranca/para el proceso. Publica el estado en `/gcs/status` a 1 Hz. Servicios: slam, camera, camera2, mjpeg, **mavros (que en realidad lanza `mavlink_bridge.py`)**, brain, barcode. | Funcionaba. Hay que cambiar "mavros" para que lance MAVROS de verdad. |
| `WP2/gcs/raspberry/mjpeg_server.py` | Pi | Servidor Flask de vídeo en `:8080/cam1` (lo muestra el dashboard). | Funcionaba. Usa la misma cámara que `camera_publisher.py` por otra vía (V4L2 vs picamera2): probablemente no pueden funcionar a la vez. |

`telemetria/` **no es un paquete ROS**: no tiene `setup.py`, se ejecuta con `python3 archivo.py`.

---

### 3.4 Visión

**Qué hace.** Mira las fotos/vídeo de la estantería, encuentra las cajas, lee sus etiquetas (código de barras CODE39/CODE128, QR) y estima sus medidas. Compara los códigos leídos con un "manifest" (CSV con lo que debería haber).

**Dónde se ejecuta.** En el **portátil** (necesita mucha potencia; GroundingDINO usa GPU si hay). Solo hay un detector ligero (`barcode_detector.py`) pensado para la Pi.

| Archivo | Qué hace | Estado |
|---|---|---|
| `WP3/app/programa_unificado.py` | Lanzador con 3 modos: `volumetria` (versión A), `detectar-imagenes` y `detectar-video` (GroundingDINO). | Funciona (validado con vídeo según vuestro documento). |
| `WP3/volumetria/volumetria_BLOC0_1.py` | **Versión A**: orquestador. Captura frames de `tcp://172.20.10.2:8888` (vídeo de la Pi con `rpicam-vid`) cada 1 s, detecta cajas (YOLO-World + MobileSAM), lee códigos y calcula volumetría. Escribe resultados en `outputs/Resultats_BLOC0`. | Funciona offline. |
| `volumetria_BLOC1/2/3_1.py` | Detección de vértices de la caja / detección y tracking / cálculo de medidas (con distancia fija `DISTANCIA_LIDAR_CM = 120`). | — |
| `WP3/volumetria/lector_codis_barres.py` | Función `detectar_codis(img)` con pyzbar + zxing-cpp, varias escalas y preprocesados. | Funciona. |
| `WP3/UNIFICACIO_FINAL/BLOC0..3.py` | **Versión B** del mismo pipeline usando GroundingDINO en lugar de YOLO. Necesita `deteccion_cajas/weights/groundingdino_swint_ogc.pth`, **que no está en el repo** (hay que descargarlo). Usa otro manifest (`etiquetes_magatzem_manifest.csv`). | Probablemente la más reciente; no se puede ejecutar sin descargar los pesos. |
| `WP3/deteccion_cajas/` | Copia del repositorio oficial de GroundingDINO (carpeta `groundingdino/`, `setup.py`, Dockerfile, demos) + scripts propios (`detector_almacen.py`, `detector_video_almacen.py`, `prueba_detector_almacen*.py`, `segmentador_contornos.py`). `detector_video_almacen` lee de `http://192.168.1.100:8080/video`. | Mezcla de librería y pruebas. |
| `WP3/volumetria/barcode/deteccio_qr_codi/detect_CB.py` | Lector de códigos independiente (892 líneas) con su propio manifest y capturas de prueba. | Versión anterior/paralela de `lector_codis_barres.py`. |
| `WP2/gcs/raspberry/barcode_detector.py` | (Pi) Lee la cámara por ROS, detecta códigos con pyzbar a 4 fps, les pone la posición del SLAM y publica `/barcode/detection` (JSON) e imagen anotada. Coge la pose de `/Odometry` (no existe) o, si no, de la TF `camera_init→aft_mapped` (esta sí funciona). | Funcionaba en la demo. |

Cómo se arranca (portátil):
```powershell
cd WP3
pip install -r config/requirements_unificado.txt
python programa_unificado.py volumetria --fuente-video tcp://<IP_PI>:8888
# En la Pi, antes:  rpicam-vid -t 0 --codec mjpeg --width 1920 --height 1080 --framerate 24 --listen -o tcp://0.0.0.0:8888
```

**Lo importante para la nueva fase**: la visión de WP3 **no recibe la pose del dron** ni usa ROS. El emparejamiento foto↔posición solo existe en `telemetry_publisher.py` (prototipo) y en `barcode_detector.py` (solo códigos, en la Pi).

---

### 3.5 GCS (estación de tierra)

**Qué hace.** Es una app de escritorio (Electron = una web dentro de una ventana) que se conecta a la Pi por rosbridge (`ws://raspi5.local:9090` por defecto; tiene un buscador de IPs en la red). Pestañas: Dashboard (cámara, armar, modos), Navegación (horizonte, GPS, IMU), SLAM (nube de puntos 3D) e Image Processing (códigos detectados, exportar CSV).

| Archivo | Qué es |
|---|---|
| `WP2/gcs/main.js`, `preload.js` | Abren la ventana. Nada más. |
| `WP2/gcs/renderer/index.html` | Toda la interfaz y el CSS. |
| `WP2/gcs/renderer/app.js` | Toda la lógica (1745 líneas). |
| `WP2/gcs/renderer/lib/roslib.js` | Librería para hablar con rosbridge. |

Cómo se arranca (portátil): `cd WP2/gcs && npm install && npm start`.

**Estado: funciona como visor**, pero está pensada para otra configuración:
- Modos de vuelo **de ArduPilot**: GUIDED, LOITER, AUTO, STABILIZE; RTL y "Hold"=LOITER. En PX4 se llaman OFFBOARD, POSCTL, AUTO.LOITER, AUTO.RTL...
- Despegue y "Go to" con altura por defecto **5 m** (peligroso en interiores).
- Dibujo de **6 motores** (hexacóptero F550). El X500 tiene 4.
- Botones de SLAM que llaman a servicios de **SLAM Toolbox** (`/slam_toolbox/save_map`...), que no se usa.
- Escucha `/Odometry` (no existe; tiene plan B por TF, que sí funciona).
- El README dice "base de datos SQLite de inventario": en la app **no hay SQLite**; los códigos se guardan en memoria y se exportan a CSV. La única SQLite es la de misiones de `brain_node.py` en la Pi.

Existen además dos GCS antiguas en ROS (`WP2/ros2/dron_control_sistema/gcs_node.py` con Tkinter y `gui_node.py` con PyQt5) que solo escuchan los topics de la simulación (`/drone/pose`, `/cerebro/target`). `gui_node.py` ni siquiera está registrado en `setup.py`. **Sin uso.**

---

### 3.6 Misión

**Qué hace.** Define la ruta (lista de puntos) y decide cuándo pasar al siguiente.

Hay **dos sistemas de misión** independientes:

| | `cerebro_node.py` + `mision.json` (WP2/ros2) | `brain_node.py` (WP2/gcs/raspberry) |
|---|---|---|
| Ruta | `mision.json`: 233 puntos cada 0,3 m, 3 estanterías en X = 0, 5, 10 m, patrón en zigzag + 44 puntos de retorno. Margen de llegada 0,18 m, **medido solo en XY** (ignora la altura). | SQLite `~/brain_data.db`. Si está vacía crea un **cuadrado de 5×5 m a 5 m de altura**. Margen de llegada 1,5 m. |
| Altura | Z fija = 1 m en **todos** los puntos. El "alto" de la estantería (0–4 m) está en el **eje Y** (ver §6). | 5 m por defecto. |
| Posición que usa | `/drone/pose` (de `lidar_bridge_node` o del simulador). | `/Odometry` (**no existe** con vuestro Point-LIO → nunca arranca). |
| Qué publica | `/cerebro/target` solo al llegar a cada punto. Necesita `mavros_node` para mover el dron. | `/mavros/setpoint_position/local` a 10 Hz + `/brain/planned_path` a 1 Hz para la GCS. |
| Estado | Funciona en simulación. | Nunca se pudo usar en vuelo (ver §5). |

Cómo se arranca la de WP2/ros2 (según `deploy.sh`):
```bash
ros2 run dron_control_sistema lidar_bridge_node
ros2 run dron_control_sistema cerebro_node
ros2 run dron_control_sistema mavros_node
```

`mision.json` lo genera `simulacion_montecarlo.py`, pero el `mision.json` del repo tiene 44 puntos de "Fin: retorno" que ese script **no genera** → el JSON viene de otra versión del script que no está en el repo.

---

## 4. Cómo se conectan: topics de ROS 2

### 4.1 Tabla por nodo

| Nodo (archivo) | Se ejecuta en | Escucha | Publica |
|---|---|---|---|
| `unitree_lidar_ros2_node` (src) | Pi | — (UDP del L2) | `/unilidar/cloud`, `/unilidar/imu` |
| `laserMapping` (Point-LIO, src) | Pi | `/unilidar/cloud`, `/unilidar/imu` | `/slam/odom`, `/slam/pose`, TF `camera_init→aft_mapped`, `/cloud_registered`, `/Laser_map`, `/path`... |
| `lidar_bridge_node` | Pi | TF `camera_init→aft_mapped`, `/cerebro/target` | `/drone/pose` |
| `cerebro_node` | Pi | `/drone/pose` | `/cerebro/target` |
| `mavros_node` | Pi | `/drone/pose`, `/mavros/local_position/pose`, `/mavros/state`, `/cerebro/target` | `/mavros/setpoint_velocity/cmd_vel_unstamped`, `/drone/cmd_vel` |
| `pixhawk_menu_node` | Pi | `/mavros/state`, `/mavros/local_position/pose`, `/mavros/setpoint_raw/target_local` | `/mavros/setpoint_velocity/cmd_vel_unstamped`; servicios `/mavros/cmd/arming`, `/mavros/set_mode`, `/mavros/cmd/takeoff` |
| `spy_mavros` | Pi | `/mavros/setpoint_velocity/cmd_vel_unstamped`, `/cerebro/target`, `/drone/pose`, `/mavros/local_position/pose` | (publica velocidades por teclado) |
| `simulador_dron` | PC | `/drone/cmd_vel` | `/drone/pose` |
| `lidar_node` | — | — | `/drone/pose` (aleatorio; choca con el simulador) |
| `gcs_node`, `gui_node` | PC | `/drone/pose`, `/cerebro/target`, `/drone/cmd_vel` | `gui_node`: `/drone/cmd_vel`, `/cerebro/target`, `/gui/speed_factor` |
| `logic_bridge` (telemetria) | Pi | `/slam/pose` | **`/mavros/vision_pose/pose`**, `/mavros/setpoint_velocity/cmd_vel_unstamped` |
| `sim_slam` (telemetria) | PC/Pi | — | `/slam/pose` (falsa) |
| `telemetry_publisher` | Pi | `/slam/pose` | `camera/image/compressed`, `telemetry/pose_sync` |
| `receptordron`, `monitor_node` | Portátil | `camera/image/compressed`, `telemetry/pose_sync` | — |
| `slam_monitor` | Pi/PC | `/slam/pose` | — |
| `telemetry_viewer` | PC | `/mavros/setpoint_velocity/cmd_vel_unstamped`, `/mavros/vision_pose/pose` | — |
| `gcs_control` | Pi | `/gcs/cmd` | `/gcs/status` |
| `mavlink_bridge` | Pi | `/drone/cmd` | `/drone/vfr`, `/drone/state`, `/drone/motors`, `/drone/gps_status`, `/mavros/battery`, `/mavros/imu/data`, `/mavros/global_position/global`, `/mavros/local_position/velocity_body` |
| `brain_node` | Pi | `/Odometry`, `/mavros/global_position/global` | **`/mavros/setpoint_position/local`**, `/brain/planned_path` |
| `camera_publisher` | Pi | — | `/camera/forward/image_raw/compressed` (o `/camera/down/...`) |
| `barcode_detector` | Pi | `/camera/forward/image_raw/compressed`, `/Odometry`, `/tf` | `/barcode/detection`, `/barcode/roi/image/compressed` |
| App GCS (por rosbridge) | Portátil | `/drone/vfr`, `/drone/state`, `/drone/motors`, `/drone/gps_status`, `/mavros/battery`, `/mavros/imu/data`, `/mavros/local_position/velocity_body`, `/mavros/global_position/global`, `/cloud_registered`, `/Odometry`, `/tf`, `/gcs/status`, `/brain/planned_path`, `/barcode/detection`, `/detection/volume`, imágenes | `/drone/cmd`, `/gcs/cmd`; servicios `/slam_toolbox/*` |

### 4.2 Las cadenas que existen hoy

```
SIMULACIÓN (funciona):
  simulador_dron ──/drone/pose──► cerebro_node ──/cerebro/target──► mavros_node ──/drone/cmd_vel──► simulador_dron

"DEMO REAL" (deploy.sh, nunca voló):
  L2 ─► Point-LIO ─TF─► lidar_bridge_node ─/drone/pose─► cerebro_node ─/cerebro/target─► mavros_node ─► MAVROS ─► PX4
  (falta: nadie manda la pose del SLAM a PX4, así que PX4 no sabe dónde está y no acepta OFFBOARD)

GCS (funcionaba como visor con ArduPilot):
  Pixhawk ─serie─► mavlink_bridge ─/drone/*, /mavros/*─► rosbridge :9090 ─Wi-Fi─► App Electron
  Point-LIO ─/cloud_registered, /tf─► rosbridge ─► App (vista SLAM)
  cámara ─► camera_publisher ─► barcode_detector ─/barcode/detection─► rosbridge ─► App

PROTOTIPO PUENTE SLAM→PX4 (nunca integrado):
  Point-LIO ─/slam/pose─► logic_bridge ─/mavros/vision_pose/pose─► MAVROS ─► EKF2 de PX4
```

**Observación**: hay dos formatos de pose conviviendo: `Float32MultiArray [x,y,z,yaw]` en `/drone/pose` (inventado por el equipo) y `PoseStamped`/`Odometry` estándar (`/slam/pose`, `/slam/odom`, `/mavros/...`). Para la nueva fase conviene quedarse solo con los estándar.

---

## 5. Lo que buscabas: ¿existe o falta?

| Pieza | ¿Existe? | Dónde | Qué hace / problemas |
|---|---|---|---|
| `pixhawk_menu_node` | **Sí** | `WP2/ros2/dron_control_sistema/pixhawk_menu_node.py` (registrado en `setup.py`) | Menú de pruebas PX4 por MAVROS (ver §3.1). Base útil para la primera prueba de OFFBOARD. Dice "F550 (PX4)": el dron anterior era PX4 en esta línea, aunque la GCS asume ArduCopter. |
| `brain_node.py` | **Sí** | `WP2/gcs/raspberry/brain_node.py` (script suelto, no está en el paquete ROS) | Planificador de misión con SQLite (ver §3.6). |
| `camera_publisher.py` | **Sí** | `WP2/gcs/raspberry/camera_publisher.py` | Publica la Pi Camera (picamera2) en `/camera/forward/image_raw/compressed`, JPEG, 640×480 a 30 fps por defecto. Funciona. |
| `simulador_dron` | **Sí** | `WP2/ros2/dron_control_sistema/simulador_dron.py` | Simulador de juguete (ver §3.1). No sirve para probar PX4; para eso haría falta PX4 SITL + Gazebo. |
| Publicador en `/mavros/vision_pose/pose` | **Sí, prototipo** | `WP2/telemetria/logic_bridge.py` | Reenvía `/slam/pose` sin transformar. Faltan: transformar del marco del LiDAR al del dron, publicar a ritmo fijo (~30 Hz), comprobar que la pose es reciente, y configurar EKF2 (`EKF2_EV_CTRL`, `EKF2_HGT_REF`...) — **no hay ningún archivo de parámetros de PX4 en el repo**. |
| Publicador en `/mavros/setpoint_position/local` | **Sí, prototipo** | `WP2/gcs/raspberry/brain_node.py` | Problemas: (1) espera `/Odometry`, que no existe → no publica nunca; (2) no publica setpoints **antes** de pedir OFFBOARD y deja de publicar al llegar al final → PX4 saldría de OFFBOARD; (3) no arma, no cambia de modo, no despega, no aterriza; (4) altura por defecto 5 m; (5) solo mira distancia en XY; (6) no hay parada de emergencia ni límite de velocidad; (7) `frame_id='map'` mientras el SLAM usa `camera_init`. |
| Launch de MAVROS para PX4 | **No** | — | Solo hay `ros2 launch mavros apm.launch fcu_url:=...:57600` en `start_all.sh`, que es el launch de **ArduPilot**. Para PX4 sería `px4.launch` con `/dev/ttyACM0:921600`. |
| Launch files propios (`.launch.py`) | **No** | — | El paquete `dron_control_sistema` no tiene ningún launch file; todo se arranca a mano o con scripts `.sh`. |
| Parámetros de PX4 / QGroundControl | **No** | — | No hay `.params` ni notas de configuración de la Pixhawk. |
| Transformación LiDAR → cuerpo del dron | **No** | — | Ningún archivo publica una TF estática `base_link → lidar` ni corrige ejes. |

---

## 6. Dudas, contradicciones y cosas raras

### 6.1 Código de otra versión (ArduPilot, SLAM 2D, hexacóptero, Humble)

| Dónde | Qué |
|---|---|
| `README.md` raíz, `WP2/gcs/README.md` | Dicen "Pixhawk FC · ArduCopter", "Autonomous waypoint navigation driven by brain_node" y "SQLite inventory database". Según vuestro documento el vuelo autónomo nunca se consiguió, y la SQLite de inventario no existe. |
| `mavlink_bridge.py` | Tabla de modos de ArduCopter, 57600 baudios, heartbeat "para mantener ArduCopter enviando". |
| `start_all.sh` | Lanza `mavros apm.launch` (ArduPilot) a 57600. Sus comentarios dicen "SLAM Toolbox" y acepta `--lidar rplidar|ydlidar|hokuyo` y `--port`, pero `slam_launch.sh` **ignora** esos argumentos y siempre arranca Unitree + Point-LIO. |
| `slam_params.yaml` | Es configuración de **SLAM Toolbox** (2D, `/scan`, `map`/`odom`/`base_link`), no de Point-LIO, aunque el README diga "Point-LIO Configuration… Unitree L1 en un quad de 250 mm". No lo usa ningún script. |
| App GCS (`index.html`, `app.js`) | Modos ArduPilot, 6 motores, servicios de SLAM Toolbox, alturas de 5 m. |
| `deploy.sh`, `pixhawk_menu_node.py`, `mavros_node.py` | Usan/recomiendan **ROS 2 Humble** (`/opt/ros/humble`, `ros-humble-mavros`). La Pi tiene Jazzy. |
| `WP2/docs/CONTEXTO_PROYECTO.md`, `WP2/ros2/CLAUDE.md` | Describen la simulación en Docker Humble. `CONTEXTO_PROYECTO.md` describe un patrón "Z" distinto al que genera el script actual. |
| `WP2/gcs/CLAUDE.md` | Dice que `app.js` tiene ~1100 líneas (tiene 1745) y lista topics (`/mavros/vfr_hud`, `/mavros/altitude`) que la app ya no usa. |
| `WP2/README.md` | Enlaza a `ros2/dron_control_sistema/COMUNICACION_ROS2_PIXHAWK.md`, pero el archivo está en `WP2/docs/`. |
| `WP2/docs/COMUNICACION_ROS2_PIXHAWK.md` | Bien escrito y correcto para PX4, pero dice que EKF2 fusiona "IMU + GPS + barómetro"; en interiores habrá que fusionar la visión externa. |

### 6.2 Problemas de diseño a tener en cuenta

- **Misión en el plano equivocado**: `simulacion_montecarlo.py` define estanterías de 3 m de ancho × 4 m de alto, pero mete la altura en **Y** con Z fija a 1 m. Si se manda tal cual a PX4, el dron se movería 4 m hacia delante/atrás (posible choque con la estantería) en lugar de subir.
- **Coordenadas**: los waypoints están en el sistema de Point-LIO (`camera_init`: origen donde arrancó el SLAM). MAVROS trabaja en su propio `map`/`odom` ENU. Si la pose de visión se envía bien, ambos coinciden; si no, los waypoints apuntarán a otro sitio.
- **`/Odometry` no existe**: `brain_node.py`, `barcode_detector.py` y la GCS lo esperan. Point-LIO publica `/slam/odom` (o `/aft_mapped_to_init` en la versión anterior).
- **Cámara compartida**: `camera_publisher.py` (picamera2) y `mjpeg_server.py` (V4L2) intentan abrir la misma cámara a la vez; `start_all.sh` arranca los dos.
- **RViz en la Pi**: el launch del driver Unitree siempre abre RViz, también desde `slam_launch.sh`. Gasta CPU en vuelo.
- **Memoria de Point-LIO**: `pcd_save_en: true` guarda todo el mapa hasta cerrar.
- **`lidar_node.py`** publica posiciones aleatorias en `/drone/pose`. Si se arranca por error junto a la cadena real, el dron recibiría posiciones falsas.

### 6.3 IPs, usuarios y rutas fijas en el código

| Valor | Archivos |
|---|---|
| `192.168.1.2` (Pi) / `192.168.1.62` (L2), interfaz `eth0` | `src/unilidar_sdk2/.../launch.py`, `WP2/gcs/raspberry/slam_launch.sh` (el comentario dice `eth1`, el código usa `eth0`) |
| `172.20.10.2:8888`, `172.20.10.3` (hotspot de un iPhone) | `WP3/volumetria/volumetria_BLOC0_1.py`, `WP3/UNIFICACIO_FINAL/BLOC0.py`, `WP3/app/programa_unificado.py`, `detect_CB.py`, `WP3/docs/Pae conexió raspberry.txt` |
| `192.168.1.100:8080/video` | `WP3/app/programa_unificado.py` (modo detectar-video) |
| `192.168.137.129` | `WP3/docs/Pae conexió raspberry.txt` |
| `147.83.46.71`, puerto `60001` (servidor UPC) | `WP2/telemetria/receptordron_cdr.py` |
| `ws://raspi5.local:9090`, `raspberrypi.local` | `WP2/gcs/renderer/app.js` |
| `udp://:14540` (simulador) | `WP1/.../px4_aruco_controller.py` |
| Usuario `raspi5`, `/home/raspi5` | `rosbridge.service`, `slam_launch.sh` (visudo), README |
| Usuario `pi`, `%h/drone-gcs/raspberry` | `drone-gcs.service` (no coincide con `rosbridge.service`) |
| `~/slam_ws`, `~/rosbridge_ws`, `~/ros2_ws`, `~/unitree_lidar_ros2`, `~/meu_projecte_ros/ros2_ws` | `deploy.sh`, `start_all.sh`, `rosbridge_boot.sh`, `WP2/ros2/CLAUDE.md` |
| `~/brain_data.db`, `~/gcs_logs`, `~/PAE/demo_output` | `brain_node.py`, `gcs_control.py`, `receptordron.py` |
| `C:\Users\Aitor\Desktop\...` | `src/.claude/settings.local.json` |
| Puerto serie: `/dev/serial0`→`ttyAMA10`→… a 57600 (bridge) vs `/dev/ttyACM0` a 921600 (doc MAVROS) | `mavlink_bridge.py` vs `COMUNICACION_ROS2_PIXHAWK.md` |

### 6.4 Duplicados

| Qué | Copias |
|---|---|
| `Presentación final PAE.pdf` | 2 en la raíz (mismo contenido, nombre con "ó" escrita de dos formas). |
| `yolov8s-world.pt` | 3 (`WP3/models/`, `WP3/modelos/yolo/`, `WP3/volumetria/models/`). |
| `mobile_sam.pt` | 3 (`WP3/models/`, `WP3/volumetria/models/`, `WP3/deteccion_cajas/models/`). Además `.gitignore` ignora `*.pt` pero estos se subieron antes. |
| Pipeline de visión BLOC0–3 | 2 versiones: `WP3/volumetria/` (YOLO) y `WP3/UNIFICACIO_FINAL/` (GroundingDINO). BLOC1 y BLOC3 son casi idénticos. |
| Lector de códigos | `lector_codis_barres.py`, `detect_CB.py`, `barcode_detector.py` (Pi) y la función `detectar_codis_frame` dentro de `UNIFICACIO_FINAL/BLOC0.py`. |
| Manifest de etiquetas | `etiquetes_magatzem_simulades_manifest.csv` en 2 sitios + `etiquetes_magatzem_manifest.csv`. |
| Scripts de arranque en la Pi | `start_all.sh`, `start_gcs.sh`, `rosbridge_boot.sh` (+ `gcs_control.py`) hacen cosas parecidas. |
| Misión | `mision.json`/`cerebro_node` y SQLite/`brain_node`. |
| GCS | App Electron + `gcs_node.py` (Tk) + `gui_node.py` (Qt). |
| Envío de imagen+pose | `telemetry_publisher.py` (ROS) y `telemetry_publisher_cdr.py` (socket). |
| Calibración / error estático ArUco | `WP1/.../calibration/calibrar_camara_pc.py` y `error_nacho/calibrar_camara_pc.py`; `medir_error_estatico*.py` en 3 sitios. |

### 6.5 Archivos sin uso o de prueba

- `WP2/ros2/dron_control_sistema/lidar_node.py`, `gcs_node.py`, `gui_node.py`.
- `WP2/telemetria/`: `network_test.py`, `test_comms.py`, `streamerdron.py`, `artificial_camera_node.py`, `monitor_node.py`, `telemetry_viewer.py`, `telemetry_publisher_cdr.py`, `receptordron_cdr.py` (roto).
- `WP2/gcs/raspberry/slam_params.yaml`, `start_gcs.sh`, `drone-gcs.service` (alternativa a `rosbridge.service`).
- `WP1/mockup_aruco/` entero para la nueva arquitectura (incluye `planos_aruco/scripts/__temp_calc_path.py`, `temp_update.py`, `src/ed3ed`, `antiguos/`, `error_nacho/`, 108 archivos en `mediciones/`).
- `WP3/deteccion_cajas/prueba_detector_almacen.py`, `docker_test.py`, `examples/`, `outputs/`. (**Ojo**: `prueba_detector_almacen2.py` **sí se usa**: `programa_unificado.py detectar-imagenes` lo importa. `detector_video_almacen.py` también, en el modo `detectar-video`.)
- `WP3/models/` y `WP3/modelos/yolo/`: ningún script los referencia. Los modelos que se cargan son los de `WP3/volumetria/models/` y `WP3/deteccion_cajas/models/`. `yolov8n-oiv7.pt` y `yolov8n-seg.pt` no los usa nadie.
- Resultados y fotos subidos al repo: `WP3/UNIFICACIO_FINAL/resultados_fotos_capturades/` (51), `WP3/volumetria/data/fotos_capturades/` (78), `WP3/volumetria/outputs/`, `.../demo_output_detected/` (27).
- `src/point_lio_ros2/Log/` (logs y gráficos del autor original), `src/.../launch/__pycache__/launch.cpython-38.pyc` (Python 3.8 compilado, basura), `src/.claude/`.
- `WP1/mockup_aruco/.github/instructions/codacy.instructions.md` (está en `.gitignore` pero subido igualmente).

---

## 7. Contradicciones con vuestro documento de contexto

| Vuestro documento dice | El repo dice |
|---|---|
| Estamos en `feature/AiM`. | Correcto, pero esa rama solo añade un PDF duplicado respecto a `main`. |
| "Point-LIO no publica `/Odometry`; la pose solo sale por la TF." | Correcto que no hay `/Odometry`, pero **sí publica odometría** en `/slam/odom` (o `/aft_mapped_to_init` si la Pi tiene la versión de antes del 20/05) y una `PoseStamped` en `/slam/pose`. Conviene comprobarlo en la Pi. |
| `logic_bridge.py` "leía una pose simulada (`/slam/pose`)". | `/slam/pose` puede ser la **real**: el Point-LIO modificado la publica. `sim_slam.py` es solo una alternativa para probar sin LiDAR. |
| `mavros_node.py` "no usaba MAVROS: publicaba en `/drone/cmd_vel`". | En esta versión publica en **los dos**: `/mavros/setpoint_velocity/cmd_vel_unstamped` y `/drone/cmd_vel`. Sigue sin límites y sin publicación continua. |
| `pixhawk_menu_node`, `brain_node.py`, `camera_publisher.py`, `simulador_dron` no aparecieron. | Existen los cuatro (ver §5). |
| `src/` = `unilidar_sdk2` + `point_lio_ros2`. | Correcto, pero no son submódulos (`.gitmodules` vacío) y Point-LIO está modificado. |
| Pixhawk por USB `/dev/ttyACM0` a 921600. | Coincide con `COMUNICACION_ROS2_PIXHAWK.md`. **No** coincide con `mavlink_bridge.py` / `start_all.sh` (UART GPIO, 57600). |
| Dron anterior: F550 + Pixhawk 6C. | `pixhawk_menu_node.py` habla de "F550 (PX4)", pero la GCS y `mavlink_bridge.py` asumen ArduCopter. Parece que el curso pasado se probaron ambos firmwares en momentos distintos. |
| Raspberry con Ubuntu 24.04 + Jazzy. | La línea `WP2/ros2` se escribió para Humble (Ubuntu 22.04 / Docker); la línea `WP2/gcs/raspberry` para Jazzy. |
