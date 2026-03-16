"""
calibrar_camara.py
==================
Script de calibración de cámara con patrón de tablero de ajedrez.

Instrucciones:
  1. Imprime un tablero de ajedrez (por defecto 9x6 esquinas interiores).
     Puedes generarlo desde: https://calib.io/pages/camera-calibration-pattern-generator
     o buscando "chessboard calibration pattern A4 PDF".

  2. Mide el lado real de cada cuadrado en metros (por defecto 0.025 = 2.5 cm).
     Ajusta SQUARE_SIZE abajo.

  3. Ejecuta este script:
         python calibrar_camara.py

  4. Mueve el tablero delante de la cámara en distintas posiciones y ángulos.
     Pulsa ESPACIO para capturar una imagen (mínimo 15, recomendable 20-30).
     Intenta cubrir toda la imagen: centro, esquinas, rotado, inclinado.

  5. Pulsa 'q' cuando tengas suficientes capturas.
     El script calibra y guarda el resultado en config/camera_calibration.json

  6. Copia los valores de camera_matrix y dist_coeffs a tu AppConfig en detector_3d.py

Dependencias:
  pip install opencv-contrib-python numpy
"""

import cv2
import numpy as np
import json
import os
from datetime import datetime


# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

# Esquinas interiores del tablero (columnas x filas)
# Un tablero estándar de 10x7 cuadrados tiene 9x6 esquinas interiores
BOARD_SIZE = (7, 7)

# Tamaño real de cada cuadrado en METROS
# Mídelo con regla después de imprimir (la impresora puede escalar)
SQUARE_SIZE = 0.01  # 1.0 cm

# Fuente de vídeo (0 = webcam por defecto)
VIDEO_SOURCE = 0

# Mínimo de capturas para calibrar
MIN_CAPTURAS = 15

# Directorio de salida
OUTPUT_DIR = "config"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "camera_calibration.json")


# ─── FUNCIONES ────────────────────────────────────────────────────────────────

def generar_puntos_objeto():
    """Genera los puntos 3D del tablero en el plano Z=0."""
    objp = np.zeros((BOARD_SIZE[0] * BOARD_SIZE[1], 3), np.float32)
    objp[:, :2] = np.mgrid[
        0:BOARD_SIZE[0], 0:BOARD_SIZE[1]
    ].T.reshape(-1, 2)
    objp *= SQUARE_SIZE
    return objp


def capturar_imagenes(cap):
    """
    Muestra el feed de cámara y permite capturar frames con ESPACIO.
    Devuelve listas de puntos objeto y puntos imagen.
    """
    objp = generar_puntos_objeto()
    obj_points = []   # puntos 3D del tablero
    img_points = []   # puntos 2D detectados en imagen
    img_size = None

    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        30, 0.001
    )

    n_capturas = 0

    print("\n" + "=" * 55)
    print("  CALIBRACIÓN DE CÁMARA")
    print("=" * 55)
    print(f"  Tablero: {BOARD_SIZE[0]}x{BOARD_SIZE[1]} esquinas interiores")
    print(f"  Tamaño cuadrado: {SQUARE_SIZE*100:.1f} cm")
    print(f"  Mínimo capturas: {MIN_CAPTURAS}")
    print("=" * 55)
    print("\n  ESPACIO = capturar  |  q = calibrar y salir\n")

    win = "Calibracion - mueve el tablero"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 720)

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        img_size = gray.shape[::-1]  # (width, height)

        # Buscar esquinas del tablero
        found, corners = cv2.findChessboardCorners(
            gray, BOARD_SIZE,
            cv2.CALIB_CB_ADAPTIVE_THRESH
            + cv2.CALIB_CB_NORMALIZE_IMAGE
            + cv2.CALIB_CB_FAST_CHECK,
        )

        display = frame.copy()

        if found:
            # Refinar a subpíxel
            corners_refined = cv2.cornerSubPix(
                gray, corners, (11, 11), (-1, -1), criteria
            )
            cv2.drawChessboardCorners(display, BOARD_SIZE, corners_refined, found)

            # Indicador verde: tablero detectado
            cv2.putText(display, "TABLERO DETECTADO - pulsa ESPACIO",
                        (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 255, 80), 2)
        else:
            cv2.putText(display, "Buscando tablero...",
                        (15, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                        (0, 120, 255), 2)

        # Contador de capturas
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

            # Flash visual
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
    print("\n  Calibrando... (puede tardar unos segundos)")

    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, img_size, None, None,
        flags=(
            cv2.CALIB_FIX_K4
            + cv2.CALIB_FIX_K5
        ),
    )

    # Calcular error de reproyección medio
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
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    data = {
        "calibration_date": datetime.now().isoformat(),
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
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"ERROR: No se puede abrir la cámara (source={VIDEO_SOURCE})")
        return

    # Resolución máxima
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1920)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 1080)

    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"\n  Cámara abierta: {w}x{h}")

    try:
        obj_points, img_points, img_size = capturar_imagenes(cap)
    finally:
        cap.release()
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
