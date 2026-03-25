from __future__ import annotations

from typing import Iterable

import cv2
import numpy as np

from .models import CalibrationData, MarkerDetection


SUPPORTED_ARUCO_DICTIONARIES: dict[str, int] = {
    "DICT_4X4_50": cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100": cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250": cv2.aruco.DICT_4X4_250,
    "DICT_4X4_1000": cv2.aruco.DICT_4X4_1000,
    "DICT_5X5_50": cv2.aruco.DICT_5X5_50,
    "DICT_5X5_100": cv2.aruco.DICT_5X5_100,
    "DICT_5X5_250": cv2.aruco.DICT_5X5_250,
    "DICT_5X5_1000": cv2.aruco.DICT_5X5_1000,
    "DICT_6X6_50": cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100": cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250": cv2.aruco.DICT_6X6_250,
    "DICT_6X6_1000": cv2.aruco.DICT_6X6_1000,
    "DICT_7X7_50": cv2.aruco.DICT_7X7_50,
    "DICT_7X7_100": cv2.aruco.DICT_7X7_100,
    "DICT_7X7_250": cv2.aruco.DICT_7X7_250,
    "DICT_7X7_1000": cv2.aruco.DICT_7X7_1000,
    "DICT_ARUCO_ORIGINAL": cv2.aruco.DICT_ARUCO_ORIGINAL,
}


def aruco_dictionary_names() -> list[str]:
    return list(SUPPORTED_ARUCO_DICTIONARIES.keys())


def _marker_object_points(marker_size_m: float) -> np.ndarray:
    half = marker_size_m / 2.0
    return np.array(
        [
            [-half, half, 0.0],
            [half, half, 0.0],
            [half, -half, 0.0],
            [-half, -half, 0.0],
        ],
        dtype=np.float32,
    )


def reprojection_rms(
    object_points: np.ndarray,
    image_points: np.ndarray,
    rvec: np.ndarray,
    tvec: np.ndarray,
    calibration: CalibrationData,
) -> float:
    projected, _ = cv2.projectPoints(
        object_points,
        rvec,
        tvec,
        calibration.camera_matrix,
        calibration.dist_coeffs,
    )
    projected = projected.reshape(-1, 2)
    image_points = image_points.reshape(-1, 2)
    error = np.sqrt(np.mean(np.sum((projected - image_points) ** 2, axis=1)))
    return float(error)


class ArucoDetector:
    """Detector ArUco reutilizable para benchmark y detector en vivo."""

    def __init__(
        self,
        calibration: CalibrationData,
        dictionary_name: str,
        marker_size_m: float,
    ):
        if dictionary_name not in SUPPORTED_ARUCO_DICTIONARIES:
            raise ValueError(
                f"Diccionario ArUco no soportado: {dictionary_name}. "
                f"Disponibles: {', '.join(aruco_dictionary_names())}"
            )

        self.calibration = calibration
        self._runtime_calibration = calibration
        self._runtime_image_size = calibration.image_size
        self.dictionary_name = dictionary_name
        self.marker_size_m = marker_size_m
        self.object_points = _marker_object_points(marker_size_m)

        dictionary = cv2.aruco.getPredefinedDictionary(
            SUPPORTED_ARUCO_DICTIONARIES[dictionary_name]
        )
        parameters = cv2.aruco.DetectorParameters()
        parameters.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX
        parameters.cornerRefinementWinSize = 5
        parameters.cornerRefinementMaxIterations = 50
        parameters.adaptiveThreshWinSizeMin = 3
        parameters.adaptiveThreshWinSizeMax = 23
        parameters.adaptiveThreshWinSizeStep = 4
        parameters.minMarkerPerimeterRate = 0.02
        parameters.maxMarkerPerimeterRate = 4.0
        self.detector = cv2.aruco.ArucoDetector(dictionary, parameters)

    def _calibration_for_frame(self, frame: np.ndarray) -> CalibrationData:
        image_size = (int(frame.shape[1]), int(frame.shape[0]))
        if self._runtime_image_size != image_size:
            self._runtime_calibration = self.calibration.scaled_to_image_size(image_size)
            self._runtime_image_size = image_size
        return self._runtime_calibration

    def detect(self, frame: np.ndarray) -> list[MarkerDetection]:
        calibration = self._calibration_for_frame(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners_list, ids, _ = self.detector.detectMarkers(gray)
        if ids is None:
            return []

        detections: list[MarkerDetection] = []
        for marker_id, corners in zip(ids.flatten().tolist(), corners_list):
            corners_2d = corners.reshape(4, 2).astype(np.float32)
            center = tuple(np.mean(corners_2d, axis=0).astype(int).tolist())
            rvec, tvec, reprojection_error = self._estimate_marker_pose(
                corners_2d,
                calibration,
            )
            detections.append(
                MarkerDetection(
                    marker_id=int(marker_id),
                    corners=corners_2d,
                    center_px=center,
                    rvec=rvec,
                    tvec=tvec,
                    reprojection_error_px=reprojection_error,
                )
            )
        return detections

    def _estimate_marker_pose(
        self,
        corners_2d: np.ndarray,
        calibration: CalibrationData,
    ) -> tuple[np.ndarray | None, np.ndarray | None, float]:
        success, rvec, tvec = cv2.solvePnP(
            self.object_points,
            corners_2d,
            calibration.camera_matrix,
            calibration.dist_coeffs,
            flags=cv2.SOLVEPNP_IPPE_SQUARE,
        )
        if not success:
            return None, None, float("inf")

        best_rvec = rvec
        best_tvec = tvec
        best_error = reprojection_rms(
            self.object_points,
            corners_2d,
            best_rvec,
            best_tvec,
            calibration,
        )

        try:
            refined_rvec, refined_tvec = cv2.solvePnPRefineLM(
                self.object_points,
                corners_2d,
                calibration.camera_matrix,
                calibration.dist_coeffs,
                rvec,
                tvec,
            )
            refined_error = reprojection_rms(
                self.object_points,
                corners_2d,
                refined_rvec,
                refined_tvec,
                calibration,
            )
            if refined_error < best_error:
                best_rvec = refined_rvec
                best_tvec = refined_tvec
                best_error = refined_error
        except cv2.error:
            pass

        return best_rvec, best_tvec, best_error

    def draw_on_frame(
        self,
        frame: np.ndarray,
        detections: Iterable[MarkerDetection],
        axis_scale: float = 0.6,
    ) -> np.ndarray:
        detections = list(detections)
        annotated = frame.copy()
        calibration = self._calibration_for_frame(frame)

        if detections:
            ids = np.asarray([det.marker_id for det in detections], dtype=np.int32).reshape(-1, 1)
            corners = [det.corners.reshape(1, 4, 2).astype(np.float32) for det in detections]
            cv2.aruco.drawDetectedMarkers(annotated, corners, ids)

        for det in detections:
            if det.has_pose:
                cv2.drawFrameAxes(
                    annotated,
                    calibration.camera_matrix,
                    calibration.dist_coeffs,
                    det.rvec,
                    det.tvec,
                    self.marker_size_m * axis_scale,
                )

            cx, cy = det.center_px
            reproj = det.reprojection_error_px
            distance = det.distance_m
            main_line = f"ID {det.marker_id}"
            if distance is not None:
                main_line += f" | {distance:.2f} m"
            if reproj is not None and np.isfinite(reproj):
                secondary = f"reproj: {reproj:.2f}px"
            else:
                secondary = "reproj: n/d"

            cv2.putText(
                annotated,
                main_line,
                (cx - 60, cy - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.52,
                (70, 255, 170),
                1,
                cv2.LINE_AA,
            )
            cv2.putText(
                annotated,
                secondary,
                (cx - 60, cy + 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.45,
                (120, 200, 255),
                1,
                cv2.LINE_AA,
            )

        return annotated
