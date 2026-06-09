"""
stream_dron.py
==============
Corre en la Raspberry Pi con Camera Module 3 NoIR.

  1. Captura frames con picamera2 (foco fijo, AF desactivado)
  2. Detecta marcadores ArUco y estima la posición 3D
  3. Envía frames JPEG + datos de posición al PC por TCP/WiFi

Uso en la Pi:
  python stream_dron.py

El script imprime la IP. En el PC ejecuta:
  python monitor_dron.py --ip <IP_DE_LA_PI>

Dependencias:
  sudo apt install -y python3-picamera2 python3-opencv python3-numpy
"""

import cv2
import numpy as np
import json, time, socket, struct
from pathlib import Path

try:
    from picamera2 import Picamera2
    USAR_PICAMERA2 = True
except ImportError:
    USAR_PICAMERA2 = False

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

PORT          = 5000
RESOLUCION    = (1280, 720)
LENS_POSITION = 4.0       # foco fijo Camera Module 3 NoIR (0=inf, 10=cerca)
FPS_MAX       = 30        # límite de envío al PC
JPEG_QUALITY  = 60        # calidad de compresión JPEG

BASE_DIR    = Path(__file__).resolve().parent
CONFIG_PATH = BASE_DIR / "config" / "markers_3d.json"
CALIB_PATH  = BASE_DIR / "config" / "camera_calibration.json"

MAX_REPROJECTION_PX = 3.0
MARKER_MIN_PX       = 40

# ─── CALIBRACIÓN DE CÁMARA ────────────────────────────────────────────────────

def _cargar_calibracion():
    if CALIB_PATH.exists():
        d  = json.loads(CALIB_PATH.read_text())
        cm = np.array(d["camera_matrix"], dtype=np.float64)
        dc = np.array(d["dist_coeffs"],   dtype=np.float64).reshape(-1, 1)
        print(f"  Calibración: {CALIB_PATH.name}  "
              f"(error={d.get('reprojection_error_px','?')} px)")
        return cm, dc
    print("  [AVISO] Sin calibración — usando valores por defecto.")
    cm = np.array([[974.90, 0, 640.0], [0, 974.61, 360.0], [0, 0, 1]], dtype=np.float64)
    dc = np.array([[-0.217752],[2.492355],[-0.003245],[-0.004504],[-7.845957]], dtype=np.float64)
    return cm, dc

CAMERA_MATRIX, DIST_COEFFS = _cargar_calibracion()

# ─── MAPA DE MARCADORES ───────────────────────────────────────────────────────

def _cargar_mapa():
    d  = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    sz = float(d.get("marker_size", 0.10))
    mk = {int(k): np.array([v["x"], v["y"], v["z"]], dtype=np.float64)
          for k, v in d["markers"].items()}
    return mk, sz

MARKERS, MARKER_SIZE = _cargar_mapa()
VALID_IDS = set(MARKERS.keys())

_h = MARKER_SIZE / 2
MARKER_OBJ_PTS = np.array(
    [[-_h, _h, 0], [_h, _h, 0], [_h, -_h, 0], [-_h, -_h, 0]], dtype=np.float32)

_dict   = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_4X4_1000)
_params = cv2.aruco.DetectorParameters()
_params.cornerRefinementMethod        = cv2.aruco.CORNER_REFINE_SUBPIX
_params.cornerRefinementWinSize       = 7
_params.cornerRefinementMaxIterations = 60
_detector = cv2.aruco.ArucoDetector(_dict, _params)

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

    def update(self, pos, rerr=1.0):
        m = pos.reshape(3, 1)
        if not self._init:
            self.kf.statePost = m.copy()
            self._init = True
            return pos.copy()
        self.kf.measurementNoiseCov = np.eye(3) * self._base * max(rerr, 0.1) ** 2
        self.kf.predict()
        return self.kf.correct(m).flatten()

# ─── ESTIMACIÓN DE POSE ───────────────────────────────────────────────────────

def _rerr(rv, tv, img):
    p, _ = cv2.projectPoints(MARKER_OBJ_PTS, rv, tv, CAMERA_MATRIX, DIST_COEFFS)
    return float(np.sqrt(np.mean(np.sum((p.reshape(4, 2) - img) ** 2, axis=1))))


def estimar_posicion(corners_det, ids_det):
    if ids_det is None or len(ids_det) == 0:
        return None, 0, float("inf")

    per_marker = []
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
                continue
            e = _rerr(rv, tv, img_pts)
            if e <= MAX_REPROJECTION_PX:
                sols.append((MARKERS[mid] + cam_local, e))
        if sols:
            per_marker.append(sols)

    if not per_marker:
        return None, 0, float("inf")

    if len(per_marker) == 1:
        best = min(per_marker[0], key=lambda x: x[1])
        return best[0], 1, best[1]

    anchor = np.median([min(s, key=lambda x: x[1])[0] for s in per_marker], axis=0)
    selected = []
    for sols in per_marker:
        best = min(sols, key=lambda s: np.linalg.norm(s[0] - anchor))
        if np.linalg.norm(best[0] - anchor) < 0.20:
            selected.append(best)

    if not selected:
        return None, 0, float("inf")

    errs = np.clip([s[1] for s in selected], 0.1, None)
    w = 1.0 / errs**2; w /= w.sum()
    return (np.average([s[0] for s in selected], weights=w, axis=0),
            len(selected),
            float(np.average(errs, weights=w)))

# ─── APERTURA DE CÁMARA ───────────────────────────────────────────────────────

def abrir_camara():
    if USAR_PICAMERA2:
        picam2 = Picamera2()
        cfg = picam2.create_video_configuration(
            main={"format": "BGR888", "size": RESOLUCION})
        picam2.configure(cfg)
        picam2.start()
        try:
            picam2.set_controls({"AfMode": 0, "LensPosition": LENS_POSITION})
            print(f"  AF desactivado — LensPosition={LENS_POSITION}")
        except Exception:
            print("  [AVISO] No se pudo fijar el foco.")
        time.sleep(0.5)
        print(f"  picamera2: {RESOLUCION[0]}x{RESOLUCION[1]}")
        return lambda: (True, picam2.capture_array()), picam2.stop
    else:
        cap = cv2.VideoCapture(0)
        cap.set(cv2.CAP_PROP_FRAME_WIDTH,  RESOLUCION[0])
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, RESOLUCION[1])
        print(f"  VideoCapture: {RESOLUCION[0]}x{RESOLUCION[1]}")
        return cap.read, cap.release

# ─── STREAMING ────────────────────────────────────────────────────────────────

def _enviar(conn, data_dict, frame):
    _, buf    = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
    img_bytes = buf.tobytes()
    js_bytes  = json.dumps(data_dict).encode('utf-8')
    conn.sendall(struct.pack('>II', len(js_bytes), len(img_bytes)) + js_bytes + img_bytes)


def _get_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return socket.gethostbyname(socket.gethostname())


def main():
    ip = _get_ip()
    print(f"\n{'='*55}")
    print(f"  STREAM DRON — Pi")
    print(f"{'='*55}")
    print(f"  IP de esta Pi : {ip}")
    print(f"  Puerto        : {PORT}")
    print(f"  En el PC ejecuta:")
    print(f"    python monitor_dron.py --ip {ip}")
    print(f"{'='*55}\n")

    read_fn, release_fn = abrir_camara()
    kalman = KalmanPos3D()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('0.0.0.0', PORT))
    srv.listen(1)
    print(f"  Esperando conexión del PC... (Ctrl+C para salir)\n")

    try:
        conn, addr = srv.accept()
        conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"  PC conectado: {addr[0]}:{addr[1]}")

        dt_min = 1.0 / FPS_MAX
        t_last = 0.0
        frames_sent = 0

        while True:
            ok, frame = read_fn()
            if not ok:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            corners, ids, _ = _detector.detectMarkers(gray)
            pos_raw, n_mk, rerr = estimar_posicion(corners, ids)

            pos_kal = kalman.update(pos_raw, rerr) if pos_raw is not None else None

            if ids is not None:
                cv2.aruco.drawDetectedMarkers(frame, corners, ids)

            now = time.monotonic()
            if now - t_last < dt_min:
                continue
            t_last = now

            data = {
                "t":         round(time.time(), 4),
                "pos":       pos_raw.tolist() if pos_raw is not None else None,
                "pos_kal":   pos_kal.tolist() if pos_kal is not None else None,
                "n_markers": n_mk,
                "reproj":    round(rerr, 4) if rerr < 99 else None,
            }

            try:
                _enviar(conn, data, frame)
                frames_sent += 1
                if frames_sent % 100 == 0:
                    pos_str = (f"  X={pos_raw[0]*100:.1f} Y={pos_raw[1]*100:.1f} "
                               f"Z={pos_raw[2]*100:.1f} cm") if pos_raw is not None else "  sin detección"
                    print(f"  Frame {frames_sent:5d} |{pos_str}")
            except (BrokenPipeError, ConnectionResetError):
                print("  PC desconectado.")
                break

    except KeyboardInterrupt:
        print("\n  Interrumpido por el usuario.")
    finally:
        try:
            conn.close()
        except Exception:
            pass
        release_fn()
        srv.close()
        print("  Servidor cerrado.")


if __name__ == "__main__":
    main()
