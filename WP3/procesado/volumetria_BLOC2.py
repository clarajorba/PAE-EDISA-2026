from __future__ import annotations

import math

import cv2
import numpy as np

DISTANCIA_REF_CM = 150.0
TRACKING_REF_PX = 400.0
MAX_FRAMES_MISSING = 2


def inicializar_estado_tracking(max_frames_missing: int = MAX_FRAMES_MISSING) -> dict:
    return {
        "next_id": 1,
        "active": {},
        "max_frames_missing": max_frames_missing,
    }


def obtenir_color_estable(box_id: int) -> tuple[int, int, int]:
    return (
        50 + (37 * box_id) % 205,
        50 + (73 * box_id) % 205,
        50 + (109 * box_id) % 205,
    )


def _centroide_de_deteccion(detection: dict) -> tuple[int, int]:
    contour = detection.get("contorno")
    if contour is not None and len(contour) >= 3:
        contour_np = np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2)
        moments = cv2.moments(contour_np)
        if moments["m00"] != 0:
            return (
                int(moments["m10"] / moments["m00"]),
                int(moments["m01"] / moments["m00"]),
            )

    x1, y1, x2, y2 = map(int, detection["bbox_px"])
    return int((x1 + x2) / 2), int((y1 + y2) / 2)


def tracking_robust_amb_memoria(
    deteccions_actuals: list[dict],
    estat_tracking: dict,
    distancia_lidar_cm: float,
) -> list[dict]:
    if estat_tracking is None:
        estat_tracking = inicializar_estado_tracking()

    active = estat_tracking["active"]
    next_id = estat_tracking["next_id"]
    max_frames_missing = estat_tracking["max_frames_missing"]
    tracking_radius = TRACKING_REF_PX * (
        DISTANCIA_REF_CM / max(distancia_lidar_cm, 1e-6)
    )

    matched_prev_ids: set[int] = set()
    enriched: list[dict] = []

    for detection in deteccions_actuals:
        cx, cy = _centroide_de_deteccion(detection)
        best_id = None
        best_distance = float("inf")

        for candidate_id, info in active.items():
            if candidate_id in matched_prev_ids:
                continue

            old_cx, old_cy = info["centroide"]
            distance = math.hypot(cx - old_cx, cy - old_cy)
            if distance < best_distance and distance < tracking_radius:
                best_distance = distance
                best_id = candidate_id

        if best_id is None:
            best_id = next_id
            next_id += 1
            active[best_id] = {
                "centroide": (cx, cy),
                "misses": 0,
                "color": obtenir_color_estable(best_id),
            }
        else:
            active[best_id]["centroide"] = (cx, cy)
            active[best_id]["misses"] = 0

        matched_prev_ids.add(best_id)
        enriched.append(
            {
                **detection,
                "id": best_id,
                "cx": cx,
                "cy": cy,
                "color": active[best_id]["color"],
            }
        )

    ids_to_remove = []
    for candidate_id, info in active.items():
        if candidate_id not in matched_prev_ids:
            info["misses"] += 1
            if info["misses"] > max_frames_missing:
                ids_to_remove.append(candidate_id)

    for candidate_id in ids_to_remove:
        del active[candidate_id]

    estat_tracking["next_id"] = next_id
    return enriched


def extreure_ids_i_posicions(
    deteccions_bloque1: list[dict],
    estat_tracking: dict,
    distancia_lidar_cm: float,
) -> list[dict]:
    return tracking_robust_amb_memoria(
        deteccions_actuals=deteccions_bloque1,
        estat_tracking=estat_tracking,
        distancia_lidar_cm=distancia_lidar_cm,
    )
