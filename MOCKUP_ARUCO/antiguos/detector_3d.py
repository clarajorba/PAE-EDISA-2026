"""
detector_3d.py  —  v2.0 (refactorizado)
========================================
Detector ArUco con localización 3D por filtro de Kalman.

Mejoras respecto a v1:
  ✓  Filtro de Kalman 6-estados (pos + vel) en lugar de EMA
  ✓  Triangulación ponderada (inversa de error de reproyección)
  ✓  Rechazo de outliers (distancia de Mahalanobis / umbral IQR)
  ✓  Resolución de ambigüedad IPPE (se elige la pose con menor reproyección)
  ✓  Arquitectura modular y configurable
  ✓  Logging estructurado

Ventanas:
  - OpenCV (pantalla completa): feed + ejes PnP + overlay XYZ + estado Kalman
  - Matplotlib (3D rotable): panel de marcadores + posición cámara + covarianza

Teclas:  q → salir  |  r → reset Kalman  |  c → congelar/descongelar mapa 3D

Dependencias:
  pip install opencv-contrib-python matplotlib numpy
"""

import cv2
import numpy as np
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import matplotlib
matplotlib.use("TkAgg")
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D  # noqa: F401
import matplotlib.patches as mpatches


# ═════════════════════════════════════════════════════════════════════════════
#  CONFIGURACIÓN Y TIPOS
# ═════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("aruco3d")


@dataclass
class MarkerInfo:
    """Información de un marcador físico registrado."""
    id: int
    pos: np.ndarray          # posición 3D en el sistema mundo [x, y, z]
    label: str = ""


@dataclass
class PoseEstimate:
    """Resultado de estimar la pose desde un solo marcador."""
    marker_id: int
    cam_world: np.ndarray    # posición cámara en coords mundo
    rvec: np.ndarray
    tvec: np.ndarray
    distance: float          # distancia cámara-marcador
    reprojection_err: float  # error de reproyección (px)


@dataclass
class AppConfig:
    """Configuración global de la aplicación."""
    video_source: int = 0
    aruco_dict: int = cv2.aruco.DICT_4X4_1000
    config_path: str = "config/markers_3d.json"

    # Intrínsecos (SUSTITUIR con calibración real para el dron)
    camera_matrix: np.ndarray = field(default_factory=lambda: np.array([
        [921.17,   0.00, 459.90],
        [  0.00, 919.02, 351.24],
        [  0.00,   0.00,   1.00],
    ], dtype=np.float64))
    dist_coeffs: np.ndarray = field(
        default_factory=lambda: np.zeros((5, 1), dtype=np.float64)
    )

    # Kalman
    kalman_process_noise: float = 0.05   # incertidumbre del modelo de movimiento
    kalman_measurement_noise: float = 0.02  # incertidumbre de la medición ArUco
    kalman_initial_cov: float = 1.0      # covarianza inicial

    # Outliers
    outlier_iqr_factor: float = 1.5      # factor IQR para rechazo
    max_reprojection_px: float = 8.0     # error reproyección máximo aceptable

    # Visualización
    plot_refresh_ms: int = 40            # refresco del mapa 3D (ms)
    max_z_display: float = 3.5           # altura máxima en el mapa


CFG = AppConfig()


# ═════════════════════════════════════════════════════════════════════════════
#  CARGA DE MAPA DE MARCADORES
# ═════════════════════════════════════════════════════════════════════════════

def cargar_mapa(path: str) -> tuple[dict[int, MarkerInfo], float, str, float]:
    """Lee el JSON de configuración y devuelve el mapa de marcadores."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))

    marker_size = float(data.get("marker_size", 0.12))
    space_name = data.get("space_name", "Panel ArUco")
    spacing = float(data.get("spacing_m", 0.50))

    markers: dict[int, MarkerInfo] = {}
    for id_str, info in data["markers"].items():
        mid = int(id_str)
        markers[mid] = MarkerInfo(
            id=mid,
            pos=np.array([info["x"], info["y"], info["z"]], dtype=np.float64),
            label=info.get("label", f"ID{mid}"),
        )

    return markers, marker_size, space_name, spacing


MARKERS, MARKER_SIZE, SPACE_NAME, SPACING = cargar_mapa(CFG.config_path)
VALID_IDS = set(MARKERS.keys())

# Puntos 3D del marcador en su sistema local (cuadrado centrado en origen)
_h = MARKER_SIZE / 2
MARKER_OBJ_PTS = np.array([
    [-_h,  _h, 0],
    [ _h,  _h, 0],
    [ _h, -_h, 0],
    [-_h, -_h, 0],
], dtype=np.float32)


def _imprimir_mapa():
    sep = "─" * 56
    log.info(f"\n{sep}")
    log.info(f"  {SPACE_NAME}  —  {len(MARKERS)} marcadores")
    log.info(f"  MARKER_SIZE={MARKER_SIZE*100:.0f} cm   SPACING={SPACING*100:.0f} cm")
    log.info(sep)
    for mid, m in sorted(MARKERS.items()):
        log.info(f"  ID {mid:3d}  {m.label:<8s}  pos={m.pos}")
    log.info(sep)


_imprimir_mapa()


# ═════════════════════════════════════════════════════════════════════════════
#  FILTRO DE KALMAN  (6 estados: x, y, z, vx, vy, vz)
# ═════════════════════════════════════════════════════════════════════════════

class KalmanFilter3D:
    """
    Filtro de Kalman lineal para posición 3D + velocidad.

    Estado:  [x, y, z, vx, vy, vz]^T
    Medida:  [x, y, z]^T

    El modelo asume velocidad ~ constante entre frames (modelo CV).
    Adecuado para un dron que se mueve suavemente entre posiciones.
    """

    def __init__(self, dt: float = 1 / 30):
        self.dt = dt
        self.n_states = 6
        self.n_meas = 3

        # Estado y covarianza
        self.x = np.zeros(6)                          # [x y z vx vy vz]
        self.P = np.eye(6) * CFG.kalman_initial_cov

        # Matriz de transición (modelo velocidad constante)
        self.F = np.eye(6)
        self.F[0, 3] = dt
        self.F[1, 4] = dt
        self.F[2, 5] = dt

        # Matriz de observación (medimos solo posición)
        self.H = np.zeros((3, 6))
        self.H[0, 0] = 1
        self.H[1, 1] = 1
        self.H[2, 2] = 1

        # Ruido del proceso (aceleración como perturbación)
        q = CFG.kalman_process_noise
        G = np.array([
            [0.5 * dt**2, 0, 0],
            [0, 0.5 * dt**2, 0],
            [0, 0, 0.5 * dt**2],
            [dt, 0, 0],
            [0, dt, 0],
            [0, 0, dt],
        ])
        self.Q = q**2 * (G @ G.T)

        # Ruido de medida
        r = CFG.kalman_measurement_noise
        self.R = np.eye(3) * r**2

        self._initialized = False
        self._last_time: Optional[float] = None

    @property
    def position(self) -> np.ndarray:
        return self.x[:3].copy()

    @property
    def velocity(self) -> np.ndarray:
        return self.x[3:].copy()

    @property
    def position_covariance(self) -> np.ndarray:
        return self.P[:3, :3].copy()

    @property
    def is_initialized(self) -> bool:
        return self._initialized

    def _update_dt(self):
        """Actualiza dt dinámicamente según el tiempo real entre frames."""
        now = time.monotonic()
        if self._last_time is not None:
            real_dt = now - self._last_time
            # Clamp entre 1ms y 500ms para evitar inestabilidades
            real_dt = np.clip(real_dt, 0.001, 0.5)
            self.dt = real_dt
            self.F[0, 3] = real_dt
            self.F[1, 4] = real_dt
            self.F[2, 5] = real_dt
            # Recalcular Q con nuevo dt
            q = CFG.kalman_process_noise
            G = np.array([
                [0.5 * real_dt**2, 0, 0],
                [0, 0.5 * real_dt**2, 0],
                [0, 0, 0.5 * real_dt**2],
                [real_dt, 0, 0],
                [0, real_dt, 0],
                [0, 0, real_dt],
            ])
            self.Q = q**2 * (G @ G.T)
        self._last_time = now

    def predict(self):
        """Paso de predicción (propagar estado con modelo CV)."""
        self._update_dt()
        self.x = self.F @ self.x
        self.P = self.F @ self.P @ self.F.T + self.Q

    def update(self, z: np.ndarray, R_override: Optional[np.ndarray] = None):
        """
        Paso de corrección con medida z = [x, y, z].

        R_override: si se proporciona, usa esta R en vez de la por defecto.
                    Útil para escalar la incertidumbre según calidad de la medida.
        """
        R = R_override if R_override is not None else self.R

        y = z - self.H @ self.x                          # innovación
        S = self.H @ self.P @ self.H.T + R                # covarianza innovación
        K = self.P @ self.H.T @ np.linalg.inv(S)          # ganancia de Kalman

        self.x = self.x + K @ y
        I_KH = np.eye(self.n_states) - K @ self.H
        # Forma Joseph (numéricamente más estable)
        self.P = I_KH @ self.P @ I_KH.T + K @ R @ K.T

    def initialize(self, z: np.ndarray):
        """Primera medida: inicializa el estado directamente."""
        self.x[:3] = z
        self.x[3:] = 0.0  # velocidad desconocida
        self.P = np.eye(6) * CFG.kalman_initial_cov
        self._initialized = True
        self._last_time = time.monotonic()
        log.info(f"Kalman inicializado en ({z[0]:.3f}, {z[1]:.3f}, {z[2]:.3f})")

    def reset(self):
        """Reinicia el filtro al estado no inicializado."""
        self.x = np.zeros(6)
        self.P = np.eye(6) * CFG.kalman_initial_cov
        self._initialized = False
        self._last_time = None
        log.info("Kalman reseteado.")

    def mahalanobis(self, z: np.ndarray) -> float:
        """Distancia de Mahalanobis de la medida respecto a la predicción."""
        y = z - self.H @ self.x
        S = self.H @ self.P @ self.H.T + self.R
        return float(np.sqrt(y.T @ np.linalg.inv(S) @ y))


# ═════════════════════════════════════════════════════════════════════════════
#  DETECTOR ARUCO + ESTIMACIÓN DE POSE
# ═════════════════════════════════════════════════════════════════════════════

_dictionary = cv2.aruco.getPredefinedDictionary(CFG.aruco_dict)
_parameters = cv2.aruco.DetectorParameters()

# Ajustes para mejorar detección
_parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
_parameters.cornerRefinementWinSize = 5
_parameters.cornerRefinementMaxIterations = 50
_parameters.adaptiveThreshWinSizeMin = 3
_parameters.adaptiveThreshWinSizeMax = 23
_parameters.adaptiveThreshWinSizeStep = 4

detector = cv2.aruco.ArucoDetector(_dictionary, _parameters)


def _error_reproyeccion(rvec, tvec, img_pts) -> float:
    """Calcula RMS del error de reproyección en píxeles."""
    proj, _ = cv2.projectPoints(
        MARKER_OBJ_PTS, rvec, tvec, CFG.camera_matrix, CFG.dist_coeffs
    )
    proj = proj.reshape(4, 2)
    err = np.sqrt(np.mean(np.sum((proj - img_pts) ** 2, axis=1)))
    return float(err)


def estimar_pose_marcador(corners: np.ndarray, mid: int) -> Optional[PoseEstimate]:
    """
    Estima la pose de la cámara a partir de un solo marcador.

    Resuelve la ambigüedad IPPE eligiendo la solución con menor
    error de reproyección (mejora clave respecto a v1).
    """
    img_pts = corners.reshape(4, 2).astype(np.float32)

    # IPPE devuelve hasta 2 soluciones — probamos ambas
    ok, rvec1, tvec1 = cv2.solvePnP(
        MARKER_OBJ_PTS, img_pts, CFG.camera_matrix, CFG.dist_coeffs,
        flags=cv2.SOLVEPNP_IPPE_SQUARE,
    )
    if not ok:
        return None

    # Segunda solución IPPE (si existe, con refinamiento)
    ok2, rvec2, tvec2 = cv2.solvePnP(
        MARKER_OBJ_PTS, img_pts, CFG.camera_matrix, CFG.dist_coeffs,
        rvec=rvec1.copy(), tvec=tvec1.copy(),
        useExtrinsicGuess=True,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )

    # Elegir la mejor por reproyección
    err1 = _error_reproyeccion(rvec1, tvec1, img_pts)

    if ok2:
        err2 = _error_reproyeccion(rvec2, tvec2, img_pts)
        if err2 < err1:
            rvec1, tvec1, err1 = rvec2, tvec2, err2

    # Descartar si el error de reproyección es excesivo
    if err1 > CFG.max_reprojection_px:
        log.debug(f"  Marcador {mid}: reproyección {err1:.1f}px > umbral, descartado")
        return None

    # Pasar de sistema local marcador → sistema mundo
    R, _ = cv2.Rodrigues(rvec1)
    cam_local = (-R.T @ tvec1).flatten()
    cam_world = MARKERS[mid].pos + cam_local
    distance = float(np.linalg.norm(tvec1))

    return PoseEstimate(
        marker_id=mid,
        cam_world=cam_world,
        rvec=rvec1,
        tvec=tvec1,
        distance=distance,
        reprojection_err=err1,
    )


def triangular_ponderado(
    corners_list: list,
    ids_list: list[int],
) -> tuple[Optional[np.ndarray], list[PoseEstimate], float]:
    """
    Combina las estimaciones de TODOS los marcadores visibles usando
    media ponderada por la inversa del error de reproyección.

    Además aplica rechazo de outliers por IQR sobre las posiciones X, Y, Z
    antes de promediar.

    Devuelve: (posicion_combinada, lista_estimaciones, incertidumbre_media)
    """
    estimates: list[PoseEstimate] = []

    for corners, mid in zip(corners_list, ids_list):
        if mid not in VALID_IDS:
            continue
        est = estimar_pose_marcador(corners, mid)
        if est is not None:
            estimates.append(est)

    if not estimates:
        return None, estimates, float("inf")

    # ── Rechazo de outliers por IQR (si hay >= 4 estimaciones) ────────────
    if len(estimates) >= 4:
        positions = np.array([e.cam_world for e in estimates])
        filtered_mask = np.ones(len(estimates), dtype=bool)

        for axis in range(3):
            vals = positions[:, axis]
            q1, q3 = np.percentile(vals, [25, 75])
            iqr = q3 - q1
            lo = q1 - CFG.outlier_iqr_factor * iqr
            hi = q3 + CFG.outlier_iqr_factor * iqr
            filtered_mask &= (vals >= lo) & (vals <= hi)

        n_rejected = np.sum(~filtered_mask)
        if n_rejected > 0:
            log.debug(f"  Outliers rechazados: {n_rejected}/{len(estimates)}")
            estimates = [e for e, keep in zip(estimates, filtered_mask) if keep]

        if not estimates:
            return None, estimates, float("inf")

    # ── Media ponderada (peso = 1 / error_reproyección²) ─────────────────
    positions = np.array([e.cam_world for e in estimates])
    errors = np.array([e.reprojection_err for e in estimates])

    # Evitar división por cero
    errors = np.clip(errors, 0.1, None)
    weights = 1.0 / (errors ** 2)
    weights /= weights.sum()

    weighted_pos = np.average(positions, weights=weights, axis=0)
    avg_uncertainty = float(np.average(errors, weights=weights))

    return weighted_pos, estimates, avg_uncertainty


# ═════════════════════════════════════════════════════════════════════════════
#  ESTADO COMPARTIDO  (hilo OpenCV ↔ hilo Matplotlib)
# ═════════════════════════════════════════════════════════════════════════════

_lock = threading.Lock()
_state = {
    "cam_pos": None,       # posición filtrada (Kalman)
    "cam_vel": None,       # velocidad estimada
    "cam_cov": None,       # covarianza posición 3x3
    "cam_raw": None,       # medida cruda (pre-Kalman)
    "ids_seen": [],
    "dists": {},
    "reproj_errs": {},
    "kalman_status": "NO INIT",
}
_running = True
_freeze_plot = False


# ═════════════════════════════════════════════════════════════════════════════
#  MAPA 3D  (hilo Matplotlib)
# ═════════════════════════════════════════════════════════════════════════════

_pos_arr = np.array([m.pos for m in MARKERS.values()])
_mg = SPACING * 0.4
X_LIM = (_pos_arr[:, 0].min() - _mg, _pos_arr[:, 0].max() + _mg)
Y_LIM = (_pos_arr[:, 1].min() - _mg, _pos_arr[:, 1].max() + _mg)
Z_LIM = (-0.05, CFG.max_z_display)


def _dibujar_panel(ax, ids_seen):
    """Dibuja el panel plano con la cuadrícula de marcadores."""
    xmin, xmax = float(_pos_arr[:, 0].min()), float(_pos_arr[:, 0].max())
    ymin, ymax = float(_pos_arr[:, 1].min()), float(_pos_arr[:, 1].max())
    mg = SPACING * 0.35

    # Superficie translúcida
    Xg = np.array([[xmin - mg, xmax + mg], [xmin - mg, xmax + mg]])
    Yg = np.array([[ymin - mg, ymin - mg], [ymax + mg, ymax + mg]])
    Zg = np.zeros((2, 2))
    ax.plot_surface(Xg, Yg, Zg, alpha=0.10, color="#2244aa",
                    linewidth=0, shade=False)

    # Borde
    bx = [xmin - mg, xmax + mg, xmax + mg, xmin - mg, xmin - mg]
    by = [ymin - mg, ymin - mg, ymax + mg, ymax + mg, ymin - mg]
    ax.plot(bx, by, [0]*5, color="#4466bb", lw=1.8, alpha=0.8)

    # Cuadrícula
    for x in sorted(set(_pos_arr[:, 0])):
        ax.plot([x, x], [ymin - mg, ymax + mg], [0, 0],
                color="#1a2a55", lw=0.9, alpha=0.7)
    for y in sorted(set(_pos_arr[:, 1])):
        ax.plot([xmin - mg, xmax + mg], [y, y], [0, 0],
                color="#1a2a55", lw=0.9, alpha=0.7)

    # Marcadores
    for mid, m in sorted(MARKERS.items()):
        px, py, pz = float(m.pos[0]), float(m.pos[1]), float(m.pos[2])
        active = mid in ids_seen
        color = "#00ee66" if active else "#1e3050"
        sz = 130 if active else 22
        edg = "#aaffcc" if active else "none"

        ax.scatter(px, py, pz, c=color, s=sz, depthshade=False,
                   edgecolors=edg, linewidths=0.8, zorder=7)

        if active:
            ax.text(px, py, pz + 0.08, f"ID{mid}\n{m.label}",
                    color="white", fontsize=6.5, ha="center",
                    fontweight="bold")
        else:
            ax.text(px, py, pz + 0.06, str(mid),
                    color="#334455", fontsize=6, ha="center")

    ax.text((xmin + xmax) / 2, ymin - mg - 0.08, 0.0,
            "Panel ArUco (Z=0)", color="#4466aa",
            fontsize=8, ha="center", va="top")


def _dibujar_elipsoide_cov(ax, center, cov_3x3, n_std=2.0, color="#00ccff"):
    """Dibuja un elipsoide de covarianza alrededor de la posición estimada."""
    try:
        eigvals, eigvecs = np.linalg.eigh(cov_3x3)
        eigvals = np.clip(eigvals, 1e-6, None)  # evitar negativos numéricos
        radii = n_std * np.sqrt(eigvals)

        # Limitar tamaño visual para no desbordar el plot
        radii = np.clip(radii, 0, 0.5)

        u = np.linspace(0, 2 * np.pi, 16)
        v = np.linspace(0, np.pi, 10)
        xs = radii[0] * np.outer(np.cos(u), np.sin(v))
        ys = radii[1] * np.outer(np.sin(u), np.sin(v))
        zs = radii[2] * np.outer(np.ones_like(u), np.cos(v))

        for i in range(len(xs)):
            for j in range(len(xs[0])):
                pt = eigvecs @ np.array([xs[i, j], ys[i, j], zs[i, j]])
                xs[i, j], ys[i, j], zs[i, j] = pt

        ax.plot_surface(
            xs + center[0], ys + center[1], zs + center[2],
            alpha=0.12, color=color, linewidth=0, shade=False
        )
    except np.linalg.LinAlgError:
        pass  # covarianza degenerada, no dibujar


def _hilo_plot():
    global _freeze_plot

    plt.ion()
    fig = plt.figure(figsize=(14, 8), facecolor="#07071a")
    fig.canvas.manager.set_window_title(f"Mapa 3D — {SPACE_NAME}")

    ax = fig.add_axes([0.01, 0.05, 0.67, 0.91], projection="3d")
    ax.set_facecolor("#07071a")

    # Panel de info (derecha)
    ax_info = fig.add_axes([0.70, 0.05, 0.28, 0.91])
    ax_info.set_facecolor("#0c0c22")
    ax_info.set_xlim(0, 1); ax_info.set_ylim(0, 1)
    ax_info.axis("off")

    ax_info.text(0.5, 0.975, "FILTRO DE KALMAN",
                 ha="center", va="top", fontsize=12,
                 color="white", fontweight="bold",
                 transform=ax_info.transAxes)
    ax_info.axhline(0.945, color="#222255", lw=1, xmin=0.04, xmax=0.96)

    _txt_status = ax_info.text(0.5, 0.91, "Estado: NO INIT",
                               ha="center", va="top", fontsize=9,
                               color="#ffaa00", transform=ax_info.transAxes)

    _txt_xyz = ax_info.text(0.5, 0.79, "—\n—\n—",
                            ha="center", va="center", fontsize=16,
                            color="#00ccff", fontweight="bold",
                            linespacing=2.0, transform=ax_info.transAxes)

    _txt_vel = ax_info.text(0.5, 0.60, "vel: —",
                            ha="center", va="center", fontsize=10,
                            color="#88aacc", transform=ax_info.transAxes)

    ax_info.axhline(0.52, color="#222255", lw=1, xmin=0.04, xmax=0.96)
    ax_info.text(0.5, 0.518, "MARCADORES VISIBLES",
                 ha="center", va="bottom", fontsize=9,
                 color="#7788aa", transform=ax_info.transAxes)

    _txt_tabla = ax_info.text(0.05, 0.50, "(ninguno)",
                              ha="left", va="top", fontsize=8.5,
                              color="#99aacc", fontfamily="monospace",
                              linespacing=1.8, transform=ax_info.transAxes)

    leyenda = [
        mpatches.Patch(color="#00ee66", label="Marcador detectado"),
        mpatches.Patch(color="#1e3050", label="No detectado"),
        mpatches.Patch(color="#00ccff", label="Posición Kalman"),
        mpatches.Patch(color="#ff6644", label="Medida cruda"),
        mpatches.Patch(color="#2255bb", label="Rayo cam→marcador"),
    ]
    ax_info.legend(handles=leyenda, loc="lower center",
                   facecolor="#10102a", labelcolor="white",
                   fontsize=7.5, framealpha=0.9,
                   bbox_to_anchor=(0.5, 0.01))

    while _running:
        if _freeze_plot:
            plt.pause(0.1)
            continue

        with _lock:
            cam_pos = _state["cam_pos"]
            cam_vel = _state["cam_vel"]
            cam_cov = _state["cam_cov"]
            cam_raw = _state["cam_raw"]
            ids_seen = list(_state["ids_seen"])
            dists = dict(_state["dists"])
            reproj = dict(_state["reproj_errs"])
            kstatus = _state["kalman_status"]

        # ── Texto info ────────────────────────────────────────────────
        _txt_status.set_text(f"Estado: {kstatus}")
        _txt_status.set_color(
            "#00ff88" if kstatus == "ACTIVO" else
            "#ffaa00" if kstatus == "PREDICCIÓN" else "#555577"
        )

        if cam_pos is not None:
            _txt_xyz.set_text(
                f"X = {cam_pos[0]:+.4f} m\n"
                f"Y = {cam_pos[1]:+.4f} m\n"
                f"Z = {cam_pos[2]:+.4f} m"
            )
            _txt_xyz.set_color("#00ccff")
        else:
            _txt_xyz.set_text("Sin señal")
            _txt_xyz.set_color("#334455")

        if cam_vel is not None:
            speed = np.linalg.norm(cam_vel)
            _txt_vel.set_text(
                f"vel: ({cam_vel[0]:+.3f}, {cam_vel[1]:+.3f}, "
                f"{cam_vel[2]:+.3f}) m/s\n|v| = {speed:.3f} m/s"
            )
        else:
            _txt_vel.set_text("vel: —")

        if ids_seen:
            rows = []
            for mid in sorted(ids_seen):
                lbl = MARKERS[mid].label if mid in MARKERS else f"ID{mid}"
                d = dists.get(mid, 0.0)
                rp = reproj.get(mid, 0.0)
                rows.append(f" ID{mid:3d}  {lbl:<8s}  {d:.2f}m  rp:{rp:.1f}px")
            _txt_tabla.set_text("\n".join(rows))
        else:
            _txt_tabla.set_text(" (ninguno)")

        # ── Eje 3D ────────────────────────────────────────────────────
        ax.clear()
        ax.set_facecolor("#07071a")
        ax.set_xlabel("X (m)", color="#6677aa", fontsize=8, labelpad=5)
        ax.set_ylabel("Y (m)", color="#6677aa", fontsize=8, labelpad=5)
        ax.set_zlabel("Z  dist (m)", color="#6677aa", fontsize=8, labelpad=5)
        ax.set_xlim(*X_LIM); ax.set_ylim(*Y_LIM); ax.set_zlim(*Z_LIM)
        ax.tick_params(colors="#334455", labelsize=6)
        for pane in [ax.xaxis.pane, ax.yaxis.pane, ax.zaxis.pane]:
            pane.fill = False
            pane.set_edgecolor("#12122a")
        ax.grid(True, color="#0e0e25", linewidth=0.4)

        n = len(ids_seen)
        ax.set_title(
            f"{SPACE_NAME}   [{n} marcador{'es' if n != 1 else ''}"
            f" visible{'s' if n != 1 else ''}]   Kalman: {kstatus}",
            color="white", fontsize=10, pad=5,
        )

        _dibujar_panel(ax, ids_seen)

        # Medida cruda (punto rojo)
        if cam_raw is not None:
            ax.scatter(*cam_raw, c="#ff6644", s=60, marker="o",
                       depthshade=False, zorder=9, alpha=0.7)

        # Posición Kalman + elipsoide
        if cam_pos is not None:
            cx, cy, cz = float(cam_pos[0]), float(cam_pos[1]), float(cam_pos[2])

            for mid in ids_seen:
                if mid not in MARKERS:
                    continue
                mx, my, mz = (float(v) for v in MARKERS[mid].pos)
                ax.plot([cx, mx], [cy, my], [cz, mz],
                        color="#2255bb", lw=1.0, alpha=0.65,
                        linestyle="--", zorder=4)

            ax.plot([cx, cx], [cy, cy], [0.0, cz],
                    color="#0099cc", lw=1.2, alpha=0.45, linestyle=":")
            ax.scatter(cx, cy, 0.0, c="#001133", s=55,
                       marker="+", depthshade=False, zorder=5)

            # Elipsoide de covarianza
            if cam_cov is not None:
                _dibujar_elipsoide_cov(ax, cam_pos, cam_cov)

            ax.scatter(cx, cy, cz, c="#00ccff", s=310, marker="^",
                       depthshade=False, zorder=11,
                       edgecolors="white", linewidths=1.0)
            ax.text(cx, cy, cz + 0.13,
                    f"({cx:.2f}, {cy:.2f}, {cz:.2f}) m",
                    color="#00deff", fontsize=7, ha="center",
                    fontweight="bold")

            # Vector velocidad
            if cam_vel is not None and np.linalg.norm(cam_vel) > 0.01:
                scale = 0.3  # escala visual
                ax.quiver(cx, cy, cz,
                          cam_vel[0]*scale, cam_vel[1]*scale, cam_vel[2]*scale,
                          color="#ffcc00", linewidth=1.5, arrow_length_ratio=0.2)
        else:
            cx_m = (X_LIM[0] + X_LIM[1]) / 2
            cy_m = (Y_LIM[0] + Y_LIM[1]) / 2
            cz_m = (Z_LIM[0] + Z_LIM[1]) / 2
            ax.text(cx_m, cy_m, cz_m, "Sin marcadores visibles",
                    color="#333355", fontsize=10, ha="center")

        fig.canvas.draw()
        plt.pause(CFG.plot_refresh_ms / 1000.0)

    plt.close("all")


# ═════════════════════════════════════════════════════════════════════════════
#  BUCLE PRINCIPAL — OpenCV + Kalman
# ═════════════════════════════════════════════════════════════════════════════

def main():
    global _running, _freeze_plot

    cap = cv2.VideoCapture(CFG.video_source)
    if not cap.isOpened():
        log.error(f"No se puede abrir la fuente: {CFG.video_source}")
        return

    win = "Detector ArUco 3D + Kalman"
    cv2.namedWindow(win, cv2.WINDOW_NORMAL)
    cv2.setWindowProperty(win, cv2.WND_PROP_FULLSCREEN, cv2.WINDOW_FULLSCREEN)

    kf = KalmanFilter3D()

    hilo = threading.Thread(target=_hilo_plot, daemon=True)
    hilo.start()

    frames_sin_medida = 0
    MAX_FRAMES_PREDICCION = 30  # tras ~1s sin medida, marcar como perdido

    log.info("Sistema iniciado — teclas: q=salir  r=reset Kalman  c=congelar mapa")

    while True:
        ok, frame = cap.read()
        if not ok:
            break

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners_det, ids_det, _ = detector.detectMarkers(gray)

        ids_list: list[int] = []
        dists_frame: dict[int, float] = {}
        reproj_frame: dict[int, float] = {}

        measurement = None
        estimates: list[PoseEstimate] = []

        if ids_det is not None and len(ids_det) > 0:
            cv2.aruco.drawDetectedMarkers(frame, corners_det, ids_det)
            ids_list = ids_det.flatten().tolist()

            measurement, estimates, avg_unc = triangular_ponderado(
                corners_det, ids_list,
            )

            for est in estimates:
                dists_frame[est.marker_id] = est.distance
                reproj_frame[est.marker_id] = est.reprojection_err

        # ── Kalman: predict + update ──────────────────────────────────────
        kalman_status = "NO INIT"

        if measurement is not None:
            frames_sin_medida = 0

            if not kf.is_initialized:
                kf.initialize(measurement)
                kalman_status = "ACTIVO"
            else:
                kf.predict()

                # Gate de Mahalanobis: rechazar medida si está muy lejos
                maha = kf.mahalanobis(measurement)
                if maha < 5.0:  # umbral chi² 3DOF ~99.9%
                    # Escalar R según incertidumbre de la medida
                    r_scale = max(avg_unc / 2.0, 0.5)
                    R_dyn = np.eye(3) * (CFG.kalman_measurement_noise * r_scale) ** 2
                    kf.update(measurement, R_override=R_dyn)
                    kalman_status = "ACTIVO"
                else:
                    log.warning(
                        f"Medida rechazada (Mahalanobis={maha:.1f}): "
                        f"posible salto o error"
                    )
                    kalman_status = "PREDICCIÓN"
        else:
            frames_sin_medida += 1
            if kf.is_initialized:
                if frames_sin_medida <= MAX_FRAMES_PREDICCION:
                    kf.predict()
                    kalman_status = "PREDICCIÓN"
                else:
                    kalman_status = "PERDIDO"
                    kf.reset()

        # Posición filtrada
        pos_kalman = kf.position if kf.is_initialized else None
        vel_kalman = kf.velocity if kf.is_initialized else None
        cov_kalman = kf.position_covariance if kf.is_initialized else None

        # ── Overlay en OpenCV ─────────────────────────────────────────────
        for est in estimates:
            cv2.drawFrameAxes(frame, CFG.camera_matrix, CFG.dist_coeffs,
                              est.rvec, est.tvec, MARKER_SIZE * 0.7)
            idx = ids_list.index(est.marker_id)
            cx_img = int(corners_det[idx][0][:, 0].mean())
            cy_img = int(corners_det[idx][0][:, 1].mean()) - 18
            lbl = MARKERS[est.marker_id].label
            cv2.putText(frame, f"ID{est.marker_id}  {lbl}",
                        (cx_img - 36, cy_img),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.47, (0, 255, 160), 1)
            cv2.putText(frame, f"d={est.distance:.2f}m  rp={est.reprojection_err:.1f}px",
                        (cx_img - 36, cy_img + 17),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.40, (80, 200, 255), 1)

        if pos_kalman is not None:
            X, Y, Z = pos_kalman
            n_ref = sum(1 for m in ids_list if m in VALID_IDS)

            # Fondo semitransparente para el HUD
            ov = frame.copy()
            cv2.rectangle(ov, (5, 5), (400, 210), (0, 0, 0), -1)
            cv2.addWeighted(ov, 0.55, frame, 0.45, 0, frame)

            # Estado del Kalman
            color_status = {
                "ACTIVO": (80, 255, 120),
                "PREDICCIÓN": (0, 170, 255),
                "PERDIDO": (80, 80, 220),
            }
            cv2.putText(frame, f"KALMAN: {kalman_status}",
                        (12, 27), cv2.FONT_HERSHEY_SIMPLEX, 0.54,
                        color_status.get(kalman_status, (170, 170, 170)), 1)
            cv2.line(frame, (8, 34), (393, 34), (40, 40, 70), 1)

            lines = [
                (f" X = {X:+.4f} m",                   (120, 220, 255)),
                (f" Y = {Y:+.4f} m",                   (120, 255, 180)),
                (f" Z = {Z:+.4f} m  (dist al panel)",   (255, 200, 100)),
                (f" refs: {n_ref} marcador/es",          (140, 140, 165)),
            ]

            if vel_kalman is not None:
                speed = np.linalg.norm(vel_kalman)
                lines.append(
                    (f" |vel| = {speed:.3f} m/s", (255, 220, 100))
                )

            for k, (txt, col) in enumerate(lines):
                cv2.putText(frame, txt, (12, 57 + k * 27),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.52, col, 1)

            log.debug(
                f"X={X:+.4f}m  Y={Y:+.4f}m  Z={Z:+.4f}m  "
                f"refs={n_ref}  status={kalman_status}"
            )
        else:
            cv2.putText(frame, "Sin marcadores visibles",
                        (14, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.70,
                        (60, 60, 200), 2)

        # ── Estado compartido ─────────────────────────────────────────────
        with _lock:
            _state["cam_pos"] = pos_kalman
            _state["cam_vel"] = vel_kalman
            _state["cam_cov"] = cov_kalman
            _state["cam_raw"] = measurement
            _state["ids_seen"] = [m for m in ids_list if m in VALID_IDS]
            _state["dists"] = dists_frame
            _state["reproj_errs"] = reproj_frame
            _state["kalman_status"] = kalman_status

        # ── Mostrar frame ─────────────────────────────────────────────────
        try:
            _, _, ww, wh = cv2.getWindowImageRect(win)
            if ww > 0 and wh > 0:
                frame = cv2.resize(frame, (ww, wh),
                                   interpolation=cv2.INTER_LINEAR)
        except Exception:
            pass

        cv2.imshow(win, frame)
        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            break
        elif key == ord("r"):
            kf.reset()
            log.info("Kalman reseteado manualmente (tecla R)")
        elif key == ord("c"):
            _freeze_plot = not _freeze_plot
            log.info(f"Mapa 3D {'congelado' if _freeze_plot else 'descongelado'}")

    # ── Cierre limpio ─────────────────────────────────────────────────────
    _running = False
    log.info("Sistema detenido.")
    cap.release()
    cv2.destroyAllWindows()
    hilo.join(timeout=2)


if __name__ == "__main__":
    main()