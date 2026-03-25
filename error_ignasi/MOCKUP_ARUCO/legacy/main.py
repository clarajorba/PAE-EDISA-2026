"""
main.py
-------
Punto de entrada principal del sistema de localización de drones
mediante marcadores ArUco en un almacén.

Uso:
    python main.py                        # webcam por defecto
    python main.py --source 1             # segunda cámara
    python main.py --source video.mp4     # archivo de vídeo
    python main.py --source video.mp4 --no-display  # modo headless/log
    python main.py --simulate             # modo simulación (sin cámara)
"""

import cv2
import numpy as np
import argparse
import logging
import json
import time
import sys
from pathlib import Path

# ── Paths del proyecto ────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from src.aruco_detector      import ArucoDetector
from src.warehouse_map        import WarehouseMap
from src.localization         import DroneLocalizer
from src.visualizer           import WarehouseVisualizer
from src.camera_calibration   import load_camera_params

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(levelname)-8s │ %(name)s │ %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("main")


# ─────────────────────────────────────────────────────────────────────────────
# Modo simulación: genera un frame sintético con marcadores dibujados
# ─────────────────────────────────────────────────────────────────────────────

class SimulatedCamera:
    """
    Cámara simulada: proyecta marcadores del mapa sobre un frame negro
    simulando que el dron se mueve por el almacén.
    """

    def __init__(self, warehouse_map: WarehouseMap, camera_matrix: np.ndarray,
                 dist_coeff: np.ndarray, width: int = 1280, height: int = 720):
        self.wmap   = warehouse_map
        self.K      = camera_matrix
        self.D      = dist_coeff
        self.width  = width
        self.height = height
        self.t      = 0.0
        self.aruco_dict = cv2.aruco.getPredefinedDictionary(
            cv2.aruco.DICT_6X6_250
        )

    def read(self):
        """Genera un frame sintético con 2-4 marcadores visibles."""
        self.t += 0.02
        frame = np.zeros((self.height, self.width, 3), dtype=np.uint8)
        frame[:] = (30, 30, 30)  # Fondo oscuro (almacén)

        # Posición simulada del dron (trayectoria circular)
        r   = 5.0
        cx  = self.wmap.width_m  / 2
        cy  = self.wmap.height_m / 2
        dz  = 2.0
        dx  = cx + r * np.cos(self.t)
        dy  = cy + r * np.sin(self.t)

        # Proyectar un marcador de prueba visible
        marker_size = self.wmap.marker_size_m
        half = marker_size / 2

        for wm in self.wmap.all_markers()[:4]:
            # Vector del dron al marcador
            rel = wm.position - np.array([dx, dy, dz])
            dist = np.linalg.norm(rel)
            if dist > 6.0:
                continue

            # Proyectar el centro del marcador en la imagen (simplificado)
            fx, fy = self.K[0, 0], self.K[1, 1]
            ppx, ppy = self.K[0, 2], self.K[1, 2]

            # Escena local de la cámara (sin rotación en la sim)
            lx, ly, lz = rel[0], rel[2], max(rel[2], 0.5)
            u = int(fx * lx / lz + ppx)
            v = int(fy * ly / lz + ppy)

            # Dibujar marcador sintético
            sz = max(20, int(fx * marker_size / max(dist, 0.5)))
            if 0 < u < self.width and 0 < v < self.height:
                marker_img = cv2.aruco.generateImageMarker(
                    self.aruco_dict, wm.marker_id, sz
                )
                mh, mw = marker_img.shape
                x0 = max(0, u - mw // 2)
                y0 = max(0, v - mh // 2)
                x1 = min(self.width,  x0 + mw)
                y1 = min(self.height, y0 + mh)
                mx0 = 0; my0 = 0
                mw_crop = x1 - x0
                mh_crop = y1 - y0
                if mw_crop > 0 and mh_crop > 0:
                    region = marker_img[my0:my0+mh_crop, mx0:mx0+mw_crop]
                    roi    = frame[y0:y1, x0:x1]
                    region_bgr = cv2.cvtColor(region, cv2.COLOR_GRAY2BGR)
                    if roi.shape == region_bgr.shape:
                        frame[y0:y1, x0:x1] = region_bgr

        # Añadir info de posición simulada
        cv2.putText(frame,
                    f"[SIM] Dron: ({dx:.1f}, {dy:.1f}, {dz:.1f})m",
                    (10, self.height - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (150, 150, 255), 1)
        return True, frame


# ─────────────────────────────────────────────────────────────────────────────
# Bucle principal
# ─────────────────────────────────────────────────────────────────────────────

def run(args):
    # ── Cargar configuraciones ───────────────────────────────────────────────
    logger.info("Cargando configuración del almacén...")
    wmap = WarehouseMap.from_config(str(ROOT / "config" / "warehouse_config.json"))
    wmap.print_summary()

    logger.info("Cargando parámetros de cámara...")
    K, D = load_camera_params(str(ROOT / "config" / "camera_params.json"))

    # ── Instanciar módulos ────────────────────────────────────────────────────
    detector   = ArucoDetector(K, D,
                               marker_size_m=wmap.marker_size_m,
                               dict_name=wmap.aruco_dict)
    localizer  = DroneLocalizer(wmap, K, D, use_kalman=not args.no_kalman)
    visualizer = WarehouseVisualizer(wmap, map_px=600) if not args.no_display else None

    # ── Fuente de vídeo ───────────────────────────────────────────────────────
    if args.simulate:
        logger.info("Modo SIMULACIÓN activado.")
        cap = SimulatedCamera(wmap, K, D)
    else:
        try:
            source = int(args.source)
        except ValueError:
            source = args.source

        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            logger.error(f"No se puede abrir la fuente de vídeo: {source}")
            sys.exit(1)

        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  1280)
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
        cap.set(cv2.CAP_PROP_FPS,          30)

    # ── Ventana ───────────────────────────────────────────────────────────────
    win_name = "Localización ArUco - Almacén"
    if not args.no_display:
        cv2.namedWindow(win_name, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win_name, 1600, 600)

    logger.info("Sistema iniciado. Pulsa 'q' para salir, 'r' para borrar trayectoria.")

    frame_count = 0
    t_start     = time.time()
    pose_log    = []

    try:
        while True:
            ret, frame = cap.read()
            if not ret:
                logger.info("Fin del vídeo.")
                break

            frame_count += 1

            # ── Detección ArUco ───────────────────────────────────────────
            detection_result = detector.detect(frame, estimate_pose=True)

            # ── Localización ──────────────────────────────────────────────
            pose = localizer.update(detection_result.markers)

            # ── Log periódico ──────────────────────────────────────────────
            if frame_count % 30 == 0:
                elapsed = time.time() - t_start
                fps     = frame_count / elapsed
                if pose:
                    logger.info(
                        f"Frame {frame_count:>5d} │ FPS:{fps:.1f} │ {pose}"
                    )
                    pose_log.append({
                        "t": round(elapsed, 3),
                        "x": round(pose.x, 3),
                        "y": round(pose.y, 3),
                        "z": round(pose.z, 3),
                        "yaw": round(pose.yaw_deg, 1),
                        "conf": pose.confidence,
                        "markers": pose.markers_ids,
                    })
                else:
                    logger.info(
                        f"Frame {frame_count:>5d} │ FPS:{fps:.1f} │ "
                        f"Sin localización ({detection_result.n_markers} det.)"
                    )

            # ── Visualización ──────────────────────────────────────────────
            if not args.no_display and visualizer:
                combined = visualizer.render(
                    detection_result.frame_annotated,
                    pose,
                    detection_result.ids_detected,
                )
                cv2.imshow(win_name, combined)
                key = cv2.waitKey(1) & 0xFF
                if key == ord('q'):
                    break
                elif key == ord('r'):
                    visualizer.reset_trail()
                    logger.info("Trayectoria borrada.")
            else:
                # Modo headless: comprobar tecla en terminal no es trivial
                # → continuar indefinidamente o hasta fin de vídeo
                time.sleep(0.001)

    except KeyboardInterrupt:
        logger.info("Interrumpido por el usuario.")

    finally:
        if not args.simulate:
            cap.release()
        if not args.no_display:
            cv2.destroyAllWindows()

        # ── Guardar log de poses ───────────────────────────────────────────
        if pose_log and args.save_log:
            log_path = ROOT / "pose_log.json"
            with open(log_path, "w") as f:
                json.dump(pose_log, f, indent=2)
            logger.info(f"Log de poses guardado en: {log_path}")

        # ── Estadísticas finales ───────────────────────────────────────────
        stats = localizer.stats()
        logger.info(f"Estadísticas finales: {stats}")
        elapsed = time.time() - t_start
        logger.info(
            f"Sesión terminada │ {frame_count} frames │ "
            f"{elapsed:.1f}s │ {frame_count/max(elapsed,1):.1f} FPS medio"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Argumentos CLI
# ─────────────────────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Sistema de localización de drones mediante ArUco en almacén",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  python main.py                          # Webcam por defecto
  python main.py --source 1              # Cámara índice 1
  python main.py --source vuelo.mp4      # Archivo de vídeo
  python main.py --simulate              # Modo simulación
  python main.py --simulate --save-log   # Simulación + guardar log
  python main.py --no-display --save-log # Headless + log
        """,
    )
    parser.add_argument("--source",     default=0,
                        help="Fuente de vídeo: índice (0,1…) o ruta archivo")
    parser.add_argument("--simulate",   action="store_true",
                        help="Usar cámara simulada (sin hardware real)")
    parser.add_argument("--no-display", action="store_true",
                        help="No abrir ventana de visualización (headless)")
    parser.add_argument("--no-kalman",  action="store_true",
                        help="Desactivar filtro de Kalman")
    parser.add_argument("--save-log",   action="store_true",
                        help="Guardar log de poses en pose_log.json")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args)
