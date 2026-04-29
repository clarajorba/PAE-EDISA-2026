"""
calibrar_camara.py
==================
Script de calibración de cámara para Raspberry Pi Camera Module 3.
Usa picamera2 (stack libcamera) para capturar frames y OpenCV para detectar
el patrón de tablero de ajedrez y calcular los parámetros intrínsecos.

La Camera Module 3 tiene autoenfoque (AF). Este script lo desactiva
y fija el foco a distancia media (~50–150 cm) para que la calibración sea
válida en el rango de uso del detector ArUco.

Requisitos del sistema (Raspberry Pi OS Bullseye / Bookworm):
  sudo apt install -y python3-picamera2 python3-opencv python3-numpy

Instrucciones:
  1. Conecta la Camera Module 3 al puerto CSI de la Raspberry Pi.
  2. Habilita la cámara con: sudo raspi-config -> Interface Options -> Camera
  3. Imprime un tablero de ajedrez de 8x8 cuadrados (7x7 esquinas interiores).
     Descárgalo en: https://calib.io/pages/camera-calibration-pattern-generator
  4. Mide con regla el lado de un cuadrado en metros y ajusta SQUARE_SIZE.
  5. Ejecuta este script desde la raíz del proyecto:
         python calibration/calibrar_camara.py
  6. Con un monitor conectado a la Pi (o X11 via SSH), verás el feed en vivo.
     Mueve el tablero a distintas posiciones. Pulsa ESPACIO para capturar.
     Mínimo 15 capturas, recomendable 20-30.
  7. Pulsa 'q' para calibrar y guardar en config/camera_calibration.json.
  8. Copia los valores de camera_matrix y dist_coeffs a AppConfig en detector_3d.py.
"""

import cv2
import numpy as np
import json
from datetime import datetime
from pathlib import Path

# ─── INTENTO DE IMPORTAR picamera2 ────────────────────────────────────────────
try:
    from picamera2 import Picamera2
    USAR_PICAMERA2 = True
except ImportError:
    USAR_PICAMERA2 = False
    print("[AVISO] picamera2 no disponible. Usando cv2.VideoCapture como fallback.")


# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

# Esquinas interiores del tablero (columnas x filas)
# Un tablero de 8x8 cuadrados tiene 7x7 esquinas interiores
BOARD_SIZE = (7, 7)

# Tamaño real de cada cuadrado en METROS
# Mídelo con regla después de imprimir (la impresora puede escalar)
SQUARE_SIZE = 0.025  # 2.5 cm — ajusta según tu impresión

# Resolución de captura (Camera Module 3 soporta hasta 4608x2592)
# Para calibración es suficiente con 1280x720 y va más fluido en la Pi
RESOLUCION = (1280, 720)

# Posición de lente para foco fijo (Camera Module 3 tiene AF)
# 0.0 = infinito, 10.0 = muy cerca. Para ArUco a 50–150 cm usar ~3.0–5.0
LENS_POSITION = 4.0   # ajusta si el tablero se ve desenfocado

# Fuente de vídeo — solo se usa si picamera2 NO está disponible
VIDEO_SOURCE_FALLBACK = 0

# Mínimo de capturas para calibrar
MIN_CAPTURAS = 15

# Directorio de salida
BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "config"
OUTPUT_FILE = OUTPUT_DIR / "camera_calibration.json"


# ─── APERTURA DE CÁMARA ───────────────────────────────────────────────────────

def abrir_camara():
    """
    Abre la Camera Module 3 via picamera2.
    Desactiva el autoenfoque y fija el foco a LENS_POSITION.
    Si picamera2 no está disponible, fallback a cv2.VideoCapture.
    Devuelve (read_fn, release_fn) donde read_fn() -> (ok, frame_BGR).
    """
    if USAR_PICAMERA2:
        picam2 = Picamera2()
        config = picam2.create_video_configuration(
            main={"format": "BGR888", "size": RESOLUCION}
        )
        picam2.configure(config)
        picam2.start()

        # Desactivar AF y fijar foco (Camera Module 3)
        try:
            picam2.set_controls({"AfMode": 0, "LensPosition": LENS_POSITION})
            print(f"  Autoenfoque desactivado — foco fijo LensPosition={LENS_POSITION}")
        except Exception:
            print("  [AVISO] No se pudo fijar el foco (¿Camera Module 2?). Continuando.")

        import time; time.sleep(0.5)   # esperar a que el foco se estabilice
        print(f"  Cámara abierta (picamera2): {RESOLUCION[0]}x{RESOLUCION[1]}")

        def read_fn():
            frame = picam2.capture_array()
            return True, frame

        def release_fn():
            picam2.stop()

        return read_fn, release_fn

    else:
        # Intentar primero con GStreamer + libcamerasrc (Ubuntu en Raspberry Pi)
        gst = (
            f"libcamerasrc ! "
            f"video/x-raw,width={RESOLUCION[0]},height={RESOLUCION[1]},framerate=30/1 ! "
            f"videoconvert ! video/x-raw,format=BGR ! appsink drop=1"
        )
        cap = cv2.VideoCapture(gst, cv2.CAP_GSTREAMER)
        if cap.isOpened():
            ok, _ = cap.read()
            if ok:
                print(f"  Cámara abierta (libcamerasrc GStreamer): {RESOLUCION[0]}x{RESOLUCION[1]}")
            else:
                cap.release()
                cap = None
        else:
            cap = None

        # Fallback a VideoCapture estándar
        if cap is None:
            cap = cv2.VideoCapture(VIDEO_SOURCE_FALLBACK)
            if not cap.isOpened():
                raise RuntimeError(
                    f"No se puede abrir la cámara (source={VIDEO_SOURCE_FALLBACK}). "
                    "Comprueba que la cámara está conectada y habilitada."
                )
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, RESOLUCION[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCION[1])
            w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            print(f"  Cámara abierta (VideoCapture): {w}x{h}")

        def read_fn():
            return cap.read()

        def release_fn():
            cap.release()

        return read_fn, release_fn


# ─── FUNCIONES ────────────────────────────────────────────────────────────────

def generar_puntos_objeto():
    """Genera los puntos 3D del tablero en el plano Z=0."""
    objp = np.zeros((BOARD_SIZE[0] * BOARD_SIZE[1], 3), np.float32)
    objp[:, :2] = np.mgrid[
        0:BOARD_SIZE[0], 0:BOARD_SIZE[1]
    ].T.reshape(-1, 2)
    objp *= SQUARE_SIZE
    return objp


def capturar_imagenes(read_fn):
    """
    Muestra el feed de cámara y permite capturar frames con ESPACIO.
    Devuelve listas de puntos objeto y puntos imagen.
    """
    objp = generar_puntos_objeto()
    obj_points = []
    img_points = []
    img_size = None

    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        30, 0.001
    )

    n_capturas = 0

    print("\n" + "=" * 55)
    print("  CALIBRACIÓN — Camera Module 3")
    print("=" * 55)
    print(f"  Tablero: {BOARD_SIZE[0]}x{BOARD_SIZE[1]} esquinas interiores")
    print(f"  Tamaño cuadrado: {SQUARE_SIZE * 100:.1f} cm")
    print(f"  Resolución: {RESOLUCION[0]}x{RESOLUCION[1]}")
    print(f"  Mínimo capturas: {MIN_CAPTURAS}")
    print("=" * 55)
    print("\n  ESPACIO = capturar  |  q = calibrar y salir\n")

    win = "Calibracion - mueve el tablero"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 540)

    while True:
        ok, frame = read_fn()
        if not ok or frame is None:
            print("  [ERROR] No se pudo leer frame de la cámara.")
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        img_size = gray.shape[::-1]  # (width, height)

        found, corners = cv2.findChessboardCorners(
            gray, BOARD_SIZE,
            cv2.CALIB_CB_ADAPTIVE_THRESH
            + cv2.CALIB_CB_NORMALIZE_IMAGE
            + cv2.CALIB_CB_FAST_CHECK,
        )

        display = frame.copy()

        if found:
            corners_refined = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1), criteria
            )
            cv2.drawChessboardCorners(display, BOARD_SIZE, corners_refined, found)
            cv2.putText(display, "TABLERO DETECTADO - pulsa ESPACIO",
                        (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 80), 2)
        else:
            cv2.putText(display, "Buscando tablero...",
                        (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 120, 255), 2)

        color_count = (0, 255, 80) if n_capturas >= MIN_CAPTURAS else (0, 170, 255)
        cv2.putText(display, f"Capturas: {n_capturas}/{MIN_CAPTURAS}",
                    (15, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.6,
                    color_count, 2)

        if n_capturas >= MIN_CAPTURAS:
            cv2.putText(display, "Suficientes! Pulsa 'q' para calibrar",
                        (15, 100), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                        (0, 255, 200), 1)

        cv2.imshow(win, display)
        key = cv2.waitKey(1) & 0xFF

        if key == ord(" ") and found:
            obj_points.append(objp)
            img_points.append(corners_refined)
            n_capturas += 1
            print(f"  Captura #{n_capturas} guardada")

            flash = frame.copy()
            cv2.rectangle(flash, (0, 0),
                          (frame.shape[1], frame.shape[0]),
                          (0, 255, 0), 15)
            cv2.imshow(win, flash)
            cv2.waitKey(150)

        elif key == ord("q"):
            if n_capturas < MIN_CAPTURAS:
                print(f"\n  Necesitas al menos {MIN_CAPTURAS} capturas "
                      f"(tienes {n_capturas}). Sigue capturando o pulsa "
                      f"Ctrl+C para abortar.")
            else:
                break

    cv2.destroyWindow(win)
    return obj_points, img_points, img_size


def calibrar(obj_points, img_points, img_size):
    """Ejecuta la calibración y devuelve los parámetros."""
    print("\n  Calibrando... (puede tardar unos segundos en la Raspberry Pi)")

    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, img_size, None, None,
        flags=(
            cv2.CALIB_FIX_K4
            + cv2.CALIB_FIX_K5
        ),
    )

    total_err = 0
    for i in range(len(obj_points)):
        proj, _ = cv2.projectPoints(
            obj_points[i], rvecs[i], tvecs[i],
            camera_matrix, dist_coeffs
        )
        err = cv2.norm(img_points[i], proj, cv2.NORM_L2)
        total_err += err ** 2
    mean_err = np.sqrt(total_err / (len(obj_points) * BOARD_SIZE[0] * BOARD_SIZE[1]))

    return camera_matrix, dist_coeffs, mean_err, ret


def guardar_calibracion(camera_matrix, dist_coeffs, mean_err, img_size):
    """Guarda la calibración en JSON."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    data = {
        "calibration_date": datetime.now().isoformat(),
        "camera_model": "Raspberry Pi Camera Module 3",
        "image_size": list(img_size),
        "reprojection_error_px": round(float(mean_err), 4),
        "camera_matrix": camera_matrix.tolist(),
        "dist_coeffs": dist_coeffs.flatten().tolist(),
    }

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print(f"\n  Guardado en: {OUTPUT_FILE}")


def mostrar_resultados(camera_matrix, dist_coeffs, mean_err):
    """Imprime los resultados para copiar a detector_3d.py."""
    fx, fy = camera_matrix[0, 0], camera_matrix[1, 1]
    cx, cy = camera_matrix[0, 2], camera_matrix[1, 2]
    d = dist_coeffs.flatten()

    print("\n" + "=" * 55)
    print("  CALIBRACIÓN COMPLETADA")
    print("=" * 55)
    print(f"  Error de reproyección: {mean_err:.4f} px")
    print(f"  (< 0.5 = excelente, < 1.0 = bueno, > 1.0 = repetir)")
    print("=" * 55)

    print(f"\n  Parámetros intrínsecos:")
    print(f"    fx = {fx:.2f}")
    print(f"    fy = {fy:.2f}")
    print(f"    cx = {cx:.2f}")
    print(f"    cy = {cy:.2f}")
    print(f"    distorsión = [{', '.join(f'{v:.6f}' for v in d)}]")

    print(f"\n  ┌─────────────────────────────────────────────────┐")
    print(f"  │  COPIA ESTO EN AppConfig de detector_3d.py:     │")
    print(f"  └─────────────────────────────────────────────────┘\n")

    print(f"    camera_matrix: np.ndarray = field(default_factory=lambda: np.array([")
    print(f"        [{fx:10.2f}, {0:10.2f}, {cx:10.2f}],")
    print(f"        [{0:10.2f}, {fy:10.2f}, {cy:10.2f}],")
    print(f"        [{0:10.2f}, {0:10.2f}, {1:10.2f}],")
    print(f"    ], dtype=np.float64))")
    print()
    print(f"    dist_coeffs: np.ndarray = field(default_factory=lambda: np.array([")
    print(f"        [{d[0]:.6f}],")
    print(f"        [{d[1]:.6f}],")
    print(f"        [{d[2]:.6f}],")
    print(f"        [{d[3]:.6f}],")
    print(f"        [{d[4]:.6f}],")
    print(f"    ], dtype=np.float64))")
    print()


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    try:
        read_fn, release_fn = abrir_camara()
    except RuntimeError as e:
        print(f"\n  ERROR: {e}")
        return

    try:
        obj_points, img_points, img_size = capturar_imagenes(read_fn)
    finally:
        release_fn()
        cv2.destroyAllWindows()

    if len(obj_points) < MIN_CAPTURAS:
        print(f"\n  Abortado: solo {len(obj_points)} capturas "
              f"(mínimo {MIN_CAPTURAS}).")
        return

    camera_matrix, dist_coeffs, mean_err, ret = calibrar(
        obj_points, img_points, img_size
    )

    mostrar_resultados(camera_matrix, dist_coeffs, mean_err)
    guardar_calibracion(camera_matrix, dist_coeffs, mean_err, img_size)

    print("\n  Listo. Ahora copia los valores a detector_3d.py y vuelve a probar.\n")


if __name__ == "__main__":
    main()
