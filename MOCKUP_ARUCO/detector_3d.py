"""
detector_3d.py
==============
Detector ArUco con mapa 3D en tiempo real.

  - 16 marcadores en un PANEL PLANO (plano XY, Z = 0).
  - Convención de IDs:  centenas = X,  decenas = Y
      ID   0 → X=0, Y=0   |   ID 110 → X=1, Y=1   |   ID 330 → X=3, Y=3
  - El eje Z del sistema mundo = distancia de la CÁMARA al panel.
  - Se triangula la posición usando TODOS los marcadores visibles a la vez
    (media ponderada de las estimaciones individuales).

Ventanas:
  - OpenCV (pantalla completa): feed de cámara + ejes PnP + overlay XYZ.
  - Matplotlib (ventana 3D rotable): panel de marcadores + posición cámara.

Teclas (ventana OpenCV activa):
  q  →  salir

Dependencias:
  pip install opencv-contrib-python matplotlib
"""

import cv2
import numpy as np
import json
import threading
import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D   # noqa: F401
import matplotlib.patches as mpatches

# ──────────────────────────────────────────────────────────────────────────────
# 1.  CONFIGURACIÓN
# ──────────────────────────────────────────────────────────────────────────────

FUENTE_VIDEO = 0
DICT_ARUCO   = cv2.aruco.DICT_4X4_1000
CONFIG_PATH  = "config/markers_3d.json"

# Intrínsecos de cámara (webcam HD estándar — sustituye si tienes calibración)
CAMERA_MATRIX = np.array([
    [921.17,   0.00, 459.90],
    [  0.00, 919.02, 351.24],
    [  0.00,   0.00,   1.00],
], dtype=np.float64)
DIST_COEFFS = np.zeros((5, 1), dtype=np.float64)

ALPHA       = 0.30   # suavizado EMA (0 = muy suave, 1 = sin filtro)
PLOT_EVERY  = 2      # frames entre actualizaciones del mapa 3D

# ──────────────────────────────────────────────────────────────────────────────
# 2.  CARGAR CONFIGURACIÓN DESDE JSON
# ──────────────────────────────────────────────────────────────────────────────

def cargar_config(path):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    marker_size = float(data.get("marker_size", 0.12))
    espacio     = data.get("space_name", "Panel ArUco")
    spacing_m   = float(data.get("spacing_m", 0.50))
    marcadores  = {}
    for id_str, info in data["markers"].items():
        mid = int(id_str)
        marcadores[mid] = {
            "pos":   np.array([info["x"], info["y"], info["z"]], dtype=np.float64),
            "label": info.get("label", f"ID{mid}"),
        }
    return marcadores, marker_size, espacio, spacing_m


marcadores, MARKER_SIZE, NOMBRE_ESPACIO, SPACING = cargar_config(CONFIG_PATH)
IDS_VALIDOS = set(marcadores.keys())

print(f"\n{'─'*52}")
print(f"  {NOMBRE_ESPACIO}   –   {len(marcadores)} marcadores")
print(f"  MARKER_SIZE={MARKER_SIZE*100:.0f} cm   SPACING={SPACING*100:.0f} cm")
print(f"{'─'*52}")
for mid, m in sorted(marcadores.items()):
    print(f"  ID {mid:3d}  {m['label']:<8s}  pos={m['pos']}")
print(f"{'─'*52}\n")

# Puntos 3D del marcador en su sistema local (cuadrado centrado)
_h = MARKER_SIZE / 2
MARKER_OBJ_PTS = np.array([
    [-_h,  _h, 0],
    [ _h,  _h, 0],
    [ _h, -_h, 0],
    [-_h, -_h, 0],
], dtype=np.float32)

# ──────────────────────────────────────────────────────────────────────────────
# 3.  DETECTOR ARUCO
# ──────────────────────────────────────────────────────────────────────────────

diccionario = cv2.aruco.getPredefinedDictionary(DICT_ARUCO)
parametros  = cv2.aruco.DetectorParameters()
detector    = cv2.aruco.ArucoDetector(diccionario, parametros)

# ──────────────────────────────────────────────────────────────────────────────
# 4.  ESTIMACIÓN DE POSE + TRIANGULACIÓN MULTI-MARCADOR
# ──────────────────────────────────────────────────────────────────────────────

def pose_desde_marcador(corners, mid):
    """
    solvePnP con un solo marcador.
    Devuelve (cam_en_mundo, rvec, tvec, distancia) o (None, None, None, None).
    cam_en_mundo = posición de la cámara en coordenadas del sistema mundo.
    """
    img_pts = corners.reshape(4, 2).astype(np.float32)
    ok, rvec, tvec = cv2.solvePnP(
        MARKER_OBJ_PTS, img_pts, CAMERA_MATRIX, DIST_COEFFS,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not ok:
        return None, None, None, None

    R, _ = cv2.Rodrigues(rvec)
    # Posición de la cámara en el sistema LOCAL del marcador
    cam_local = (-R.T @ tvec).flatten()

    # Los marcadores están en el plano Z=0, todos con normal +Z
    # → el sistema local del marcador coincide con el mundo (misma orientación)
    # → traducir sumando la posición del marcador en el mundo
    cam_mundo = marcadores[mid]["pos"] + cam_local
    dist      = float(np.linalg.norm(tvec))

    return cam_mundo, rvec, tvec, dist


def triangular_posicion(corners_list, ids_list):
    """
    Estima la posición de la cámara combinando TODOS los marcadores válidos.
    Devuelve (posicion_media: ndarray|None, lista_detalles, dict_dists).
    """
    detalles = []
    dists    = {}

    for corners, mid in zip(corners_list, ids_list):
        if mid not in IDS_VALIDOS:
            continue
        cam_m, rvec, tvec, dist = pose_desde_marcador(corners, mid)
        if cam_m is None:
            continue
        detalles.append((mid, cam_m, rvec, tvec, dist))
        dists[mid] = dist

    if not detalles:
        return None, detalles, dists

    # Media aritmética de todas las estimaciones individuales
    posicion = np.mean([d[1] for d in detalles], axis=0)
    return posicion, detalles, dists

# ──────────────────────────────────────────────────────────────────────────────
# 5.  ESTADO COMPARTIDO (hilo OpenCV ↔ hilo matplotlib)
# ──────────────────────────────────────────────────────────────────────────────

_lock   = threading.Lock()
_estado = {
    "cam_pos":    None,
    "ids_vistos": [],
    "dists":      {},
}
_running = True

# ──────────────────────────────────────────────────────────────────────────────
# 6.  MAPA 3D MATPLOTLIB  (hilo secundario)
# ──────────────────────────────────────────────────────────────────────────────

_pos_arr = np.array([m["pos"] for m in marcadores.values()])
_mg      = SPACING * 0.4
X_LIM = (_pos_arr[:, 0].min() - _mg, _pos_arr[:, 0].max() + _mg)
Y_LIM = (_pos_arr[:, 1].min() - _mg, _pos_arr[:, 1].max() + _mg)
Z_LIM = (-0.05, 3.5)   # eje Z = distancia máxima esperada de la cámara


def _dibujar_panel(ax, ids_vistos):
    """Dibuja el panel plano con la cuadrícula de marcadores ArUco."""
    xmin, xmax = float(_pos_arr[:, 0].min()), float(_pos_arr[:, 0].max())
    ymin, ymax = float(_pos_arr[:, 1].min()), float(_pos_arr[:, 1].max())
    mg = SPACING * 0.35

    # Fondo del panel (superficie translúcida)
    Xg = np.array([[xmin - mg, xmax + mg], [xmin - mg, xmax + mg]])
    Yg = np.array([[ymin - mg, ymin - mg], [ymax + mg, ymax + mg]])
    Zg = np.zeros((2, 2))
    ax.plot_surface(Xg, Yg, Zg, alpha=0.10, color="#2244aa",
                    linewidth=0, shade=False)

    # Borde del panel
    bx = [xmin - mg, xmax + mg, xmax + mg, xmin - mg, xmin - mg]
    by = [ymin - mg, ymin - mg, ymax + mg, ymax + mg, ymin - mg]
    bz = [0] * 5
    ax.plot(bx, by, bz, color="#4466bb", lw=1.8, alpha=0.8)

    # Líneas de cuadrícula del panel
    for x in sorted(set(_pos_arr[:, 0])):
        ax.plot([x, x], [ymin - mg, ymax + mg], [0, 0],
                color="#1a2a55", lw=0.9, alpha=0.7)
    for y in sorted(set(_pos_arr[:, 1])):
        ax.plot([xmin - mg, xmax + mg], [y, y], [0, 0],
                color="#1a2a55", lw=0.9, alpha=0.7)

    # Marcadores individuales
    for mid, m in sorted(marcadores.items()):
        px, py, pz = float(m["pos"][0]), float(m["pos"][1]), float(m["pos"][2])
        activo = mid in ids_vistos
        color  = "#00ee66" if activo else "#1e3050"
        sz     = 130       if activo else 22
        edg    = "#aaffcc" if activo else "none"

        ax.scatter(px, py, pz, c=color, s=sz, depthshade=False,
                   edgecolors=edg, linewidths=0.8, zorder=7)

        if activo:
            ax.text(px, py, pz + 0.08, f"ID{mid}\n{m['label']}",
                    color="white", fontsize=6.5, ha="center",
                    fontweight="bold")
        else:
            ax.text(px, py, pz + 0.06, str(mid),
                    color="#334455", fontsize=6, ha="center")

    # Etiqueta del panel
    ax.text((xmin + xmax) / 2, ymin - mg - 0.08, 0.0,
            "Panel ArUco (Z=0)", color="#4466aa",
            fontsize=8, ha="center", va="top")


def _hilo_plot():
    plt.ion()
    fig = plt.figure(figsize=(14, 8), facecolor="#07071a")
    fig.canvas.manager.set_window_title(f"Mapa 3D — {NOMBRE_ESPACIO}")

    # ── Eje 3D (izquierda) ────────────────────────────────────────────────────
    ax = fig.add_axes([0.01, 0.05, 0.67, 0.91], projection="3d")
    ax.set_facecolor("#07071a")

    # ── Panel de información (derecha) ────────────────────────────────────────
    ax_info = fig.add_axes([0.70, 0.05, 0.28, 0.91])
    ax_info.set_facecolor("#0c0c22")
    ax_info.set_xlim(0, 1)
    ax_info.set_ylim(0, 1)
    ax_info.axis("off")

    ax_info.text(0.5, 0.975, "POSICIÓN CÁMARA",
                 ha="center", va="top", fontsize=12,
                 color="white", fontweight="bold",
                 transform=ax_info.transAxes)
    ax_info.axhline(0.945, color="#222255", lw=1,
                    xmin=0.04, xmax=0.96)

    _txt_xyz = ax_info.text(0.5, 0.79, "—\n—\n—",
                            ha="center", va="center",
                            fontsize=16, color="#00ccff",
                            fontweight="bold", linespacing=2.0,
                            transform=ax_info.transAxes)

    ax_info.axhline(0.60, color="#222255", lw=1,
                    xmin=0.04, xmax=0.96)
    ax_info.text(0.5, 0.598, "MARCADORES VISIBLES",
                 ha="center", va="bottom", fontsize=9,
                 color="#7788aa", transform=ax_info.transAxes)

    _txt_tabla = ax_info.text(0.05, 0.575, "(ninguno)",
                              ha="left", va="top",
                              fontsize=8.5, color="#99aacc",
                              fontfamily="monospace", linespacing=1.8,
                              transform=ax_info.transAxes)

    leyenda = [
        mpatches.Patch(color="#00ee66",  label="Marcador detectado"),
        mpatches.Patch(color="#1e3050",  label="No detectado"),
        mpatches.Patch(color="#00ccff",  label="Posición cámara"),
        mpatches.Patch(color="#2255bb",  label="Rayo cam→marcador"),
    ]
    ax_info.legend(handles=leyenda, loc="lower center",
                   facecolor="#10102a", labelcolor="white",
                   fontsize=7.5, framealpha=0.9,
                   bbox_to_anchor=(0.5, 0.01))

    while _running:
        with _lock:
            cam_pos    = _estado["cam_pos"]
            ids_vistos = list(_estado["ids_vistos"])
            dists      = dict(_estado["dists"])

        # ── Texto coordenadas ─────────────────────────────────────────────────
        if cam_pos is not None:
            X, Y, Z = cam_pos
            _txt_xyz.set_text(
                f"X = {X:+.4f} m\n"
                f"Y = {Y:+.4f} m\n"
                f"Z = {Z:+.4f} m"
            )
            _txt_xyz.set_color("#00ccff")
        else:
            _txt_xyz.set_text("Sin señal")
            _txt_xyz.set_color("#334455")

        # ── Tabla marcadores ──────────────────────────────────────────────────
        if ids_vistos:
            filas = []
            for mid in sorted(ids_vistos):
                lbl  = marcadores[mid]["label"] if mid in marcadores else f"ID{mid}"
                dist = dists.get(mid, 0.0)
                filas.append(f" ID{mid:3d}  {lbl:<8s}  {dist:.2f}m")
            _txt_tabla.set_text("\n".join(filas))
        else:
            _txt_tabla.set_text(" (ninguno)")

        # ── Eje 3D ────────────────────────────────────────────────────────────
        ax.clear()
        ax.set_facecolor("#07071a")
        ax.set_xlabel("X (m)", color="#6677aa", fontsize=8, labelpad=5)
        ax.set_ylabel("Y (m)", color="#6677aa", fontsize=8, labelpad=5)
        ax.set_zlabel("Z  distancia (m)", color="#6677aa", fontsize=8, labelpad=5)
        ax.set_xlim(*X_LIM)
        ax.set_ylim(*Y_LIM)
        ax.set_zlim(*Z_LIM)
        ax.tick_params(colors="#334455", labelsize=6)
        for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
            pane.fill = False
            pane.set_edgecolor("#12122a")
        ax.grid(True, color="#0e0e25", linewidth=0.4)

        n = len(ids_vistos)
        ax.set_title(
            f"{NOMBRE_ESPACIO}   "
            f"[{n} marcador{'es' if n != 1 else ''} visible{'s' if n != 1 else ''}]",
            color="white", fontsize=10, pad=5,
        )

        _dibujar_panel(ax, ids_vistos)

        # ── Cámara y rayos ────────────────────────────────────────────────────
        if cam_pos is not None:
            cx, cy, cz = float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])

            for mid in ids_vistos:
                if mid not in marcadores:
                    continue
                mx, my, mz = (float(v) for v in marcadores[mid]["pos"])
                ax.plot([cx, mx], [cy, my], [cz, mz],
                        color="#2255bb", lw=1.0, alpha=0.65,
                        linestyle="--", zorder=4)

            # Proyección vertical al panel
            ax.plot([cx, cx], [cy, cy], [0.0, cz],
                    color="#0099cc", lw=1.2, alpha=0.45,
                    linestyle=":")
            ax.scatter(cx, cy, 0.0, c="#001133", s=55,
                       marker="+", depthshade=False, zorder=5)

            # Icono de la cámara
            ax.scatter(cx, cy, cz,
                       c="#00ccff", s=310, marker="^",
                       depthshade=False, zorder=11,
                       edgecolors="white", linewidths=1.0)
            ax.text(cx, cy, cz + 0.13,
                    f"({cx:.2f}, {cy:.2f}, {cz:.2f}) m",
                    color="#00deff", fontsize=7, ha="center",
                    fontweight="bold")
        else:
            cx_m = (X_LIM[0] + X_LIM[1]) / 2
            cy_m = (Y_LIM[0] + Y_LIM[1]) / 2
            cz_m = (Z_LIM[0] + Z_LIM[1]) / 2
            ax.text(cx_m, cy_m, cz_m,
                    "Sin marcadores visibles",
                    color="#333355", fontsize=10, ha="center")

        fig.canvas.draw()
        plt.pause(0.04)

    plt.close("all")


# ──────────────────────────────────────────────────────────────────────────────
# 7.  BUCLE PRINCIPAL — OpenCV
# ──────────────────────────────────────────────────────────────────────────────

cap = cv2.VideoCapture(FUENTE_VIDEO)
if not cap.isOpened():
    print(f"ERROR: No se puede abrir la fuente: {FUENTE_VIDEO}")
    exit(1)

WIN_CV = "Detector ArUco 3D — cámara"
cv2.namedWindow(WIN_CV, cv2.WINDOW_NORMAL)
cv2.setWindowProperty(WIN_CV, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

hilo_plot = threading.Thread(target=_hilo_plot, daemon=True)
hilo_plot.start()

pos_suav = None
frame_n  = 0

print("Sistema iniciado — pulsa 'q' para salir.\n")

while True:
    ok, frame = cap.read()
    if not ok:
        break

    frame_n += 1
    gris = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    corners_det, ids_det, _ = detector.detectMarkers(gris)

    ids_lista   = []
    dists_frame = {}

    if ids_det is not None and len(ids_det) > 0:
        cv2.aruco.drawDetectedMarkers(frame, corners_det, ids_det)
        ids_lista = ids_det.flatten().tolist()

        cam_raw, detalles, dists_frame = triangular_posicion(
            corners_det, ids_lista
        )

        # Dibujar ejes PnP y etiquetas para cada marcador reconocido
        for mid, cam_w, rvec, tvec, dist in detalles:
            cv2.drawFrameAxes(frame, CAMERA_MATRIX, DIST_COEFFS,
                              rvec, tvec, MARKER_SIZE * 0.7)
            idx    = ids_lista.index(mid)
            cx_img = int(corners_det[idx][0][:, 0].mean())
            cy_img = int(corners_det[idx][0][:, 1].mean()) - 18
            lbl    = marcadores[mid]["label"]
            cv2.putText(frame, f"ID{mid}  {lbl}",
                        (cx_img - 36, cy_img),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.47,
                        (0, 255, 160), 1)
            cv2.putText(frame, f"d={dist:.2f}m",
                        (cx_img - 36, cy_img + 17),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.43,
                        (80, 200, 255), 1)
    else:
        cam_raw = None

    # ── EMA + overlay de posición sobre el frame ──────────────────────────────
    if cam_raw is not None:
        if pos_suav is None:
            pos_suav = cam_raw.copy()
        else:
            pos_suav = ALPHA * cam_raw + (1 - ALPHA) * pos_suav

        X, Y, Z   = pos_suav
        n_ref     = sum(1 for m in ids_lista if m in IDS_VALIDOS)

        ov = frame.copy()
        cv2.rectangle(ov, (5, 5), (365, 175), (0, 0, 0), -1)
        cv2.addWeighted(ov, 0.55, frame, 0.45, 0, frame)

        cv2.putText(frame, "POSICION CAMARA  (triangulada)",
                    (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.54,
                    (170, 170, 170), 1)
        cv2.line(frame, (8, 34), (358, 34), (40, 40, 70), 1)

        for k, (txt, col) in enumerate([
            (f" X = {X:+.4f} m",                    (120, 220, 255)),
            (f" Y = {Y:+.4f} m",                    (120, 255, 180)),
            (f" Z = {Z:+.4f} m  (dist al panel)",    (255, 200, 100)),
            (f" refs: {n_ref} marcador/es visibles",  (140, 140, 165)),
        ]):
            cv2.putText(frame, txt, (12, 57 + k * 27),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.57, col, 1)

        print(f"\r  X={X:+.4f}m  Y={Y:+.4f}m  Z={Z:+.4f}m  "
              f"refs={n_ref}  ", end="", flush=True)
    else:
        pos_suav = None
        cv2.putText(frame, "Sin marcadores visibles",
                    (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.70,
                    (60, 60, 200), 2)

    # ── Actualizar estado compartido ──────────────────────────────────────────
    with _lock:
        _estado["cam_pos"]    = (pos_suav.copy()
                                 if pos_suav is not None else None)
        _estado["ids_vistos"] = [m for m in ids_lista if m in IDS_VALIDOS]
        _estado["dists"]      = dists_frame

    # ── Escalar y mostrar frame ───────────────────────────────────────────────
    try:
        _, _, ww, wh = cv2.getWindowImageRect(WIN_CV)
        if ww > 0 and wh > 0:
            frame = cv2.resize(frame, (ww, wh),
                               interpolation=cv2.INTER_LINEAR)
    except Exception:
        pass

    cv2.imshow(WIN_CV, frame)
    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

# ── Cierre limpio ─────────────────────────────────────────────────────────────
_running = False
print("\n\nSistema detenido.")
cap.release()
cv2.destroyAllWindows()
hilo_plot.join(timeout=2)
