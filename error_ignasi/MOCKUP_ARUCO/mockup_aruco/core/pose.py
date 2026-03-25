from __future__ import annotations

from collections import Counter

import cv2
import numpy as np

from .aruco import reprojection_rms
from .models import (
    CalibrationData,
    CameraPoseEstimate,
    MarkerDefinition,
    MarkerDetection,
    MarkerLayout,
    rotation_matrix_z,
)


def filter_detections(
    layout: MarkerLayout,
    detections: list[MarkerDetection],
    selected_marker_ids: list[int] | None = None,
) -> list[MarkerDetection]:
    """Filtra solo marcadores conocidos y opcionalmente seleccionados."""
    allowed = set(selected_marker_ids or layout.ids)
    return [
        detection
        for detection in detections
        if detection.marker_id in allowed and detection.has_pose and layout.get_marker(detection.marker_id)
    ]


def camera_pose_from_single_marker(
    marker: MarkerDefinition,
    detection: MarkerDetection,
) -> CameraPoseEstimate | None:
    """Invierte la transformacion marcador-camara para obtener la pose global."""
    if not detection.has_pose:
        return None

    rotation_camera_from_marker, _ = cv2.Rodrigues(detection.rvec)
    translation_camera_from_marker = detection.tvec.reshape(3)

    rotation_marker_from_camera = rotation_camera_from_marker.T
    translation_marker_from_camera = (
        -rotation_marker_from_camera @ translation_camera_from_marker
    )

    marker_rotation_world = rotation_matrix_z(marker.yaw_deg)
    camera_rotation_world = marker_rotation_world @ rotation_marker_from_camera
    camera_position_world = (
        marker_rotation_world @ translation_marker_from_camera + marker.position
    )

    return CameraPoseEstimate(
        position_world=camera_position_world,
        rotation_world=camera_rotation_world,
        visible_marker_ids=[detection.marker_id],
        reprojection_error_px=float(detection.reprojection_error_px or 0.0),
        method="single_marker",
        markers_used=1,
    )


def estimate_weighted_pose(
    layout: MarkerLayout,
    detections: list[MarkerDetection],
    selected_marker_ids: list[int] | None = None,
    required_markers: int = 1,
) -> CameraPoseEstimate | None:
    """Combina estimaciones individuales con pesos segun error de reproyeccion."""
    known = filter_detections(layout, detections, selected_marker_ids)
    if len(known) < required_markers:
        return None

    single_estimates: list[CameraPoseEstimate] = []
    for detection in known:
        marker = layout.get_marker(detection.marker_id)
        if marker is None:
            continue
        estimate = camera_pose_from_single_marker(marker, detection)
        if estimate is not None:
            single_estimates.append(estimate)

    if len(single_estimates) < required_markers:
        return None

    reproj = np.asarray(
        [max(estimate.reprojection_error_px, 0.05) for estimate in single_estimates],
        dtype=np.float64,
    )
    weights = 1.0 / np.square(reproj)
    weights /= weights.sum()

    positions = np.vstack([estimate.position_world for estimate in single_estimates])
    position_world = np.average(positions, axis=0, weights=weights)

    best_index = int(np.argmin(reproj))
    best_rotation = single_estimates[best_index].rotation_world
    visible_ids = [estimate.visible_marker_ids[0] for estimate in single_estimates]
    weighted_error = float(np.average(reproj, weights=weights))

    return CameraPoseEstimate(
        position_world=position_world,
        rotation_world=best_rotation,
        visible_marker_ids=visible_ids,
        reprojection_error_px=weighted_error,
        method="weighted_single",
        markers_used=len(single_estimates),
    )


def estimate_multi_marker_pose(
    layout: MarkerLayout,
    detections: list[MarkerDetection],
    calibration: CalibrationData,
    selected_marker_ids: list[int] | None = None,
    required_markers: int = 2,
) -> CameraPoseEstimate | None:
    """Resuelve la pose global con todos los marcadores visibles mediante PnP."""
    known = filter_detections(layout, detections, selected_marker_ids)
    if len(known) < required_markers:
        return None

    object_points: list[np.ndarray] = []
    image_points: list[np.ndarray] = []
    visible_ids: list[int] = []

    for detection in known:
        object_points.append(layout.world_corners(detection.marker_id))
        image_points.append(detection.corners)
        visible_ids.append(detection.marker_id)

    object_points_np = np.vstack(object_points).astype(np.float32)
    image_points_np = np.vstack(image_points).astype(np.float32)

    success, rvec, tvec, _ = cv2.solvePnPRansac(
        object_points_np,
        image_points_np,
        calibration.camera_matrix,
        calibration.dist_coeffs,
        iterationsCount=200,
        reprojectionError=3.5,
        confidence=0.999,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not success:
        return estimate_weighted_pose(
            layout=layout,
            detections=known,
            selected_marker_ids=selected_marker_ids,
            required_markers=required_markers,
        )

    try:
        rvec, tvec = cv2.solvePnPRefineLM(
            object_points_np,
            image_points_np,
            calibration.camera_matrix,
            calibration.dist_coeffs,
            rvec,
            tvec,
        )
    except cv2.error:
        pass

    rotation_camera_from_world, _ = cv2.Rodrigues(rvec)
    rotation_world_from_camera = rotation_camera_from_world.T
    position_world = -rotation_world_from_camera @ tvec.reshape(3)
    reprojection_error = reprojection_rms(
        object_points_np,
        image_points_np,
        rvec,
        tvec,
        calibration,
    )

    return CameraPoseEstimate(
        position_world=position_world,
        rotation_world=rotation_world_from_camera,
        visible_marker_ids=visible_ids,
        reprojection_error_px=reprojection_error,
        method="multi_pnp",
        markers_used=len(visible_ids),
    )


def estimate_best_pose(
    layout: MarkerLayout,
    detections: list[MarkerDetection],
    calibration: CalibrationData,
    selected_marker_ids: list[int] | None = None,
    required_markers: int = 1,
) -> CameraPoseEstimate | None:
    """Prefiere PnP global cuando hay suficientes marcadores y usa fusion si no."""
    multi_threshold = max(2, required_markers)
    estimate = estimate_multi_marker_pose(
        layout=layout,
        detections=detections,
        calibration=calibration,
        selected_marker_ids=selected_marker_ids,
        required_markers=multi_threshold,
    )
    if estimate is not None:
        return estimate

    return estimate_weighted_pose(
        layout=layout,
        detections=detections,
        selected_marker_ids=selected_marker_ids,
        required_markers=required_markers,
    )


def count_methods(samples: list[CameraPoseEstimate]) -> dict[str, int]:
    """Pequena utilidad para diagnostico."""
    return dict(Counter(sample.method for sample in samples))
