"""
medir_error_estatico.py
=======================
Mide el error estático de localización ArUco.

Uso:
  1. Coloca la cámara en una posición FIJA frente a los marcadores.
  2. Ejecuta:  python medir_error_estatico.py
  3. El script graba posiciones durante DURACION_S segundos.
  4. Al terminar muestra estadísticas y guarda:
     - CSV con todas las muestras (para análisis externo)
     - Resumen en consola y en archivo .txt

Opcionalmente puedes indicar la posición real conocida para calcular
el error absoluto (si la has medido con cinta métrica).

Dependencias (Ubuntu / venv):
  python3 -m pip install numpy opencv-contrib-python

Opcional en Raspberry Pi OS:
  sudo apt install -y python3-picamera2 python3-opencv python3-numpy
"""

import cv2
import numpy as np
import json
import time
import csv
import os
import importlib
from pathlib import Path
from datetime import datetime

# ─── INTENTO DE IMPORTAR picamera2 ────────────────────────────────────────────
def cargar_picamera2():
    """
    Importa picamera2 de forma dinámica para evitar avisos del editor
    en sistemas donde el módulo no existe, como Windows.
    """
    try:
        module = importlib.import_module("picamera2")
        return module.Picamera2, True
    except ImportError:
        return None, False


Picamera2, USAR_PICAMERA2 = cargar_picamera2()


# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

DURACION_S = 10          # segundos de grabación
VIDEO_SOURCE = 0         # en Ubuntu suele ser 0 o "/dev/video0"
RESOLUCION = (1280, 720)
CONFIG_PATH = "config/markers_3d.json"
OUTPUT_DIR = "mediciones"
PREFERIR_PICAMERA2 = False   # en Ubuntu normal, deja esto en False
CAMERA_BACKEND = cv2.CAP_V4L2  # recomendado en Linux/Ubuntu
MOSTRAR_PREVIEW = True       # ponlo en False si ejecutas por SSH o sin GUI

# Posición real conocida (metros). Pon None si no la sabes.
# Si la conoces (medida con cinta métrica), rellénala para obtener error absoluto.
POSICION_REAL = None      # ejemplo: np.array([0.75, 0.75, 1.00])

# ─── Parámetros de cámara (copiar de detector_3d.py) ─────────────────────────

CAMERA_MATRIX = np.array([
    [974.90,   0.00, 627.25],
    [  0.00, 974.61, 365.31],
    [  0.00,   0.00,   1.00],
], dtype=np.float64)

DIST_COEFFS = np.array([
    [-0.217752],
    [ 2.492355],
    [-0.003245],
    [-0.004504],
    [-7.845957],
], dtype=np.float64)

DICT_ARUCO = cv2.aruco.DICT_4X4_1000
MAX_REPROJECTION_PX = 8.0


# ─── APERTURA DE CÁMARA ───────────────────────────────────────────────────────

def abrir_camara():
    """
    Abre la cámara con picamera2 si se ha pedido explícitamente.
    En Ubuntu normal usa cv2.VideoCapture.
    Devuelve (read_fn, release_fn) donde read_fn() -> (ok, frame_BGR).
    """
    if PREFERIR_PICAMERA2 and USAR_PICAMERA2:
        picam2 = Picamera2()
        config = picam2.create_video_configuration(
            main={"format": "BGR888", "size": RESOLUCION}
        )
        picam2.configure(config)
        picam2.start()
        print(f"  Cámara abierta (picamera2): {RESOLUCION[0]}x{RESOLUCION[1]}")

        def read_fn():
            frame = picam2.capture_array()
            return True, frame

        def release_fn():
            picam2.stop()

        return read_fn, release_fn

    else:
        cap = cv2.VideoCapture(VIDEO_SOURCE, CAMERA_BACKEND)
        if not cap.isOpened():
            cap.release()
            cap = cv2.VideoCapture(VIDEO_SOURCE)

        if not cap.isOpened():
            raise RuntimeError(
                f"No se puede abrir la cámara (source={VIDEO_SOURCE}). "
                "Comprueba que la cámara está conectada, que existe "
                "/dev/video0 y que tienes permisos para acceder a ella."
            )
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUCION[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCION[1])
        print(f"  Cámara abierta (VideoCapture): {RESOLUCION[0]}x{RESOLUCION[1]}")

        def read_fn():
            return cap.read()

        def release_fn():
            cap.release()

        return read_fn, release_fn


# ─── CARGAR MAPA DE MARCADORES ────────────────────────────────────────────────

def cargar_mapa(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    marker_size = float(data.get("marker_size", 0.12))
    markers = {}
    for id_str, info in data["markers"].items():
        mid = int(id_str)
        markers[mid] = np.array([info["x"], info["y"], info["z"]], dtype=np.float64)
    return markers, marker_size


MARKERS, MARKER_SIZE = cargar_mapa(CONFIG_PATH)
VALID_IDS = set(MARKERS.keys())

_h = MARKER_SIZE / 2
MARKER_OBJ_PTS = np.array([
    [-_h,  _h, 0],
    [ _h,  _h, 0],
    [ _h, -_h, 0],
    [-_h, -_h, 0],
], dtype=np.float32)


# ─── ESTIMACIÓN DE POSE ──────────────────────────────────────────────────────

dictionary = cv2.aruco.getPredefinedDictionary(DICT_ARUCO)
parameters = cv2.aruco.DetectorParameters()
parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
parameters.cornerRefinementWinSize = 5
parameters.cornerRefinementMaxIterations = 50
detector = cv2.aruco.ArucoDetector(dictionary, parameters)


def error_reproyeccion(rvec, tvec, img_pts):
    proj, _ = cv2.projectPoints(
        MARKER_OBJ_PTS, rvec, tvec, CAMERA_MATRIX, DIST_COEFFS
    )
    proj = proj.reshape(4, 2)
    return float(np.sqrt(np.mean(np.sum((proj - img_pts) ** 2, axis=1))))


def estimar_posicion(corners_det, ids_det):
    """
    Triangulación ponderada (misma lógica que detector_3d.py v2).
    Devuelve posición o None.
    """
    if ids_det is None or len(ids_det) == 0:
        return None, 0

    ids_list = ids_det.flatten().tolist()
    estimaciones = []

    for corners, mid in zip(corners_det, ids_list):
        if mid not in VALID_IDS:
            continue

        img_pts = corners.reshape(4, 2).astype(np.float32)

        ok, rvec, tvec = cv2.solvePnP(
            MARKER_OBJ_PTS, img_pts, CAMERA_MATRIX, DIST_COEFFS,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not ok:
            continue

        # Refinamiento iterativo
        ok2, rvec2, tvec2 = cv2.solvePnP(
            MARKER_OBJ_PTS, img_pts, CAMERA_MATRIX, DIST_COEFFS,
            rvec=rvec.copy(), tvec=tvec.copy(),
            useExtrinsicGuess=True,
            flags=cv2.SOLVEPNP_ITERATIVE,
        )

        err1 = error_reproyeccion(rvec, tvec, img_pts)
        if ok2:
            err2 = error_reproyeccion(rvec2, tvec2, img_pts)
            if err2 < err1:
                rvec, tvec, err1 = rvec2, tvec2, err2

        if err1 > MAX_REPROJECTION_PX:
            continue

        R, _ = cv2.Rodrigues(rvec)
        cam_local = (-R.T @ tvec).flatten()
        cam_world = MARKERS[mid] + cam_local

        estimaciones.append((cam_world, err1))

    if not estimaciones:
        return None, 0

    # Rechazo IQR si hay suficientes
    if len(estimaciones) >= 4:
        positions = np.array([e[0] for e in estimaciones])
        mask = np.ones(len(estimaciones), dtype=bool)
        for axis in range(3):
            vals = positions[:, axis]
            q1, q3 = np.percentile(vals, [25, 75])
            iqr = q3 - q1
            mask &= (vals >= q1 - 1.5 * iqr) & (vals <= q3 + 1.5 * iqr)
        estimaciones = [e for e, m in zip(estimaciones, mask) if m]

    if not estimaciones:
        return None, 0

    # Media ponderada
    positions = np.array([e[0] for e in estimaciones])
    errors = np.array([e[1] for e in estimaciones])
    errors = np.clip(errors, 0.1, None)
    weights = 1.0 / (errors ** 2)
    weights /= weights.sum()

    pos = np.average(positions, weights=weights, axis=0)
    return pos, len(estimaciones)


# ─── GRABACIÓN Y ANÁLISIS ────────────────────────────────────────────────────

def grabar_posiciones(read_fn, duracion_s):
    """Graba posiciones crudas (sin Kalman) durante N segundos."""
    muestras = []
    t_inicio = time.monotonic()
    frame_count = 0

    win = "Medicion estatica - NO MOVER LA CAMARA"
    if MOSTRAR_PREVIEW:
        cv2.namedWindow(win, cv2.WINDOW_NORMAL)
        cv2.resizeWindow(win, 960, 720)

    print(f"\n  Grabando durante {duracion_s} segundos...")
    print(f"  NO MUEVAS LA CÁMARA\n")

    while True:
        elapsed = time.monotonic() - t_inicio
        if elapsed >= duracion_s:
            break

        ok, frame = read_fn()
        if not ok:
            break

        frame_count += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners_det, ids_det, _ = detector.detectMarkers(gray)

        pos, n_markers = estimar_posicion(corners_det, ids_det)

        # Dibujar marcadores
        if ids_det is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners_det, ids_det)

        # HUD
        remaining = max(0, duracion_s - elapsed)
        bar_width = int(300 * (elapsed / duracion_s))

        ov = frame.copy()
        cv2.rectangle(ov, (5, 5), (360, 130), (0, 0, 0), -1)
        cv2.addWeighted(ov, 0.6, frame, 0.4, 0, frame)

        cv2.putText(frame, f"GRABANDO  {remaining:.1f}s restantes",
                    (12, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    (0, 120, 255), 2)

        # Barra de progreso
        cv2.rectangle(frame, (12, 45), (312, 60), (40, 40, 40), -1)
        cv2.rectangle(frame, (12, 45), (12 + bar_width, 60), (0, 200, 100), -1)

        cv2.putText(frame, f"Muestras: {len(muestras)}  |  Markers: {n_markers}",
                    (12, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    (180, 180, 180), 1)

        if pos is not None:
            cv2.putText(frame,
                        f"X={pos[0]:+.4f}  Y={pos[1]:+.4f}  Z={pos[2]:+.4f}",
                        (12, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 255, 200), 1)
            muestras.append({
                "t": round(elapsed, 4),
                "x": pos[0],
                "y": pos[1],
                "z": pos[2],
                "n_markers": n_markers,
            })

        if MOSTRAR_PREVIEW:
            cv2.imshow(win, frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    if MOSTRAR_PREVIEW:
        cv2.destroyWindow(win)
    print(f"  Grabación terminada: {len(muestras)} muestras en "
          f"{frame_count} frames ({elapsed:.1f}s)")

    return muestras


def analizar(muestras):
    """Calcula estadísticas de las muestras."""
    if not muestras:
        print("\n  ERROR: 0 muestras recogidas. No se detectaron marcadores.")
        return None

    xs = np.array([m["x"] for m in muestras])
    ys = np.array([m["y"] for m in muestras])
    zs = np.array([m["z"] for m in muestras])

    stats = {
        "n_muestras": len(muestras),
        "duracion_s": muestras[-1]["t"] - muestras[0]["t"],
        "frecuencia_hz": len(muestras) / max(muestras[-1]["t"] - muestras[0]["t"], 0.01),
    }

    for label, vals in [("x", xs), ("y", ys), ("z", zs)]:
        stats[f"{label}_media"] = float(np.mean(vals))
        stats[f"{label}_mediana"] = float(np.median(vals))
        stats[f"{label}_std"] = float(np.std(vals))
        stats[f"{label}_var"] = float(np.var(vals))
        stats[f"{label}_min"] = float(np.min(vals))
        stats[f"{label}_max"] = float(np.max(vals))
        stats[f"{label}_rango"] = float(np.max(vals) - np.min(vals))

    # Error 3D (dispersión respecto a la media)
    media = np.array([stats["x_media"], stats["y_media"], stats["z_media"]])
    distancias = np.sqrt((xs - media[0])**2 + (ys - media[1])**2 + (zs - media[2])**2)
    stats["error_3d_medio"] = float(np.mean(distancias))
    stats["error_3d_std"] = float(np.std(distancias))
    stats["error_3d_max"] = float(np.max(distancias))
    stats["error_3d_p95"] = float(np.percentile(distancias, 95))

    # Error absoluto si se conoce la posición real
    if POSICION_REAL is not None:
        diff = media - POSICION_REAL
        stats["error_abs_x"] = float(diff[0])
        stats["error_abs_y"] = float(diff[1])
        stats["error_abs_z"] = float(diff[2])
        stats["error_abs_3d"] = float(np.linalg.norm(diff))

    return stats


def imprimir_resultados(stats):
    """Imprime los resultados en consola."""
    sep = "═" * 58

    print(f"\n{sep}")
    print(f"  RESULTADOS — ERROR ESTÁTICO")
    print(f"{sep}")
    print(f"  Muestras:   {stats['n_muestras']}")
    print(f"  Duración:   {stats['duracion_s']:.2f} s")
    print(f"  Frecuencia: {stats['frecuencia_hz']:.1f} Hz")
    print(f"{'─' * 58}")

    print(f"\n  {'':8s} {'Media':>10s} {'Std':>10s} {'Varianza':>10s} {'Rango':>10s}")
    print(f"  {'─'*50}")
    for axis in ["x", "y", "z"]:
        print(f"  {axis.upper():8s}"
              f" {stats[f'{axis}_media']:+10.5f}"
              f" {stats[f'{axis}_std']:10.5f}"
              f" {stats[f'{axis}_var']:10.7f}"
              f" {stats[f'{axis}_rango']:10.5f}")

    print(f"\n{'─' * 58}")
    print(f"  Error 3D (dispersión respecto a media):")
    print(f"    Medio:  {stats['error_3d_medio']*1000:.3f} mm")
    print(f"    Std:    {stats['error_3d_std']*1000:.3f} mm")
    print(f"    P95:    {stats['error_3d_p95']*1000:.3f} mm")
    print(f"    Máximo: {stats['error_3d_max']*1000:.3f} mm")

    if "error_abs_3d" in stats:
        print(f"\n{'─' * 58}")
        print(f"  Error absoluto (vs posición real conocida):")
        print(f"    ΔX: {stats['error_abs_x']*1000:+.3f} mm")
        print(f"    ΔY: {stats['error_abs_y']*1000:+.3f} mm")
        print(f"    ΔZ: {stats['error_abs_z']*1000:+.3f} mm")
        print(f"    3D: {stats['error_abs_3d']*1000:.3f} mm")

    print(f"\n{sep}\n")


def guardar_resultados(muestras, stats):
    """Guarda CSV con las muestras y TXT con el resumen."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    # CSV
    csv_path = os.path.join(OUTPUT_DIR, f"estatico_{timestamp}.csv")
    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["t", "x", "y", "z", "n_markers"])
        writer.writeheader()
        writer.writerows(muestras)
    print(f"  CSV guardado:     {csv_path}")

    # Resumen TXT
    txt_path = os.path.join(OUTPUT_DIR, f"estatico_{timestamp}_resumen.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write(f"Medición error estático — {timestamp}\n")
        f.write(f"{'=' * 50}\n\n")
        for k, v in stats.items():
            if isinstance(v, float):
                f.write(f"{k}: {v:.7f}\n")
            else:
                f.write(f"{k}: {v}\n")
    print(f"  Resumen guardado: {txt_path}")

    # JSON (para procesado automático)
    json_path = os.path.join(OUTPUT_DIR, f"estatico_{timestamp}_stats.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(stats, f, indent=2)
    print(f"  JSON guardado:    {json_path}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    try:
        read_fn, release_fn = abrir_camara()
    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        return

    try:
        muestras = grabar_posiciones(read_fn, DURACION_S)
    finally:
        release_fn()
        cv2.destroyAllWindows()

    stats = analizar(muestras)
    if stats is None:
        return

    imprimir_resultados(stats)
    guardar_resultados(muestras, stats)

    print(f"\n  Listo. Usa el CSV para hacer gráficas en Excel/Python si quieres.\n")


if __name__ == "__main__":
    main()
