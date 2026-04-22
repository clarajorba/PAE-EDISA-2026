from __future__ import annotations

import math
import statistics
from dataclasses import dataclass


@dataclass(slots=True)
class LidarConfig:
    distancia_lidar_cm: float = 150.0
    distancia_focal_px: float = 2976.74
    correccio_perspectiva_z: float = 1.0


def es_rectangle_frontal(punts: list[tuple[int, int]], tolerancia_graus: float = 20.0) -> bool:
    if len(punts) != 4:
        return False

    angles = []
    for index in range(4):
        p1 = punts[index - 1]
        p2 = punts[index]
        p3 = punts[(index + 1) % 4]

        v1 = (p1[0] - p2[0], p1[1] - p2[1])
        v2 = (p3[0] - p2[0], p3[1] - p2[1])

        dot = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.hypot(v1[0], v1[1])
        mag2 = math.hypot(v2[0], v2[1])
        if mag1 == 0 or mag2 == 0:
            return False

        cos_theta = max(-1.0, min(1.0, dot / (mag1 * mag2)))
        angles.append(math.degrees(math.acos(cos_theta)))

    return all(abs(angle - 90.0) <= tolerancia_graus for angle in angles)


def calcular_volumetria(
    diccionari_punts: dict[str, list[tuple[int, int]]],
    frame_shape: tuple[int, ...],
    config: LidarConfig | None = None,
) -> dict | None:
    if not diccionari_punts:
        return None

    config = config or LidarConfig()
    ample_img = frame_shape[1]
    centre_x = ample_img / 2.0

    resultats_amplada_frontal: list[float] = []
    resultats_alcada_frontal: list[float] = []
    resultats_amplada_persp: list[float] = []
    resultats_alcada_persp: list[float] = []
    resultats_profunditat_persp: list[float] = []
    samples_frontals: list[str] = []
    samples_perspectiva: list[str] = []

    for sample_name, punts in diccionari_punts.items():
        if len(punts) < 4:
            continue

        x_coords = [point[0] for point in punts]
        y_coords = [point[1] for point in punts]

        x_left, x_right = min(x_coords), max(x_coords)
        y_top, y_bottom = min(y_coords), max(y_coords)

        if len(punts) == 4 and es_rectangle_frontal(punts):
            w_px = x_right - x_left
            h_px = y_bottom - y_top
            amplada_cm = (w_px * config.distancia_lidar_cm) / config.distancia_focal_px
            alcada_cm = (h_px * config.distancia_lidar_cm) / config.distancia_focal_px
            resultats_amplada_frontal.append(amplada_cm)
            resultats_alcada_frontal.append(alcada_cm)
            samples_frontals.append(sample_name)
            continue

        if len(punts) >= 5:
            p_bottom = punts[y_coords.index(y_bottom)]
            x_center_edge = float(p_bottom[0])

            width_face_1_px = abs(x_center_edge - x_left)
            width_face_2_px = abs(x_right - x_center_edge)
            box_height_px = abs(y_bottom - y_top)

            if width_face_1_px < width_face_2_px:
                amplada_px = width_face_2_px
                u_front = abs(x_center_edge - centre_x)
                u_back = abs(x_left - centre_x)
            else:
                amplada_px = width_face_1_px
                u_front = abs(x_center_edge - centre_x)
                u_back = abs(x_right - centre_x)

            if u_back >= u_front:
                continue

            u_back = max(u_back, 1.0)
            amplada_cm = (amplada_px * config.distancia_lidar_cm) / config.distancia_focal_px
            alcada_cm = (box_height_px * config.distancia_lidar_cm) / config.distancia_focal_px
            profunditat_cm = config.distancia_lidar_cm * ((u_front / u_back) - 1.0)
            profunditat_cm *= config.correccio_perspectiva_z

            resultats_amplada_persp.append(amplada_cm)
            resultats_alcada_persp.append(alcada_cm)
            resultats_profunditat_persp.append(profunditat_cm)
            samples_perspectiva.append(sample_name)

    if not resultats_profunditat_persp:
        return None

    if resultats_amplada_frontal:
        amp_final = statistics.median(resultats_amplada_frontal)
        alc_final = statistics.median(resultats_alcada_frontal)
        mode_xy = "frontal"
    else:
        amp_final = statistics.median(resultats_amplada_persp)
        alc_final = statistics.median(resultats_alcada_persp)
        mode_xy = "perspectiva"

    prof_final = statistics.median(resultats_profunditat_persp)
    volum_final = amp_final * prof_final * alc_final

    return {
        "amplada_cm": amp_final,
        "alcada_cm": alc_final,
        "profunditat_cm": prof_final,
        "volum_cm3": volum_final,
        "mode_xy": mode_xy,
        "num_frontals": len(resultats_amplada_frontal),
        "num_perspectiva": len(resultats_profunditat_persp),
        "samples_frontals": samples_frontals,
        "samples_perspectiva": samples_perspectiva,
    }
