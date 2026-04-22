from __future__ import annotations

from dataclasses import dataclass

from volumetria_BLOC1 import detectar_qualsevol_caixa, vertices_tocan_borde
from volumetria_BLOC2 import extreure_ids_i_posicions, inicializar_estado_tracking
from volumetria_BLOC3_1 import LidarConfig, calcular_volumetria


@dataclass(slots=True)
class VolumetriaRuntimeConfig:
    min_frames_per_box: int = 3
    max_samples_per_box: int = 12
    sample_every_n_frames: int = 1
    marge_borde_validacio: int = 10


def inicializar_estado_volumetria(
    runtime_config: VolumetriaRuntimeConfig | None = None,
) -> dict:
    return {
        "frame_index": 0,
        "tracking": inicializar_estado_tracking(),
        "historial_vertices": {},
        "ultimo_hash_vertices": {},
        "volumenes": {},
        "runtime_config": runtime_config or VolumetriaRuntimeConfig(),
    }


def _quantized_hash(vertices: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    return tuple((int(x) // 4, int(y) // 4) for x, y in vertices)


def procesar_frame_volumetria(
    frame,
    detecciones_bloque1: list[dict],
    estado_tracking: dict,
    config_lidar: LidarConfig | None = None,
) -> dict:
    config_lidar = config_lidar or LidarConfig()
    runtime_config: VolumetriaRuntimeConfig = estado_tracking["runtime_config"]

    cajas_trakeadas = extreure_ids_i_posicions(
        detecciones_bloque1=detecciones_bloque1,
        estat_tracking=estado_tracking["tracking"],
        distancia_lidar_cm=config_lidar.distancia_lidar_cm,
    )

    for caixa in cajas_trakeadas:
        box_id = caixa["id"]
        vertices = detectar_qualsevol_caixa(
            ruta_o_img=frame,
            bbox_objectiu=caixa.get("bbox_px"),
            vertices_precalculados=caixa.get("contorno"),
        )
        caixa["vertices"] = vertices
        caixa["vertices_validos"] = False
        caixa["volumetria"] = estado_tracking["volumenes"].get(box_id)

        if vertices is None:
            continue
        if vertices_tocan_borde(vertices, frame.shape, runtime_config.marge_borde_validacio):
            continue
        if runtime_config.sample_every_n_frames > 1:
            if estado_tracking["frame_index"] % runtime_config.sample_every_n_frames != 0:
                continue

        caixa["vertices_validos"] = True
        vertex_hash = _quantized_hash(vertices)
        if estado_tracking["ultimo_hash_vertices"].get(box_id) == vertex_hash:
            continue

        historial = estado_tracking["historial_vertices"].setdefault(box_id, {})
        if len(historial) >= runtime_config.max_samples_per_box:
            continue

        sample_name = f"frame_{estado_tracking['frame_index']:06d}"
        historial[sample_name] = vertices
        estado_tracking["ultimo_hash_vertices"][box_id] = vertex_hash

        if len(historial) >= runtime_config.min_frames_per_box:
            volumetria = calcular_volumetria(
                diccionari_punts=historial,
                frame_shape=frame.shape,
                config=config_lidar,
            )
            if volumetria is not None:
                estado_tracking["volumenes"][box_id] = volumetria
                caixa["volumetria"] = volumetria

    estado_tracking["frame_index"] += 1
    return {
        "cajas_trakeadas": cajas_trakeadas,
        "volumenes": estado_tracking["volumenes"],
        "historial_vertices": estado_tracking["historial_vertices"],
    }
