"""
aruco_detector.py
-----------------
Módulo de detección de marcadores ArUco y estimación de pose.

Detecta marcadores ArUco en un frame de vídeo y calcula la pose
(posición + orientación) de cada marcador relativa a la cámara.
"""

import cv2
import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple, Dict
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Estructuras de datos
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class MarkerDetection:
    """Información de un marcador ArUco detectado en un frame."""
    marker_id: int
    corners: np.ndarray          # (4, 2) esquinas en píxeles
    rvec: Optional[np.ndarray]   # Vector de rotación  (Rodrigues, 3x1)
    tvec: Optional[np.ndarray]   # Vector de traslación (metros,   3x1)
    center_px: Tuple[int, int]   # Centro en píxeles

    @property
    def distance_m(self) -> Optional[float]:
        """Distancia euclídea del marcador a la cámara en metros."""
        if self.tvec is not None:
            return float(np.linalg.norm(self.tvec))
        return None

    @property
    def position_camera(self) -> Optional[np.ndarray]:
        """Posición 3-D del marcador en el sistema de la cámara [x, y, z]."""
        if self.tvec is not None:
            return self.tvec.flatten()
        return None


@dataclass
class DetectionResult:
    """Resultado completo de un frame procesado."""
    frame_id: int
    markers: List[MarkerDetection] = field(default_factory=list)
    frame_annotated: Optional[np.ndarray] = None

    @property
    def ids_detected(self) -> List[int]:
        return [m.marker_id for m in self.markers]

    @property
    def n_markers(self) -> int:
        return len(self.markers)


# ─────────────────────────────────────────────────────────────────────────────
# Detector principal
# ─────────────────────────────────────────────────────────────────────────────

class ArucoDetector:
    """
    Detecta marcadores ArUco y estima su pose en el espacio 3-D.

    Parámetros
    ----------
    camera_matrix    : matriz intrínseca de la cámara (3×3)
    dist_coefficients: coeficientes de distorsión (1×5)
    marker_size_m    : lado del marcador en metros
    dict_name        : nombre del diccionario ArUco (ej. 'DICT_6X6_250')
    """

    # Diccionarios disponibles en OpenCV
    DICT_MAP: Dict[str, int] = {
        "DICT_4X4_50":       cv2.aruco.DICT_4X4_50,
        "DICT_4X4_100":      cv2.aruco.DICT_4X4_100,
        "DICT_4X4_250":      cv2.aruco.DICT_4X4_250,
        "DICT_4X4_1000":     cv2.aruco.DICT_4X4_1000,
        "DICT_5X5_50":       cv2.aruco.DICT_5X5_50,
        "DICT_5X5_100":      cv2.aruco.DICT_5X5_100,
        "DICT_5X5_250":      cv2.aruco.DICT_5X5_250,
        "DICT_5X5_1000":     cv2.aruco.DICT_5X5_1000,
        "DICT_6X6_50":       cv2.aruco.DICT_6X6_50,
        "DICT_6X6_100":      cv2.aruco.DICT_6X6_100,
        "DICT_6X6_250":      cv2.aruco.DICT_6X6_250,
        "DICT_6X6_1000":     cv2.aruco.DICT_6X6_1000,
        "DICT_7X7_50":       cv2.aruco.DICT_7X7_50,
        "DICT_7X7_100":      cv2.aruco.DICT_7X7_100,
        "DICT_7X7_250":      cv2.aruco.DICT_7X7_250,
        "DICT_7X7_1000":     cv2.aruco.DICT_7X7_1000,
        "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
    }

    def __init__(
        self,
        camera_matrix: np.ndarray,
        dist_coefficients: np.ndarray,
        marker_size_m: float = 0.15,
        dict_name: str = "DICT_6X6_250",
    ):
        self.camera_matrix = camera_matrix
        self.dist_coefficients = dist_coefficients
        self.marker_size_m = marker_size_m

        # Inicializar diccionario y parámetros
        dict_id = self.DICT_MAP.get(dict_name)
        if dict_id is None:
            raise ValueError(f"Diccionario desconocido: {dict_name}. "
                             f"Disponibles: {list(self.DICT_MAP.keys())}")

        self.aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)
        self.detector_params = cv2.aruco.DetectorParameters()

        # Ajustes de detección para entornos de almacén
        self.detector_params.adaptiveThreshWinSizeMin  = 3
        self.detector_params.adaptiveThreshWinSizeMax  = 23
        self.detector_params.adaptiveThreshWinSizeStep = 10
        self.detector_params.minMarkerPerimeterRate    = 0.03
        self.detector_params.maxMarkerPerimeterRate    = 4.0
        self.detector_params.polygonalApproxAccuracyRate = 0.03
        self.detector_params.cornerRefinementMethod   = cv2.aruco.CORNER_REFINE_SUBPIX

        self.detector = cv2.aruco.ArucoDetector(self.aruco_dict, self.detector_params)

        # Puntos 3-D de las esquinas del marcador en su sistema local
        half = marker_size_m / 2.0
        self._obj_points = np.array([
            [-half,  half, 0.0],
            [ half,  half, 0.0],
            [ half, -half, 0.0],
            [-half, -half, 0.0],
        ], dtype=np.float32)

        self._frame_id = 0
        logger.info(f"ArucoDetector listo │ dict={dict_name} │ marker={marker_size_m*100:.1f} cm")

    # ── Detección ──────────────────────────────────────────────────────────

    def detect(self, frame: np.ndarray, estimate_pose: bool = True) -> DetectionResult:
        """
        Procesa un frame y devuelve todos los marcadores detectados.

        Parameters
        ----------
        frame         : imagen BGR de la cámara
        estimate_pose : si True calcula rvec/tvec por cada marcador

        Returns
        -------
        DetectionResult con la lista de MarkerDetection y el frame anotado
        """
        self._frame_id += 1
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

        corners_list, ids, rejected = self.detector.detectMarkers(gray)

        result = DetectionResult(frame_id=self._frame_id)
        annotated = frame.copy()

        if ids is None:
            result.frame_annotated = annotated
            return result

        ids_flat = ids.flatten().tolist()

        for i, (marker_id, corners) in enumerate(zip(ids_flat, corners_list)):
            corners_2d = corners.reshape(4, 2)
            cx = int(np.mean(corners_2d[:, 0]))
            cy = int(np.mean(corners_2d[:, 1]))

            rvec, tvec = None, None
            if estimate_pose:
                rvec, tvec = self._estimate_pose(corners_2d)

            detection = MarkerDetection(
                marker_id=marker_id,
                corners=corners_2d,
                rvec=rvec,
                tvec=tvec,
                center_px=(cx, cy),
            )
            result.markers.append(detection)

        # Dibujar sobre el frame
        cv2.aruco.drawDetectedMarkers(annotated, corners_list, ids)
        for det in result.markers:
            if det.rvec is not None:
                cv2.drawFrameAxes(
                    annotated,
                    self.camera_matrix,
                    self.dist_coefficients,
                    det.rvec, det.tvec,
                    self.marker_size_m * 0.6,
                )
            self._draw_info_overlay(annotated, det)

        result.frame_annotated = annotated
        return result

    # ── Pose ──────────────────────────────────────────────────────────────

    def _estimate_pose(
        self, corners_2d: np.ndarray
    ) -> Tuple[Optional[np.ndarray], Optional[np.ndarray]]:
        """Estima rvec/tvec usando solvePnP."""
        success, rvec, tvec = cv2.solvePnP(
            self._obj_points,
            corners_2d.astype(np.float32),
            self.camera_matrix,
            self.dist_coefficients,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not success:
            return None, None
        # Refinar con iteración
        rvec, tvec = cv2.solvePnPRefineVVS(
            self._obj_points,
            corners_2d.astype(np.float32),
            self.camera_matrix,
            self.dist_coefficients,
            rvec, tvec,
        )
        return rvec, tvec

    def rotation_matrix_from_rvec(self, rvec: np.ndarray) -> np.ndarray:
        """Convierte vector Rodrigues → matriz de rotación 3×3."""
        R, _ = cv2.Rodrigues(rvec)
        return R

    def euler_angles_from_rvec(self, rvec: np.ndarray) -> Tuple[float, float, float]:
        """
        Devuelve (roll, pitch, yaw) en grados a partir de un rvec Rodrigues.
        Convención: ZYX (yaw → pitch → roll).
        """
        R = self.rotation_matrix_from_rvec(rvec)
        sy = np.sqrt(R[0, 0] ** 2 + R[1, 0] ** 2)
        singular = sy < 1e-6
        if not singular:
            roll  = float(np.degrees(np.arctan2( R[2, 1], R[2, 2])))
            pitch = float(np.degrees(np.arctan2(-R[2, 0], sy)))
            yaw   = float(np.degrees(np.arctan2( R[1, 0], R[0, 0])))
        else:
            roll  = float(np.degrees(np.arctan2(-R[1, 2], R[1, 1])))
            pitch = float(np.degrees(np.arctan2(-R[2, 0], sy)))
            yaw   = 0.0
        return roll, pitch, yaw

    # ── Overlay visual ────────────────────────────────────────────────────

    def _draw_info_overlay(self, frame: np.ndarray, det: MarkerDetection):
        """Dibuja ID, distancia y orientación sobre el frame."""
        cx, cy = det.center_px
        label = f"ID:{det.marker_id}"

        if det.tvec is not None:
            dist = det.distance_m
            roll, pitch, yaw = self.euler_angles_from_rvec(det.rvec)
            label += f"  {dist:.2f}m"
            sub = f"R:{roll:.0f} P:{pitch:.0f} Y:{yaw:.0f}"
            cv2.putText(frame, sub, (cx - 50, cy + 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 255, 255), 1, cv2.LINE_AA)

        cv2.putText(frame, label, (cx - 50, cy - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2, cv2.LINE_AA)

    # ── Utilidades ────────────────────────────────────────────────────────

    def undistort_frame(self, frame: np.ndarray) -> np.ndarray:
        """Corrige la distorsión de lente del frame."""
        return cv2.undistort(frame, self.camera_matrix, self.dist_coefficients)
