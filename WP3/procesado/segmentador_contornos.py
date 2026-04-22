from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path

SAM_WEIGHTS = "mobile_sam.pt"
POLY_MIN_VERTICES = 4
POLY_MAX_VERTICES = 8
CLAHE_CLIP_LIMIT = 2.0
CLAHE_GRID_SIZE = (8, 8)


def cargar_segmentador(weights_path: str = SAM_WEIGHTS):
    from ultralytics import SAM

    return SAM(weights_path)


def _norm_to_px(boxes_norm: np.ndarray, img_h: int, img_w: int) -> np.ndarray:
    cx, cy, w, h = (
        boxes_norm[:, 0],
        boxes_norm[:, 1],
        boxes_norm[:, 2],
        boxes_norm[:, 3],
    )
    x1 = np.clip((cx - w / 2) * img_w, 0, img_w).astype(int)
    y1 = np.clip((cy - h / 2) * img_h, 0, img_h).astype(int)
    x2 = np.clip((cx + w / 2) * img_w, 0, img_w).astype(int)
    y2 = np.clip((cy + h / 2) * img_h, 0, img_h).astype(int)
    return np.stack([x1, y1, x2, y2], axis=1)


def aplicar_clahe_roi(image_bgr: np.ndarray, bbox_px: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = bbox_px
    if x2 <= x1 or y2 <= y1:
        return image_bgr

    roi = image_bgr[y1:y2, x1:x2].copy()
    if roi.size == 0:
        return image_bgr

    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    l_channel, a_channel, b_channel = cv2.split(lab)
    clahe = cv2.createCLAHE(
        clipLimit=CLAHE_CLIP_LIMIT,
        tileGridSize=CLAHE_GRID_SIZE,
    )
    l_equalized = clahe.apply(l_channel)
    roi_enhanced = cv2.cvtColor(
        cv2.merge((l_equalized, a_channel, b_channel)),
        cv2.COLOR_LAB2BGR,
    )

    enhanced = image_bgr.copy()
    enhanced[y1:y2, x1:x2] = roi_enhanced
    return enhanced


def _mask_to_polygon_geometric(mask: np.ndarray) -> np.ndarray | None:
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    if cv2.contourArea(contour) <= 0:
        return None

    rect = cv2.minAreaRect(contour)
    box_points = cv2.boxPoints(rect).astype(np.int32)

    mask_rect = np.zeros_like(mask)
    cv2.drawContours(mask_rect, [box_points], 0, 255, -1)

    intersection = cv2.bitwise_and(mask, mask_rect)
    area_sam = cv2.countNonZero(mask)
    area_rect = cv2.countNonZero(mask_rect)
    area_intersection = cv2.countNonZero(intersection)

    if area_rect > 0:
        union = float(area_rect + area_sam - area_intersection)
        iou = (area_intersection / union) if union > 0 else 0.0
        if iou > 0.85:
            return box_points.reshape(-1, 2)

    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    if perimeter <= 0:
        return None

    polygon = cv2.approxPolyDP(hull, 0.04 * perimeter, True)
    if POLY_MIN_VERTICES <= len(polygon) <= POLY_MAX_VERTICES:
        return polygon.reshape(-1, 2)

    polygon = cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True)
    polygon = polygon.reshape(-1, 2)
    if len(polygon) < POLY_MIN_VERTICES:
        return None
    return polygon


def _extract_mask(results) -> np.ndarray | None:
    if not results:
        return None

    mask_data = getattr(results[0], "masks", None)
    if mask_data is None:
        return None

    data = getattr(mask_data, "data", None)
    if data is None or len(data) == 0:
        return None

    mask = (data[0].cpu().numpy() > 0.5).astype(np.uint8) * 255
    return mask


def segmentar_cajas_desde_bboxes_px(
    image_bgr: np.ndarray,
    bboxes_px: list[tuple[int, int, int, int]] | np.ndarray,
    sam_model,
    scores: list[float] | np.ndarray | None = None,
    phrases: list[str] | None = None,
    run_dir: Path | None = None,
    stem: str | None = None,
) -> list[dict]:
    if bboxes_px is None or len(bboxes_px) == 0:
        return []

    boxes_array = np.asarray(bboxes_px, dtype=int)
    scores = np.asarray(scores if scores is not None else np.ones(len(boxes_array)), dtype=float)
    phrases = list(phrases if phrases is not None else ["box"] * len(boxes_array))

    debug_img = image_bgr.copy()
    results_out: list[dict] = []

    n_boxes = len(boxes_array)
    colors = [
        tuple(
            int(value)
            for value in cv2.cvtColor(
                np.uint8([[[int(index * 180 / max(1, n_boxes)), 220, 220]]]),
                cv2.COLOR_HSV2BGR,
            )[0][0]
        )
        for index in range(n_boxes)
    ]

    for index, bbox_px in enumerate(boxes_array):
        x1, y1, x2, y2 = map(int, bbox_px)
        if x2 <= x1 or y2 <= y1:
            continue

        enhanced = aplicar_clahe_roi(image_bgr, (x1, y1, x2, y2))

        try:
            results = sam_model(enhanced, bboxes=[[x1, y1, x2, y2]], verbose=False)
        except Exception:
            continue

        mask = _extract_mask(results)
        if mask is None:
            continue

        vertices = _mask_to_polygon_geometric(mask)
        if vertices is None:
            continue

        results_out.append(
            {
                "idx": index,
                "phrase": phrases[index],
                "score": float(scores[index]),
                "vertices": vertices,
                "bbox_px": (x1, y1, x2, y2),
            }
        )

        if run_dir is None or stem is None:
            continue

        color = colors[index]
        overlay = debug_img.copy()
        color_layer = np.zeros_like(debug_img)
        color_layer[mask > 0] = color
        cv2.addWeighted(overlay, 0.55, color_layer, 0.45, 0, debug_img)
        debug_img[mask == 0] = overlay[mask == 0]

        pts = vertices.reshape((-1, 1, 2))
        cv2.polylines(debug_img, [pts], isClosed=True, color=color, thickness=2)

        label = f"[{index + 1}] {phrases[index]} {float(scores[index]):.2f}"
        cv2.putText(
            debug_img,
            label,
            (x1, max(y1 - 8, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 0, 0),
            3,
        )
        cv2.putText(
            debug_img,
            label,
            (x1, max(y1 - 8, 12)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            color,
            1,
        )

    if run_dir is not None and stem is not None:
        run_dir.mkdir(parents=True, exist_ok=True)
        cv2.imwrite(str(run_dir / f"{stem}_8_contornos.jpg"), debug_img)

    return results_out


def segmentar_cajas(
    image_bgr: np.ndarray,
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    sam_model,
    run_dir: Path | None = None,
    stem: str | None = None,
) -> list[dict]:
    if boxes is None or len(boxes) == 0:
        return []

    img_h, img_w = image_bgr.shape[:2]
    bboxes_px = _norm_to_px(boxes, img_h, img_w)
    return segmentar_cajas_desde_bboxes_px(
        image_bgr=image_bgr,
        bboxes_px=bboxes_px,
        sam_model=sam_model,
        scores=logits,
        phrases=phrases,
        run_dir=run_dir,
        stem=stem,
    )


def imprimir_vertices(resultados: list[dict]) -> None:
    for result in resultados:
        header = (
            f"Caja [{result['idx'] + 1}] "
            f"{result['phrase']} "
            f"(score={result['score']:.3f})"
        )
        print(header)
        for vertex_index, (vx, vy) in enumerate(result["vertices"], start=1):
            print(f"  v{vertex_index}: ({int(vx)}, {int(vy)})")
