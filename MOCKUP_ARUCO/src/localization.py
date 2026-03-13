"""
localization.py
---------------
Motor de auto-localización del dron basado en marcadores ArUco.

Estrategia:
  1. Para cada marcador detectado cuyo ID es conocido en el mapa,
     se invierte la transformación cámara→marcador para obtener
     la posición de la cámara (dron) en el mundo.
  2. Con múltiples marcadores se aplica un filtro de Kalman 6-DoF
     para suavizar y fusionar las estimaciones.
  3. Si hay ≥4 marcadores visibles se usa solvePnP global sobre todos
     los puntos para mayor precisión.
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
from collections import deque
import time
import logging

from .aruco_detector import MarkerDetection
from .warehouse_map import WarehouseMap

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Pose del dron
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DronePose:
    """Pose estimada del dron en el sistema de coordenadas del mundo."""
    position: np.ndarray         # [x, y, z] en metros
    rotation_matrix: np.ndarray  # R 3×3
    timestamp: float             # tiempo UNIX
    n_markers_used: int          # marcadores usados en la estimación
    confidence: float            # [0-1] calidad de la estimación
    markers_ids: List[int] = field(default_factory=list)

    @property
    def x(self) -> float: return float(self.position[0])

    @property
    def y(self) -> float: return float(self.position[1])

    @property
    def z(self) -> float: return float(self.position[2])

    @property
    def euler_deg(self) -> Tuple[float, float, float]:
        """(roll, pitch, yaw) en grados. Convención ZYX."""
        R = self.rotation_matrix
        sy = np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
        if sy > 1e-6:
            roll  = float(np.degrees(np.arctan2( R[2, 1], R[2, 2])))
            pitch = float(np.degrees(np.arctan2(-R[2, 0], sy)))
            yaw   = float(np.degrees(np.arctan2( R[1, 0], R[0, 0])))
        else:
            roll  = float(np.degrees(np.arctan2(-R[1, 2], R[1, 1])))
            pitch = float(np.degrees(np.arctan2(-R[2, 0], sy)))
            yaw   = 0.0
        return roll, pitch, yaw

    @property
    def yaw_deg(self) -> float:
        return self.euler_deg[2]

    def __str__(self) -> str:
        roll, pitch, yaw = self.euler_deg
        return (
            f"Pos=({self.x:.2f},{self.y:.2f},{self.z:.2f})m  "
            f"RPY=({roll:.1f}°,{pitch:.1f}°,{yaw:.1f}°)  "
            f"Marcadores={self.n_markers_used}  Confianza={self.confidence:.2f}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Filtro de Kalman 6-DoF
# ─────────────────────────────────────────────────────────────────────────────

class PoseKalmanFilter:
    """
    Filtro de Kalman para suavizar la estimación de posición (x, y, z)
    con modelo de movimiento de velocidad constante.

    Estado: [x, y, z, vx, vy, vz]
    """

    def __init__(self, process_noise: float = 0.01, measure_noise: float = 0.05):
        self.kf = cv2.KalmanFilter(6, 3)

        dt = 1.0 / 30.0   # Asumimos ~30 fps

        # Matriz de transición
        self.kf.transitionMatrix = np.array([
            [1, 0, 0, dt,  0,  0],
            [0, 1, 0,  0, dt,  0],
            [0, 0, 1,  0,  0, dt],
            [0, 0, 0,  1,  0,  0],
            [0, 0, 0,  0,  1,  0],
            [0, 0, 0,  0,  0,  1],
        ], dtype=np.float32)

        # Matriz de medida
        self.kf.measurementMatrix = np.array([
            [1, 0, 0, 0, 0, 0],
            [0, 1, 0, 0, 0, 0],
            [0, 0, 1, 0, 0, 0],
        ], dtype=np.float32)

        self.kf.processNoiseCov     = np.eye(6, dtype=np.float32) * process_noise
        self.kf.measurementNoiseCov = np.eye(3, dtype=np.float32) * measure_noise
        self.kf.errorCovPost        = np.eye(6, dtype=np.float32)

        self.initialized = False

    def update(self, position: np.ndarray) -> np.ndarray:
        meas = position.reshape(3, 1).astype(np.float32)
        if not self.initialized:
            self.kf.statePre[:3] = meas
            self.kf.statePost[:3] = meas
            self.initialized = True

        self.kf.predict()
        corrected = self.kf.correct(meas)
        return corrected[:3].flatten().astype(np.float64)

    def reset(self):
        self.initialized = False
        self.kf.errorCovPost = np.eye(6, dtype=np.float32)


# ─────────────────────────────────────────────────────────────────────────────
# Motor de localización
# ─────────────────────────────────────────────────────────────────────────────

class DroneLocalizer:
    """
    Calcula la posición del dron en el almacén a partir de los marcadores
    ArUco detectados y el mapa del almacén.

    Parameters
    ----------
    warehouse_map    : mapa con posiciones conocidas de marcadores
    camera_matrix    : matriz intrínseca de la cámara
    dist_coefficients: coeficientes de distorsión
    use_kalman       : activar filtro de Kalman para suavizar
    history_size     : nº de poses pasadas a guardar
    """

    def __init__(
        self,
        warehouse_map: WarehouseMap,
        camera_matrix: np.ndarray,
        dist_coefficients: np.ndarray,
        use_kalman: bool = True,
        history_size: int = 60,
    ):
        self.wmap              = warehouse_map
        self.camera_matrix     = camera_matrix
        self.dist_coefficients = dist_coefficients
        self.use_kalman        = use_kalman

        self._kalman = PoseKalmanFilter()
        self._history: deque = deque(maxlen=history_size)
        self._last_pose: Optional[DronePose] = None
        self._frames_without_detection = 0

        logger.info("DroneLocalizer inicializado.")

    # ── API pública ────────────────────────────────────────────────────────

    def update(self, detections: List[MarkerDetection]) -> Optional[DronePose]:
        """
        Actualiza la estimación de pose con las detecciones del frame actual.

        Returns
        -------
        DronePose si se pudo estimar, None en caso contrario.
        """
        # Filtrar sólo los marcadores conocidos en el mapa
        known = [d for d in detections
                 if self.wmap.is_known(d.marker_id) and d.tvec is not None]

        if not known:
            self._frames_without_detection += 1
            if self._frames_without_detection > 30:
                self._kalman.reset()
            return self._last_pose   # devuelve la última si la hay

        self._frames_without_detection = 0

        pose = None
        if len(known) >= 4:
            # ── Método global: solvePnP con todos los marcadores ──────────
            pose = self._localize_multi_pnp(known)
        elif len(known) >= 1:
            # ── Método individual: media ponderada por distancia ──────────
            pose = self._localize_weighted_mean(known)

        if pose is None:
            return self._last_pose

        # Filtro de Kalman sobre la posición
        if self.use_kalman:
            smooth_pos = self._kalman.update(pose.position)
            pose = DronePose(
                position=smooth_pos,
                rotation_matrix=pose.rotation_matrix,
                timestamp=pose.timestamp,
                n_markers_used=pose.n_markers_used,
                confidence=pose.confidence,
                markers_ids=pose.markers_ids,
            )

        self._last_pose = pose
        self._history.append(pose)
        return pose

    @property
    def last_pose(self) -> Optional[DronePose]:
        return self._last_pose

    @property
    def history(self) -> List[DronePose]:
        return list(self._history)

    # ── Métodos de localización ────────────────────────────────────────────

    def _localize_single(self, det: MarkerDetection) -> Optional[DronePose]:
        """
        Estima la pose del dron a partir de UN marcador.
        Invierte T_{camera→marker} para obtener T_{world→camera}.
        """
        wm = self.wmap.get_marker(det.marker_id)
        if wm is None or det.rvec is None:
            return None

        # Rotación y traslación del marcador en el sistema cámara
        R_cm, _ = cv2.Rodrigues(det.rvec)
        t_cm    = det.tvec.flatten()

        # Invertir: pose de la cámara relativa al marcador
        R_mc = R_cm.T
        t_mc = -R_mc @ t_cm

        # Transformar al sistema mundo
        R_wm = wm.rotation_matrix        # Rotación marcador→mundo
        p_w  = wm.position               # Posición marcador en el mundo

        R_wc = R_wm @ R_mc               # Rotación cámara en el mundo
        t_wc = R_wm @ t_mc + p_w        # Posición cámara en el mundo

        conf = self._compute_confidence([det])
        return DronePose(
            position=t_wc,
            rotation_matrix=R_wc,
            timestamp=time.time(),
            n_markers_used=1,
            confidence=conf,
            markers_ids=[det.marker_id],
        )

    def _localize_weighted_mean(
        self, detections: List[MarkerDetection]
    ) -> Optional[DronePose]:
        """Media ponderada de estimaciones individuales (peso = 1/distancia)."""
        poses_positions = []
        poses_rotations = []
        weights         = []
        ids             = []

        for det in detections:
            single = self._localize_single(det)
            if single is None:
                continue
            dist = float(np.linalg.norm(det.tvec))
            w    = 1.0 / max(dist, 0.1) ** 2
            poses_positions.append(single.position * w)
            poses_rotations.append(single.rotation_matrix)
            weights.append(w)
            ids.append(det.marker_id)

        if not weights:
            return None

        total_w  = sum(weights)
        mean_pos = sum(poses_positions) / total_w

        # Para la rotación, usar la del marcador más cercano (peso mayor)
        best_idx = weights.index(max(weights))
        mean_rot = poses_rotations[best_idx]

        conf = self._compute_confidence(detections)
        return DronePose(
            position=mean_pos,
            rotation_matrix=mean_rot,
            timestamp=time.time(),
            n_markers_used=len(weights),
            confidence=conf,
            markers_ids=ids,
        )

    def _localize_multi_pnp(
        self, detections: List[MarkerDetection]
    ) -> Optional[DronePose]:
        """
        solvePnP global: reúne todos los puntos 3-D mundo y sus proyecciones
        2-D en imagen para una estimación más robusta con múltiples marcadores.
        """
        obj_pts_all = []
        img_pts_all = []

        for det in detections:
            world_corners = self.wmap.get_world_corners(det.marker_id)
            if world_corners is None:
                continue
            obj_pts_all.append(world_corners)
            img_pts_all.append(det.corners)

        if not obj_pts_all:
            return self._localize_weighted_mean(detections)

        obj_pts = np.vstack(obj_pts_all).astype(np.float32)
        img_pts = np.vstack(img_pts_all).astype(np.float32)

        try:
            success, rvec, tvec, inliers = cv2.solvePnPRansac(
                obj_pts, img_pts,
                self.camera_matrix, self.dist_coefficients,
                iterationsCount=200, reprojectionError=5.0,
                confidence=0.999, flags=cv2.SOLVEPNP_ITERATIVE,
            )
        except cv2.error as e:
            logger.warning(f"solvePnPRansac falló: {e}")
            return self._localize_weighted_mean(detections)

        if not success:
            return self._localize_weighted_mean(detections)

        # rvec/tvec apuntan del mundo a la cámara: invertir
        R_cw, _ = cv2.Rodrigues(rvec)
        t_cw    = tvec.flatten()
        R_wc    = R_cw.T
        t_wc    = -R_wc @ t_cw

        n_inliers = len(inliers) if inliers is not None else len(obj_pts)
        conf = min(1.0, n_inliers / len(obj_pts) * (1.0 + len(detections) * 0.1))

        return DronePose(
            position=t_wc,
            rotation_matrix=R_wc,
            timestamp=time.time(),
            n_markers_used=len(detections),
            confidence=min(conf, 1.0),
            markers_ids=[d.marker_id for d in detections],
        )

    # ── Confianza ─────────────────────────────────────────────────────────

    def _compute_confidence(self, detections: List[MarkerDetection]) -> float:
        """
        Calcula un valor de confianza [0-1] basado en:
        - Número de marcadores detectados
        - Distancia media a los marcadores
        """
        n = len(detections)
        base = min(1.0, n / 4.0)   # 4 marcadores → confianza máxima base

        if n == 0:
            return 0.0

        mean_dist = np.mean([np.linalg.norm(d.tvec) for d in detections
                             if d.tvec is not None])
        # Penalizar distancias >5m
        dist_factor = max(0.2, 1.0 - max(0.0, mean_dist - 1.0) / 10.0)

        return round(min(1.0, base * dist_factor + 0.1 * n), 3)

    # ── Estadísticas ──────────────────────────────────────────────────────

    def stats(self) -> Dict:
        """Devuelve estadísticas de las últimas estimaciones."""
        if not self._history:
            return {"status": "sin datos"}
        positions = np.array([p.position for p in self._history])
        return {
            "n_poses":    len(self._history),
            "mean_pos":   positions.mean(axis=0).tolist(),
            "std_pos":    positions.std(axis=0).tolist(),
            "last_conf":  self._last_pose.confidence if self._last_pose else 0.0,
        }
