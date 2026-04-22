"""
detector_realtime_almacen_v2.py
===============================
GroundingDINO + SAM + filtros en cascada para detección de cajas en TIEMPO REAL.
Captura desde stream RTSP/HTTP de Raspberry Pi.

Controles:
  - 'q' : Salir
  - 's' : Guardar frame actual manualmente
  - 'p' : Pausar/Reanudar
  - '+' : Aumentar frame skip
  - '-' : Reducir frame skip
"""

import cv2
import torch
import numpy as np
from pathlib import Path
from datetime import datetime
from threading import Thread, Lock
import time

from groundingdino.util.inference import load_model, predict

# Importamos las funcionalidades de SAM del primer código
from segmentador_contornos import cargar_segmentador, segmentar_cajas

# ============================================================
#  ⚙️  PARÁMETROS
# ============================================================

CONFIG_PATH  = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "weights/groundingdino_swint_ogc.pth"

# STREAM INPUT - Ajusta según tu configuración de Raspberry Pi
STREAM_URL = "http://192.168.1.100:8080/video"

# OUTPUT
OUTPUT_BASE = "capturas_realtime/"
SAVE_ON_DETECTION = True

# RENDIMIENTO (CPU)
PROCESS_WIDTH = 800        
FRAME_SKIP = 3             
DISPLAY_SCALE = 1.0        

# ACTIVAR/DESACTIVAR SAM EN TIEMPO REAL
# (Recomendado en False para streams, a menos que tengas GPU potente)
ENABLE_SAM_REALTIME = False 

TEXT_PROMPT = "cardboard box . box . carton . stacked cardboard box . warehouse package . pallet ."

BOX_THRESHOLD         = 0.19
TEXT_THRESHOLD        = 0.3
IOU_THRESHOLD         = 0.7
CONTAINMENT_THRESHOLD = 0.5   # Actualizado según código 1
CENTER_DIST_THRESHOLD = 0.05

# FILTROS DE TAMAÑO Y FORMA
MIN_BOX_SIZE          = 0.06  # Actualizado según código 1
MAX_BOX_ASPECT_RATIO  = 2.2

# DETECCIÓN DE VIGAS NARANJAS
BEAM_HSV_LOW          = np.array([8, 150, 120])
BEAM_HSV_HIGH         = np.array([18, 255, 255])
BEAM_ROW_THRESHOLD    = 0.25
BEAM_MIN_HEIGHT_PX    = 10
BEAM_PALLET_RATIO     = 0.18  # Actualizado según código 1

PALLET_KEYWORDS       = {"pallet"}
PALLET_MIN_ASPECT_RATIO = 2.5

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


# ============================================================
#  🔧  UTILIDADES VECTORIZADAS
# ============================================================

def _to_corners_batch(boxes: np.ndarray) -> np.ndarray:
    cx, cy, w, h = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    return np.stack([cx - w/2, cy - h/2, cx + w/2, cy + h/2], axis=1)

def _iou_matrix(corners: np.ndarray) -> np.ndarray:
    x1 = np.maximum(corners[:, None, 0], corners[None, :, 0])
    y1 = np.maximum(corners[:, None, 1], corners[None, :, 1])
    x2 = np.minimum(corners[:, None, 2], corners[None, :, 2])
    y2 = np.minimum(corners[:, None, 3], corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    areas = (corners[:, 2] - corners[:, 0]) * (corners[:, 3] - corners[:, 1])
    union = areas[:, None] + areas[None, :] - inter
    return np.where(union > 0, inter / union, 0.0)


# ============================================================
#  🟧  DETECCIÓN DE VIGAS NARANJAS
# ============================================================

def detect_orange_beams(image_bgr):
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
            if y - y_start >= BEAM_MIN_HEIGHT_PX:
                beams.append((y_start, y, 0, w))
    
    if in_beam and h - y_start >= BEAM_MIN_HEIGHT_PX:
        beams.append((y_start, h, 0, w))
    
    return beams

def get_valid_zones(beams, img_height):
    if len(beams) == 0:
        return None
    zones = []
    if len(beams) == 1:
        beam_top = beams[0][0]
        pallet_margin = int(beam_top * BEAM_PALLET_RATIO)
        y_min, y_max = 0, beam_top - pallet_margin
        if y_max > y_min:
            zones.append((y_min, y_max))
    else:
        for i in range(len(beams) - 1):
            y_upper = beams[i][1]
            y_lower = beams[i + 1][0]
            level_height = y_lower - y_upper
            pallet_margin = int(level_height * BEAM_PALLET_RATIO)
            y_min, y_max = y_upper, y_lower - pallet_margin
            if y_max > y_min:
                zones.append((y_min, y_max))
        if beams[0][0] > 50:
            pallet_margin = int(beams[0][0] * BEAM_PALLET_RATIO)
            y_min, y_max = 0, beams[0][0] - pallet_margin
            if y_max > y_min:
                zones.insert(0, (y_min, y_max))
    return zones if zones else None


# ============================================================
#  🗂️  FILTROS ACTUALIZADOS (Desde código 1)
# ============================================================

def split_boxes_pallets(boxes, logits, phrases):
    pallet_mask = np.array([any(kw in p.lower() for kw in PALLET_KEYWORDS) for p in phrases])
    return np.where(~pallet_mask)[0], np.where(pallet_mask)[0]

def apply_beam_zone_filter(boxes, logits, phrases, valid_zones, img_height):
    if valid_zones is None or len(boxes) == 0:
        return boxes, logits, phrases
    cy = boxes[:, 1]
    keep = np.zeros(len(boxes), dtype=bool)
    for y_min, y_max in valid_zones:
        y_min_norm, y_max_norm = y_min / img_height, y_max / img_height
        keep |= (cy >= y_min_norm) & (cy <= y_max_norm)
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]

def apply_min_size_filter(boxes, logits, phrases, min_size):
    if len(boxes) == 0: return boxes, logits, phrases
    w, h = boxes[:, 2], boxes[:, 3]
    keep = (w >= min_size) & (h >= min_size)
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]

def apply_aspect_ratio_filter(boxes, logits, phrases, max_ratio):
    if len(boxes) == 0: return boxes, logits, phrases
    w, h = boxes[:, 2], boxes[:, 3]
    aspect = np.maximum(w, h) / np.clip(np.minimum(w, h), 1e-6, None)
    keep = aspect <= max_ratio
    kept_idx = np.where(keep)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]

def apply_containment_filter(boxes, logits, phrases, threshold):
    if len(boxes) == 0: return boxes, logits, phrases
    corners = _to_corners_batch(boxes)
    areas = (corners[:, 2] - corners[:, 0]) * (corners[:, 3] - corners[:, 1])
    x1 = np.maximum(corners[:, None, 0], corners[None, :, 0])
    y1 = np.maximum(corners[:, None, 1], corners[None, :, 1])
    x2 = np.minimum(corners[:, None, 2], corners[None, :, 2])
    y2 = np.minimum(corners[:, None, 3], corners[None, :, 3])
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    cont = np.where(areas[:, None] > 0, inter / areas[:, None], 0.0)
    is_group = np.zeros(len(boxes), dtype=bool)
    for j in range(len(boxes)):
        smaller = areas < areas[j]
        if np.any(smaller & (cont[:, j] >= threshold)):
            is_group[j] = True
    kept_idx = np.where(~is_group)[0]
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]

def apply_center_distance_filter(boxes, logits, phrases, dist_threshold):
    if len(boxes) == 0: return boxes, logits, phrases
    order = np.argsort(logits)[::-1]
    active = np.ones(len(boxes), dtype=bool)
    kept = []
    for idx in order:
        if not active[idx]: continue
        kept.append(idx)
        active_idx = np.where(active)[0]
        dists = np.sqrt((boxes[active_idx, 0] - boxes[idx, 0])**2 + 
                        (boxes[active_idx, 1] - boxes[idx, 1])**2)
        too_close = active_idx[dists < dist_threshold]
        active[too_close[too_close != idx]] = False
    kept_idx = sorted(kept)
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]

def apply_nms(boxes, logits, phrases, iou_threshold):
    if len(boxes) == 0: return boxes, logits, phrases
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
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]

def apply_pallet_filter(boxes, logits, phrases, box_idx, pallet_idx, containment_threshold=0.5):
    """Actualizado: detecta correctamente pallets vacíos y ocupados."""
    if len(pallet_idx) == 0:
        return box_idx, pallet_idx

    pw, ph = boxes[pallet_idx, 2], boxes[pallet_idx, 3]
    aspect = np.maximum(pw, ph) / np.clip(np.minimum(pw, ph), 1e-6, None)
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
    inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
    areas_box = (bc[:, 2] - bc[:, 0]) * (bc[:, 3] - bc[:, 1])
    cont = np.where(areas_box[:, None] > 0, inter / areas_box[:, None], 0.0)
    has_boxes = np.any(cont >= containment_threshold, axis=0)

    return box_idx, surviving[~has_boxes]


# ============================================================
#  🎬  CAPTURA DE STREAM
# ============================================================

class StreamCapture:
    def __init__(self, url):
        self.url = url
        self.cap = None
        self.frame = None
        self.lock = Lock()
        self.running = False
        self.connected = False
        
    def start(self):
        self.running = True
        self.thread = Thread(target=self._capture_loop, daemon=True)
        self.thread.start()
        
        timeout = 10
        start = time.time()
        while not self.connected and time.time() - start < timeout:
            time.sleep(0.1)
        
        return self.connected
    
    def _capture_loop(self):
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                print(f"📡 Conectando a {self.url}...")
                self.cap = cv2.VideoCapture(self.url)
                self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1) 
                
                if self.cap.isOpened():
                    self.connected = True
                    print("✅ Conectado al stream")
                else:
                    time.sleep(2)
                    continue
            
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
            else:
                self.connected = False
                self.cap.release()
                self.cap = None
                time.sleep(1)
    
    def read(self):
        with self.lock:
            return self.frame.copy() if self.frame is not None else None
    
    def stop(self):
        self.running = False
        if self.cap:
            self.cap.release()


# ============================================================
#  🖊️  VISUALIZACIÓN
# ============================================================

def draw_detections(image, boxes, logits, phrases, img_height, img_width, contornos=None):
    """Dibuja bounding boxes y contornos de SAM si existen."""
    # Dibujar contornos primero para que queden bajo las cajas
    if contornos:
        for item in contornos:
            pts = np.array(item['poligono_simple'], np.int32)
            pts = pts.reshape((-1, 1, 2))
            cv2.polylines(image, [pts], isClosed=True, color=(255, 0, 255), thickness=2)
            
            # (Opcional) Rellenar semitransparente
            overlay = image.copy()
            cv2.fillPoly(overlay, [pts], (255, 0, 255))
            cv2.addWeighted(overlay, 0.3, image, 0.7, 0, image)

    # Dibujar Bounding Boxes
    for box, score, phrase in zip(boxes, logits, phrases):
        cx, cy, bw, bh = box
        x1 = int((cx - bw/2) * img_width)
        y1 = int((cy - bh/2) * img_height)
        x2 = int((cx + bw/2) * img_width)
        y2 = int((cy + bh/2) * img_height)
        
        color = (0, int(255 * score), int(255 * (1 - score)))
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 3)
        
        label = f"{phrase[:12]} {score:.2f}"
        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 2)
        cv2.rectangle(image, (x1, y1 - th - 6), (x1 + tw + 4, y1), color, -1)
        cv2.putText(image, label, (x1 + 2, y1 - 4), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 2)
    
    return image


def draw_overlay(image, fps, n_detections, frame_skip, paused, valid_zones=None):
    h, w = image.shape[:2]
    status = "PAUSADO" if paused else "EN VIVO"
    lines = [
        f"{status} | FPS: {fps:.1f}",
        f"Cajas: {n_detections} | Skip: {frame_skip} | SAM: {'ON' if ENABLE_SAM_REALTIME else 'OFF'}",
        "[Q]Salir [S]Guardar [P]Pausa [+/-]Skip",
    ]
    
    font, fs, th = cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2
    for i, line in enumerate(lines):
        y = 30 + i * 30
        cv2.putText(image, line, (12, y), font, fs, (0, 0, 0), th + 2)
        cv2.putText(image, line, (10, y), font, fs, (0, 255, 255), th)
    
    if valid_zones:
        for y_min, y_max in valid_zones:
            cv2.line(image, (0, y_min), (w, y_min), (0, 255, 0), 2)
            cv2.line(image, (0, y_max), (w, y_max), (0, 0, 255), 2)
    
    return image


# ============================================================
#  🔍  PROCESAMIENTO UNIFICADO
# ============================================================

def process_frame(model, sam_model, frame_bgr):
    h, w = frame_bgr.shape[:2]
    
    if PROCESS_WIDTH and w > PROCESS_WIDTH:
        scale = PROCESS_WIDTH / w
        proc_frame = cv2.resize(frame_bgr, None, fx=scale, fy=scale)
    else:
        proc_frame = frame_bgr
        scale = 1.0
    
    proc_h, proc_w = proc_frame.shape[:2]
    
    beams = detect_orange_beams(proc_frame)
    valid_zones = get_valid_zones(beams, proc_h)
    
    if valid_zones and scale != 1.0:
        valid_zones = [(int(y1/scale), int(y2/scale)) for y1, y2 in valid_zones]
    
    frame_rgb = cv2.cvtColor(proc_frame, cv2.COLOR_BGR2RGB)
    image = torch.from_numpy(frame_rgb).permute(2, 0, 1).float() / 255.0
    
    with torch.no_grad():
        raw_boxes, raw_logits, raw_phrases = predict(
            model=model,
            image=image,
            caption=TEXT_PROMPT,
            box_threshold=BOX_THRESHOLD,
            text_threshold=TEXT_THRESHOLD,
            device=DEVICE,
        )
    
    boxes = raw_boxes.numpy()
    logits = raw_logits.numpy()
    phrases = list(raw_phrases)
    
    if len(boxes) == 0:
        return np.array([]), np.array([]), [], valid_zones, []
    
    box_idx, pallet_idx = split_boxes_pallets(boxes, logits, phrases)
    b, l, ph = boxes[box_idx], logits[box_idx], [phrases[i] for i in box_idx]
    
    # Cascade Pipeline 1-6
    b, l, ph = apply_beam_zone_filter(b, l, ph, get_valid_zones(beams, proc_h), proc_h)
    b, l, ph = apply_min_size_filter(b, l, ph, MIN_BOX_SIZE)
    b, l, ph = apply_aspect_ratio_filter(b, l, ph, MAX_BOX_ASPECT_RATIO)
    b, l, ph = apply_containment_filter(b, l, ph, CONTAINMENT_THRESHOLD)
    b, l, ph = apply_center_distance_filter(b, l, ph, CENTER_DIST_THRESHOLD)
    b, l, ph = apply_nms(b, l, ph, IOU_THRESHOLD)
    
    # 7 - Pallet Filter unificado
    if len(pallet_idx) > 0:
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

    # 8 - SAM Contornos (Si está activado)
    contornos = []
    if ENABLE_SAM_REALTIME and len(b) > 0 and sam_model is not None:
        contornos = segmentar_cajas(
            image_bgr=proc_frame,
            boxes=b,
            logits=l,
            phrases=ph,
            sam_model=sam_model,
            run_dir=None, # No guardamos imágenes debug en realtime
            stem=None
        )

    return b, l, ph, valid_zones, contornos


# ============================================================
#  🏁  MAIN
# ============================================================

def main():
    global FRAME_SKIP
    
    print(f"⚡ Dispositivo: {DEVICE.upper()}")
    print("📦 Cargando modelo GroundingDINO...")
    model = load_model(CONFIG_PATH, WEIGHTS_PATH).to(DEVICE)
    model.eval()

    sam_model = None
    if ENABLE_SAM_REALTIME:
        print("🪄 Cargando modelo Segment Anything (SAM)...")
        sam_model = cargar_segmentador()
    
    output_dir = Path(OUTPUT_BASE)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    stream = StreamCapture(STREAM_URL)
    if not stream.start():
        print(f"❌ No se pudo conectar a {STREAM_URL}")
        return
    
    print("\n🎬 Iniciando detección en tiempo real...")
    print("   Controles: [Q]Salir [S]Guardar [P]Pausa [+/-]Skip\n")
    
    frame_count = 0
    fps = 0.0
    fps_start = time.time()
    fps_frames = 0
    paused = False
    
    last_boxes = np.array([])
    last_logits = np.array([])
    last_phrases = []
    last_zones = None
    last_contours = []
    
    while True:
        frame = stream.read()
        if frame is None:
            time.sleep(0.01)
            continue
        
        h, w = frame.shape[:2]
        display = frame.copy()
        
        if not paused and frame_count % FRAME_SKIP == 0:
            last_boxes, last_logits, last_phrases, last_zones, last_contours = process_frame(model, sam_model, frame)
            
            if SAVE_ON_DETECTION and len(last_boxes) > 0:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
                save_path = output_dir / f"det_{timestamp}.jpg"
                annotated = draw_detections(frame.copy(), last_boxes, last_logits, 
                                           last_phrases, h, w, last_contours)
                annotated = draw_overlay(annotated, fps, len(last_boxes), 
                                        FRAME_SKIP, paused, last_zones)
                cv2.imwrite(str(save_path), annotated)
            
            fps_frames += 1
        
        if len(last_boxes) > 0:
            display = draw_detections(display, last_boxes, last_logits, 
                                     last_phrases, h, w, last_contours)
        
        if time.time() - fps_start >= 1.0:
            fps = fps_frames / (time.time() - fps_start)
            fps_start = time.time()
            fps_frames = 0
        
        display = draw_overlay(display, fps, len(last_boxes), FRAME_SKIP, paused, last_zones)
        
        if DISPLAY_SCALE != 1.0:
            display = cv2.resize(display, None, fx=DISPLAY_SCALE, fy=DISPLAY_SCALE)
        
        cv2.imshow("Detector Almacen - Tiempo Real", display)
        
        key = cv2.waitKey(1) & 0xFF
        if key == ord('q'):
            break
        elif key == ord('s'):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            save_path = output_dir / f"manual_{timestamp}.jpg"
            cv2.imwrite(str(save_path), display)
            print(f"💾 Guardado: {save_path}")
        elif key == ord('p'):
            paused = not paused
            print(f"{'⏸️ Pausado' if paused else '▶️ Reanudado'}")
        elif key == ord('+') or key == ord('='):
            FRAME_SKIP = min(FRAME_SKIP + 1, 30)
            print(f"⏭️ Frame skip: {FRAME_SKIP}")
        elif key == ord('-'):
            FRAME_SKIP = max(FRAME_SKIP - 1, 1)
            print(f"⏮️ Frame skip: {FRAME_SKIP}")
        
        frame_count += 1
    
    stream.stop()
    cv2.destroyAllWindows()
    print("\n✅ Finalizado")
    print(f"💾 Capturas guardadas en: {output_dir}")

if __name__ == "__main__":
    main()