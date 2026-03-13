"""
detector_simple.py
==================
Versión simplificada para estudiantes.

¿Qué hace este programa?
  - Abre la cámara del ordenador (o un archivo de vídeo).
  - Detecta marcadores ArUco (IDs del 0 al 4) en cada frame.
  - Dibuja un recuadro y el ID sobre cada marcador encontrado.
  - Muestra un pequeño mapa del almacén donde aparece el marcador visto.

Teclas:
  q  →  salir

Dependencias:
  pip install opencv-contrib-python
"""

import cv2
import numpy as np

# ──────────────────────────────────────────────
# 1.  CONFIGURACIÓN  (cambia estos valores)
# ──────────────────────────────────────────────

FUENTE_VIDEO = 0          # 0 = webcam, o pon una ruta: "video.mp4"
DICT_ARUCO   = cv2.aruco.DICT_4X4_1000   # diccionario que coincide con tus SVG

# Posiciones de los marcadores en el mapa (metros)
# El mapa es un rectángulo de ANCHO x ALTO
ANCHO_MAPA = 5.0   # metros
ALTO_MAPA  = 4.0   # metros

POSICIONES_MARCADORES = {
    0: (0.0,  0.0),   # esquina izquierda-arriba
    1: (5.0,  0.0),   # esquina derecha-arriba
    2: (5.0,  4.0),   # esquina derecha-abajo
    3: (0.0,  4.0),   # esquina izquierda-abajo
    4: (2.5,  2.0),   # centro
}

# ──────────────────────────────────────────────
# 2.  PREPARAR EL DETECTOR ARUCO
# ──────────────────────────────────────────────

diccionario = cv2.aruco.getPredefinedDictionary(DICT_ARUCO)
parametros  = cv2.aruco.DetectorParameters()
detector    = cv2.aruco.ArucoDetector(diccionario, parametros)

# ──────────────────────────────────────────────
# 3.  PREPARAR EL MAPA (canvas de 400x320 px)
# ──────────────────────────────────────────────

MAP_W, MAP_H = 400, 320   # tamaño del mapa en píxeles
PAD          = 30          # margen interior

def metros_a_pixeles(x_m, y_m):
    """Convierte coordenadas en metros a píxeles en el mapa."""
    px = int(PAD + x_m / ANCHO_MAPA * (MAP_W - 2 * PAD))
    py = int(PAD + y_m / ALTO_MAPA  * (MAP_H - 2 * PAD))
    return px, py

def dibujar_mapa(ids_detectados):
    """
    Dibuja el mapa del almacén.
    Pinta en VERDE los marcadores que se ven ahora mismo.
    Pinta en GRIS  los que no se ven.
    """
    mapa = np.full((MAP_H, MAP_W, 3), (30, 30, 30), dtype=np.uint8)

    # Borde del almacén
    cv2.rectangle(mapa, (PAD, PAD), (MAP_W - PAD, MAP_H - PAD), (150, 150, 150), 2)

    # Título
    cv2.putText(mapa, "MAPA DEL ALMACEN", (PAD, PAD - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (200, 200, 200), 1)

    # Dibujar cada marcador
    for marker_id, (x_m, y_m) in POSICIONES_MARCADORES.items():
        px, py = metros_a_pixeles(x_m, y_m)

        if marker_id in ids_detectados:
            color  = (0, 220, 80)    # verde  → detectado
            radius = 12
        else:
            color  = (80, 80, 80)    # gris   → no visto
            radius = 8

        cv2.circle(mapa, (px, py), radius, color, -1)
        cv2.putText(mapa, str(marker_id), (px - 5, py + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Leyenda
    cv2.circle(mapa, (PAD,      MAP_H - 10), 6, (0, 220, 80), -1)
    cv2.putText(mapa, "visto",  (PAD + 10,  MAP_H - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)
    cv2.circle(mapa, (PAD + 80, MAP_H - 10), 6, (80, 80, 80), -1)
    cv2.putText(mapa, "no visto", (PAD + 90, MAP_H - 6),
                cv2.FONT_HERSHEY_SIMPLEX, 0.38, (200, 200, 200), 1)

    return mapa

# ──────────────────────────────────────────────
# 4.  BUCLE PRINCIPAL
# ──────────────────────────────────────────────

cap = cv2.VideoCapture(FUENTE_VIDEO)

if not cap.isOpened():
    print(f"ERROR: No se puede abrir la fuente de vídeo: {FUENTE_VIDEO}")
    exit()

print("Sistema iniciado. Pulsa 'q' para salir.")

while True:
    # --- Leer un frame de la cámara ---
    ok, frame = cap.read()
    if not ok:
        break

    # --- Detectar marcadores ArUco ---
    esquinas, ids, _ = detector.detectMarkers(frame)

    # ids es None si no se detecta nada; si no, es un array de arrays
    ids_lista = []
    if ids is not None:
        ids_lista = ids.flatten().tolist()   # convertir a lista normal: [0, 2, ...]

    # --- Dibujar sobre el frame de la cámara ---
    if ids is not None:
        # Recuadro verde sobre cada marcador
        cv2.aruco.drawDetectedMarkers(frame, esquinas, ids)

        # Etiqueta con el ID encima de cada marcador
        for i, marker_id in enumerate(ids_lista):
            # Centro del marcador (media de las 4 esquinas)
            cx = int(esquinas[i][0][:, 0].mean())
            cy = int(esquinas[i][0][:, 1].mean())

            cv2.putText(frame, f"ID: {int(marker_id)}",
                        (cx - 20, cy - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

    # Texto de estado en la esquina
    estado = f"Detectados: {ids_lista}" if ids_lista else "Buscando marcadores..."
    cv2.putText(frame, estado, (10, 30),
                cv2.FONT_HERSHEY_SIMPLEX, 0.65, (0, 200, 255), 2)

    # --- Dibujar el mapa ---
    mapa = dibujar_mapa(ids_lista)

    # --- Combinar cámara + mapa en una sola ventana ---
    # Escalar la cámara para que tenga la misma altura que el mapa
    cam_h, cam_w = frame.shape[:2]
    escala       = MAP_H / cam_h
    cam_pequena  = cv2.resize(frame, (int(cam_w * escala), MAP_H))

    ventana      = np.hstack([cam_pequena, mapa])   # poner uno al lado del otro

    cv2.imshow("Detector ArUco - Almacen", ventana)

    # --- Salir con 'q' ---
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

# ──────────────────────────────────────────────
# 5.  CERRAR
# ──────────────────────────────────────────────
cap.release()
cv2.destroyAllWindows()
print("Programa terminado.")
