"""
prueba_detector_almacen.py
==========================
GroundingDINO + filtros en cascada para detección de cajas de almacén.

Orden de filtros:
  1. Min size     — elimina detecciones muy pequeñas (fondo)
  2. Aspect ratio — elimina detecciones muy alargadas (pallets mal etiquetados)
  3. Containment  — elimina detecciones "grupo" que engloban varias cajas
  4. Center dist  — elimina duplicados ligeramente desplazados
  5. NMS          — elimina solapamientos directos
  6. Pallet       — descarta pallets vacíos (aspect ratio) y ocupados (cajas encima)

Por cada imagen se guardan 7 archivos:
  _0_sinfiltros.jpg
  _1_minsize.jpg
  _2_aspectratio.jpg
  _3_containment.jpg
  _4_center.jpg
  _5_nms.jpg
  _6_pallet.jpg
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
FOTOS_DIR    = "data/mis_imagenes/"
#IMAGE_NAME   = "20260218_131608.jpg"   
IMAGE_NAME   = "20260218_131604.jpg"
#IMAGE_NAME   = "Imagenpegada.png"
OUTPUT_BASE  = "outputs/comparacion_resultados/"

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
# Rango ajustado para naranja saturado, excluyendo marrones de pallets
BEAM_HSV_LOW          = np.array([8, 150, 120])    # Naranja saturado (excluye marrón)
BEAM_HSV_HIGH         = np.array([18, 255, 255])   # Naranja puro (excluye amarillo)
 
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
 
# Umbral: una fila debe tener al menos este % del ancho con píxeles naranjas
BEAM_ROW_THRESHOLD = 0.25   # 25% del ancho de imagen
# Altura mínima de viga (en píxeles) para evitar ruido
BEAM_MIN_HEIGHT_PX = 10
 
def detect_orange_beams(image_bgr):
    """
    Detecta vigas naranjas por proyección horizontal.
    Suma píxeles naranjas por fila Y → encuentra franjas con alta densidad.
    Robusto a huecos horizontales (plásticos, obstáculos).
    
    Retorna lista de (y_top, y_bottom, 0, w) en píxeles, ordenadas por y_top.
    """
    h, w = image_bgr.shape[:2]
    
    # Convertir a HSV y crear máscara naranja
    hsv = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, BEAM_HSV_LOW, BEAM_HSV_HIGH)
    
    # Proyección horizontal: contar píxeles naranjas por cada fila Y
    # projection[y] = número de píxeles naranjas en la fila y
    projection = np.sum(mask > 0, axis=1)
    
    # Umbral en píxeles (% del ancho)
    threshold_px = w * BEAM_ROW_THRESHOLD
    
    # Encontrar filas que superan el umbral
    is_beam_row = projection >= threshold_px
    
    # Agrupar filas consecutivas → cada grupo es una viga
    beams = []
    in_beam = False
    y_start = 0
    
    for y in range(h):
        if is_beam_row[y] and not in_beam:
            # Inicio de viga
            in_beam = True
            y_start = y
        elif not is_beam_row[y] and in_beam:
            # Fin de viga
            in_beam = False
            beam_height = y - y_start
            if beam_height >= BEAM_MIN_HEIGHT_PX:
                beams.append((y_start, y, 0, w))
    
    # Si terminamos dentro de una viga
    if in_beam:
        beam_height = h - y_start
        if beam_height >= BEAM_MIN_HEIGHT_PX:
            beams.append((y_start, h, 0, w))
    
    # Ya están ordenadas por Y (de arriba a abajo)
    return beams, mask, projection
 
 
# Proporción de zona pallet respecto al espacio entre vigas (o altura de nivel)
BEAM_PALLET_RATIO = 0.12  # 12% del espacio es zona pallet (ajustar entre 0.10-0.15)
 
def get_valid_zones(beams, img_height):
    """
    Dadas las vigas detectadas, retorna lista de zonas válidas (y_min, y_max).
    
    Estructura por nivel (de arriba a abajo en la imagen):
        [VIGA SUPERIOR]  ← y_min = borde inferior de esta viga
        [CAJAS]          ← zona válida
        [PALLETS]        ← descartar (BEAM_PALLET_RATIO del espacio)
        [VIGA INFERIOR]  ← y_max = borde superior de esta viga - margen pallet
    
    Casos:
        - 0 vigas: retorna None (no filtrar)
        - 1 viga: último piso, desde viga hacia arriba hasta top de imagen
        - 2+ vigas: un nivel por cada par de vigas consecutivas
    """
    if len(beams) == 0:
        return None
    
    zones = []
    
    if len(beams) == 1:
        # Último piso: desde la viga hacia arriba (sin límite superior)
        beam = beams[0]  # (y_top, y_bottom, x1, x2)
        beam_top = beam[0]
        
        # Espacio desde top de imagen hasta la viga
        level_height = beam_top
        pallet_margin = int(level_height * BEAM_PALLET_RATIO)
        
        y_min = 0  # Top de imagen
        y_max = beam_top - pallet_margin  # Viga - margen pallet
        
        if y_max > y_min:
            zones.append((y_min, y_max))
    
    else:
        # Múltiples vigas: un nivel por cada par consecutivo
        for i in range(len(beams) - 1):
            beam_upper = beams[i]      # Viga de arriba
            beam_lower = beams[i + 1]  # Viga de abajo
            
            # Espacio entre vigas
            y_upper = beam_upper[1]  # Borde inferior de viga superior
            y_lower = beam_lower[0]  # Borde superior de viga inferior
            
            level_height = y_lower - y_upper
            pallet_margin = int(level_height * BEAM_PALLET_RATIO)
            
            y_min = y_upper  # Justo debajo de viga superior
            y_max = y_lower - pallet_margin  # Viga inferior - margen pallet
            
            if y_max > y_min:
                zones.append((y_min, y_max))
        
        # Último piso (encima de la primera viga, si hay espacio)
        first_beam = beams[0]
        if first_beam[0] > 50:  # Si hay espacio significativo arriba
            level_height = first_beam[0]
            pallet_margin = int(level_height * BEAM_PALLET_RATIO)
            
            y_min = 0
            y_max = first_beam[0] - pallet_margin
            
            if y_max > y_min:
                zones.insert(0, (y_min, y_max))
    
    return zones if zones else None
 
 
def apply_beam_zone_filter(boxes, logits, phrases, valid_zones, img_height):
    """
    Filtra detecciones fuera de las zonas válidas entre vigas.
    boxes en formato normalizado (0-1).
    Una detección se mantiene si su centro está en CUALQUIERA de las zonas válidas.
    """
    if valid_zones is None or len(boxes) == 0:
        print("   Filtro beam zone     : sin vigas detectadas, no se aplica")
        return boxes, logits, phrases
    
    # Centro Y de cada caja (normalizado)
    cy = boxes[:, 1]
    
    # Una caja se mantiene si está en alguna zona válida
    keep = np.zeros(len(boxes), dtype=bool)
    
    for y_min, y_max in valid_zones:
        y_min_norm = y_min / img_height
        y_max_norm = y_max / img_height
        keep |= (cy >= y_min_norm) & (cy <= y_max_norm)
    
    removed = (~keep).sum()
    if removed:
        print(f"   Filtro beam zone     : eliminadas {removed} detección(es) fuera de zona")
    else:
        print(f"   Filtro beam zone     : {len(valid_zones)} zona(s) válida(s), 0 eliminadas")
    
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]
 
 
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
 
def apply_min_size_filter(boxes, logits, phrases, min_size):
    """Elimina detecciones cuyo ancho O alto sea menor que min_size."""
    if len(boxes) == 0 or min_size == 0.0:
        return boxes, logits, phrases
    w, h = boxes[:, 2], boxes[:, 3]
    keep = (w >= min_size) & (h >= min_size)
    removed = (~keep).sum()
    if removed:
        print(f"   Filtro tamaño mín    : eliminadas {removed} detección(es) pequeñas")
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]
 
 
def apply_aspect_ratio_filter(boxes, logits, phrases, max_ratio):
    """Elimina detecciones con aspect ratio > max_ratio."""
    if len(boxes) == 0 or max_ratio == 0.0:
        return boxes, logits, phrases
    w, h = boxes[:, 2], boxes[:, 3]
    aspect = np.maximum(w, h) / np.clip(np.minimum(w, h), 1e-6, None)
    keep = aspect <= max_ratio
    removed = (~keep).sum()
    if removed:
        print(f"   Filtro aspect ratio  : eliminadas {removed} detección(es) alargadas")
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
    if is_group.sum():
        print(f"   Filtro contenimiento : eliminadas {is_group.sum()} caja(s) 'grupo'")
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
    removed  = len(boxes) - len(kept_idx)
    if removed:
        print(f"   Filtro centros       : eliminadas {removed} detección(es) duplicada(s)")
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
    removed  = len(boxes) - len(kept_idx)
    if removed:
        print(f"   Filtro NMS           : eliminadas {removed} detección(es)")
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]
 
 
def apply_pallet_filter(boxes, logits, phrases, box_idx, pallet_idx,
                        containment_threshold=0.5):
    if len(pallet_idx) == 0:
        return box_idx, pallet_idx
 
    pw = boxes[pallet_idx, 2]
    ph = boxes[pallet_idx, 3]
    aspect       = np.maximum(pw, ph) / np.clip(np.minimum(pw, ph), 1e-6, None)
    empty_pallet = aspect >= PALLET_MIN_ASPECT_RATIO
 
    if empty_pallet.sum():
        print(f"   Filtro pallet vacío  : descartados {empty_pallet.sum()} pallet(s)")
 
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
    if has_boxes.sum():
        print(f"   Filtro pallet ocupado: descartados {has_boxes.sum()} pallet(s) con cajas encima")
 
    return box_idx, surviving[~has_boxes]
 
 
# ============================================================
#  🖊️  OVERLAY + GUARDADO POR PASO
# ============================================================
 
def draw_params_overlay(image, n_final, valid_zones=None):
    lines = [
        f"BOX: {BOX_THRESHOLD}",
        f"TEXT: {TEXT_THRESHOLD}",
        f"IOU: {IOU_THRESHOLD}",
        f"CONT: {CONTAINMENT_THRESHOLD}",
        f"CENTER: {CENTER_DIST_THRESHOLD}",
        f"MIN_SIZE: {MIN_BOX_SIZE}",
        f"MAX_AR: {MAX_BOX_ASPECT_RATIO}",
        f"PALLET_%: {BEAM_PALLET_RATIO*100:.0f}%",
    ]
    font, fs, th, pad = cv2.FONT_HERSHEY_SIMPLEX, 1.4, 3, 14
    line_h  = int(cv2.getTextSize("A", font, fs, th)[0][1] + pad * 2)
    block_h = line_h * len(lines) + pad
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (400, block_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, image)
    for i, line in enumerate(lines):
        y = pad + line_h * i + line_h - pad
        cv2.putText(image, line, (12, y), font, fs, (0, 0, 0), th + 3)
        cv2.putText(image, line, (10, y), font, fs, (255, 255, 255), th)
    
    # Dibujar zonas válidas si existen
    if valid_zones is not None:
        h, w = image.shape[:2]
        for y_min, y_max in valid_zones:
            # Línea verde = límite superior de zona válida
            cv2.line(image, (0, y_min), (w, y_min), (0, 255, 0), 3)
            # Línea roja = límite inferior de zona válida (ya sin pallets)
            cv2.line(image, (0, y_max), (w, y_max), (0, 0, 255), 3)
    
    return image
 
 
def _save_step(image_source, boxes, logits, phrases, stem, run_dir, step, label, valid_zones=None):
    """Anota y guarda la imagen tras un paso del pipeline."""
    annotated = annotate(
        image_source=image_source,
        boxes=torch.from_numpy(boxes),
        logits=torch.from_numpy(logits),
        phrases=phrases,
    )
    annotated = draw_params_overlay(annotated, len(boxes), valid_zones)
    out_path  = run_dir / f"{stem}_{step}_{label}.jpg"
    cv2.imwrite(str(out_path), annotated)
    print(f"   💾 [{label}] {len(boxes)} detecc. → {out_path.name}")
 
 
def _save_beam_debug(image_bgr, beams, mask, projection, stem, run_dir):
    """Guarda imagen de debug mostrando vigas detectadas y proyección."""
    h, w = image_bgr.shape[:2]
    
    # Crear imagen con espacio extra a la derecha para el gráfico de proyección
    proj_width = 150
    debug = np.zeros((h, w + proj_width, 3), dtype=np.uint8)
    debug[:, :w] = image_bgr
    
    # Dibujar bounding boxes de vigas detectadas
    for i, (y1, y2, x1, x2) in enumerate(beams):
        cv2.rectangle(debug, (0, y1), (w, y2), (0, 165, 255), 4)
        cv2.putText(debug, f"BEAM {i+1}", (10, y1 + 25), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 165, 255), 2)
    
    # Dibujar gráfico de proyección a la derecha
    # Normalizar proyección al ancho del gráfico
    if projection.max() > 0:
        proj_normalized = (projection / projection.max() * (proj_width - 10)).astype(int)
    else:
        proj_normalized = np.zeros_like(projection)
    
    # Fondo del gráfico
    debug[:, w:] = (40, 40, 40)
    
    # Línea de umbral
    threshold_px = w * BEAM_ROW_THRESHOLD
    if projection.max() > 0:
        thresh_x = int(threshold_px / projection.max() * (proj_width - 10))
        cv2.line(debug, (w + thresh_x, 0), (w + thresh_x, h), (0, 0, 255), 1)
    
    # Dibujar proyección como barras horizontales
    for y in range(0, h, 2):  # Cada 2 píxeles para que no sea muy denso
        bar_len = proj_normalized[y]
        if bar_len > 0:
            color = (0, 255, 0) if projection[y] >= threshold_px else (100, 100, 100)
            cv2.line(debug, (w + 5, y), (w + 5 + bar_len, y), color, 1)
    
    out_path = run_dir / f"{stem}_beams_debug.jpg"
    cv2.imwrite(str(out_path), debug)
    print(f"   🟧 Vigas detectadas: {len(beams)} → {out_path.name}")
 
 
# ============================================================
#  📂  SELECCIÓN DE IMÁGENES Y CARPETA DE SALIDA
# ============================================================
 
def select_image_paths():
    fotos      = Path(FOTOS_DIR)
    extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    if IMAGE_NAME is not None:
        p = fotos / IMAGE_NAME
        if not p.exists():
            available = sorted(f.name for f in fotos.iterdir() if f.suffix.lower() in extensions)
            print(f"\n❌ No se encontró '{IMAGE_NAME}' en {FOTOS_DIR}")
            print("   Disponibles: " + ", ".join(available))
            raise FileNotFoundError(p)
        return [p]
    return sorted(f for f in fotos.iterdir() if f.suffix.lower() in extensions)
 
 
def create_run_folder():
    run_dir = Path(OUTPUT_BASE)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir
 
 
# ============================================================
#  🚀  DETECCIÓN PRINCIPAL
# ============================================================
 
def run_detection(model, image_paths, run_dir):
    all_results = []
 
    for img_path in image_paths:
        print(f"\n🔍 Procesando: {img_path.name}")
 
        image_source, image = load_image(str(img_path))
        image_bgr = cv2.imread(str(img_path))
        img_height, img_width = image_bgr.shape[:2]
        
        # Detectar vigas naranjas
        beams, beam_mask, projection = detect_orange_beams(image_bgr)
        _save_beam_debug(image_bgr, beams, beam_mask, projection, img_path.stem, run_dir)
        
        valid_zones = get_valid_zones(beams, img_height)
        if valid_zones:
            print(f"   Zonas válidas        : {len(valid_zones)} nivel(es)")
            for i, (y_min, y_max) in enumerate(valid_zones):
                print(f"      Nivel {i+1}: Y={y_min} a Y={y_max} ({y_max-y_min}px)")
        
        # Detección con GroundingDINO
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
        print(f"   Detecciones brutas   : {len(boxes)}")
 
        box_idx, pallet_idx = split_boxes_pallets(boxes, logits, phrases)
        print(f"   Cajas / Pallets      : {len(box_idx)} / {len(pallet_idx)}")
 
        b  = boxes[box_idx].copy()
        l  = logits[box_idx].copy()
        ph = [phrases[i] for i in box_idx]
 
        # 0 — sin filtros
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 0, "0_sinfiltros", valid_zones)
 
        # 1 — beam zone (NUEVO)
        b, l, ph = apply_beam_zone_filter(b, l, ph, valid_zones, img_height)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 1, "1_beamzone", valid_zones)
 
        # 2 — min size
        b, l, ph = apply_min_size_filter(b, l, ph, MIN_BOX_SIZE)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 2, "2_minsize", valid_zones)
 
        # 3 — aspect ratio
        b, l, ph = apply_aspect_ratio_filter(b, l, ph, MAX_BOX_ASPECT_RATIO)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 3, "3_aspectratio", valid_zones)
 
        # 4 — containment
        b, l, ph = apply_containment_filter(b, l, ph, CONTAINMENT_THRESHOLD)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 4, "4_containment", valid_zones)
 
        # 5 — center distance
        b, l, ph = apply_center_distance_filter(b, l, ph, CENTER_DIST_THRESHOLD)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 5, "5_center", valid_zones)
 
        # 6 — NMS
        b, l, ph = apply_nms(b, l, ph, IOU_THRESHOLD)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 6, "6_nms", valid_zones)
 
        # 7 — pallet
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
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 7, "7_pallet", valid_zones)
 
        n_final = len(b)
        print(f"   Detecciones finales  : {n_final}")
        for i, (score, phrase) in enumerate(zip(l, ph)):
            print(f"      [{i+1}] '{phrase}'  score={score:.3f}")
 
        all_results.append({
            "imagen":      img_path.name,
            "detecciones": n_final,
            "objetos":     list(zip(ph, l.tolist())),
        })
 
    return all_results
 
 
# ============================================================
#  📊  RESUMEN
# ============================================================
 
def print_summary(results, run_dir):
    print("\n" + "=" * 60)
    print("📊  RESUMEN FINAL")
    print("=" * 60)
    total = 0
    for r in results:
        print(f"  {r['imagen']:35s} → {r['detecciones']} caja(s)")
        for phrase, score in r["objetos"]:
            print(f"      • {phrase} ({score:.2f})")
        total += r["detecciones"]
    print(f"\n  TOTAL detecciones : {total}")
    print(f"  Resultados en     : {run_dir}")
    print(f"  BOX={BOX_THRESHOLD} | TEXT={TEXT_THRESHOLD} | "
          f"IOU={IOU_THRESHOLD} | CONT={CONTAINMENT_THRESHOLD}")
    print(f"  MIN_SIZE={MIN_BOX_SIZE} | MAX_AR={MAX_BOX_ASPECT_RATIO}")
    print(f"  PALLET_RATIO={BEAM_PALLET_RATIO*100:.0f}%")
    print("=" * 60)
 
 
# ============================================================
#  🏁  MAIN
# ============================================================
 
def main():
    print(f"⚡ Dispositivo: {DEVICE.upper()}")
    print("📦 Cargando modelo...")
    model = load_model(CONFIG_PATH, WEIGHTS_PATH).to(DEVICE)
 
    image_paths = select_image_paths()
    run_dir     = create_run_folder()
 
    print(f"\n🖼️  {len(image_paths)} imagen(s) seleccionada(s)")
    print(f"📁 Resultados en: {run_dir}")
    print(f"🔎 Prompt: {TEXT_PROMPT}")
 
    results = run_detection(model, image_paths, run_dir)
    print_summary(results, run_dir)
 
 
if __name__ == "__main__":
    main()
