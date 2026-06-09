"""
calibrar_camara_rpicam.py
==========================
Versión modificada para usar rpicam-still en lugar de picamera2 o cv2.VideoCapture.
Ideal para Raspberry Pi 5 con cámara Module 3 NoIR.
"""

import cv2
import numpy as np
import json
import os
import time
import tempfile
import shutil
from datetime import datetime
from pathlib import Path

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

# Esquinas interiores del tablero (columnas x filas)
BOARD_SIZE = (7, 7)

# Tamaño real de cada cuadrado en METROS
SQUARE_SIZE = 0.025  # 2.5 cm

# Resolución de captura
RESOLUCION = (1280, 720)

# Mínimo de capturas para calibrar
MIN_CAPTURAS = 15

# Directorio de salida
BASE_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = BASE_DIR / "config"
OUTPUT_FILE = OUTPUT_DIR / "camera_calibration.json"


# ─── CAPTURA CON RPICAM-STILL ─────────────────────────────────────────────────

def capturar_con_rpicam():
    """
    Captura imágenes usando rpicam-still en lugar de streaming.
    Retorna listas de puntos objeto y puntos imagen.
    """
    objp = generar_puntos_objeto()
    obj_points = []
    img_points = []
    img_size = None
    
    criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
    
    # Crear directorio temporal para las imágenes
    temp_dir = Path(tempfile.mkdtemp(prefix="calib_cam_"))
    print(f"\n  Directorio temporal: {temp_dir}")
    
    n_capturas = 0
    
    print("\n" + "=" * 55)
    print("  CALIBRACIÓN — Camera Module 3 NoIR (con rpicam-still)")
    print("=" * 55)
    print(f"  Tablero: {BOARD_SIZE[0]}x{BOARD_SIZE[1]} esquinas interiores")
    print(f"  Tamaño cuadrado: {SQUARE_SIZE * 100:.1f} cm")
    print(f"  Resolución: {RESOLUCION[0]}x{RESOLUCION[1]}")
    print(f"  Mínimo capturas: {MIN_CAPTURAS}")
    print("=" * 55)
    print("\n  INSTRUCCIONES:")
    print("  1. Muestra el tablero a la cámara")
    print("  2. Presiona ESPACIO para capturar cuando el tablero sea detectado")
    print("  3. Mueve el tablero entre capturas (diferentes ángulos/posiciones)")
    print("  4. Presiona 'q' para calibrar y salir (mínimo 15 capturas)\n")
    
    # Ventana para mostrar preview
    win = "Calibracion - Mueve el tablero y presiona ESPACIO"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, 960, 540)
    
    # Crear preview con libcamera (opcional, para ver lo que capturas)
    preview_process = None
    try:
        # Iniciar preview en segundo plano (sin guardar archivo)
        import subprocess
        preview_process = subprocess.Popen(
            ["rpicam-vid", "--preview", "--framerate", "15", "--width", "640", "--height", "360"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except:
        print("[AVISO] No se pudo iniciar preview, solo verás las imágenes capturadas")
    
    while True:
        # Esperar tecla antes de capturar
        key = cv2.waitKey(100) & 0xFF
        
        if key == ord(' '):
            # Capturar imagen con rpicam-still
            img_path = temp_dir / f"captura_{n_capturas+1:03d}.jpg"
            
            # Comando rpicam-still con resolución fija
            cmd = [
                "rpicam-still",
                "-o", str(img_path),
                "--width", str(RESOLUCION[0]),
                "--height", str(RESOLUCION[1]),
                "--nopreview",
                "--timeout", "100"  # 100ms timeout
            ]
            
            print(f"  Capturando imagen {n_capturas+1}...")
            result = os.system(" ".join(cmd))
            time.sleep(0.5)  # Esperar a que se escriba el archivo
            
            if not img_path.exists() or img_path.stat().st_size == 0:
                print("  ❌ Error en captura, reintenta...")
                continue
            
            # Leer la imagen capturada
            frame = cv2.imread(str(img_path))
            if frame is None:
                print("  ❌ No se pudo leer la imagen capturada")
                continue
            
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            img_size = gray.shape[::-1]  # (width, height)
            
            # Buscar esquinas del tablero
            found, corners = cv2.findChessboardCorners(
                gray, BOARD_SIZE,
                cv2.CALIB_CB_ADAPTIVE_THRESH + cv2.CALIB_CB_NORMALIZE_IMAGE
            )
            
            if found:
                corners_refined = cv2.cornerSubPix(gray, corners, (11,11), (-1,-1), criteria)
                obj_points.append(objp)
                img_points.append(corners_refined)
                n_capturas += 1
                print(f"  ✅ Captura #{n_capturas} guardada (tablero detectado)")
                
                # Mostrar feedback visual
                display = frame.copy()
                cv2.drawChessboardCorners(display, BOARD_SIZE, corners_refined, found)
                cv2.putText(display, f"CAPTURA #{n_capturas} GUARDADA!", 
                           (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 1, (0,255,0), 3)
                cv2.imshow(win, display)
                cv2.waitKey(500)
            else:
                print(f"  ❌ Tablero no detectado en captura {n_capturas+1}, reintenta")
                # Mostrar frame fallido
                cv2.putText(frame, "TABLERO NO DETECTADO - Reintenta", 
                           (50, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,0,255), 2)
                cv2.imshow(win, frame)
                cv2.waitKey(1000)
                continue
                
        elif key == ord('q'):
            if n_capturas >= MIN_CAPTURAS:
                break
            else:
                print(f"\n  Necesitas al menos {MIN_CAPTURAS} capturas (tienes {n_capturas})")
                continue
        
        # Mostrar estado actual en ventana
        if 'display' in locals():
            pass  # Ya mostramos algo
        else:
            # Mostrar mensaje de espera
            blank = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(blank, f"Capturas: {n_capturas}/{MIN_CAPTURAS}", 
                       (50, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)
            cv2.putText(blank, "Presiona ESPACIO para capturar", 
                       (50, 280), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
            cv2.putText(blank, "Presiona 'q' para calibrar", 
                       (50, 320), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (200,200,200), 1)
            cv2.imshow(win, blank)
    
    # Limpiar
    cv2.destroyAllWindows()
    if preview_process:
        preview_process.terminate()
    
    # Limpiar directorio temporal
    shutil.rmtree(temp_dir)
    
    return obj_points, img_points, img_size


def generar_puntos_objeto():
    """Genera los puntos 3D del tablero en el plano Z=0."""
    objp = np.zeros((BOARD_SIZE[0] * BOARD_SIZE[1], 3), np.float32)
    objp[:, :2] = np.mgrid[0:BOARD_SIZE[0], 0:BOARD_SIZE[1]].T.reshape(-1, 2)
    objp *= SQUARE_SIZE
    return objp


def calibrar(obj_points, img_points, img_size):
    """Ejecuta la calibración y devuelve los parámetros."""
    print("\n  Calibrando... (puede tardar unos segundos)")
    
    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        obj_points, img_points, img_size, None, None
    )
    
    # Calcular error de reproyección
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
        "camera_model": "Raspberry Pi Camera Module 3 NoIR (rpicam-still)",
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
    print(f"  (< 0.5 = excelente, < 1.0 = bueno)")
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
    print("\n  Verificando rpicam-still...")
    if os.system("rpicam-still --version") != 0:
        print("  ERROR: rpicam-still no está instalado o no funciona.")
        print("  Instálalo con: sudo apt install rpicam-apps")
        return
    
    print("  ✅ rpicam-still disponible\n")
    
    obj_points, img_points, img_size = capturar_con_rpicam()
    
    if len(obj_points) < MIN_CAPTURAS:
        print(f"\n  Abortado: solo {len(obj_points)} capturas (mínimo {MIN_CAPTURAS}).")
        return
    
    camera_matrix, dist_coeffs, mean_err, ret = calibrar(obj_points, img_points, img_size)
    
    mostrar_resultados(camera_matrix, dist_coeffs, mean_err)
    guardar_calibracion(camera_matrix, dist_coeffs, mean_err, img_size)
    
    print("\n  ✅ Listo. Ahora copia los valores a detector_3d.py\n")


if __name__ == "__main__":
    main()
