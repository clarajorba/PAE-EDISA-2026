# Montar el simulador (PX4 SITL + Gazebo + MAVROS + QGroundControl)

> Hecho el 14/10/2026 en el portátil de Alex: **Xubuntu 24.04.3** (Ubuntu Noble, escritorio Xfce), instalado nativo, **sistema en catalán** (`~/Baixades`, `~/Imatges`…; apt y git responden en catalán).
> Hardware: AMD Ryzen AI 7 445, 14 GB de RAM, gráfica integrada Radeon 840M (driver libre `amdgpu`/Mesa, OpenGL 4.6). No hace falta instalar drivers.
> Todo lo que hay aquí se ha ejecutado y comprobado. Ocupa unos **12 GB** en total.

Versiones que quedan instaladas:

| Pieza | Versión |
|---|---|
| ROS 2 | Jazzy (desktop) |
| MAVROS | 2.16.0 (paquetes apt) |
| PX4-Autopilot | **v1.17.0** (última estable; la misma que QGC instala en la Pixhawk) |
| Gazebo | Harmonic (`gz sim` 8.15) |
| QGroundControl | **v5.1.5** (AppImage estable) |

Los comandos con `sudo` hay que lanzarlos a mano en una terminal (piden contraseña).

---

## 0. Antes de empezar (ya hecho en el portátil de Alex)

La instalación de partida era casi limpia (no había ni `curl` ni `git`).

```bash
sudo apt update && sudo apt install -y curl git          # herramientas básicas
# VS Code: descargar el .deb de https://code.visualstudio.com y luego:
sudo apt install ./code_*_amd64.deb                     # instala VS Code (desde ~/Baixades)
curl -fsSL https://claude.ai/install.sh | bash          # Claude Code (instalador nativo)
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc # para que la terminal encuentre `claude`
git config --global user.name "Nombre Apellidos"        # identidad de git
git config --global user.email "tu@correo"
git clone https://github.com/clarajorba/PAE-EDISA-2026.git ~/PAE-EDISA-2026   # repo (~1,3 GB)
cd ~/PAE-EDISA-2026 && git switch feature/AiM && git pull                        # rama de trabajo (nunca main)
```

Comprobaciones previas útiles: `lsb_release -a` (tiene que ser 24.04), `df -h /` (≥ 20 GB libres), `glxinfo -B` (que diga `Accelerated: yes`).

---

## 1. ROS 2 Jazzy + herramientas de compilación

Guía oficial: <https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html>

```bash
sudo apt clean && sudo apt update && sudo apt full-upgrade -y    # poner el sistema al día antes de instalar ROS (lo pide la guía)
export ROS_APT_SOURCE_VERSION=$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}')   # última versión del paquete que añade el repo de ROS
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo ${UBUNTU_CODENAME:-${VERSION_CODENAME}})_all.deb"   # descargarlo
sudo dpkg -i /tmp/ros2-apt-source.deb                            # añadir el repositorio de ROS 2 a apt
sudo apt update && sudo apt install -y ros-dev-tools ros-jazzy-desktop   # ROS 2 Jazzy + colcon, rosdep, vcs (~5 GB)
sudo rosdep init                                                 # configurar rosdep (una sola vez por máquina)
rosdep update                                                    # descargar su base de datos
echo "source /opt/ros/jazzy/setup.bash" >> ~/.bashrc             # cargar ROS en cada terminal nueva
```

El repositorio *universe* ya venía activado en Xubuntu. El locale `ca_ES.UTF-8` sirve (ROS solo pide UTF-8).

**Comprobar** (dos terminales):
```bash
ros2 run demo_nodes_cpp talker      # terminal 1: publica "Hello World: N"
ros2 run demo_nodes_py listener     # terminal 2: tiene que escribir "I heard: [Hello World: N]"
```

---

## 2. MAVROS + datasets de GeographicLib

```bash
sudo apt install -y ros-jazzy-mavros ros-jazzy-mavros-extras            # MAVROS (puente MAVLink ↔ ROS 2) y plugins extra
sudo /opt/ros/jazzy/lib/mavros/install_geographiclib_datasets.sh       # modelos de geoide/gravedad/magnético (24 MB); sin ellos MAVROS se cierra al arrancar
```

⚠️ El README de MAVROS dice `sudo ros2 run mavros install_geographiclib_datasets.sh`. Eso falla porque `sudo` no carga el entorno de ROS. Hay que llamar al script por su ruta completa, como arriba.

**Comprobar:** `ros2 pkg list | grep mavros` → `mavros`, `mavros_extras`, `mavros_msgs`; y `ls /usr/share/GeographicLib` → `geoids gravity magnetic`.

---

## 3. PX4-Autopilot (SITL) + Gazebo Harmonic

Guía oficial: <https://docs.px4.io/main/en/dev_setup/dev_env_linux_ubuntu.html>

```bash
cd ~ && git clone https://github.com/PX4/PX4-Autopilot.git --recursive -b v1.17.0   # PX4 estable con submódulos (~3 GB); avisa de "detached HEAD", es normal
bash ~/PX4-Autopilot/Tools/setup/ubuntu.sh                                          # dependencias, compilador ARM para la Pixhawk y Gazebo Harmonic (pide sudo dentro)
# REINICIAR el portátil (el script te añade al grupo dialout, necesario para USB/serie)
cd ~/PX4-Autopilot && make px4_sitl gz_x500                                         # compilar y lanzar el SITL con el X500 (1.ª vez ~5–10 min)
```

**Comprobar:** se abre Gazebo con `x500_0` en el suelo. En la consola `pxh>` de esa terminal escribe `commander status` → `Disarmed`, `navigation mode: Hold`, `in failsafe: no`.

- La consola `pxh>` acepta comandos aunque los mensajes de PX4 tapen el prompt. Para cerrar PX4 y Gazebo, escribe `shutdown` (mejor que Ctrl+C).
- Avisos normales al arrancar: `gz_frame_id ... not defined in SDF` (cosmético), `ekf2 missing data` / `system power unavailable` (solo los primeros segundos) y `No connection to the GCS` (se va al abrir QGC).
- PX4 abre un canal MAVLink para cada cliente: **QGC → UDP 14550** y **MAVROS (*Onboard*) → PX4 escucha en 14580 y envía al 14540**.

---

## 4. QGroundControl

Guía oficial: <https://docs.qgroundcontrol.com/master/en/qgc-user-guide/getting_started/download_and_install.html>

```bash
sudo apt install -y libxcb-cursor0                       # la única librería que faltaba (las otras que pide la guía ya estaban)
sudo systemctl mask --now ModemManager.service           # evita que ModemManager "secuestre" el USB de la Pixhawk o de la radio SiK
mkdir -p ~/QGroundControl && cd ~/QGroundControl
curl -L -o QGroundControl-x86_64.AppImage https://github.com/mavlink/qgroundcontrol/releases/download/v5.1.5/QGroundControl-x86_64.AppImage   # versión estable (187 MB)
chmod +x QGroundControl-x86_64.AppImage                  # darle permiso de ejecución
~/QGroundControl/QGroundControl-x86_64.AppImage          # abrirlo (con el SITL en marcha)
```

**Comprobar:** se conecta solo al SITL y arriba sale **"Ready"**, modo Hold, GPS con 10 satélites, y el mapa en el campus Irchel (Zúrich, la ubicación por defecto del SITL). En *Preferences* conviene poner Firmware = PX4 y Vehicle = Multi-Rotor.

La guía apunta al build diario (*master*). Usamos la versión estable de GitHub Releases.

---

## 5. MAVROS conectado al PX4 simulado

```bash
ros2 launch mavros px4.launch fcu_url:=udp://:14540@127.0.0.1:14580    # escucha en 14540 y envía al 14580 de esta máquina
```

Formato de la URL: `udp://[dónde escucho]:[puerto]@[a quién envío]:[puerto]`. En el dron real será el USB de la Pixhawk, p. ej. `fcu_url:=/dev/ttyACM0:57600` (el valor por defecto de `px4.launch`).

MAVROS se queda en marcha mostrando mensajes, así que no hay que cerrarlo. La línea clave es `CON: Got HEARTBEAT, connected. FCU: PX4 Autopilot`. Los `[WARN] VER: ... request timeout` del arranque son reintentos y no importan.

**Comprobar** (en otra terminal):
```bash
ros2 topic echo --once /mavros/state                 # connected: true, mode: AUTO.LOITER (= Hold)
ros2 topic hz /mavros/local_position/pose            # ~30 Hz; la pose está en ENU (x=Este, y=Norte, z=Arriba)
```

---

## 6. Nuestros paquetes ROS 2 (carpeta `ros2/` del repo)

```bash
mkdir -p ~/ros2_ws/src                                                     # workspace colcon, fuera del repo
ln -s ~/PAE-EDISA-2026/ros2 ~/ros2_ws/src/pae                              # enlace a toda la carpeta ros2/ del repo, no copia: los cambios del repo se ven directamente
cd ~/ros2_ws && rosdep check --from-paths src --ignore-src -r              # "All system dependencies have been satisfied"
colcon build --symlink-install --packages-select dron_control_sistema dron_percepcion dron_gcs_bridge dron_bringup   # compilar los nuestros (Point-LIO y el driver del L2 solo hacen falta en la Pi)
source ~/ros2_ws/install/setup.bash                                        # cargar el paquete en esta terminal
ros2 pkg executables dron_control_sistema                                  # tiene que listar 7 nodos
```

Compila sin errores en Jazzy. Pendiente (no impide ejecutar):
- `package.xml` solo declara `mavros_msgs`. Faltan `rclpy`, `std_msgs`, `geometry_msgs`, `tf2_ros`, `ament_index_python`, `python3-numpy`, `python3-matplotlib` y `python3-scipy`. Aquí funciona porque ROS desktop ya los trae; en la Pi `rosdep` no sabría instalarlos.
- Restos de Humble: `deploy.sh` (`/opt/ros/humble`) y los mensajes de ayuda de `pixhawk_menu_node.py` y `mavros_node.py`.
- `colcon test` falla en flake8/pep257 (~650 avisos de estilo, sobre todo en `simulacion_montecarlo.py`). No afecta al funcionamiento.

---

## 7. Primera prueba OFFBOARD con `pixhawk_menu_node`

Hacen falta 4 terminales abiertas a la vez:

| Terminal | Qué corre |
|---|---|
| 1 | `cd ~/PX4-Autopilot && make px4_sitl gz_x500` (PX4 + Gazebo, consola `pxh>`) |
| 2 | `~/QGroundControl/QGroundControl-x86_64.AppImage` |
| 3 | `ros2 launch mavros px4.launch fcu_url:=udp://:14540@127.0.0.1:14580` |
| 4 | `source ~/ros2_ws/install/setup.bash && ros2 run dron_control_sistema pixhawk_menu_node` |

**Secuencia que funciona hoy:**
1. En QGC: **Takeoff** y deslizar para confirmar (arma y sube a ~3 m en `AUTO.TAKEOFF`, luego Hold).
2. En el menú: **`3`** → OFFBOARD. El dron se queda quieto en el aire, porque el nodo envía velocidad 0 a 10 Hz.
3. **`w` / `s` / `a` / `d`** → Norte / Sur / Oeste / Este a 0,3 m/s durante 1 s.
4. **`5`** → AUTO.LAND. Aterriza y se desarma solo.

**Lo que NO funciona del menú (y por qué):**
- **Despegar en OFFBOARD con `r` no funciona.** PX4 tiene un despegue suave: 1 s de arranque de motores (`COM_SPOOLUP_TIME`) y una rampa de 3 s (`MPC_TKO_RAMP_T`) en la que el empuje empieza por debajo del necesario para despegar. Con los valores por defecto no puede subir hasta ~1,4 s después de pedirlo, y cada `r` solo pide subir durante 1 s. A los 10 s de estar armado sin despegar, PX4 desarma solo (`COM_DISARM_PRFLT`). Visto en el código de PX4 (`src/modules/mc_pos_control/Takeoff/Takeoff.cpp`) y en el log `.ulg`.
- **`[4] Despegar`** usa el comando de despegue de MAVLink: PX4 pasa a `AUTO.TAKEOFF` (sale de OFFBOARD) y no arma el dron. Además envía `altitude=1.5` (que MAVLink entiende como altura sobre el nivel del mar) y `lat/lon = 0`.
- **Chorro de `[PX4 ACK] vx=+nan ...`:** cuando PX4 no controla por velocidad (desarmado u otro modo) responde con `NaN`, y el filtro del nodo no lo descarta. El menú sigue funcionando debajo: se puede escribir y pulsar Enter igualmente.
- **Si PX4 cree que está volando pero está en el suelo** (QGC dice "Flying" y solo ofrece Land): desarmar (`2`) se rechaza. Hay que usar **`5`** (aterrizar): detecta el suelo y desarma solo.
- El control es **por velocidad**: cada pulsación no mueve exactamente 0,30 m y el dron deriva un poco. Para volar delante de la estantería habrá que controlar **por posición** (`/mavros/setpoint_position/local`).

---

## 8. Problemas que pueden aparecer

- **"L'aplicació ros2 s'ha aturat inesperadament"** (informe de fallos de Ubuntu): aparece si un `ros2 topic ...` se corta con `timeout` (señal TERM). Es inofensivo; pulsa "No enviïs". Para evitarlo, usa `timeout -s INT ...` o Ctrl+C.
- **Logs de vuelo de PX4 (SITL):** `~/PX4-Autopilot/build/px4_sitl_default/rootfs/log/AAAA-MM-DD/*.ulg`. Se pueden abrir con <https://review.px4.io> o con `pyulog` (lo instala `ubuntu.sh`).
