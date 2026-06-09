"""
monitor_dron.py
===============
Corre en el PC. Se conecta a la Raspberry Pi por WiFi y muestra:
  - Feed de cámara en directo con marcadores ArUco detectados
  - Dashboard con posición X/Y/Z, métricas de calidad y series temporales
  - Opcionalmente guarda los datos en CSV

Uso:
  python monitor_dron.py --ip <IP_DE_LA_PI>

Teclas durante la sesión:
  r  →  iniciar / parar grabación en CSV
  q  →  salir

Dependencias:
  pip install opencv-contrib-python numpy
"""

import cv2
import numpy as np
import socket, struct, json, csv, os, time, threading, queue, argparse
from collections import deque
from datetime import datetime
from pathlib import Path

# ─── CONFIGURACIÓN ────────────────────────────────────────────────────────────

PORT        = 5000
CAM_W       = 800
CAM_H       = 450
DASH_W      = 480
COMP_W      = CAM_W + DASH_W
OUTPUT_DIR  = "mediciones"
TIMEOUT_S   = 5.0      # segundos sin recibir datos → aviso de desconexión

# ─── RECEPCIÓN TCP ────────────────────────────────────────────────────────────

def _recv_exactly(sock, n):
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionResetError("Conexión cerrada por la Pi")
        buf += chunk
    return buf


def receptor(ip, data_queue, stop_event):
    """Hilo receptor: lee frames de la Pi y los mete en la cola."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(TIMEOUT_S)
    print(f"  Conectando a {ip}:{PORT}...")
    try:
        sock.connect((ip, PORT))
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        print(f"  Conectado a la Pi.")
    except Exception as e:
        print(f"  [ERROR] No se pudo conectar: {e}")
        stop_event.set()
        return

    try:
        while not stop_event.is_set():
            header = _recv_exactly(sock, 8)
            js_len, img_len = struct.unpack('>II', header)
            js_bytes  = _recv_exactly(sock, js_len)
            img_bytes = _recv_exactly(sock, img_len)

            data  = json.loads(js_bytes.decode('utf-8'))
            img_arr = np.frombuffer(img_bytes, dtype=np.uint8)
            frame = cv2.imdecode(img_arr, cv2.IMREAD_COLOR)

            try:
                data_queue.put_nowait((data, frame))
            except queue.Full:
                pass   # descarta frame si la cola está llena (PC va lento)

    except (ConnectionResetError, TimeoutError, OSError) as e:
        print(f"\n  [AVISO] Conexión perdida: {e}")
        stop_event.set()
    finally:
        sock.close()

# ─── DASHBOARD ────────────────────────────────────────────────────────────────

class Dashboard:
    BG   = (18,  22,  32)
    SEP  = (45,  55,  75)
    TXT  = (190, 200, 210)
    MUTE = (90,  100, 115)
    GOOD = (60,  200,  80)
    INFO = (200, 160,  20)
    WARN = (30,  130, 255)
    CX   = (200, 120,  60)
    CY   = ( 60, 200, 100)
    CZ   = ( 80,  80, 220)
    KAL  = (200, 140, 255)
    REC  = (  0,   0, 220)

    def __init__(self):
        self.hx   = deque(maxlen=400)
        self.hy   = deque(maxlen=400)
        self.hz   = deque(maxlen=400)
        self.fps_hist = deque(maxlen=30)

    def push(self, pos):
        if pos is not None:
            self.hx.append(pos[0] * 100)
            self.hy.append(pos[1] * 100)
            self.hz.append(pos[2] * 100)

    @staticmethod
    def _txt(p, txt, x, y, color, scale=0.42, thick=1):
        cv2.putText(p, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

    @staticmethod
    def _big(p, txt, x, y, color, scale=0.65, thick=2):
        cv2.putText(p, txt, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, color, thick, cv2.LINE_AA)

    @staticmethod
    def _hline(p, y, c):
        cv2.line(p, (0, y), (DASH_W, y), c, 1)

    @staticmethod
    def _series(p, data, x0, y0, x1, y1, color):
        cv2.rectangle(p, (x0, y0), (x1, y1), (22, 27, 42), -1)
        if not data or len(data) < 2:
            return
        arr = np.array(data, dtype=np.float32)
        mn, mx = arr.min(), arr.max()
        rng = mx - mn if mx - mn > 1e-4 else 1e-4
        w, h = x1 - x0, y1 - y0
        mu = float(arr.mean())
        my_px = int(y1 - (mu - mn) / rng * h)
        cv2.line(p, (x0, my_px), (x1, my_px), (55, 62, 80), 1)
        n = len(arr)
        pts = np.array([[x0 + int(i*(w-1)/max(n-1,1)),
                         int(y1 - (v - mn)/rng * (h-1))]
                        for i, v in enumerate(arr)], dtype=np.int32).reshape(-1, 1, 2)
        pts[:, 0, 1] = np.clip(pts[:, 0, 1], y0, y1)
        cv2.polylines(p, [pts], False, color, 1, cv2.LINE_AA)

    def render(self, pos_raw, pos_kal, n_mk, reproj, fps, grabando, n_muestras) -> np.ndarray:
        W = DASH_W
        panel = np.full((CAM_H, W, 3), self.BG, dtype=np.uint8)
        t = self._txt
        b = self._big
        hl = self._hline

        # ── Header ───────────────────────────────────────────────────────────
        cv2.rectangle(panel, (0, 0), (W, 40), (28, 33, 48), -1)
        if grabando:
            b(panel, f"● REC  {n_muestras} muestras", 10, 27, self.REC)
        else:
            b(panel, "MONITOR EN VIVO  (r=grabar  q=salir)", 10, 27, self.GOOD, 0.45)
        hl(panel, 40, self.SEP)

        # ── Posición ──────────────────────────────────────────────────────────
        y = 56
        t(panel, "POSICION  (metros → cm)", 10, y, self.MUTE, 0.37)
        y += 18
        axes = [("X", pos_raw[0]*100 if pos_raw is not None else None, self.CX),
                ("Y", pos_raw[1]*100 if pos_raw is not None else None, self.CY),
                ("Z", pos_raw[2]*100 if pos_raw is not None else None, self.CZ)]
        for lbl, val, col in axes:
            vt = f"{val:+.2f} cm" if val is not None else "  ---"
            t(panel, lbl, 12, y, col, 0.52, 2)
            b(panel, vt, 38, y, self.TXT, 0.60, 1)
            if pos_kal is not None:
                idx = ["X","Y","Z"].index(lbl)
                t(panel, f"kal {pos_kal[idx]*100:+.2f}", 265, y, self.KAL, 0.37)
            y += 27
        hl(panel, y + 3, self.SEP)

        # ── Métricas ─────────────────────────────────────────────────────────
        y += 12
        re_col = self.GOOD if (reproj is not None and reproj < 1.5) else self.WARN
        re_txt = f"{reproj:.3f} px" if reproj is not None else "---"
        t(panel, f"Reproyeccion : {re_txt}", 10, y, re_col, 0.41); y += 18
        t(panel, f"Markers vis. : {n_mk}", 10, y, self.TXT, 0.41); y += 18
        fps_col = self.GOOD if fps >= 20 else (self.INFO if fps >= 10 else self.WARN)
        t(panel, f"FPS recibidos: {fps:.1f}", 10, y, fps_col, 0.41); y += 16
        hl(panel, y + 2, self.SEP)

        # ── Series temporales ────────────────────────────────────────────────
        y += 8
        rem_h = CAM_H - y - 5
        g_h   = max((rem_h - 20) // 3, 38)
        for i, (lbl, buf, col) in enumerate([
            ("X (cm)", list(self.hx), self.CX),
            ("Y (cm)", list(self.hy), self.CY),
            ("Z (cm)", list(self.hz), self.CZ),
        ]):
            gy = y + i * (g_h + 7)
            t(panel, lbl, 5, gy + 10, col, 0.34)
            self._series(panel, buf, 0, gy + 13, W - 2, gy + 13 + g_h - 13, col)

        return panel

# ─── OVERLAY EN EL FRAME DE CÁMARA ───────────────────────────────────────────

def dibujar_overlay(frame, pos_raw, n_mk, reproj):
    """Superpone posición y métricas encima del frame de cámara."""
    if pos_raw is not None:
        txt = (f"X={pos_raw[0]*100:+.1f}  Y={pos_raw[1]*100:+.1f}  "
               f"Z={pos_raw[2]*100:+.1f} cm")
        cv2.putText(frame, txt, (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 80), 2, cv2.LINE_AA)
    else:
        cv2.putText(frame, "Sin deteccion ArUco", (10, 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 80, 255), 2, cv2.LINE_AA)
    if reproj is not None:
        cv2.putText(frame, f"reproj={reproj:.2f}px  mk={n_mk}", (10, 58),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (180, 180, 180), 1, cv2.LINE_AA)

# ─── GUARDAR CSV ──────────────────────────────────────────────────────────────

def abrir_csv(ts):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    path = os.path.join(OUTPUT_DIR, f"dron_{ts}.csv")
    f    = open(path, "w", newline="")
    w    = csv.DictWriter(f, fieldnames=["t","x","y","z","x_kal","y_kal","z_kal",
                                          "n_markers","reproj"])
    w.writeheader()
    print(f"  Grabando en: {path}")
    return f, w, path

# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Monitor de posición ArUco del dron")
    parser.add_argument("--ip", required=True, help="IP de la Raspberry Pi")
    args = parser.parse_args()

    data_queue = queue.Queue(maxsize=5)
    stop_event = threading.Event()

    hilo = threading.Thread(target=receptor,
                            args=(args.ip, data_queue, stop_event), daemon=True)
    hilo.start()

    dash     = Dashboard()
    grabando = False
    csv_file = csv_writer = csv_path = None
    n_muestras = 0

    win = "Monitor Dron — ArUco"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(win, COMP_W, CAM_H)

    pos_raw = pos_kal = None
    n_mk    = 0
    reproj  = None
    fps     = 0.0
    t_last  = time.monotonic()

    # Frame vacío mientras no llega la primera imagen
    blank = np.zeros((CAM_H, CAM_W, 3), dtype=np.uint8)
    cv2.putText(blank, "Conectando a la Pi...", (20, CAM_H//2),
                cv2.FONT_HERSHEY_SIMPLEX, 1.0, (100, 100, 100), 2)

    print("\n  Teclas:  r = grabar/parar   q = salir\n")

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    while not stop_event.is_set():
        # ── Recibir dato más reciente ─────────────────────────────────────
        frame_disp = blank.copy()
        try:
            data, frame_raw = data_queue.get(timeout=0.1)

            pos_raw = np.array(data["pos"])    if data["pos"]    else None
            pos_kal = np.array(data["pos_kal"]) if data["pos_kal"] else None
            n_mk    = data.get("n_markers", 0)
            reproj  = data.get("reproj")

            now = time.monotonic()
            dt  = now - t_last
            t_last = now
            fps = 0.7 * fps + 0.3 * (1.0 / max(dt, 0.01))

            dash.push(pos_raw)

            dibujar_overlay(frame_raw, pos_raw, n_mk, reproj)
            frame_disp = cv2.resize(frame_raw, (CAM_W, CAM_H))

            # Guardar en CSV si grabando
            if grabando and csv_writer is not None:
                row = {
                    "t":         data.get("t", ""),
                    "x":         pos_raw[0]  if pos_raw is not None else "",
                    "y":         pos_raw[1]  if pos_raw is not None else "",
                    "z":         pos_raw[2]  if pos_raw is not None else "",
                    "x_kal":     pos_kal[0]  if pos_kal is not None else "",
                    "y_kal":     pos_kal[1]  if pos_kal is not None else "",
                    "z_kal":     pos_kal[2]  if pos_kal is not None else "",
                    "n_markers": n_mk,
                    "reproj":    reproj if reproj is not None else "",
                }
                csv_writer.writerow(row)
                n_muestras += 1

        except queue.Empty:
            pass

        # ── Renderizar ventana compuesta ──────────────────────────────────
        panel     = dash.render(pos_raw, pos_kal, n_mk, reproj, fps, grabando, n_muestras)
        composite = np.hstack([frame_disp, panel])
        cv2.imshow(win, composite)

        # ── Teclas ───────────────────────────────────────────────────────
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("r"):
            if not grabando:
                csv_file, csv_writer, csv_path = abrir_csv(ts)
                grabando   = True
                n_muestras = 0
                print("  ● Grabación iniciada")
            else:
                grabando = False
                if csv_file:
                    csv_file.close()
                    csv_file = None
                print(f"  ■ Grabación parada — {n_muestras} muestras → {csv_path}")

    # ── Limpieza ─────────────────────────────────────────────────────────────
    stop_event.set()
    if csv_file:
        csv_file.close()
        print(f"  CSV guardado: {csv_path}  ({n_muestras} muestras)")
    cv2.destroyAllWindows()
    print("  Monitor cerrado.")


if __name__ == "__main__":
    main()
