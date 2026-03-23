"""
medir_error_estatico_pc.py  (v3)
=================================
Interfaz profesional para medir el error estático ArUco con webcam de PC.

Ventana de grabación
  ┌──────────────────────────┬─────────────────────────┐
  │  Feed cámara con ArUco   │  Dashboard en tiempo    │
  │  detecciones marcadas    │  real: posición, ruido, │
  │                          │  series, métricas       │
  └──────────────────────────┴─────────────────────────┘

Al finalizar
  - Pantalla de resultados con stats RAW vs KALMAN
  - Serie temporal X/Y/Z con bandas ±2σ
  - Scatter 2D con elipses de confianza
  - Mapa 3D: marcadores + nube de posiciones de cámara

Dependencias:
  pip install opencv-contrib-python numpy matplotlib
"""

import cv2
import numpy as np
import json, time, csv, os
from collections import deque
from pathlib import Path
from datetime import datetime

try:
    import matplotlib
    matplotlib.use("Agg")           # backend no-GUI para guardar PNGs
    import matplotlib.pyplot as plt
    from mpl_toolkits.mplot3d import Axes3D          # noqa: F401
    from mpl_toolkits.mplot3d.art3d import Poly3DCollection
    from matplotlib.patches import Ellipse
    MATPLOTLIB_OK = True
except ImportError:
    MATPLOTLIB_OK = False
    print("[AVISO] matplotlib no disponible. Instala: pip install matplotlib")


# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

DURACION_S   = 30
VIDEO_SOURCE = 0
RESOLUCION   = (1280, 720)
CONFIG_PATH  = "config/markers_3d.json"
OUTPUT_DIR   = "mediciones"
POSICION_REAL = np.array([0.0, 0.0, 1.36])  # Z=136cm real; X,Y desconocidos → solo ΔZ es válido

# Filtrado
MAX_REPROJECTION_PX = 3.0
MARKER_MIN_PX       = 40
WARM_UP_S           = 2.0
UMBRAL_FILTRO_M     = 0.050
VENTANA_MEDIANA     = 30

# Kalman
USAR_KALMAN       = True
KALMAN_PROC_NOISE = 1e-5
KALMAN_MEAS_NOISE = 1e-3

# Layout ventana compuesta
CAM_W, CAM_H = 800, 450        # cámara redimensionada
DASH_W       = 480             # ancho del dashboard
COMP_W       = CAM_W + DASH_W  # 1280 px total

# ─── Parámetros de cámara ─────────────────────────────────────────────────────

CAMERA_MATRIX = np.array([
    [960.18,   0.00, 632.91],
    [  0.00, 960.77, 364.30],
    [  0.00,   0.00,   1.00],
], dtype=np.float64)

DIST_COEFFS = np.array([
    [ -0.246352],
    [  2.713296],
    [ -0.001691],
    [ -0.004008],
    [-10.388485],
], dtype=np.float64)

DICT_ARUCO = cv2.aruco.DICT_4X4_1000


# ─── KALMAN 3D ────────────────────────────────────────────────────────────────

class KalmanPos3D:
    def __init__(self, proc=1e-5, meas=1e-3):
        self.kf = cv2.KalmanFilter(3, 3, 0, cv2.CV_64F)
        self.kf.transitionMatrix    = np.eye(3)
        self.kf.measurementMatrix   = np.eye(3)
        self.kf.processNoiseCov     = np.eye(3) * proc
        self.kf.measurementNoiseCov = np.eye(3) * meas
        self.kf.errorCovPost        = np.eye(3)
        self._base = meas
        self._init = False

    def update(self, pos: np.ndarray, rerr: float = 1.0) -> np.ndarray:
        m = pos.reshape(3, 1)
        if not self._init:
            self.kf.statePost = m.copy()
            self._init = True
            return pos.copy()
        self.kf.measurementNoiseCov = np.eye(3) * self._base * max(rerr, 0.1) ** 2
        self.kf.predict()
        return self.kf.correct(m).flatten()


# ─── MAPA Y DETECTOR ──────────────────────────────────────────────────────────

def cargar_mapa(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    sz = float(d.get("marker_size", 0.10))
    mk = {int(k): np.array([v["x"], v["y"], v["z"]], dtype=np.float64)
          for k, v in d["markers"].items()}
    return mk, sz

MARKERS, MARKER_SIZE = cargar_mapa(CONFIG_PATH)
VALID_IDS = set(MARKERS.keys())

_h = MARKER_SIZE / 2
MARKER_OBJ_PTS = np.array(
    [[-_h, _h, 0], [_h, _h, 0], [_h, -_h, 0], [-_h, -_h, 0]], dtype=np.float32)

_dict   = cv2.aruco.getPredefinedDictionary(DICT_ARUCO)
_params = cv2.aruco.DetectorParameters()
_params.cornerRefinementMethod        = cv2.aruco.CORNER_REFINE_SUBPIX
_params.cornerRefinementWinSize       = 7
_params.cornerRefinementMaxIterations = 60
detector = cv2.aruco.ArucoDetector(_dict, _params)


# ─── ESTIMACIÓN DE POSE ───────────────────────────────────────────────────────

def _rerr(rv, tv, img):
    p, _ = cv2.projectPoints(MARKER_OBJ_PTS, rv, tv, CAMERA_MATRIX, DIST_COEFFS)
    return float(np.sqrt(np.mean(np.sum((p.reshape(4, 2) - img) ** 2, axis=1))))


def _pnp_best(img_pts):
    """Mejor solución IPPE_SQUARE filtrando soluciones espejo explícitamente.

    solvePnPGeneric con IPPE_SQUARE devuelve EXACTAMENTE las 2 soluciones
    físicas del problema. Filtramos la que pone la cámara detrás del marcador
    (cam_z ≤ 0) o a distancia irreal (>8 m).
    """
    try:
        _, rvecs, tvecs, _ = cv2.solvePnPGeneric(
            MARKER_OBJ_PTS, img_pts, CAMERA_MATRIX, DIST_COEFFS,
            flags=cv2.SOLVEPNP_IPPE_SQUARE)
    except cv2.error:
        return False, None, None, float("inf")

    best_e, best_rv, best_tv = float("inf"), None, None
    for rv, tv in zip(rvecs, tvecs):
        R_m, _ = cv2.Rodrigues(rv)
        cam_z = float((-R_m.T @ tv).flatten()[2])
        if cam_z <= 0 or cam_z > 8.0:   # espejo o distancia irreal → descartar
            continue
        e = _rerr(rv, tv, img_pts)
        if e < best_e:
            best_e, best_rv, best_tv = e, rv, tv

    if best_rv is None:
        return False, None, None, float("inf")
    return True, best_rv, best_tv, best_e


def _combined_pnp_world(valid_markers):
    """
    PnP combinado multi-marcador usando coordenadas mundo reales.

    Se pasan TODOS los puntos de TODOS los marcadores a solvePnP en una sola
    llamada. Se prueba como semilla la pose de cada marcador individual
    convertida de coordenadas locales a coordenadas mundo:
        t_world = t_local - R_local @ center_world
    Esto garantiza que el optimizador parte cerca de la solución real.

    Tras el solve se aplica RANSAC iterativo: se elimina el marcador con
    mayor error de reproyección si supera el umbral, y se re-optimiza.

    valid_markers: list of (mid, img_pts, rv_local, tv_local, individual_err)
    Returns: (cam_world_3d, n_markers_used, combined_reproj_err)
    """

    def _solve_subset(subset):
        obj = np.vstack([MARKERS[m[0]] + MARKER_OBJ_PTS for m in subset]).astype(np.float32)
        img = np.vstack([m[1] for m in subset]).astype(np.float32)

        best_e, best_rv, best_tv = float("inf"), None, None

        # ── Semillas: cada marcador individual convertido a coords mundo ──────
        # En solve con coords locales: P_cam = R * P_local + t_local
        # En solve con coords mundo:   P_cam = R * P_world + t_world
        # Como P_world = P_local + center:  t_world = t_local - R @ center
        for m in subset:
            rv_loc = m[2].reshape(3, 1).astype(np.float64)
            tv_loc = m[3].reshape(3, 1).astype(np.float64)
            R_loc, _ = cv2.Rodrigues(rv_loc)
            center = MARKERS[m[0]].astype(np.float64).reshape(3, 1)
            tv_w = tv_loc - R_loc @ center   # semilla en coordenadas mundo

            ok, rv, tv = cv2.solvePnP(obj, img, CAMERA_MATRIX, DIST_COEFFS,
                                       rvec=rv_loc, tvec=tv_w,
                                       useExtrinsicGuess=True,
                                       flags=cv2.SOLVEPNP_ITERATIVE)
            if ok:
                proj, _ = cv2.projectPoints(obj, rv, tv, CAMERA_MATRIX, DIST_COEFFS)
                e = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img)**2, axis=1))))
                if e < best_e:
                    best_e, best_rv, best_tv = e, rv.copy(), tv.copy()

        # ── Semilla libre: SQPNP + refinado ITERATIVE ─────────────────────────
        ok, rv, tv = cv2.solvePnP(obj, img, CAMERA_MATRIX, DIST_COEFFS,
                                   flags=cv2.SOLVEPNP_SQPNP)
        if ok:
            ok2, rv2, tv2 = cv2.solvePnP(obj, img, CAMERA_MATRIX, DIST_COEFFS,
                                          rvec=rv.copy(), tvec=tv.copy(),
                                          useExtrinsicGuess=True,
                                          flags=cv2.SOLVEPNP_ITERATIVE)
            if ok2:
                rv, tv = rv2, tv2
            proj, _ = cv2.projectPoints(obj, rv, tv, CAMERA_MATRIX, DIST_COEFFS)
            e = float(np.sqrt(np.mean(np.sum((proj.reshape(-1, 2) - img)**2, axis=1))))
            if e < best_e:
                best_e, best_rv, best_tv = e, rv.copy(), tv.copy()

        if best_rv is None:
            return None
        return best_rv, best_tv, best_e, obj, img

    # ── RANSAC iterativo: eliminar el peor marcador hasta que todos estén OK ──
    current   = list(valid_markers)
    last_good = None

    while len(current) >= 1:
        res = _solve_subset(current)
        if res is None:
            break
        rv, tv, err, obj, img = res
        last_good = (rv, tv, err, len(current))

        if len(current) == 1:
            break  # nada más que eliminar

        # Error por marcador
        proj, _ = cv2.projectPoints(obj, rv, tv, CAMERA_MATRIX, DIST_COEFFS)
        per_corner  = np.sqrt(np.sum((proj.reshape(-1, 2) - img)**2, axis=1))
        marker_errs = [float(np.mean(per_corner[i*4:(i+1)*4])) for i in range(len(current))]
        worst_idx   = int(np.argmax(marker_errs))

        if marker_errs[worst_idx] <= MAX_REPROJECTION_PX * 1.5:
            break  # todos dentro del umbral

        current = [m for i, m in enumerate(current) if i != worst_idx]

    if last_good is None:
        return None

    rv, tv, err, n = last_good
    R, _ = cv2.Rodrigues(rv)
    return (-R.T @ tv).flatten(), n, err


def estimar_posicion(corners_det, ids_det):
    if ids_det is None or len(ids_det) == 0:
        return None, 0, float("inf")

    # ── Paso 1: por cada marcador, obtener AMBAS soluciones IPPE_SQUARE ────────
    # solvePnPGeneric devuelve las 2 soluciones físicas. Guardamos todas las
    # válidas (cam_z > 0, distancia razonable, reproyección OK) por marcador.
    per_marker = []   # [ [(cam_world, reproj_err), ...], ... ]

    for corners, mid in zip(corners_det, ids_det.flatten().tolist()):
        if mid not in VALID_IDS:
            continue
        img_pts = corners.reshape(4, 2).astype(np.float32)
        if min(np.linalg.norm(img_pts[(i+1)%4] - img_pts[i]) for i in range(4)) < MARKER_MIN_PX:
            continue

        try:
            _, rvecs, tvecs, _ = cv2.solvePnPGeneric(
                MARKER_OBJ_PTS, img_pts, CAMERA_MATRIX, DIST_COEFFS,
                flags=cv2.SOLVEPNP_IPPE_SQUARE)
        except cv2.error:
            continue

        sols = []
        for rv, tv in zip(rvecs, tvecs):
            R_m, _ = cv2.Rodrigues(rv)
            cam_local = (-R_m.T @ tv).flatten()
            if cam_local[2] <= 0 or cam_local[2] > 8.0:
                continue                             # espejo o distancia irreal
            e = _rerr(rv, tv, img_pts)
            if e > MAX_REPROJECTION_PX:
                continue
            sols.append((MARKERS[mid] + cam_local, e))

        if sols:
            per_marker.append(sols)

    if not per_marker:
        return None, 0, float("inf")

    # ── Paso 2: 1 marcador → mejor solución directamente ────────────────────
    if len(per_marker) == 1:
        best = min(per_marker[0], key=lambda x: x[1])
        return best[0], 1, best[1]

    # ── Paso 3: N marcadores → selección por consistencia mutua ─────────────
    # Cada marcador puede tener 1-2 candidatos. La solución correcta es la que
    # maximiza el acuerdo entre marcadores (todas deben dar la misma posición).
    #
    # Algoritmo:
    #   a) Anchor = mediana de las mejores soluciones individuales
    #   b) Para cada marcador, elegir el candidato más cercano al anchor
    #   c) Descartar marcadores que superen el umbral de consistencia
    #   d) Media ponderada de los seleccionados

    first_best = [min(sols, key=lambda x: x[1]) for sols in per_marker]
    anchor = np.median([s[0] for s in first_best], axis=0)

    selected_pos, selected_err = [], []
    for sols in per_marker:
        best = min(sols, key=lambda s: np.linalg.norm(s[0] - anchor))
        if np.linalg.norm(best[0] - anchor) < 0.20:   # 20 cm de tolerancia
            selected_pos.append(best[0])
            selected_err.append(best[1])

    if not selected_pos:
        return None, 0, float("inf")

    errs = np.clip(selected_err, 0.1, None)
    w = 1.0 / errs**2; w /= w.sum()
    return (np.average(selected_pos, weights=w, axis=0),
            len(selected_pos),
            float(np.average(selected_err, weights=w)))


# ─── DASHBOARD ────────────────────────────────────────────────────────────────

class Dashboard:
    """Panel derecho de la ventana compuesta con métricas en tiempo real."""

    BG   = (18, 22, 32)
    SEP  = (45, 55, 75)
    TXT  = (190, 200, 210)
    MUTE = (90, 100, 115)
    GOOD = (60, 200, 80)
    INFO = (200, 160, 20)
    WARN = (30, 130, 255)
    CX   = (200, 120,  60)   # color eje X (azulado)
    CY   = ( 60, 200, 100)   # color eje Y (verdoso)
    CZ   = ( 80,  80, 220)   # color eje Z (rojizo)
    KAL  = (200, 140, 255)   # kalman (violeta)

    def __init__(self, h: int, duracion_s: float):
        self.h = h
        self.dur = duracion_s
        self.hx: deque = deque(maxlen=400)
        self.hy: deque = deque(maxlen=400)
        self.hz: deque = deque(maxlen=400)
        self.roll: deque = deque(maxlen=30)

    def push(self, pos):
        if pos is not None:
            self.hx.append(pos[0] * 100)
            self.hy.append(pos[1] * 100)
            self.hz.append(pos[2] * 100)
            self.roll.append(pos)

    # ── helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _txt(p, txt, x, y, color, scale=0.42, thick=1):
        cv2.putText(p, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, thick, cv2.LINE_AA)

    @staticmethod
    def _big(p, txt, x, y, color, scale=0.65, thick=2):
        cv2.putText(p, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX,
                    scale, color, thick, cv2.LINE_AA)

    @staticmethod
    def _hline(p, y, c, w=DASH_W):
        cv2.line(p, (0, y), (w, y), c, 1)

    @staticmethod
    def _bar(p, x0, y0, x1, y1, pct, fg, bg=(35, 40, 55)):
        cv2.rectangle(p, (x0, y0), (x1, y1), bg, -1)
        fx = x0 + int((x1 - x0) * min(max(pct, 0), 1))
        if fx > x0:
            cv2.rectangle(p, (x0, y0), (fx, y1), fg, -1)

    @staticmethod
    def _series(p, data, x0, y0, x1, y1, color):
        cv2.rectangle(p, (x0, y0), (x1, y1), (22, 27, 42), -1)
        arr = np.array(data, dtype=np.float32) if data else None
        if arr is None or len(arr) < 2:
            return
        mn, mx = arr.min(), arr.max()
        rng = mx - mn if mx - mn > 1e-4 else 1e-4
        w, h = x1 - x0, y1 - y0
        mu = float(arr.mean())
        my_px = int(y1 - (mu - mn) / rng * h)
        cv2.line(p, (x0, my_px), (x1, my_px), (55, 62, 80), 1)
        n = len(arr)
        pts = np.array([[x0 + int(i*(w-1)/max(n-1,1)),
                         int(y1 - (v - mn)/rng * (h-1))]
                        for i, v in enumerate(arr)],
                       dtype=np.int32).reshape(-1, 1, 2)
        pts[:, 0, 1] = np.clip(pts[:, 0, 1], y0, y1)
        cv2.polylines(p, [pts], False, color, 1, cv2.LINE_AA)

    # ── render ────────────────────────────────────────────────────────────────

    def render(self, elapsed, en_warmup, elapsed_total,
               n_muestras, n_rechazadas, n_markers, reproj_err,
               pos, pos_kal, frames_tot, frames_det) -> np.ndarray:

        W = DASH_W
        panel = np.full((self.h, W, 3), self.BG, dtype=np.uint8)
        t = self._txt
        b = self._big
        hl = self._hline
        br = self._bar

        # ── 1. Header ─────────────────────────────────────────────────────
        cv2.rectangle(panel, (0, 0), (W, 40), (28, 33, 48), -1)
        if en_warmup:
            remaining = max(0, WARM_UP_S - elapsed_total)
            b(panel, f"CALENTANDO  {remaining:.1f}s", 10, 27, self.INFO)
            prog = elapsed_total / max(WARM_UP_S, 0.01)
            fc = self.INFO
        else:
            remaining = max(0, self.dur - elapsed)
            b(panel, f"GRABANDO  {remaining:.1f}s restantes", 10, 27, self.WARN)
            prog = elapsed / max(self.dur, 0.01)
            fc = self.GOOD
        br(panel, 0, 40, W, 50, prog, fc)
        hl(panel, 50, self.SEP)

        # ── 2. Posición ───────────────────────────────────────────────────
        y = 56
        t(panel, "POSICION ACTUAL", 10, y, self.MUTE, 0.37)
        y += 18
        axes = [("X", pos[0]*100 if pos is not None else None, self.CX),
                ("Y", pos[1]*100 if pos is not None else None, self.CY),
                ("Z", pos[2]*100 if pos is not None else None, self.CZ)]
        for lbl, val, col in axes:
            vt = f"{val:+.3f} cm" if val is not None else "  ---"
            t(panel, lbl, 12, y, col, 0.52, 2)
            b(panel, vt, 38, y, self.TXT, 0.60, 1)
            if pos_kal is not None:
                idx = ["X","Y","Z"].index(lbl)
                kv = pos_kal[idx] * 100
                t(panel, f"kal {kv:+.3f}", 260, y, self.KAL, 0.37)
            y += 27

        hl(panel, y + 3, self.SEP)

        # ── 3. Ruido rolling ──────────────────────────────────────────────
        y += 12
        t(panel, "RUIDO  σ  rolling (30 muestras)", 10, y, self.MUTE, 0.37)
        y += 16
        if len(self.roll) >= 3:
            stds = np.std(np.array(self.roll), axis=0) * 1000
            max_s = max(float(stds.max()), 1.5)
        else:
            stds = np.zeros(3)
            max_s = 1.5

        s3d = float(np.sqrt(np.sum(stds**2)))
        s3d_col = self.GOOD if s3d < 5 else (self.INFO if s3d < 15 else self.WARN)

        for lbl, sv, col in [("X", stds[0], self.CX),
                               ("Y", stds[1], self.CY),
                               ("Z", stds[2], self.CZ)]:
            t(panel, lbl, 12, y, col, 0.4, 1)
            br(panel, 30, y-11, 340, y, sv/max_s, col)
            t(panel, f"{sv:.2f}mm", 348, y, self.TXT, 0.38)
            y += 17

        t(panel, f"3D: {s3d:.2f}mm", 10, y, s3d_col, 0.40, 1)
        y += 14
        hl(panel, y + 2, self.SEP)

        # ── 4. Métricas de calidad ─────────────────────────────────────────
        y += 10
        det_rate = 100.0 * frames_det / max(frames_tot, 1)
        rej_rate = 100.0 * n_rechazadas / max(n_muestras + n_rechazadas, 1)

        re_col = self.GOOD if reproj_err < 1.5 else self.WARN
        re_txt = f"{reproj_err:.3f} px" if reproj_err < 99 else "---"

        t(panel, f"Reproyeccion: {re_txt}", 10, y, re_col, 0.41)
        y += 18
        t(panel, f"Markers vis.: {n_markers}   Det. rate: {det_rate:.0f}%", 10, y, self.TXT, 0.41)
        y += 18
        t(panel, f"Muestras: {n_muestras}   Rechazadas: {n_rechazadas} ({rej_rate:.0f}%)",
          10, y, self.TXT, 0.38)
        y += 16
        hl(panel, y + 2, self.SEP)

        # ── 5. Series temporales ──────────────────────────────────────────
        y += 8
        rem_h  = self.h - y - 5
        g_h    = max((rem_h - 20) // 3, 38)
        labels = ["X (cm)", "Y (cm)", "Z (cm)"]
        bufs   = [list(self.hx), list(self.hy), list(self.hz)]
        cols   = [self.CX, self.CY, self.CZ]

        for i, (lbl, buf, col) in enumerate(zip(labels, bufs, cols)):
            gy = y + i * (g_h + 7)
            t(panel, lbl, 5, gy + 10, col, 0.34)
            self._series(panel, buf, 0, gy + 13, W - 2, gy + 13 + g_h - 13, col)

        return panel


# ─── GRABACIÓN ────────────────────────────────────────────────────────────────

def grabar_posiciones(cap, duracion_s):
    muestras_raw, muestras_kal = [], []
    n_rej   = 0
    ventana = deque(maxlen=VENTANA_MEDIANA)
    kalman  = KalmanPos3D(KALMAN_PROC_NOISE, KALMAN_MEAS_NOISE) if USAR_KALMAN else None
    dash    = Dashboard(CAM_H, duracion_s)

    frames_tot = frames_det = 0
    t0    = time.monotonic()
    t_rec = None

    win = "Medicion Estatica PC"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, COMP_W, CAM_H)

    print(f"\n  Calentamiento {WARM_UP_S:.0f}s → grabación {duracion_s}s. NO MUEVAS LA CÁMARA.\n")

    while True:
        et = time.monotonic() - t0
        en_warmup = t_rec is None
        if en_warmup and et >= WARM_UP_S:
            t_rec = time.monotonic()
            print("  Grabación iniciada.")
        elapsed = (time.monotonic() - t_rec) if t_rec else 0.0
        if t_rec and elapsed >= duracion_s:
            break

        ok, frame = cap.read()
        if not ok:
            break
        frames_tot += 1

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners_det, ids_det, _ = detector.detectMarkers(gray)
        pos_raw, n_mk, rerr = estimar_posicion(corners_det, ids_det)

        if ids_det is not None:
            cv2.aruco.drawDetectedMarkers(frame, corners_det, ids_det)
        if pos_raw is not None:
            frames_det += 1


        pos_kal = None
        if not en_warmup and pos_raw is not None:
            accept = True
            if len(ventana) >= 20:
                ref = np.median(np.array(ventana), axis=0)
                if np.linalg.norm(pos_raw - ref) > UMBRAL_FILTRO_M:
                    accept = False
                    n_rej += 1

            if accept:
                ventana.append(pos_raw.copy())
                dash.push(pos_raw)
                pos_kal = kalman.update(pos_raw, rerr) if kalman else pos_raw

                entry = {"t": round(elapsed, 4), "n_markers": n_mk,
                         "reproj_err": round(rerr, 4)}
                muestras_raw.append({**entry, "x": pos_raw[0], "y": pos_raw[1], "z": pos_raw[2]})
                muestras_kal.append({**entry, "x": pos_kal[0], "y": pos_kal[1], "z": pos_kal[2]})

        # Composición del frame
        cam_resized = cv2.resize(frame, (CAM_W, CAM_H))
        panel = dash.render(elapsed, en_warmup, et, len(muestras_raw), n_rej,
                            n_mk, rerr, pos_raw, pos_kal, frames_tot, frames_det)
        composite = np.hstack([cam_resized, panel])

        cv2.imshow(win, composite)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cv2.destroyWindow(win)
    det_r = 100.0 * frames_det / max(frames_tot, 1)
    rej_r = 100.0 * n_rej / max(len(muestras_raw) + n_rej, 1)
    print(f"  Fin: {len(muestras_raw)} muestras | Det {det_r:.1f}% | "
          f"Rechazadas {n_rej} ({rej_r:.1f}%)")
    return muestras_raw, muestras_kal, n_rej, det_r


# ─── ANÁLISIS ─────────────────────────────────────────────────────────────────

def analizar(muestras, n_rej=0, label="raw"):
    if not muestras:
        return None
    xs = np.array([m["x"] for m in muestras])
    ys = np.array([m["y"] for m in muestras])
    zs = np.array([m["z"] for m in muestras])
    dur = muestras[-1]["t"] - muestras[0]["t"]

    s = {"label": label, "n_muestras": len(muestras), "n_rechazadas": n_rej,
         "tasa_rechazo_pct": round(100*n_rej/max(len(muestras)+n_rej,1), 2),
         "duracion_s": round(dur, 3),
         "frecuencia_hz": round(len(muestras)/max(dur, 0.01), 2)}

    for l, v in [("x", xs), ("y", ys), ("z", zs)]:
        s[f"{l}_media"]   = float(np.mean(v))
        s[f"{l}_mediana"] = float(np.median(v))
        s[f"{l}_std"]     = float(np.std(v))
        s[f"{l}_rango"]   = float(np.ptp(v))

    media = np.array([s["x_media"], s["y_media"], s["z_media"]])
    d3    = np.linalg.norm(np.column_stack([xs, ys, zs]) - media, axis=1)
    s["sep50_mm"]          = float(np.percentile(d3, 50) * 1000)
    s["sep95_mm"]          = float(np.percentile(d3, 95) * 1000)
    s["error_3d_medio_mm"] = float(np.mean(d3) * 1000)
    s["error_3d_std_mm"]   = float(np.std(d3)  * 1000)
    s["error_3d_max_mm"]   = float(np.max(d3)  * 1000)

    dxz = np.sqrt((xs - media[0])**2 + (zs - media[2])**2)
    s["cep50_xz_mm"] = float(np.percentile(dxz, 50) * 1000)
    s["cep95_xz_mm"] = float(np.percentile(dxz, 95) * 1000)

    if "reproj_err" in muestras[0]:
        rp = np.array([m["reproj_err"] for m in muestras])
        s["reproj_media_px"] = float(np.mean(rp))
        s["reproj_max_px"]   = float(np.max(rp))

    if POSICION_REAL is not None:
        diff = media - POSICION_REAL
        s["sesgo_x_mm"]  = float(diff[0] * 1000)
        s["sesgo_y_mm"]  = float(diff[1] * 1000)
        s["sesgo_z_mm"]  = float(diff[2] * 1000)
        s["sesgo_3d_mm"] = float(np.linalg.norm(diff) * 1000)
    return s


# ─── VISUALIZACIÓN FINAL ──────────────────────────────────────────────────────

def _conf_ellipse(ax, x, y, n_std=2, color="steelblue", lbl=""):
    if len(x) < 3:
        return
    vals, vecs = np.linalg.eigh(np.cov(x, y))
    order = vals.argsort()[::-1]
    vals, vecs = vals[order], vecs[:, order]
    angle = np.degrees(np.arctan2(*vecs[:, 0][::-1]))
    w, h = 2 * n_std * np.sqrt(np.maximum(vals, 0))
    ax.add_patch(Ellipse(xy=(np.mean(x), np.mean(y)), width=w, height=h, angle=angle,
                          facecolor="none", edgecolor=color, lw=2, ls="--", label=lbl))


def generar_visualizacion(muestras_raw, muestras_kal, s_raw, s_kal, ts, out_dir):
    if not MATPLOTLIB_OK or not muestras_raw:
        return []

    def arr(ms, k):
        return np.array([m[k] for m in ms])

    t  = arr(muestras_raw, "t")
    xr = arr(muestras_raw, "x") * 100
    yr = arr(muestras_raw, "y") * 100
    zr = arr(muestras_raw, "z") * 100
    xk = arr(muestras_kal, "x") * 100 if muestras_kal else xr
    yk = arr(muestras_kal, "y") * 100 if muestras_kal else yr
    zk = arr(muestras_kal, "z") * 100 if muestras_kal else zr

    os.makedirs(out_dir, exist_ok=True)
    paths = []

    # ── Fig 1: series temporales ──────────────────────────────────────────
    fig, axes = plt.subplots(3, 1, figsize=(13, 7), sharex=True)
    fig.patch.set_facecolor("#0e1117")
    fig.suptitle(f"Series temporales — {ts}", color="white", fontsize=12)

    for ax, raw, kal, lbl, col in zip(
            axes,
            [xr, yr, zr], [xk, yk, zk],
            ["X", "Y", "Z"],
            ["#4c9be8", "#4ce880", "#e84c4c"]):
        ax.set_facecolor("#161b27")
        mu, sg = np.mean(raw), np.std(raw)
        ax.plot(t, raw, alpha=0.3, color=col, lw=0.7, label="Raw")
        if USAR_KALMAN:
            ax.plot(t, kal, color=col, lw=1.4, alpha=0.9, label="Kalman")
        ax.axhline(mu, color="white", lw=1.0, ls="--", alpha=0.6,
                   label=f"μ={mu:.3f}cm")
        ax.fill_between(t, mu-2*sg, mu+2*sg, alpha=0.1, color=col,
                        label=f"±2σ={2*sg*10:.2f}mm")
        ax.set_ylabel(f"{lbl} (cm)", color="white")
        ax.tick_params(colors="white")
        ax.spines[:].set_color("#2a3048")
        ax.legend(loc="upper right", fontsize=7, ncol=2,
                  facecolor="#1a2035", labelcolor="white")
        ax.grid(True, alpha=0.15, color="white")

    axes[-1].set_xlabel("Tiempo (s)", color="white")
    plt.tight_layout()
    p1 = os.path.join(out_dir, f"estatico_pc_{ts}_series.png")
    fig.savefig(p1, dpi=150, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    paths.append(p1)

    # ── Fig 2: scatter 2D ──────────────────────────────────────────────────
    fig2, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 5))
    fig2.patch.set_facecolor("#0e1117")
    fig2.suptitle(f"Dispersión espacial — {ts}", color="white", fontsize=12)

    for ax, a, b_, ak, bk, xl, yl, title in [
        (ax1, xr, zr, xk, zk, "X (cm)", "Z (cm)", "Vista lateral  X – Z"),
        (ax2, xr, yr, xk, yk, "X (cm)", "Y (cm)", "Vista frontal  X – Y"),
    ]:
        ax.set_facecolor("#161b27")
        ax.scatter(a, b_, s=4, alpha=0.2, color="#4c9be8", label="Raw")
        if USAR_KALMAN:
            ax.scatter(ak, bk, s=4, alpha=0.3, color="#e84c8a", label="Kalman")
        _conf_ellipse(ax, a, b_, 2, "#4c9be8", "2σ raw")
        if USAR_KALMAN:
            _conf_ellipse(ax, ak, bk, 2, "#e84c8a", "2σ Kalman")
        ax.scatter([np.mean(a)], [np.mean(b_)], s=120, color="gold",
                   marker="*", zorder=5, label="Media")
        ax.set_xlabel(xl, color="white"); ax.set_ylabel(yl, color="white")
        ax.set_title(title, color="white")
        ax.tick_params(colors="white"); ax.spines[:].set_color("#2a3048")
        ax.legend(fontsize=7, facecolor="#1a2035", labelcolor="white")
        ax.grid(True, alpha=0.15, color="white")
        ax.set_aspect("equal", adjustable="datalim")

    plt.tight_layout()
    p2 = os.path.join(out_dir, f"estatico_pc_{ts}_scatter.png")
    fig2.savefig(p2, dpi=150, bbox_inches="tight", facecolor=fig2.get_facecolor())
    plt.close(fig2)
    paths.append(p2)

    # ── Fig 3: mapa 3D ────────────────────────────────────────────────────
    fig3 = plt.figure(figsize=(14, 7))
    fig3.patch.set_facecolor("#0e1117")

    ax3d = fig3.add_subplot(121, projection="3d")
    ax3d.set_facecolor("#161b27")

    # Panel de fondo (rect gris donde están los marcadores)
    xs_m = [v[0] for v in MARKERS.values()]
    ys_m = [v[1] for v in MARKERS.values()]
    margin = MARKER_SIZE
    px0, px1 = min(xs_m)-margin, max(xs_m)+margin
    py0, py1 = min(ys_m)-margin, max(ys_m)+margin
    panel_verts = [[(px0,py0,0),(px1,py0,0),(px1,py1,0),(px0,py1,0)]]
    ax3d.add_collection3d(Poly3DCollection(panel_verts, alpha=0.08,
                                            facecolor="#aaaaaa", edgecolor="#555555"))

    # Marcadores como cuadrados naranjas
    for mid, mpos in MARKERS.items():
        h2 = MARKER_SIZE / 2
        verts = [[(mpos[0]-h2, mpos[1]-h2, 0), (mpos[0]+h2, mpos[1]-h2, 0),
                  (mpos[0]+h2, mpos[1]+h2, 0), (mpos[0]-h2, mpos[1]+h2, 0)]]
        ax3d.add_collection3d(Poly3DCollection(verts, alpha=0.85,
                                                facecolor="#f5a623", edgecolor="#333"))
        ax3d.text(mpos[0], mpos[1], 0.005, f"{mid}", fontsize=5,
                  ha="center", color="white")

    # Nube de posiciones raw
    xs_r = arr(muestras_raw, "x")
    ys_r = arr(muestras_raw, "y")
    zs_r = arr(muestras_raw, "z")
    ax3d.scatter(xs_r, ys_r, zs_r, s=2, alpha=0.15, color="#4c9be8", label="Raw")

    # Nube Kalman
    if muestras_kal and USAR_KALMAN:
        ax3d.scatter(arr(muestras_kal,"x"), arr(muestras_kal,"y"), arr(muestras_kal,"z"),
                     s=2, alpha=0.2, color="#e84c8a", label="Kalman")

    # Media y líneas a marcadores visibles
    mx, my, mz = s_raw["x_media"], s_raw["y_media"], s_raw["z_media"]
    ax3d.scatter([mx], [my], [mz], s=180, color="gold", marker="*",
                 zorder=10, label=f"Media ({mx*100:.1f},{my*100:.1f},{mz*100:.1f})cm")

    # Línea vertical desde marcador panel al punto cámara
    for mpos in MARKERS.values():
        ax3d.plot([mpos[0], mx], [mpos[1], my], [0, mz],
                  color="#ffffff", alpha=0.08, lw=0.6, ls="--")

    # Anotación de distancia
    closest = min(MARKERS.values(), key=lambda p: np.linalg.norm(p - np.array([mx,my,mz])))
    dist_m  = float(np.linalg.norm(closest - np.array([mx, my, mz])))
    ax3d.text(mx, my, mz + 0.02, f"d≈{dist_m*100:.1f}cm", color="gold", fontsize=8)

    ax3d.set_xlabel("X (m)", color="white"); ax3d.set_ylabel("Y (m)", color="white")
    ax3d.set_zlabel("Z (m)", color="white")
    ax3d.set_title("Mapa 3D", color="white")
    ax3d.tick_params(colors="white")
    ax3d.xaxis.pane.fill = False; ax3d.yaxis.pane.fill = False; ax3d.zaxis.pane.fill = False
    ax3d.xaxis.pane.set_edgecolor("#2a3048")
    ax3d.yaxis.pane.set_edgecolor("#2a3048")
    ax3d.zaxis.pane.set_edgecolor("#2a3048")
    ax3d.legend(fontsize=7, facecolor="#1a2035", labelcolor="white",
                loc="upper left")
    ax3d.view_init(elev=18, azim=-55)

    # Tabla de stats
    ax_t = fig3.add_subplot(122)
    ax_t.set_facecolor("#0e1117")
    ax_t.axis("off")

    rows = [
        ["Métrica", "RAW", "KALMAN" if s_kal else "—"],
        ["SEP50 (3D P50)", f"{s_raw['sep50_mm']:.2f}mm",
         f"{s_kal['sep50_mm']:.2f}mm" if s_kal else "—"],
        ["SEP95 (3D P95)", f"{s_raw['sep95_mm']:.2f}mm",
         f"{s_kal['sep95_mm']:.2f}mm" if s_kal else "—"],
        ["CEP50 (X-Z)", f"{s_raw['cep50_xz_mm']:.2f}mm",
         f"{s_kal['cep50_xz_mm']:.2f}mm" if s_kal else "—"],
        ["CEP95 (X-Z)", f"{s_raw['cep95_xz_mm']:.2f}mm",
         f"{s_kal['cep95_xz_mm']:.2f}mm" if s_kal else "—"],
        ["Error 3D medio", f"{s_raw['error_3d_medio_mm']:.2f}mm",
         f"{s_kal['error_3d_medio_mm']:.2f}mm" if s_kal else "—"],
        ["Error 3D máx",   f"{s_raw['error_3d_max_mm']:.2f}mm",
         f"{s_kal['error_3d_max_mm']:.2f}mm" if s_kal else "—"],
        ["", "", ""],
        ["Posición X", f"{s_raw['x_media']*100:.3f}cm", ""],
        ["Posición Y", f"{s_raw['y_media']*100:.3f}cm", ""],
        ["Posición Z", f"{s_raw['z_media']*100:.3f}cm", ""],
        ["", "", ""],
        ["Frecuencia", f"{s_raw['frecuencia_hz']:.1f} Hz", ""],
        ["Muestras",   f"{s_raw['n_muestras']}", ""],
    ]
    if "reproj_media_px" in s_raw:
        rows.append(["Reproyección", f"{s_raw['reproj_media_px']:.3f}px", ""])

    tbl = ax_t.table(cellText=rows[1:], colLabels=rows[0],
                     cellLoc="center", loc="center",
                     colWidths=[0.42, 0.29, 0.29])
    tbl.auto_set_font_size(False)
    tbl.set_fontsize(9)

    header_color = "#1e2a45"
    cell_color   = "#141a28"
    alt_color    = "#1a2235"

    for (r, c), cell in tbl.get_celld().items():
        cell.set_edgecolor("#2a3048")
        if r == 0:
            cell.set_facecolor(header_color)
            cell.set_text_props(color="white", fontweight="bold")
        else:
            cell.set_facecolor(cell_color if r % 2 == 0 else alt_color)
            cell.set_text_props(color="#c8d0dc")

    ax_t.set_title("Resultados", color="white", fontsize=11, pad=10)

    plt.tight_layout()
    p3 = os.path.join(out_dir, f"estatico_pc_{ts}_mapa3d.png")
    fig3.savefig(p3, dpi=150, bbox_inches="tight", facecolor=fig3.get_facecolor())
    plt.close(fig3)
    paths.append(p3)

    return paths


# ─── PANTALLA DE RESULTADOS ───────────────────────────────────────────────────

def mostrar_resultados_cv2(s_raw, s_kal, plots):
    """Muestra las gráficas generadas en ventanas cv2. Tecla cualquiera para avanzar."""
    if not plots:
        return

    titulos = ["Series temporales  (cualquier tecla → siguiente)",
               "Scatter 2D  (cualquier tecla → siguiente)",
               "Mapa 3D + Resultados  (cualquier tecla → cerrar)"]

    for path, titulo in zip(plots, titulos):
        img = cv2.imread(path)
        if img is None:
            continue
        # Escalar para que quepa en pantalla
        h, w = img.shape[:2]
        max_w, max_h = 1400, 800
        scale = min(max_w / w, max_h / h, 1.0)
        if scale < 1.0:
            img = cv2.resize(img, (int(w*scale), int(h*scale)))
        cv2.namedWindow(titulo, cv2.WINDOW_NORMAL)
        cv2.imshow(titulo, img)
        cv2.waitKey(0)
        cv2.destroyWindow(titulo)


# ─── IMPRIMIR EN TERMINAL ─────────────────────────────────────────────────────

def imprimir_resultados(s_raw, s_kal=None):
    W = 72
    sep = "═" * W

    print(f"\n{sep}")
    print(f"  RESULTADOS — ERROR ESTÁTICO (PC)")
    print(f"{sep}")
    print(f"  Muestras  : {s_raw['n_muestras']}  |  "
          f"Rechazadas: {s_raw['n_rechazadas']} ({s_raw['tasa_rechazo_pct']:.1f}%)")
    print(f"  Duración  : {s_raw['duracion_s']:.2f}s  |  "
          f"Frecuencia: {s_raw['frecuencia_hz']:.1f} Hz")
    if "reproj_media_px" in s_raw:
        print(f"  Reproyecc.: media={s_raw['reproj_media_px']:.3f}px  "
              f"max={s_raw['reproj_max_px']:.3f}px")

    print(f"\n  {'Eje':4s} {'Media':>10s} {'Mediana':>10s} {'Std':>9s} {'Rango':>9s}", end="")
    if s_kal:
        print(f"   {'KalStd':>8s}  {'KalRango':>9s}", end="")
    print()
    print(f"  {'─'*65}")

    for ax in ["x", "y", "z"]:
        mu = s_raw[f"{ax}_media"]   * 100
        md = s_raw[f"{ax}_mediana"] * 100
        st = s_raw[f"{ax}_std"]     * 1000
        rn = s_raw[f"{ax}_rango"]   * 1000
        line = f"  {ax.upper():4s} {mu:+10.3f}cm {md:+10.3f}cm {st:9.2f}mm {rn:9.2f}mm"
        if s_kal:
            line += f"   {s_kal[f'{ax}_std']*1000:8.2f}mm  {s_kal[f'{ax}_rango']*1000:9.2f}mm"
        print(line)

    print(f"\n  {'─'*65}")
    print(f"  {'Métrica':30s}  {'RAW':>10s}", end="")
    if s_kal:
        print(f"  {'KALMAN':>10s}", end="")
    print()
    print(f"  {'─'*55}")

    for nombre, key in [
        ("SEP50  — P50 esférico 3D",  "sep50_mm"),
        ("SEP95  — P95 esférico 3D",  "sep95_mm"),
        ("CEP50  — P50 plano X-Z",    "cep50_xz_mm"),
        ("CEP95  — P95 plano X-Z",    "cep95_xz_mm"),
        ("Error 3D medio",            "error_3d_medio_mm"),
        ("Error 3D std",              "error_3d_std_mm"),
        ("Error 3D máximo",           "error_3d_max_mm"),
    ]:
        line = f"  {nombre:30s}  {s_raw[key]:>8.2f} mm"
        if s_kal and key in s_kal:
            line += f"  {s_kal[key]:>8.2f} mm"
        print(line)

    if "sesgo_3d_mm" in s_raw:
        print(f"\n  Sesgo vs posición real: "
              f"ΔX={s_raw['sesgo_x_mm']:+.2f}  "
              f"ΔY={s_raw['sesgo_y_mm']:+.2f}  "
              f"ΔZ={s_raw['sesgo_z_mm']:+.2f}  "
              f"|3D|={s_raw['sesgo_3d_mm']:.2f} mm")

    print(f"\n{sep}\n")


# ─── GUARDAR ──────────────────────────────────────────────────────────────────

def guardar(muestras_raw, muestras_kal, s_raw, s_kal, plots, ts):
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    campos = ["t", "x", "y", "z", "n_markers", "reproj_err"]
    if muestras_kal:
        campos += ["x_kal", "y_kal", "z_kal"]
        for r, k in zip(muestras_raw, muestras_kal):
            r["x_kal"] = k["x"]; r["y_kal"] = k["y"]; r["z_kal"] = k["z"]

    csv_p = os.path.join(OUTPUT_DIR, f"estatico_pc_{ts}.csv")
    with open(csv_p, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=campos, extrasaction="ignore")
        w.writeheader(); w.writerows(muestras_raw)

    jso_p = os.path.join(OUTPUT_DIR, f"estatico_pc_{ts}_stats.json")
    with open(jso_p, "w", encoding="utf-8") as f:
        json.dump({"raw": s_raw, "kalman": s_kal or {}}, f, indent=2, ensure_ascii=False)

    print(f"  CSV   : {csv_p}")
    print(f"  Stats : {jso_p}")
    for p in plots:
        print(f"  Plot  : {p}")


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    cap = cv2.VideoCapture(VIDEO_SOURCE)
    if not cap.isOpened():
        print(f"\n  ERROR: No se puede abrir la cámara (source={VIDEO_SOURCE}).")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  RESOLUCION[0])
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCION[1])
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"\n  Cámara {w}×{h} | marker={MARKER_SIZE*100:.0f}cm | "
          f"Kalman={'ON' if USAR_KALMAN else 'OFF'} | "
          f"Plots={'ON' if MATPLOTLIB_OK else 'OFF'}")

    try:
        muestras_raw, muestras_kal, n_rej, det_r = grabar_posiciones(cap, DURACION_S)
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if not muestras_raw:
        print("\n  Sin muestras — no se detectaron marcadores.")
        return

    s_raw = analizar(muestras_raw, n_rej,  label="raw")
    s_kal = analizar(muestras_kal, label="kalman") if USAR_KALMAN and muestras_kal else None

    imprimir_resultados(s_raw, s_kal)

    ts    = datetime.now().strftime("%Y%m%d_%H%M%S")
    plots = generar_visualizacion(muestras_raw, muestras_kal, s_raw, s_kal, ts, OUTPUT_DIR)
    guardar(muestras_raw, muestras_kal, s_raw, s_kal, plots, ts)

    print("\n  Mostrando gráficas — pulsa cualquier tecla para avanzar...\n")
    mostrar_resultados_cv2(s_raw, s_kal, plots)
    print("  Listo.\n")


if __name__ == "__main__":
    main()
