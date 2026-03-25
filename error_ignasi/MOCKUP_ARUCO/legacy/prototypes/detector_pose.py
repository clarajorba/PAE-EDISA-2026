"""
detector_pose.py
================
Detector ArUco con triangulación 3D en tiempo real.

¿Qué añade respecto a detector_simple.py?
  - Para cada marcador visible calcula su pose con solvePnP:
      rvec, tvec  →  orientación y posición del marcador en el sistema de la cámara
  - Invierte la transformación para obtener la posición de la CÁMARA en el sistema MUNDO.
  - Si hay varios marcadores visibles, promedia las estimaciones (triangulación).
  - Muestra X, Y, Z en metros sobre la imagen y en la consola.

Matemática clave
----------------
  solvePnP devuelve  (R, t)  tal que:
      p_camara = R · p_marcador_local + t

  Despejando la posición de la cámara en el sistema "marcador local":
      pos_cam_local = –R^T · t          (vector 3×1, metros)

  Pasando al sistema MUNDO (se suma la posición conocida del marcador):
      X_mundo = X_marcador + pos_cam_local[0]
      Y_mundo = Y_marcador + pos_cam_local[1]
      Z_mundo =              pos_cam_local[2]   ← altura sobre el suelo

  Con N marcadores: se promedian todas las estimaciones.

Teclas:
  q  →  salir
  r  →  resetear media de Z (si la escena cambia)

Dependencias:
  pip install opencv-contrib-python
"""

import cv2
import numpy as np
import time
import os

# ──────────────────────────────────────────────────────────────────────────────
# 1.  CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────────────────────

FUENTE_VIDEO  = 0                          # 0 = webcam  |  "video.mp4"
DICT_ARUCO    = cv2.aruco.DICT_4X4_1000   # coincide con los SVG 4x4_1000-X.svg

# Tamaño FÍSICO del marcador impreso (lado del cuadrado negro) en METROS
# ¡Mídelo con una regla y ajusta este valor!
MARKER_SIZE = 0.15    # 15 cm por defecto

# ─── Parámetros intrínsecos de la cámara ─────────────────────────────────────
# Si tienes un archivo de calibración, cárgalo aquí.
# Estos valores son típicos para una webcam HD 1280×720.
CAMERA_MATRIX = np.array([
    [921.17,   0.00, 459.90],
    [  0.00, 919.02, 351.24],
    [  0.00,   0.00,   1.00],
], dtype=np.float64)

DIST_COEFFS = np.zeros((5, 1), dtype=np.float64)   # sin aberración (aprox.)

# ─── Posiciones MUNDO de los marcadores (x, y) en metros ─────────────────────
# El suelo es el plano Z=0.  Los marcadores están posados en el suelo (Z_marcador=0).
ANCHO_MAPA = 5.0
ALTO_MAPA  = 4.0

POSICIONES_MARCADORES = {
    0: (0.0, 0.0),
    1: (5.0, 0.0),
    2: (5.0, 4.0),
    3: (0.0, 4.0),
    4: (2.5, 2.0),
}

# ─── Puntos 3D del marcador en su sistema LOCAL (origen = centro) ─────────────
_h = MARKER_SIZE / 2
MARKER_OBJ_PTS = np.array([
    [-_h,  _h, 0.0],   # esquina superior-izquierda
    [ _h,  _h, 0.0],   # esquina superior-derecha
    [ _h, -_h, 0.0],   # esquina inferior-derecha
    [-_h, -_h, 0.0],   # esquina inferior-izquierda
], dtype=np.float32)

# ─── Configuración de capturas fotográficas ──────────────────────────────────
DIST_MIN       = 1.50   # distancia máxima cámara↔marcador para activar captura (m)
TIEMPO_CAPTURA = 2.0    # segundos continuos dentro de DIST_MIN → dispara foto
COOLDOWN_FOTOS = 5.0    # espera mínima (s) entre fotos del mismo marcador
CARPETA_FOTOS  = "fotos_aruco"  # subcarpeta de salida

# ──────────────────────────────────────────────────────────────────────────────
# 2.  PREPARAR EL DETECTOR ARUCO
# ──────────────────────────────────────────────────────────────────────────────

diccionario = cv2.aruco.getPredefinedDictionary(DICT_ARUCO)
parametros  = cv2.aruco.DetectorParameters()
detector    = cv2.aruco.ArucoDetector(diccionario, parametros)

# ──────────────────────────────────────────────────────────────────────────────
# 3.  FUNCIÓN: estimar posición 3D de la cámara desde UN marcador
# ──────────────────────────────────────────────────────────────────────────────

def estimar_posicion_camara(corners_marcador, id_marcador):
    """
    Dados los corners de un marcador y su ID, devuelve la posición (X, Y, Z)
    de la cámara en el sistema mundo (metros).

    Pasos:
      1. solvePnP  →  rvec, tvec  (marcador en el sistema cámara)
      2. Invertir  →  cámara en el sistema marcador local
      3. Rotar     →  cámara en el sistema mundo (suma posición mundo del marcador)
    """
    if id_marcador not in POSICIONES_MARCADORES:
        return None, None, None

    # Reshape de corners: (1, 4, 2)  →  (4, 2)
    img_pts = corners_marcador.reshape(4, 2).astype(np.float32)

    ok, rvec, tvec = cv2.solvePnP(
        MARKER_OBJ_PTS,
        img_pts,
        CAMERA_MATRIX,
        DIST_COEFFS,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not ok:
        return None, None, None

    # ── Rotación: vector → matriz 3×3 ─────────────────────────────────────────
    R, _ = cv2.Rodrigues(rvec)

    # ── Posición de la cámara en el sistema LOCAL del marcador ─────────────────
    #    p_cam_local = –R^T · t
    pos_cam_local = (-R.T @ tvec).flatten()   # [dx_m, dy_m, dz_m]

    # ── Posición en el sistema MUNDO ───────────────────────────────────────────
    mx, my = POSICIONES_MARCADORES[id_marcador]  # posición mundo del marcador
    world_x = mx + pos_cam_local[0]
    world_y = my + pos_cam_local[1]
    world_z =      pos_cam_local[2]              # altura sobre el suelo

    return world_x, world_y, world_z, rvec, tvec

# ──────────────────────────────────────────────────────────────────────────────
# 4.  FUNCIÓN: dibujar el MAPA con la posición estimada
# ──────────────────────────────────────────────────────────────────────────────

MAP_W, MAP_H = 400, 320
PAD          = 30

def metros_a_pixeles(x_m, y_m):
    px = int(PAD + np.clip(x_m, 0, ANCHO_MAPA) / ANCHO_MAPA * (MAP_W - 2 * PAD))
    py = int(PAD + np.clip(y_m, 0, ALTO_MAPA)  / ALTO_MAPA  * (MAP_H - 2 * PAD))
    return px, py

# Altura del bloque de métricas que se añade bajo el mapa
METRICS_H = 130

def dibujar_mapa(ids_detectados, cam_x=None, cam_y=None, prox_state=None):
    """
    prox_state: dict  mid → {'dist': float, 'tiempo': float, 'fotos': int}
    """
    if prox_state is None:
        prox_state = {}

    mapa = np.full((MAP_H, MAP_W, 3), (20, 20, 30), dtype=np.uint8)
    cv2.rectangle(mapa, (PAD, PAD), (MAP_W - PAD, MAP_H - PAD), (120, 120, 120), 2)
    cv2.putText(mapa, "MAPA MUNDO (X-Y)", (PAD, PAD - 8),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (180, 180, 180), 1)

    # Marcadores
    for mid, (mx, my) in POSICIONES_MARCADORES.items():
        px, py = metros_a_pixeles(mx, my)
        activo  = mid in ids_detectados
        en_zona = mid in prox_state and prox_state[mid]['dist'] <= DIST_MIN
        color   = (0, 220, 80) if activo else (70, 70, 70)
        radio   = 10           if activo else 6

        # Anillo naranja si está en zona de captura
        if en_zona:
            t_ratio = min(prox_state[mid]['tiempo'] / TIEMPO_CAPTURA, 1.0)
            r_outer = int(18 + 6 * t_ratio)
            cv2.circle(mapa, (px, py), r_outer, (0, 140, 255), 1)
            # Arco de progreso (dibujar N puntos del círculo)
            n_pts = int(t_ratio * 36)
            for k in range(n_pts):
                ang = -np.pi / 2 + 2 * np.pi * k / 36
                ex = int(px + r_outer * np.cos(ang))
                ey = int(py + r_outer * np.sin(ang))
                cv2.circle(mapa, (ex, ey), 2, (0, 200, 255), -1)

        cv2.circle(mapa, (px, py), radio, color, -1)
        cv2.putText(mapa, str(mid), (px - 5, py + 5),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1)

    # Posición estimada de la cámara
    if cam_x is not None and cam_y is not None:
        px_c, py_c = metros_a_pixeles(cam_x, cam_y)
        for mid in ids_detectados:
            if mid in POSICIONES_MARCADORES:
                pm = metros_a_pixeles(*POSICIONES_MARCADORES[mid])
                cv2.line(mapa, (px_c, py_c), pm, (80, 160, 255), 1)
        cv2.circle(mapa, (px_c, py_c), 10, (0, 200, 255), -1)
        cv2.circle(mapa, (px_c, py_c), 10, (255, 255, 255),  1)
        cv2.putText(mapa, "CAM", (px_c - 14, py_c - 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 200, 255), 1)

    # ── Panel de métricas de proximidad ──────────────────────────────────────
    panel = np.full((METRICS_H, MAP_W, 3), (12, 12, 20), dtype=np.uint8)
    cv2.line(panel, (0, 0), (MAP_W, 0), (80, 80, 80), 1)
    cv2.putText(panel, "PROXIMIDAD  (umbral {:.2f}m)".format(DIST_MIN),
                (8, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (150, 150, 150), 1)

    # Una fila por marcador visible
    for row, mid in enumerate(sorted(prox_state.keys())):
        if row >= 5:
            break
        st   = prox_state[mid]
        dist = st['dist']
        t    = st['tiempo']
        ftos = st['fotos']
        en_z = dist <= DIST_MIN

        y = 30 + row * 20
        # Columna ID
        cv2.putText(panel, f"ID{mid}", (8, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (200, 200, 200), 1)
        # Distancia
        col_dist = (0, 200, 80) if en_z else (160, 160, 160)
        cv2.putText(panel, f"{dist:.2f}m", (50, y), cv2.FONT_HERSHEY_SIMPLEX,
                    0.4, col_dist, 1)
        # Barra de progreso del timer  [████░░░░]  120 px ancho
        bx, bw, bh = 105, 120, 10
        cv2.rectangle(panel, (bx, y - bh), (bx + bw, y), (40, 40, 40), -1)
        fill = int(bw * min(t / TIEMPO_CAPTURA, 1.0)) if en_z else 0
        bar_color = (0, 220, 255) if fill < bw else (0, 255, 80)
        if fill > 0:
            cv2.rectangle(panel, (bx, y - bh), (bx + fill, y), bar_color, -1)
        cv2.rectangle(panel, (bx, y - bh), (bx + bw, y), (80, 80, 80), 1)
        # Tiempo en texto
        cv2.putText(panel, f"{t:.1f}s/{TIEMPO_CAPTURA:.0f}s",
                    (bx + bw + 5, y), cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)
        # Cámara de foto si ya se han tomado fotos
        if ftos > 0:
            cv2.putText(panel, f"[{ftos}f]", (bx + bw + 60, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (80, 255, 160), 1)

    if not prox_state:
        cv2.putText(panel, "Sin marcadores detectados", (8, 50),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, (80, 80, 80), 1)

    return np.vstack([mapa, panel])

# ──────────────────────────────────────────────────────────────────────────────
# 5.  BUCLE PRINCIPAL
# ──────────────────────────────────────────────────────────────────────────────

# ── Crear carpeta de fotos ────────────────────────────────────────────────────
os.makedirs(CARPETA_FOTOS, exist_ok=True)
print(f"Fotos se guardarán en: {os.path.abspath(CARPETA_FOTOS)}")

# ── Estado para control de capturas (por marcador) ───────────────────────────
timer_enter   = {}   # mid → timestamp de entrada en zona DIST_MIN
ultima_foto   = {}   # mid → timestamp de la última foto tomada
fotos_tomadas = {}   # mid → contador de fotos

cap = cv2.VideoCapture(FUENTE_VIDEO)
if not cap.isOpened():
    print(f"ERROR: No se puede abrir la fuente: {FUENTE_VIDEO}")
    exit()

print("Detector con triangulación 3D iniciado.")
print("  q → salir\n")

# ── Ventana a pantalla completa ───────────────────────────────────────────────
WIN_NAME = "Detector ArUco — Triangulacion 3D"
cv2.namedWindow(WIN_NAME, cv2.WINDOW_NORMAL)
cv2.setWindowProperty(WIN_NAME, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

# Posición estimada (suavizada con media móvil)
alpha    = 0.4      # factor de suavizado EMA (0=muy suave, 1=sin suavizado)
pos_suav = None     # (X, Y, Z) suavizado

while True:
    ok, frame = cap.read()
    if not ok:
        break

    # ── Detección ─────────────────────────────────────────────────────────────
    gris       = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners, ids, _ = detector.detectMarkers(gris)

    # ── Anotación básica de los marcadores ────────────────────────────────────
    ids_lista   = []
    estimados   = []   # lista de (X, Y, Z) uno por marcador
    prox_state  = {}   # mid → {dist, tiempo, fotos}
    ahora       = time.time()

    if ids is not None:
        cv2.aruco.drawDetectedMarkers(frame, corners, ids)
        ids_lista = ids.flatten().tolist()

        for i, mid in enumerate(ids_lista):
            result = estimar_posicion_camara(corners[i], mid)
            if result[0] is not None:
                world_x, world_y, world_z, rvec, tvec = result
                estimados.append((world_x, world_y, world_z))

                # Dibujar ejes 3D sobre el marcador
                cv2.drawFrameAxes(frame, CAMERA_MATRIX, DIST_COEFFS,
                                  rvec, tvec, MARKER_SIZE * 0.8)

                # Distancia euclídea cámara→marcador
                dist = float(np.linalg.norm(tvec))

                # Diagnóstico en consola: siempre visible
                estado = "EN ZONA" if dist <= DIST_MIN else f"fuera (>{DIST_MIN:.2f}m)"
                print(f"\r  ID{mid}  dist={dist:.3f}m  umbral={DIST_MIN:.2f}m  [{estado}]          ",
                      end="", flush=True)

                # ── Lógica de captura por proximidad ─────────────────────────
                if dist <= DIST_MIN:
                    if mid not in timer_enter:
                        timer_enter[mid] = ahora
                    tiempo_en_zona = ahora - timer_enter[mid]
                    cooldown_ok = (mid not in ultima_foto or
                                   ahora - ultima_foto[mid] >= COOLDOWN_FOTOS)

                    if tiempo_en_zona >= TIEMPO_CAPTURA and cooldown_ok:
                        ts     = time.strftime("%Y%m%d_%H%M%S")
                        nombre = os.path.join(CARPETA_FOTOS,
                                              f"aruco_{mid:02d}_{ts}.jpg")
                        cv2.imwrite(nombre, frame)
                        ultima_foto[mid]   = ahora
                        fotos_tomadas[mid] = fotos_tomadas.get(mid, 0) + 1
                        print(f"\n  [FOTO] Guardada: {nombre}")
                        # Flash verde en pantalla
                        overlay_flash = frame.copy()
                        cv2.rectangle(overlay_flash, (0, 0),
                                      (frame.shape[1], frame.shape[0]),
                                      (0, 255, 80), 12)
                        cv2.addWeighted(overlay_flash, 0.4, frame, 0.6, 0, frame)
                else:
                    # Salió de la zona → resetear timer
                    timer_enter.pop(mid, None)

                # Tiempo acumulado en zona (0 si no está dentro)
                t_zona = (ahora - timer_enter[mid]) if mid in timer_enter else 0.0
                prox_state[mid] = {
                    'dist':   dist,
                    'tiempo': t_zona,
                    'fotos':  fotos_tomadas.get(mid, 0),
                }

                # Etiqueta sobre el marcador
                en_zona = dist <= DIST_MIN
                col_lbl = (0, 140, 255) if en_zona else (0, 255, 200)
                cx_img  = int(corners[i][0][:, 0].mean())
                cy_img  = int(corners[i][0][:, 1].mean()) - 14
                cv2.putText(frame, f"ID{mid}  d={dist:.2f}m",
                            (cx_img - 30, cy_img),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, col_lbl, 1)
                if en_zona:
                    t_zona = prox_state[mid]['tiempo']
                    cv2.putText(frame, f"  Timer: {t_zona:.1f}/{TIEMPO_CAPTURA:.0f}s",
                                (cx_img - 30, cy_img - 18),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 200, 255), 1)

    # ── Triangulación: promedio de las estimaciones ────────────────────────────
    if estimados:
        xs = [e[0] for e in estimados]
        ys = [e[1] for e in estimados]
        zs = [e[2] for e in estimados]
        pos_raw = (sum(xs) / len(xs),
                   sum(ys) / len(ys),
                   sum(zs) / len(zs))

        # Media móvil exponencial para suavizar el jitter
        if pos_suav is None:
            pos_suav = pos_raw
        else:
            pos_suav = tuple(alpha * r + (1 - alpha) * s
                             for r, s in zip(pos_raw, pos_suav))

        X, Y, Z = pos_suav

        # ── Overlay en la imagen ───────────────────────────────────────────────
        # Fondo semitransparente para el texto
        overlay = frame.copy()
        cv2.rectangle(overlay, (8, 8), (310, 115), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        lineas = [
            (f"Marcadores visibles: {len(estimados)}", (180, 180, 180)),
            (f"X = {X:+.3f} m  (Este-Oeste)",         (100, 220, 255)),
            (f"Y = {Y:+.3f} m  (Norte-Sur)",           (100, 255, 180)),
            (f"Z = {Z:+.3f} m  (Altura)",              (255, 200, 100)),
        ]
        for k, (texto, color) in enumerate(lineas):
            cv2.putText(frame, texto, (14, 30 + k * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 1)

        # Consola: posición + resumen de proximidad
        fotos_str = "  ".join(
            f"ID{m}:{prox_state[m]['dist']:.2f}m"
            for m in sorted(prox_state)
        )
        print(f"\r  CÁMARA →  X={X:+6.3f}m   Y={Y:+6.3f}m   Z={Z:+6.3f}m"
              f"  | {fotos_str}", end="", flush=True)

    else:
        pos_suav = None   # si no se ve nada, resetear
        # Aviso en pantalla
        cv2.putText(frame, "Sin marcadores visibles", (14, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, (60, 60, 255), 2)

    # ── Mapa + panel de métricas ─────────────────────────────────────────────
    cam_x    = pos_suav[0] if pos_suav else None
    cam_y    = pos_suav[1] if pos_suav else None
    mapa     = dibujar_mapa(ids_lista, cam_x, cam_y, prox_state)
    total_h  = MAP_H + METRICS_H

    # Redimensionar frame para que coincida en altura con mapa + métricas
    h_frame = frame.shape[0]
    if h_frame != total_h:
        escala   = total_h / h_frame
        nuevo_w  = int(frame.shape[1] * escala)
        frame_rs = cv2.resize(frame, (nuevo_w, total_h))
    else:
        frame_rs = frame

    combinado = np.hstack([frame_rs, mapa])

    # Escalar el resultado al tamaño real de la ventana/pantalla
    _, _, win_w, win_h = cv2.getWindowImageRect(WIN_NAME)
    if win_w > 0 and win_h > 0:
        combinado = cv2.resize(combinado, (win_w, win_h),
                               interpolation=cv2.INTER_LINEAR)

    cv2.imshow(WIN_NAME, combinado)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

print("\nSistema detenido.")
cap.release()
cv2.destroyAllWindows()
