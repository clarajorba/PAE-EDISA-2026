# Reorganización del repo (15/10/2026)

El repo pasó de estar ordenado por Work Packages (`WP2/`, `WP3/`, `src/`) a estar ordenado por **qué es cada cosa y dónde se ejecuta**. No se ha borrado ningún archivo: solo se han movido (con `git mv`, así que `git log --follow <archivo>` sigue mostrando su historia).

La estructura anterior está en la etiqueta **`fin-curso-2025-26`** (`git checkout fin-curso-2025-26`).

## Dónde está ahora cada cosa

| Antes | Ahora |
|---|---|
| `src/point_lio_ros2/`, `src/unilidar_sdk2/` | `ros2/third_party/` |
| `WP2/ros2/` (paquete `dron_control_sistema`) | `ros2/dron_control/` — **el paquete se sigue llamando `dron_control_sistema`** |
| `WP2/ros2/deploy.sh` | `raspberry/deploy.sh` (ahora copia y compila los 4 paquetes propios) |
| `WP2/gcs/raspberry/gcs_control.py`, `mavlink_bridge.py`, `brain_node.py` | `ros2/dron_gcs_bridge/` (paquete nuevo) |
| `WP2/gcs/raspberry/camera_publisher.py`, `barcode_detector.py` | `ros2/dron_percepcion/` (paquete nuevo) |
| `WP2/telemetria/telemetry_publisher.py` | `ros2/dron_percepcion/` |
| `WP2/telemetria/logic_bridge.py` | `ros2/dron_control/dron_control_sistema/` (`ros2 run dron_control_sistema logic_bridge`) |
| `WP2/gcs/raspberry/*.sh`, `*.service`, `mjpeg_server.py`, `README.md` | `raspberry/` |
| Resto de `WP2/telemetria/` | `tools/` |
| `WP2/gcs/` (app Electron) | `gcs/` |
| `WP3/` | `vision/` (por dentro, igual que antes) |
| `WP2/docs/COMUNICACION_ROS2_PIXHAWK.*`, `generar_pdf.py` | `docs/arquitectura/` |
| `WP2/docs/CONTEXTO_PROYECTO.md`, `docs/INVENTARIO.md` | `docs/estado/` |
| `WP2/README.md` | `docs/estado/README_WP2_curso_anterior.md` |
| `docs/SETUP_SIMULADOR.md`, `WP3/docs/Pae conexió raspberry.txt` | `docs/setup/` |
| `Presentación final PAE.pdf` | `docs/entregables/` |
| `WP2/docs/simulation_results/` | `sim/resultados/` |
| `WP2/.gitignore` | sus reglas están en el `.gitignore` de la raíz |

Nuevo: `ros2/dron_bringup/` (vacío, para los launch files y la configuración de MAVROS/PX4) y `data/` (datos grandes fuera de git).

## Cambios de código necesarios para la mudanza

- Los nodos de la Pi se lanzan con `ros2 run <paquete> <nodo>` en lugar de `python3 <ruta>.py`: lo hacen así `gcs_control`, `start_all.sh`, `start_gcs.sh` y `rosbridge_boot.sh`.
- `gcs_control` busca `slam_launch.sh` y `mjpeg_server.py` en `$PAE_RASPBERRY_DIR` (lo exporta `rosbridge_boot.sh`; si no está, en `~`).
- `start_all.sh` y `start_gcs.sh` cargan también `~/slam_ws/install/setup.bash`, que es donde `deploy.sh` compila los paquetes.
- A los scripts de `tools/` que tenían `main()` pero no la llamaban se les ha añadido `if __name__ == '__main__': main()`.
- Test de visión: `from vision.app import captura_segura`; se ejecuta con `python3 -B -m unittest discover -s vision/tests`.

## Qué hay que rehacer en cada máquina

**Portátil (simulador):** el workspace ahora enlaza la carpeta `ros2/` entera:
```bash
rm ~/ros2_ws/src/dron_control_sistema                    # el enlace viejo (apuntaba a WP2/ros2)
ln -s ~/PAE-EDISA-2026/ros2 ~/ros2_ws/src/pae
cd ~/ros2_ws && colcon build --symlink-install --packages-select dron_control_sistema dron_percepcion dron_gcs_bridge dron_bringup
```

**Raspberry:** `./raspberry/deploy.sh <usuario>@<ip>` y volver a copiar `raspberry/*` a `~`. Sin probar todavía en la Pi.
