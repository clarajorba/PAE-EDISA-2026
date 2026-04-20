"""
detector_video_almacen.py
=========================
GroundingDINO + filtros en cascada para detección de cajas en VIDEO de almacén.

Procesa 1 de cada N fotogramas y guarda solo el resultado final anotado.
Basado en prueba_detector_almacen.py (versión imágenes).
"""

import cv2
import torch
import numpy as np
from pathlib import Path
from groundingdino.util.inference import load_model, load_image, predict, annotate

# ============================================================
#  ⚙️  PARÁMETROS
# ============================================================

CONFIG_PATH  = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "weights/groundingdino_swint_ogc.pth"

# VIDEO INPUT/OUTPUT
VIDEO_PATH   = "mis_videos/video_almacen.mp4"   # Ruta al video de entrada
OUTPUT_BASE  = "resultados_video/"               # Carpeta de salida
FRAME_SKIP   = 3                                 # Procesar 1 de cada N frames

TEXT_PROMPT  = "cardboard box . box . carton . stacked cardboard box . warehouse package . pallet ."

BOX_THRESHOLD         = 0.19
TEXT_THRESHOLD        = 0.3
IOU_THRESHOLD         = 0.7
CONTAINMENT_THRESHOLD = 0.3
CENTER_DIST_THRESHOLD = 0.05

# FILTROS DE TAMAÑO Y FORMA
MIN_BOX_SIZE          = 0.04
MAX_BOX_ASPECT_RATIO  = 2.2

# DETECCIÓN DE VIGAS NARANJAS (HSV + PROYECCIÓN)
BEAM_HSV_LOW          = np.array([8, 150, 120])
BEAM_HSV_HIGH         = np.array([18, 255, 255])

# Umbral: una fila debe tener al menos este % del ancho con píxeles naranjas
BEAM_ROW_THRESHOLD = 0.25
# Altura mínima de viga (en píxeles) para evitar ruido
BEAM_MIN_HEIGHT_PX = 10
# Proporción de zona pallet respecto al espacio entre vigas
BEAM_PALLET_RATIO = 0.12

PALLET_KEYWORDS       = {"pallet"}
PALLET_MIN_ASPECT_RATIO = 2.5

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ============================================================
#  🔧  UTILIDADES VECTORIZADAS
# ============================================================

def _to_corners_batch(boxes: np.ndarray) -> np.ndarray:
    """(N,4) cx cy w h  →  (N,4) x1 y1 x2 y2"""
    cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    return np.stack([cx - w/2, cy - h/2, cx + w/2, cy + h/2], axis=1)


def _iou_matrix(corners: np.ndarray) -> np.ndarray:
    """Matriz IoU (N×N) a partir de corners (N,4)."""
    x1 = np.maximum(corners[:, None, 0], corners[None, :, 0])
    y1 = np.maximum(corners[:, None, 1], corners[None, :, 1])
    x2 = np.minimum(corners[:, None, 2], corners[None, :, 2])
    y2 = np.minimum(corners[:, None, 3], corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    areas = (corners[:, 2] - corners[:, 0]) * (corners[:, 3] - corners[:, 1])
    union = areas[:, None] + areas[None, :] - inter
    return np.where(union > 0, inter / union, 0.0)


# ============================================================
#  🟧  DETECCIÓN DE VIGAS NARANJAS (PROYECCIÓN HORIZONTAL)
# ============================================================

def detect_orange_beams(image_bgr):
    """
    Detecta vigas naranjas por proyección horizontal.
    Retorna lista de (y_top, y_bottom, 0, w) en píxeles, ordenadas por y_top.
    """
    h, w = image_bgr.shape[:2]
    
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BEAM_HSV_LOW, BEAM_HSV_HIGH)
    
    projection = np.sum(mask > 0, axis=1)
    threshold_px = w * BEAM_ROW_THRESHOLD
    is_beam_row = projection >= threshold_px
    
    beams = []
    in_beam = False
    y_start = 0
    
    for y in range(h):
        if is_beam_row[y] and not in_beam:
            in_beam = True
            y_start = y
        elif not is_beam_row[y] and in_beam:
            in_beam = False
            beam_height = y - y_start
            if beam_height >= BEAM_MIN_HEIGHT_PX:
                beams.append((y_start, y, 0, w))
    
    if in_beam:
        beam_height = h - y_start
        if beam_height >= BEAM_MIN_HEIGHT_PX:
            beams.append((y_start, h, 0, w))
    
    return beams


def get_valid_zones(beams, img_height):
    """
    Retorna lista de zonas válidas (y_min, y_max) basadas en las vigas detectadas.
    """
    if len(beams) == 0:
        return None
    
    zones = []
    
    if len(beams) == 1:
        beam = beams[0]
        beam_top = beam[0]
        level_height = beam_top
        pallet_margin = int(level_height * BEAM_PALLET_RATIO)
        
        y_min = 0
        y_max = beam_top - pallet_margin
        
        if y_max > y_min:
            zones.append((y_min, y_max))
    
    else:
        for i in range(len(beams) - 1):
            beam_upper = beams[i]
            beam_lower = beams[i + 1]
            
            y_upper = beam_upper[1]
            y_lower = beam_lower[0]
            
            level_height = y_lower - y_upper
            pallet_margin = int(level_height * BEAM_PALLET_RATIO)
            
            y_min = y_upper
            y_max = y_lower - pallet_margin
            
            if y_max > y_min:
                zones.append((y_min, y_max))
        
        first_beam = beams[0]
        if first_beam[0] > 50:
            level_height = first_beam[0]
            pallet_margin = int(level_height * BEAM_PALLET_RATIO)
            
            y_min = 0
            y_max = first_beam[0] - pallet_margin
            
            if y_max > y_min:
                zones.insert(0, (y_min, y_max))
    
    return zones if zones else None


# ============================================================
#  🗂️  SEPARACIÓN CAJAS / PALLETS
# ============================================================

def split_boxes_pallets(boxes, logits, phrases):
    pallet_mask = np.array([
        any(kw in p.lower() for kw in PALLET_KEYWORDS)
        for p in phrases
    ])
    return np.where(~pallet_mask)[0], np.where(pallet_mask)[0]


# ============================================================
#  🔍  FILTROS
# ============================================================

def apply_beam_zone_filter(boxes, logits, phrases, valid_zones, img_height):
    """Filtra detecciones fuera de las zonas válidas entre vigas."""
    if valid_zones is None or len(boxes) == 0:
        return boxes, logits, phrases
    
    cy = boxes[:, 1]
    keep = np.zeros(len(boxes), dtype=bool)
    
    for y_min, y_max in valid_zones:
        y_min_norm = y_min / img_height
        y_max_norm = y_max / img_height
        keep |= (cy >= y_min_norm) & (cy <= y_max_norm)
    
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def apply_min_size_filter(boxes, logits, phrases, min_size):
    """Elimina detecciones cuyo ancho O alto sea menor que min_size."""
    if len(boxes) == 0 or min_size == 0.0:
        return boxes, logits, phrases
    w, h = boxes[:, 2], boxes[:, 3]
    keep = (w >= min_size) & (h >= min_size)
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def apply_aspect_ratio_filter(boxes, logits, phrases, max_ratio):
    """Elimina detecciones con aspect ratio > max_ratio."""
    if len(boxes) == 0 or max_ratio == 0.0:
        return boxes, logits, phrases
    w, h = boxes[:, 2], boxes[:, 3]
    aspect = np.maximum(w, h) / np.clip(np.minimum(w, h), 1e-6, None)
    keep = aspect <= max_ratio
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def apply_containment_filter(boxes, logits, phrases, threshold):
    if len(boxes) == 0 or threshold == 0.0:
        return boxes, logits, phrases
    corners = _to_corners_batch(boxes)
    areas   = (corners[:, 2] - corners[:, 0]) * (corners[:, 3] - corners[:, 1])
    x1 = np.maximum(corners[:, None, 0], corners[None, :, 0])
    y1 = np.maximum(corners[:, None, 1], corners[None, :, 1])
    x2 = np.minimum(corners[:, None, 2], corners[None, :, 2])
    y2 = np.minimum(corners[:, None, 3], corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    cont  = np.where(areas[:, None] > 0, inter / areas[:, None], 0.0)
    is_group = np.zeros(len(boxes), dtype=bool)
    for j in range(len(boxes)):
        smaller = areas < areas[j]
        if np.any(smaller & (cont[:, j] >= threshold)):
            is_group[j] = True
    kept_idx = np.where(~is_group)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def apply_center_distance_filter(boxes, logits, phrases, dist_threshold):
    if len(boxes) == 0 or dist_threshold == 0.0:
        return boxes, logits, phrases
    order  = np.argsort(logits)[::-1]
    active = np.ones(len(boxes), dtype=bool)
    kept   = []
    for idx in order:
        if not active[idx]:
            continue
        kept.append(idx)
        active_idx = np.where(active)[0]
        dists = np.sqrt(
            (boxes[active_idx, 0] - boxes[idx, 0]) ** 2 +
            (boxes[active_idx, 1] - boxes[idx, 1]) ** 2
        )
        too_close = active_idx[dists < dist_threshold]
        too_close = too_close[too_close != idx]
        active[too_close] = False
    kept_idx = sorted(kept)
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def apply_nms(boxes, logits, phrases, iou_threshold):
    if len(boxes) == 0:
        return boxes, logits, phrases
    corners = _to_corners_batch(boxes)
    iou     = _iou_matrix(corners)
    order   = np.argsort(logits)[::-1]
    kept    = []
    while len(order) > 0:
        best  = order[0]
        kept.append(best)
        rest  = order[1:]
        order = rest[iou[best, rest] < iou_threshold]
    kept_idx = sorted(kept)
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def apply_pallet_filter(boxes, logits, phrases, box_idx, pallet_idx,
                        containment_threshold=0.5):
    if len(pallet_idx) == 0:
        return box_idx, pallet_idx

    pw = boxes[pallet_idx, 2]
    ph = boxes[pallet_idx, 3]
    aspect       = np.maximum(pw, ph) / np.clip(np.minimum(pw, ph), 1e-6, None)
    empty_pallet = aspect >= PALLET_MIN_ASPECT_RATIO

    surviving = pallet_idx[~empty_pallet]

    if len(surviving) == 0 or len(box_idx) == 0:
        return box_idx, surviving

    bc = _to_corners_batch(boxes[box_idx])
    pc = _to_corners_batch(boxes[surviving])
    x1 = np.maximum(bc[:, None, 0], pc[None, :, 0])
    y1 = np.maximum(bc[:, None, 1], pc[None, :, 1])
    x2 = np.minimum(bc[:, None, 2], pc[None, :, 2])
    y2 = np.minimum(bc[:, None, 3], pc[None, :, 3])
    inter     = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    areas_box = (bc[:, 2] - bc[:, 0]) * (bc[:, 3] - bc[:, 1])
    cont      = np.where(areas_box[:, None] > 0, inter / areas_box[:, None], 0.0)

    has_boxes = np.any(cont >= containment_threshold, axis=0)

    return box_idx, surviving[~has_boxes]


# ============================================================
#  🖊️  OVERLAY
# ============================================================

def draw_params_overlay(image, frame_num, n_detections, valid_zones=None):
    """Dibuja parámetros y zonas válidas sobre la imagen."""
    lines = [
        f"FRAME: {frame_num}",
        f"CAJAS: {n_detections}",
        f"BOX: {BOX_THRESHOLD}",
        f"MIN_SIZE: {MIN_BOX_SIZE}",
        f"MAX_AR: {MAX_BOX_ASPECT_RATIO}",
        f"PALLET_%: {BEAM_PALLET_RATIO*100:.0f}%",
    ]
    font, fs, th, pad = cv2.FONT_HERSHEY_SIMPLEX, 1.2, 2, 10
    line_h  = int(cv2.getTextSize("A", font, fs, th)[0][1] + pad * 2)
    block_h = line_h * len(lines) + pad
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (350, block_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, image)
    for i, line in enumerate(lines):
        y = pad + line_h * i + line_h - pad
        cv2.putText(image, line, (12, y), font, fs, (0, 0, 0), th + 2)
        cv2.putText(image, line, (10, y), font, fs, (255, 255, 255), th)
    
    # Dibujar zonas válidas
    if valid_zones is not None:
        h, w = image.shape[:2]
        for y_min, y_max in valid_zones:
            cv2.line(image, (0, y_min), (w, y_min), (0, 255, 0), 2)
            cv2.line(image, (0, y_max), (w, y_max), (0, 0, 255), 2)
    
    return image


def draw_detections(image_bgr, boxes, logits, phrases):
    """Dibuja bounding boxes sobre la imagen BGR."""
    h, w = image_bgr.shape[:2]
    
    for i, (box, score, phrase) in enumerate(zip(boxes, logits, phrases)):
        cx, cy, bw, bh = box
        x1 = int((cx - bw/2) * w)
        y1 = int((cy - bh/2) * h)
        x2 = int((cx + bw/2) * w)
        y2 = int((cy + bh/2) * h)
        
        # Color según score
        color = (0, int(255 * score), int(255 * (1 - score)))
        
        cv2.rectangle(image_bgr, (x1, y1), (x2, y2), color, 3)
        
        label = f"{phrase[:15]} {score:.2f}"
        (tw, th_text), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(image_bgr, (x1, y1 - th_text - 8), (x1 + tw + 4, y1), color, -1)
        cv2.putText(image_bgr, label, (x1 + 2, y1 - 4), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
    
    return image_bgr


# ============================================================
#  🎬  PROCESAMIENTO DE VIDEO
# ============================================================

def process_frame(model, frame_bgr, frame_num, img_height, img_width):
    """Procesa un frame y retorna las detecciones filtradas."""
    
    # Detectar vigas naranjas
    beams = detect_orange_beams(frame_bgr)
    valid_zones = get_valid_zones(beams, img_height)
    
    # Preparar imagen para GroundingDINO (RGB normalizado)
    frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    image = torch.from_numpy(frame_rgb).permute(2, 0, 1).float() / 255.0
    
    # Detección
    raw_boxes, raw_logits, raw_phrases = predict(
        model=model,
        image=image,
        caption=TEXT_PROMPT,
        box_threshold=BOX_THRESHOLD,
        text_threshold=TEXT_THRESHOLD,
        device=DEVICE,
    )
    
    boxes   = raw_boxes.numpy()
    logits  = raw_logits.numpy()
    phrases = list(raw_phrases)
    
    if len(boxes) == 0:
        return np.array([]), np.array([]), [], valid_zones
    
    # Separar cajas y pallets
    box_idx, pallet_idx = split_boxes_pallets(boxes, logits, phrases)
    
    b  = boxes[box_idx].copy()
    l  = logits[box_idx].copy()
    ph = [phrases[i] for i in box_idx]
    
    # Aplicar filtros en cascada
    b, l, ph = apply_beam_zone_filter(b, l, ph, valid_zones, img_height)
    b, l, ph = apply_min_size_filter(b, l, ph, MIN_BOX_SIZE)
    b, l, ph = apply_aspect_ratio_filter(b, l, ph, MAX_BOX_ASPECT_RATIO)
    b, l, ph = apply_containment_filter(b, l, ph, CONTAINMENT_THRESHOLD)
    b, l, ph = apply_center_distance_filter(b, l, ph, CENTER_DIST_THRESHOLD)
    b, l, ph = apply_nms(b, l, ph, IOU_THRESHOLD)
    
    # Filtro pallet
    if len(b) > 0 and len(pallet_idx) > 0:
        all_b  = np.concatenate([b,  boxes[pallet_idx]], axis=0)
        all_l  = np.concatenate([l,  logits[pallet_idx]], axis=0)
        all_ph = ph + [phrases[i] for i in pallet_idx]
        kept_box_idx, _ = apply_pallet_filter(
            all_b, all_l, all_ph,
            box_idx=np.arange(len(b)),
            pallet_idx=np.arange(len(b), len(b) + len(pallet_idx)),
            containment_threshold=0.5,
        )
        b  = b[kept_box_idx]
        l  = l[kept_box_idx]
        ph = [ph[i] for i in kept_box_idx]
    
    return b, l, ph, valid_zones


def process_video(model, video_path, output_dir, frame_skip):
    """Procesa el video y guarda fotogramas anotados."""
    
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError(f"No se pudo abrir el video: {video_path}")
    
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    
    print(f"📹 Video: {video_path.name}")
    print(f"   Resolución: {width}x{height}")
    print(f"   FPS: {fps:.2f}")
    print(f"   Total frames: {total_frames}")
    print(f"   Frames a procesar: ~{total_frames // frame_skip}")
    print(f"   Salto: 1 de cada {frame_skip}")
    print()
    
    frame_num = 0
    processed = 0
    results = []
    
    while True:
        ret, frame = cap.read()
        if not ret:
            break
        
        # Procesar solo cada N frames
        if frame_num % frame_skip == 0:
            print(f"   🔍 Frame {frame_num}/{total_frames}", end="")
            
            # Procesar frame
            boxes, logits, phrases, valid_zones = process_frame(
                model, frame, frame_num, height, width
            )
            
            n_detections = len(boxes)
            print(f" → {n_detections} caja(s)")
            
            # Anotar frame
            annotated = frame.copy()
            if n_detections > 0:
                annotated = draw_detections(annotated, boxes, logits, phrases)
            annotated = draw_params_overlay(annotated, frame_num, n_detections, valid_zones)
            
            # Guardar
            out_path = output_dir / f"frame_{frame_num:06d}.jpg"
            cv2.imwrite(str(out_path), annotated)
            
            results.append({
                "frame": frame_num,
                "detecciones": n_detections,
            })
            
            processed += 1
        
        frame_num += 1
    
    cap.release()
    
    return results, processed


# ============================================================
#  📊  RESUMEN
# ============================================================

def print_summary(results, output_dir, video_name):
    print("\n" + "=" * 60)
    print("📊  RESUMEN VIDEO")
    print("=" * 60)
    
    total_boxes = sum(r["detecciones"] for r in results)
    frames_with_boxes = sum(1 for r in results if r["detecciones"] > 0)
    
    print(f"  Video           : {video_name}")
    print(f"  Frames procesados: {len(results)}")
    print(f"  Frames con cajas : {frames_with_boxes}")
    print(f"  Total detecciones: {total_boxes}")
    print(f"  Media por frame  : {total_boxes / len(results):.1f}" if results else "N/A")
    print(f"  Resultados en    : {output_dir}")
    print("=" * 60)


# ============================================================
#  🏁  MAIN
# ============================================================

def main():
    print(f"⚡ Dispositivo: {DEVICE.upper()}")
    print("📦 Cargando modelo...")
    model = load_model(CONFIG_PATH, WEIGHTS_PATH).to(DEVICE)
    
    video_path = Path(VIDEO_PATH)
    if not video_path.exists():
        print(f"❌ No se encontró el video: {VIDEO_PATH}")
        return
    
    # Crear carpeta de salida con nombre del video
    output_dir = Path(OUTPUT_BASE) / video_path.stem
    output_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"📁 Resultados en: {output_dir}")
    print()
    
    results, processed = process_video(model, video_path, output_dir, FRAME_SKIP)
    print_summary(results, output_dir, video_path.name)
    
    print(f"\n✅ Procesados {processed} frames")
    print(f"💾 Guardados en: {output_dir}")


if __name__ == "__main__":
    main()