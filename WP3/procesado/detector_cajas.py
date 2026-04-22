from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import torch

from segmentador_contornos import segmentar_cajas, segmentar_cajas_desde_bboxes_px

TEXT_PROMPT = (
    "cardboard box . box . carton . stacked cardboard box . "
    "warehouse package . pallet ."
)

PALLET_KEYWORDS = {"pallet"}


@dataclass(slots=True)
class DetectorConfig:
    gdino_config_path: str = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
    gdino_weights_path: str = "weights/groundingdino_swint_ogc.pth"
    yolo_weights_path: str = "yolov8s-world.pt"
    text_prompt: str = TEXT_PROMPT
    box_threshold: float = 0.19
    text_threshold: float = 0.3
    iou_threshold: float = 0.7
    containment_threshold: float = 0.5
    center_dist_threshold: float = 0.05
    min_box_size: float = 0.06
    max_box_aspect_ratio: float = 2.2
    pallet_min_aspect_ratio: float = 2.5
    beam_hsv_low: tuple[int, int, int] = (8, 150, 120)
    beam_hsv_high: tuple[int, int, int] = (18, 255, 255)
    beam_row_threshold: float = 0.25
    beam_min_height_px: int = 10
    beam_pallet_ratio: float = 0.18
    process_width: int | None = 960
    frame_skip_detection: int = 5


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def _to_corners_batch(boxes: np.ndarray) -> np.ndarray:
    cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    return np.stack([cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2], axis=1)


def _iou_matrix(corners: np.ndarray) -> np.ndarray:
    x1 = np.maximum(corners[:, None, 0], corners[None, :, 0])
    y1 = np.maximum(corners[:, None, 1], corners[None, :, 1])
    x2 = np.minimum(corners[:, None, 2], corners[None, :, 2])
    y2 = np.minimum(corners[:, None, 3], corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    areas = (corners[:, 2] - corners[:, 0]) * (corners[:, 3] - corners[:, 1])
    union = areas[:, None] + areas[None, :] - inter
    return np.where(union > 0, inter / union, 0.0)


def _corners_to_bbox_px(corners: np.ndarray, img_h: int, img_w: int) -> np.ndarray:
    bbox_px = np.zeros_like(corners, dtype=int)
    bbox_px[:, 0] = np.clip(corners[:, 0] * img_w, 0, img_w).astype(int)
    bbox_px[:, 1] = np.clip(corners[:, 1] * img_h, 0, img_h).astype(int)
    bbox_px[:, 2] = np.clip(corners[:, 2] * img_w, 0, img_w).astype(int)
    bbox_px[:, 3] = np.clip(corners[:, 3] * img_h, 0, img_h).astype(int)
    return bbox_px


def detect_orange_beams(image_bgr: np.ndarray, config: DetectorConfig) -> tuple[list[tuple[int, int, int, int]], np.ndarray, np.ndarray]:
    h, w = image_bgr.shape[:2]
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    lower = np.array(config.beam_hsv_low, dtype=np.uint8)
    upper = np.array(config.beam_hsv_high, dtype=np.uint8)
    mask = cv2.inRange(hsv, lower, upper)

    projection = np.sum(mask > 0, axis=1)
    threshold_px = w * config.beam_row_threshold
    is_beam_row = projection >= threshold_px

    beams = []
    in_beam = False
    start_y = 0
    for y in range(h):
        if is_beam_row[y] and not in_beam:
            in_beam = True
            start_y = y
        elif not is_beam_row[y] and in_beam:
            in_beam = False
            if (y - start_y) >= config.beam_min_height_px:
                beams.append((start_y, y, 0, w))

    if in_beam and (h - start_y) >= config.beam_min_height_px:
        beams.append((start_y, h, 0, w))

    return beams, mask, projection


def get_valid_zones(beams: list[tuple[int, int, int, int]], img_height: int, config: DetectorConfig) -> list[tuple[int, int]] | None:
    if not beams:
        return None

    zones: list[tuple[int, int]] = []
    if len(beams) == 1:
        beam_top = beams[0][0]
        pallet_margin = int(beam_top * config.beam_pallet_ratio)
        y_min, y_max = 0, beam_top - pallet_margin
        if y_max > y_min:
            zones.append((y_min, y_max))
        return zones or None

    for index in range(len(beams) - 1):
        y_upper = beams[index][1]
        y_lower = beams[index + 1][0]
        level_height = y_lower - y_upper
        pallet_margin = int(level_height * config.beam_pallet_ratio)
        y_min, y_max = y_upper, y_lower - pallet_margin
        if y_max > y_min:
            zones.append((y_min, y_max))

    first_beam = beams[0]
    if first_beam[0] > 50:
        pallet_margin = int(first_beam[0] * config.beam_pallet_ratio)
        y_min, y_max = 0, first_beam[0] - pallet_margin
        if y_max > y_min:
            zones.insert(0, (y_min, y_max))

    return zones or None


def split_boxes_pallets(boxes: np.ndarray, logits: np.ndarray, phrases: list[str]) -> tuple[np.ndarray, np.ndarray]:
    pallet_mask = np.array(
        [any(keyword in phrase.lower() for keyword in PALLET_KEYWORDS) for phrase in phrases]
    )
    return np.where(~pallet_mask)[0], np.where(pallet_mask)[0]


def apply_beam_zone_filter(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    valid_zones: list[tuple[int, int]] | None,
    img_height: int,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if valid_zones is None or len(boxes) == 0:
        return boxes, logits, phrases

    cy = boxes[:, 1]
    keep = np.zeros(len(boxes), dtype=bool)
    for y_min, y_max in valid_zones:
        keep |= (cy >= y_min / img_height) & (cy <= y_max / img_height)

    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[index] for index in kept_idx]


def apply_min_size_filter(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    min_size: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if len(boxes) == 0 or min_size == 0.0:
        return boxes, logits, phrases

    keep = (boxes[:, 2] >= min_size) & (boxes[:, 3] >= min_size)
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[index] for index in kept_idx]


def apply_aspect_ratio_filter(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    max_ratio: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if len(boxes) == 0 or max_ratio == 0.0:
        return boxes, logits, phrases

    w = boxes[:, 2]
    h = boxes[:, 3]
    aspect = np.maximum(w, h) / np.clip(np.minimum(w, h), 1e-6, None)
    keep = aspect <= max_ratio
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[index] for index in kept_idx]


def apply_containment_filter(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    threshold: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if len(boxes) == 0 or threshold == 0.0:
        return boxes, logits, phrases

    corners = _to_corners_batch(boxes)
    areas = (corners[:, 2] - corners[:, 0]) * (corners[:, 3] - corners[:, 1])
    x1 = np.maximum(corners[:, None, 0], corners[None, :, 0])
    y1 = np.maximum(corners[:, None, 1], corners[None, :, 1])
    x2 = np.minimum(corners[:, None, 2], corners[None, :, 2])
    y2 = np.minimum(corners[:, None, 3], corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    containment = np.where(areas[:, None] > 0, inter / areas[:, None], 0.0)

    is_group = np.zeros(len(boxes), dtype=bool)
    for candidate in range(len(boxes)):
        smaller = areas < areas[candidate]
        if np.any(smaller & (containment[:, candidate] >= threshold)):
            is_group[candidate] = True

    kept_idx = np.where(~is_group)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[index] for index in kept_idx]


def apply_center_distance_filter(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    dist_threshold: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if len(boxes) == 0 or dist_threshold == 0.0:
        return boxes, logits, phrases

    order = np.argsort(logits)[::-1]
    active = np.ones(len(boxes), dtype=bool)
    kept = []

    for index in order:
        if not active[index]:
            continue
        kept.append(index)
        active_idx = np.where(active)[0]
        dists = np.sqrt(
            (boxes[active_idx, 0] - boxes[index, 0]) ** 2
            + (boxes[active_idx, 1] - boxes[index, 1]) ** 2
        )
        too_close = active_idx[dists < dist_threshold]
        too_close = too_close[too_close != index]
        active[too_close] = False

    kept_idx = sorted(kept)
    return boxes[kept_idx], logits[kept_idx], [phrases[index] for index in kept_idx]


def apply_nms(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    iou_threshold: float,
) -> tuple[np.ndarray, np.ndarray, list[str]]:
    if len(boxes) == 0:
        return boxes, logits, phrases

    corners = _to_corners_batch(boxes)
    iou = _iou_matrix(corners)
    order = np.argsort(logits)[::-1]
    kept = []

    while len(order) > 0:
        best = order[0]
        kept.append(best)
        rest = order[1:]
        order = rest[iou[best, rest] < iou_threshold]

    kept_idx = sorted(kept)
    return boxes[kept_idx], logits[kept_idx], [phrases[index] for index in kept_idx]


def apply_pallet_filter(
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    box_idx: np.ndarray,
    pallet_idx: np.ndarray,
    containment_threshold: float,
    pallet_min_aspect_ratio: float,
) -> tuple[np.ndarray, np.ndarray]:
    del logits, phrases
    if len(pallet_idx) == 0:
        return box_idx, pallet_idx

    pw = boxes[pallet_idx, 2]
    ph = boxes[pallet_idx, 3]
    aspect = np.maximum(pw, ph) / np.clip(np.minimum(pw, ph), 1e-6, None)
    empty_pallet = aspect >= pallet_min_aspect_ratio
    surviving_pallets = pallet_idx[~empty_pallet]

    if len(surviving_pallets) == 0 or len(box_idx) == 0:
        return box_idx, surviving_pallets

    box_corners = _to_corners_batch(boxes[box_idx])
    pallet_corners = _to_corners_batch(boxes[surviving_pallets])
    x1 = np.maximum(box_corners[:, None, 0], pallet_corners[None, :, 0])
    y1 = np.maximum(box_corners[:, None, 1], pallet_corners[None, :, 1])
    x2 = np.minimum(box_corners[:, None, 2], pallet_corners[None, :, 2])
    y2 = np.minimum(box_corners[:, None, 3], pallet_corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    box_areas = (box_corners[:, 2] - box_corners[:, 0]) * (box_corners[:, 3] - box_corners[:, 1])
    containment = np.where(box_areas[:, None] > 0, inter / box_areas[:, None], 0.0)
    has_boxes = np.any(containment >= containment_threshold, axis=0)
    return box_idx, surviving_pallets[~has_boxes]


def _resize_for_detector(frame_bgr: np.ndarray, process_width: int | None) -> tuple[np.ndarray, float]:
    if process_width is None:
        return frame_bgr, 1.0

    height, width = frame_bgr.shape[:2]
    if width <= process_width:
        return frame_bgr, 1.0

    scale = process_width / float(width)
    resized = cv2.resize(frame_bgr, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    return resized, scale


def cargar_modelo_detector(config: DetectorConfig | None = None) -> dict:
    config = config or DetectorConfig()
    base_dir = Path(__file__).resolve().parent
    device = "cuda" if torch.cuda.is_available() else "cpu"
    gdino_config = _resolve_path(base_dir, config.gdino_config_path)
    gdino_weights = _resolve_path(base_dir, config.gdino_weights_path)
    yolo_weights = _resolve_path(base_dir, config.yolo_weights_path)

    if str(base_dir) not in sys.path:
        sys.path.insert(0, str(base_dir))

    if gdino_config.exists() and gdino_weights.exists():
        try:
            from groundingdino.util.inference import load_model

            model = load_model(str(gdino_config), str(gdino_weights)).to(device)
            model.eval()
            return {
                "backend": "groundingdino",
                "model": model,
                "device": device,
                "warning": None,
            }
        except Exception as exc:
            warning = f"GroundingDINO no disponible, activado fallback YOLO: {exc}"
    else:
        warning = (
            "GroundingDINO no disponible, activado fallback YOLO: "
            f"faltan {gdino_config.name} o {gdino_weights.name}"
        )

    from ultralytics import YOLO

    yolo_model = YOLO(str(yolo_weights))
    try:
        yolo_model.set_classes(["box", "pallet"])
    except Exception:
        pass

    return {
        "backend": "yolo",
        "model": yolo_model,
        "device": device,
        "warning": warning,
    }


def _predict_with_groundingdino(
    model_ctx: dict,
    frame_bgr: np.ndarray,
    config: DetectorConfig,
) -> tuple[np.ndarray, np.ndarray, list[str], dict]:
    from groundingdino.util.inference import predict

    proc_frame, scale = _resize_for_detector(frame_bgr, config.process_width)
    frame_rgb = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2RGB)
    image = torch.from_numpy(frame_rgb).permute(2, 0, 1).float() / 255.0

    with torch.no_grad():
        raw_boxes, raw_logits, raw_phrases = predict(
            model=model_ctx["model"],
            image=image,
            caption=config.text_prompt,
            box_threshold=config.box_threshold,
            text_threshold=config.text_threshold,
            device=model_ctx["device"],
        )

    return (
        raw_boxes.cpu().numpy() if hasattr(raw_boxes, "cpu") else np.asarray(raw_boxes),
        raw_logits.cpu().numpy() if hasattr(raw_logits, "cpu") else np.asarray(raw_logits),
        list(raw_phrases),
        {
            "scale": scale,
            "processed_shape": proc_frame.shape[:2],
        },
    )


def _predict_with_yolo(
    model_ctx: dict,
    frame_bgr: np.ndarray,
    config: DetectorConfig,
) -> tuple[np.ndarray, np.ndarray, list[str], dict]:
    proc_frame, scale = _resize_for_detector(frame_bgr, config.process_width)
    results = model_ctx["model"].predict(proc_frame, conf=config.box_threshold, verbose=False)
    if not results or results[0].boxes is None or len(results[0].boxes) == 0:
        return np.empty((0, 4), dtype=float), np.empty((0,), dtype=float), [], {
            "scale": scale,
            "processed_shape": proc_frame.shape[:2],
        }

    proc_h, proc_w = proc_frame.shape[:2]
    xyxy = results[0].boxes.xyxy.cpu().numpy()
    conf = results[0].boxes.conf.cpu().numpy()
    cls = results[0].boxes.cls.cpu().numpy().astype(int)
    names = getattr(results[0], "names", {}) or getattr(model_ctx["model"], "names", {})

    boxes = np.zeros((len(xyxy), 4), dtype=float)
    phrases: list[str] = []
    for index, (x1, y1, x2, y2) in enumerate(xyxy):
        width = max(0.0, x2 - x1)
        height = max(0.0, y2 - y1)
        boxes[index] = np.array(
            [
                ((x1 + x2) / 2.0) / proc_w,
                ((y1 + y2) / 2.0) / proc_h,
                width / proc_w,
                height / proc_h,
            ],
            dtype=float,
        )
        phrases.append(str(names.get(int(cls[index]), "box")))

    return boxes, conf.astype(float), phrases, {
        "scale": scale,
        "processed_shape": proc_frame.shape[:2],
    }


def _predict_boxes(
    model_ctx: dict,
    frame_bgr: np.ndarray,
    config: DetectorConfig,
) -> tuple[np.ndarray, np.ndarray, list[str], dict]:
    if model_ctx["backend"] == "groundingdino":
        return _predict_with_groundingdino(model_ctx, frame_bgr, config)
    return _predict_with_yolo(model_ctx, frame_bgr, config)


def _build_detection_dicts(
    frame_bgr: np.ndarray,
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    segmented: list[dict],
    backend: str,
) -> list[dict]:
    img_h, img_w = frame_bgr.shape[:2]
    corners = _to_corners_batch(boxes)
    bbox_px = _corners_to_bbox_px(corners, img_h, img_w)
    segmented_by_idx = {item["idx"]: item for item in segmented}

    detections: list[dict] = []
    for index, (bbox_norm, bbox_pixels, score, phrase) in enumerate(
        zip(corners, bbox_px, logits, phrases)
    ):
        segmentation = segmented_by_idx.get(index)
        detections.append(
            {
                "bbox": [float(value) for value in bbox_norm.tolist()],
                "score": float(score),
                "contorno": None if segmentation is None else np.asarray(segmentation["vertices"], dtype=np.int32),
                "bbox_px": [int(value) for value in bbox_pixels.tolist()],
                "label": phrase,
                "backend": backend,
            }
        )

    return detections


def procesar_frame_detector(
    frame_bgr: np.ndarray,
    modelo_detector: dict,
    segmentador_sam,
    config: DetectorConfig | None = None,
) -> tuple[list[dict], dict]:
    config = config or DetectorConfig()
    boxes, logits, phrases, infer_info = _predict_boxes(modelo_detector, frame_bgr, config)

    proc_h, _ = infer_info["processed_shape"]
    beams, _, _ = detect_orange_beams(
        cv2.resize(frame_bgr, (0, 0), fx=infer_info["scale"], fy=infer_info["scale"], interpolation=cv2.INTER_AREA)
        if infer_info["scale"] != 1.0
        else frame_bgr,
        config,
    )
    valid_zones = get_valid_zones(beams, proc_h, config)
    if valid_zones and infer_info["scale"] != 1.0:
        inv_scale = 1.0 / infer_info["scale"]
        valid_zones = [(int(y1 * inv_scale), int(y2 * inv_scale)) for y1, y2 in valid_zones]

    metadata = {
        "backend": modelo_detector["backend"],
        "raw_detections": int(len(boxes)),
        "valid_zones": valid_zones,
        "warning": modelo_detector.get("warning"),
        "cached": False,
    }

    if len(boxes) == 0:
        return [], metadata

    box_idx, pallet_idx = split_boxes_pallets(boxes, logits, phrases)
    filtered_boxes = boxes[box_idx].copy()
    filtered_logits = logits[box_idx].copy()
    filtered_phrases = [phrases[index] for index in box_idx]

    filtered_boxes, filtered_logits, filtered_phrases = apply_beam_zone_filter(
        filtered_boxes,
        filtered_logits,
        filtered_phrases,
        valid_zones,
        frame_bgr.shape[0],
    )
    filtered_boxes, filtered_logits, filtered_phrases = apply_min_size_filter(
        filtered_boxes,
        filtered_logits,
        filtered_phrases,
        config.min_box_size,
    )
    filtered_boxes, filtered_logits, filtered_phrases = apply_aspect_ratio_filter(
        filtered_boxes,
        filtered_logits,
        filtered_phrases,
        config.max_box_aspect_ratio,
    )
    filtered_boxes, filtered_logits, filtered_phrases = apply_containment_filter(
        filtered_boxes,
        filtered_logits,
        filtered_phrases,
        config.containment_threshold,
    )
    filtered_boxes, filtered_logits, filtered_phrases = apply_center_distance_filter(
        filtered_boxes,
        filtered_logits,
        filtered_phrases,
        config.center_dist_threshold,
    )
    filtered_boxes, filtered_logits, filtered_phrases = apply_nms(
        filtered_boxes,
        filtered_logits,
        filtered_phrases,
        config.iou_threshold,
    )

    if len(pallet_idx) > 0:
        all_boxes = np.concatenate([filtered_boxes, boxes[pallet_idx]], axis=0)
        all_logits = np.concatenate([filtered_logits, logits[pallet_idx]], axis=0)
        all_phrases = filtered_phrases + [phrases[index] for index in pallet_idx]
        kept_box_idx, _ = apply_pallet_filter(
            all_boxes,
            all_logits,
            all_phrases,
            box_idx=np.arange(len(filtered_boxes)),
            pallet_idx=np.arange(len(filtered_boxes), len(filtered_boxes) + len(pallet_idx)),
            containment_threshold=config.containment_threshold,
            pallet_min_aspect_ratio=config.pallet_min_aspect_ratio,
        )
        filtered_boxes = filtered_boxes[kept_box_idx]
        filtered_logits = filtered_logits[kept_box_idx]
        filtered_phrases = [filtered_phrases[index] for index in kept_box_idx]

    segmented = []
    if segmentador_sam is not None and len(filtered_boxes) > 0:
        segmented = segmentar_cajas(
            image_bgr=frame_bgr,
            boxes=filtered_boxes,
            logits=filtered_logits,
            phrases=filtered_phrases,
            sam_model=segmentador_sam,
            run_dir=None,
            stem=None,
        )

    metadata["final_detections"] = int(len(filtered_boxes))
    detections = _build_detection_dicts(
        frame_bgr=frame_bgr,
        boxes=filtered_boxes,
        logits=filtered_logits,
        phrases=filtered_phrases,
        segmented=segmented,
        backend=modelo_detector["backend"],
    )
    return detections, metadata


def detectar_y_segmentar_frame(
    frame_bgr: np.ndarray,
    modelo_gdino: dict,
    segmentador_sam,
    config: DetectorConfig | None = None,
) -> list[dict]:
    detections, _ = procesar_frame_detector(frame_bgr, modelo_gdino, segmentador_sam, config)
    return detections


def resegmentar_detecciones_cacheadas(
    frame_bgr: np.ndarray,
    detecciones_previas: list[dict],
    segmentador_sam,
) -> list[dict]:
    if not detecciones_previas:
        return []

    copied = [dict(item) for item in detecciones_previas]
    if segmentador_sam is None:
        return copied

    bboxes_px = [tuple(det["bbox_px"]) for det in copied]
    logits = [float(det.get("score", 0.0)) for det in copied]
    phrases = [str(det.get("label", "box")) for det in copied]
    segmented = segmentar_cajas_desde_bboxes_px(
        image_bgr=frame_bgr,
        bboxes_px=bboxes_px,
        sam_model=segmentador_sam,
        scores=logits,
        phrases=phrases,
        run_dir=None,
        stem=None,
    )
    segmented_by_idx = {item["idx"]: item for item in segmented}

    for index, det in enumerate(copied):
        segmentation = segmented_by_idx.get(index)
        det["contorno"] = None if segmentation is None else np.asarray(segmentation["vertices"], dtype=np.int32)

    return copied
