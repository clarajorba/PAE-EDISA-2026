from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np


def as_vector(values: Iterable[float]) -> np.ndarray:
    """Convierte una secuencia numerica a vector columna 3D."""
    return np.asarray(list(values), dtype=np.float64).reshape(3)


def rotation_matrix_z(yaw_deg: float) -> np.ndarray:
    """Rotacion alrededor del eje Z."""
    yaw = np.deg2rad(yaw_deg)
    c = float(np.cos(yaw))
    s = float(np.sin(yaw))
    return np.array(
        [
            [c, -s, 0.0],
            [s, c, 0.0],
            [0.0, 0.0, 1.0],
        ],
        dtype=np.float64,
    )


def rotation_matrix_to_euler_deg(rotation: np.ndarray) -> tuple[float, float, float]:
    """Devuelve roll, pitch y yaw en grados con convencion ZYX."""
    sy = float(np.sqrt(rotation[0, 0] ** 2 + rotation[1, 0] ** 2))
    singular = sy < 1e-6

    if not singular:
        roll = np.rad2deg(np.arctan2(rotation[2, 1], rotation[2, 2]))
        pitch = np.rad2deg(np.arctan2(-rotation[2, 0], sy))
        yaw = np.rad2deg(np.arctan2(rotation[1, 0], rotation[0, 0]))
    else:
        roll = np.rad2deg(np.arctan2(-rotation[1, 2], rotation[1, 1]))
        pitch = np.rad2deg(np.arctan2(-rotation[2, 0], sy))
        yaw = 0.0

    return float(roll), float(pitch), float(yaw)


@dataclass(slots=True)
class CalibrationData:
    camera_matrix: np.ndarray
    dist_coeffs: np.ndarray
    image_size: tuple[int, int] | None = None
    reprojection_error_px: float | None = None
    calibration_date: str | None = None

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "camera_matrix": self.camera_matrix.tolist(),
            "dist_coeffs": self.dist_coeffs.flatten().tolist(),
            "image_size": list(self.image_size) if self.image_size else None,
            "reprojection_error_px": self.reprojection_error_px,
            "calibration_date": self.calibration_date,
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "CalibrationData":
        image_size = data.get("image_size")
        if image_size is None:
            width = data.get("image_width")
            height = data.get("image_height")
            image_size = (int(width), int(height)) if width and height else None
        else:
            image_size = (int(image_size[0]), int(image_size[1]))

        dist_values = data.get("dist_coeffs", data.get("dist_coefficients", []))

        return cls(
            camera_matrix=np.asarray(data["camera_matrix"], dtype=np.float64),
            dist_coeffs=np.asarray(dist_values, dtype=np.float64).reshape(-1, 1),
            image_size=image_size,
            reprojection_error_px=data.get(
                "reprojection_error_px",
                data.get("calibration_error_rms"),
            ),
            calibration_date=data.get("calibration_date"),
        )

    def scaled_to_image_size(self, image_size: tuple[int, int]) -> "CalibrationData":
        """Escala los intrinsecos si se usa otra resolucion distinta a la calibrada."""
        if self.image_size is None or self.image_size == image_size:
            return CalibrationData(
                camera_matrix=self.camera_matrix.copy(),
                dist_coeffs=self.dist_coeffs.copy(),
                image_size=image_size,
                reprojection_error_px=self.reprojection_error_px,
                calibration_date=self.calibration_date,
            )

        scale_x = image_size[0] / self.image_size[0]
        scale_y = image_size[1] / self.image_size[1]

        scaled_matrix = self.camera_matrix.copy()
        scaled_matrix[0, 0] *= scale_x
        scaled_matrix[1, 1] *= scale_y
        scaled_matrix[0, 2] *= scale_x
        scaled_matrix[1, 2] *= scale_y

        return CalibrationData(
            camera_matrix=scaled_matrix,
            dist_coeffs=self.dist_coeffs.copy(),
            image_size=image_size,
            reprojection_error_px=self.reprojection_error_px,
            calibration_date=self.calibration_date,
        )


@dataclass(slots=True)
class CameraDescriptor:
    source: int | str
    width: int
    height: int
    fps: float
    backend_name: str = ""
    name: str = ""


@dataclass(slots=True)
class CameraProfile:
    name: str
    source: int | str
    width: int
    height: int
    fps: float = 30.0
    calibration: CalibrationData | None = None
    notes: str = ""

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "source": self.source,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "notes": self.notes,
            "calibration": (
                self.calibration.to_json_dict() if self.calibration is not None else None
            ),
        }

    @classmethod
    def from_json_dict(cls, data: dict[str, Any]) -> "CameraProfile":
        calibration_block = data.get("calibration")
        calibration = (
            CalibrationData.from_json_dict(calibration_block)
            if calibration_block
            else None
        )
        return cls(
            name=data["name"],
            source=data["source"],
            width=int(data["width"]),
            height=int(data["height"]),
            fps=float(data.get("fps", 30.0)),
            calibration=calibration,
            notes=data.get("notes", ""),
        )


@dataclass(slots=True)
class MarkerDefinition:
    marker_id: int
    position: np.ndarray
    label: str = ""
    yaw_deg: float = 0.0

    def to_json_dict(self) -> dict[str, Any]:
        return {
            "x": float(self.position[0]),
            "y": float(self.position[1]),
            "z": float(self.position[2]),
            "label": self.label,
            "yaw_deg": self.yaw_deg,
        }


@dataclass(slots=True)
class MarkerLayout:
    name: str
    aruco_dict: str
    marker_size_m: float
    markers: dict[int, MarkerDefinition]
    spacing_m: float | None = None
    description: str = ""

    def get_marker(self, marker_id: int) -> MarkerDefinition | None:
        return self.markers.get(marker_id)

    @property
    def ids(self) -> list[int]:
        return sorted(self.markers)

    def world_corners(self, marker_id: int) -> np.ndarray:
        marker = self.markers[marker_id]
        half = self.marker_size_m / 2.0
        local_corners = np.array(
            [
                [-half, half, 0.0],
                [half, half, 0.0],
                [half, -half, 0.0],
                [-half, -half, 0.0],
            ],
            dtype=np.float64,
        )
        rotation = rotation_matrix_z(marker.yaw_deg)
        return (rotation @ local_corners.T).T + marker.position

    def to_json_dict(self) -> dict[str, Any]:
        markers = {
            str(marker_id): marker.to_json_dict()
            for marker_id, marker in sorted(self.markers.items())
        }
        return {
            "space_name": self.name,
            "aruco_dict": self.aruco_dict,
            "marker_size": self.marker_size_m,
            "spacing_m": self.spacing_m,
            "description": self.description,
            "markers": markers,
        }


@dataclass(slots=True)
class MarkerDetection:
    marker_id: int
    corners: np.ndarray
    center_px: tuple[int, int]
    rvec: np.ndarray | None = None
    tvec: np.ndarray | None = None
    reprojection_error_px: float | None = None

    @property
    def distance_m(self) -> float | None:
        if self.tvec is None:
            return None
        return float(np.linalg.norm(self.tvec))

    @property
    def has_pose(self) -> bool:
        return self.rvec is not None and self.tvec is not None


@dataclass(slots=True)
class CameraPoseEstimate:
    position_world: np.ndarray
    rotation_world: np.ndarray
    visible_marker_ids: list[int]
    reprojection_error_px: float
    method: str
    markers_used: int

    @property
    def euler_deg(self) -> tuple[float, float, float]:
        return rotation_matrix_to_euler_deg(self.rotation_world)


@dataclass(slots=True)
class TestDefinition:
    name: str
    layout: MarkerLayout
    expected_camera_position: np.ndarray
    duration_s: float = 10.0
    required_visible_markers: int = 1
    selected_marker_ids: list[int] = field(default_factory=list)
    description: str = ""


@dataclass(slots=True)
class SampleRecord:
    timestamp_s: float
    frame_index: int
    position_world: np.ndarray
    rotation_world: np.ndarray
    visible_marker_ids: list[int]
    reprojection_error_px: float
    method: str

    @property
    def visible_marker_count(self) -> int:
        return len(self.visible_marker_ids)

    @property
    def euler_deg(self) -> tuple[float, float, float]:
        return rotation_matrix_to_euler_deg(self.rotation_world)

    def to_json_dict(self, expected_position: np.ndarray | None = None) -> dict[str, Any]:
        roll, pitch, yaw = self.euler_deg
        data = {
            "timestamp_s": self.timestamp_s,
            "frame_index": self.frame_index,
            "position_world_m": self.position_world.tolist(),
            "rotation_world_euler_deg": [roll, pitch, yaw],
            "visible_marker_ids": self.visible_marker_ids,
            "visible_marker_count": self.visible_marker_count,
            "reprojection_error_px": self.reprojection_error_px,
            "method": self.method,
        }
        if expected_position is not None:
            error_vector = self.position_world - expected_position
            data["error_vector_m"] = error_vector.tolist()
            data["error_norm_m"] = float(np.linalg.norm(error_vector))
        return data
