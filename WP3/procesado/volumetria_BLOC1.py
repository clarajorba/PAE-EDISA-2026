from __future__ import annotations

import cv2
import numpy as np

MIN_VERTEXS = 4
MAX_VERTEXS = 8
MARGE_BORDE_VALIDACIO = 10


def ordenar_vertices_clockwise(vertices: list[tuple[int, int]] | np.ndarray) -> list[tuple[int, int]]:
    points = np.asarray(vertices, dtype=np.float32).reshape(-1, 2)
    if len(points) == 0:
        return []

    centroid = points.mean(axis=0)
    angles = np.arctan2(points[:, 1] - centroid[1], points[:, 0] - centroid[0])
    order = np.argsort(angles)
    ordered = points[order]

    start_idx = np.argmin(ordered[:, 0] + ordered[:, 1])
    ordered = np.roll(ordered, -start_idx, axis=0)
    return [(int(round(x)), int(round(y))) for x, y in ordered]


def refinar_vertices_desde_contorno(contorno: list[tuple[int, int]] | np.ndarray | None) -> list[tuple[int, int]] | None:
    if contorno is None:
        return None

    contour = np.asarray(contorno, dtype=np.int32).reshape(-1, 1, 2)
    if len(contour) < MIN_VERTEXS:
        return None

    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    if perimeter <= 0:
        return None

    best = None
    for factor in np.linspace(0.01, 0.08, 15):
        approx = cv2.approxPolyDP(hull, factor * perimeter, True).reshape(-1, 2)
        if MIN_VERTEXS <= len(approx) <= MAX_VERTEXS:
            best = approx
            break

    if best is None:
        approx = cv2.approxPolyDP(hull, 0.02 * perimeter, True).reshape(-1, 2)
        if len(approx) >= MIN_VERTEXS:
            best = approx

    if best is None:
        return None

    return ordenar_vertices_clockwise(best)


def vertices_tocan_borde(
    vertices: list[tuple[int, int]] | np.ndarray | None,
    frame_shape: tuple[int, ...],
    margen: int = MARGE_BORDE_VALIDACIO,
) -> bool:
    if vertices is None:
        return True

    height, width = frame_shape[:2]
    for x, y in np.asarray(vertices, dtype=int).reshape(-1, 2):
        if x <= margen or x >= (width - margen) or y <= margen or y >= (height - margen):
            return True
    return False


def detectar_qualsevol_caixa(
    ruta_o_img=None,
    mostrar_visualment: bool = False,
    bbox_objectiu=None,
    segmentador=None,
    detector=None,
    vertices_precalculados: list[tuple[int, int]] | np.ndarray | None = None,
):
    del mostrar_visualment, detector

    if vertices_precalculados is not None:
        return refinar_vertices_desde_contorno(vertices_precalculados)

    if ruta_o_img is None or bbox_objectiu is None or segmentador is None:
        return None

    image = ruta_o_img
    if isinstance(ruta_o_img, str):
        image = cv2.imread(ruta_o_img)
    if image is None:
        return None

    from segmentador_contornos import segmentar_cajas_desde_bboxes_px

    segmented = segmentar_cajas_desde_bboxes_px(
        image_bgr=image,
        bboxes_px=[tuple(map(int, bbox_objectiu))],
        sam_model=segmentador,
        scores=[1.0],
        phrases=["box"],
        run_dir=None,
        stem=None,
    )
    if not segmented:
        return None

    return refinar_vertices_desde_contorno(segmented[0]["vertices"])
