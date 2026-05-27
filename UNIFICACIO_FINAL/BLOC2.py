
# BLOC 2: DETECCIO (GroundingDINO) + FILTRAT + TRACKING DE CAIXES
#
# Substitueix el detector YOLO per GroundingDINO. La signatura publica
# (extreure_ids_i_posicions) i el format de sortida son IDENTICS a la versio
# YOLO, aixi que BLOC0 no necessita canvis a la logica, nomes a la carrega
# del detector (veure snippet de BLOC0).
#
# Cascada de filtres: beam_zone -> min_size -> aspect -> containment ->
#                     dist_centres -> NMS

import os
import cv2
import math
import torch
import numpy as np
from PIL import Image

from groundingdino.util.inference import predict
import groundingdino.datasets.transforms as T


# ==========================================
# CONFIGURACIO GROUNDINGDINO
# ==========================================
GD_TEXT_PROMPT     = "cardboard box . box . carton . stacked cardboard box . pallet ."
GD_BOX_THRESHOLD   = 0.19
GD_TEXT_THRESHOLD  = 0.30
GD_DEVICE          = "cuda" if torch.cuda.is_available() else "cpu"

# ==========================================
# CONFIGURACIO DE FILTRES GEOMETRICS (mateixos valors que la versio YOLO)
# ==========================================
MIN_BOX_SIZE_NORM          = 0.06
MAX_BOX_ASPECT_RATIO       = 2.2
CONTAINMENT_THRESHOLD      = 0.5
CENTER_DIST_THRESHOLD_NORM = 0.05
IOU_THRESHOLD              = 0.7

# ==========================================
# CONFIGURACIO DEL FILTRE DE PALLETS (portat de prueba_detector_almacen2.py)
# ==========================================
PALLET_KEYWORDS         = {"pallet"}
PALLET_MIN_ASPECT_RATIO = 2.5

# ==========================================
# CONFIGURACIO DETECCIO DE VIGUES TARONJA (portat de prueba_detector_almacen.py)
# ==========================================
BEAM_HSV_LOW       = np.array([8, 150, 120])
BEAM_HSV_HIGH      = np.array([18, 255, 255])
BEAM_ROW_THRESHOLD = 0.25      # % d'amplada que ha d'estar saturada de taronja
BEAM_MIN_HEIGHT_PX = 10        # alcada minima per considerar-ho una viga
BEAM_PALLET_RATIO  = 0.18      # marge inferior de cada nivell (zona del pallet)
# ==========================================


# ============================================================
#  GROUNDINGDINO: BGR (np) -> tensor -> prediccio -> xyxy en pixels
# ============================================================

_GD_TRANSFORM = T.Compose([
   T.RandomResize([800], max_size=1333),
   T.ToTensor(),
   T.Normalize([0.485, 0.456, 0.406], [0.229, 0.224, 0.225]),
])


def _img_bgr_to_tensor(img_bgr):
   """OpenCV BGR -> tensor que espera GroundingDINO."""
   img_rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
   pil = Image.fromarray(img_rgb)
   tensor, _ = _GD_TRANSFORM(pil, None)
   return tensor


def _predir_groundingdino(img_bgr, model):
   """
   Crida GroundingDINO i retorna:
       boxes_xyxy  np.float32 (N, 4)  en pixels absoluts
       scores      np.float32 (N,)
       phrases     list[str]          etiqueta textual de cada deteccio
   """
   image_t = _img_bgr_to_tensor(img_bgr)
   boxes_cxcywh, logits, phrases = predict(
       model=model,
       image=image_t,
       caption=GD_TEXT_PROMPT,
       box_threshold=GD_BOX_THRESHOLD,
       text_threshold=GD_TEXT_THRESHOLD,
       device=GD_DEVICE,
   )

   if boxes_cxcywh is None or len(boxes_cxcywh) == 0:
       return np.zeros((0, 4), dtype=np.float32), np.zeros((0,), dtype=np.float32), []

   H, W = img_bgr.shape[:2]
   b = boxes_cxcywh.cpu().numpy()
   cx, cy, bw, bh = b[:, 0], b[:, 1], b[:, 2], b[:, 3]
   boxes_xyxy = np.stack([
       (cx - bw / 2.0) * W,
       (cy - bh / 2.0) * H,
       (cx + bw / 2.0) * W,
       (cy + bh / 2.0) * H,
   ], axis=1).astype(np.float32)
   scores = logits.cpu().numpy().astype(np.float32)
   return boxes_xyxy, scores, list(phrases)


# ============================================================
#  DETECCIO DE VIGUES TARONJA (proieccio horitzontal HSV)
# ============================================================

def _detect_orange_beams(img_bgr):
   """Retorna llista de vigues com a tuples (y_top, y_bottom)."""
   h, w = img_bgr.shape[:2]
   hsv  = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2HSV)
   mask = cv2.inRange(hsv, BEAM_HSV_LOW, BEAM_HSV_HIGH)
   projection   = np.sum(mask > 0, axis=1)
   threshold_px = w * BEAM_ROW_THRESHOLD
   is_beam_row  = projection >= threshold_px

   beams   = []
   in_beam = False
   y_start = 0
   for y in range(h):
       if is_beam_row[y] and not in_beam:
           in_beam = True
           y_start = y
       elif not is_beam_row[y] and in_beam:
           in_beam = False
           if (y - y_start) >= BEAM_MIN_HEIGHT_PX:
               beams.append((y_start, y))
   if in_beam and (h - y_start) >= BEAM_MIN_HEIGHT_PX:
       beams.append((y_start, h))
   return beams


def _get_valid_zones(beams, img_height):
   """A partir de les vigues, retorna llista de (y_min, y_max) vàlides."""
   if not beams:
       return None

   zones = []
   if len(beams) == 1:
       top    = beams[0][0]
       margin = int(top * BEAM_PALLET_RATIO)
       if top - margin > 0:
           zones.append((0, top - margin))
   else:
       for i in range(len(beams) - 1):
           y_upper = beams[i][1]
           y_lower = beams[i + 1][0]
           margin  = int((y_lower - y_upper) * BEAM_PALLET_RATIO)
           if y_lower - margin > y_upper:
               zones.append((y_upper, y_lower - margin))
       if beams[0][0] > 50:
           margin = int(beams[0][0] * BEAM_PALLET_RATIO)
           if beams[0][0] - margin > 0:
               zones.insert(0, (0, beams[0][0] - margin))

   return zones if zones else None


# ============================================================
#  SEPARACIO CAIXES / PALLETS (portat de prueba_detector_almacen2.py)
# ============================================================

def split_boxes_pallets(phrases):
   """Separa indexs de deteccions 'box' (~pallet) i 'pallet' segons l'etiqueta."""
   pallet_mask = np.array([
       any(kw in p.lower() for kw in PALLET_KEYWORDS)
       for p in phrases
   ], dtype=bool)
   if len(pallet_mask) == 0:
       return np.array([], dtype=int), np.array([], dtype=int)
   return np.where(~pallet_mask)[0], np.where(pallet_mask)[0]


def apply_pallet_filter(boxes_xyxy, box_idx, pallet_idx,
                       containment_threshold=CONTAINMENT_THRESHOLD):
   """
   Descarta pallets vuits (aspect ratio allargat) i ocupats (amb caixes a sobre).
   Treballa amb caixes en format xyxy (pixels). Retorna (box_idx, pallets_supervivents);
   box_idx no es modifica mai (els pallets supervivents no es retornen a BLOC0).
   """
   if len(pallet_idx) == 0:
       return box_idx, pallet_idx

   arr = np.asarray(boxes_xyxy, dtype=np.float32)
   pw  = arr[pallet_idx, 2] - arr[pallet_idx, 0]
   ph  = arr[pallet_idx, 3] - arr[pallet_idx, 1]
   aspect       = np.maximum(pw, ph) / np.clip(np.minimum(pw, ph), 1e-6, None)
   empty_pallet = aspect >= PALLET_MIN_ASPECT_RATIO

   if empty_pallet.sum():
       print(f"   [pallet]      buit: descartats {int(empty_pallet.sum())} pallet(s)")

   surviving = pallet_idx[~empty_pallet]

   if len(surviving) == 0 or len(box_idx) == 0:
       return box_idx, surviving

   bc = arr[box_idx]
   pc = arr[surviving]
   x1 = np.maximum(bc[:, None, 0], pc[None, :, 0])
   y1 = np.maximum(bc[:, None, 1], pc[None, :, 1])
   x2 = np.minimum(bc[:, None, 2], pc[None, :, 2])
   y2 = np.minimum(bc[:, None, 3], pc[None, :, 3])
   inter     = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
   areas_box = (bc[:, 2] - bc[:, 0]) * (bc[:, 3] - bc[:, 1])
   cont      = np.where(areas_box[:, None] > 0, inter / areas_box[:, None], 0.0)
   has_boxes = np.any(cont >= containment_threshold, axis=0)

   if has_boxes.sum():
       print(f"   [pallet]      ocupat: descartats {int(has_boxes.sum())} pallet(s) amb caixes a sobre")

   return box_idx, surviving[~has_boxes]


# ============================================================
#  FILTRES (cascada)
# ============================================================

def _filtre_beam_zone(boxes, scores, img_bgr):
   """Descarta deteccions el centre Y de les quals queda fora de zones valides."""
   if len(boxes) == 0:
       return boxes, scores
   H     = img_bgr.shape[0]
   beams = _detect_orange_beams(img_bgr)
   zones = _get_valid_zones(beams, H)
   if zones is None:
       print("   [beam_zone]   sense vigues detectades, no s'aplica")
       return boxes, scores

   arr  = np.array(boxes, dtype=np.float32)
   cy   = (arr[:, 1] + arr[:, 3]) / 2.0
   keep = np.zeros(len(arr), dtype=bool)
   for y_min, y_max in zones:
       keep |= (cy >= y_min) & (cy <= y_max)

   if (~keep).sum():
       print(f"   [beam_zone]   elim. {(~keep).sum()} (fora de {len(zones)} zona/es)")
   return arr[keep].tolist(), scores[keep]


def _filtre_min_size(boxes, scores, img_shape):
   if len(boxes) == 0: return boxes, scores
   H, W = img_shape[:2]
   arr = np.array(boxes, dtype=np.float32)
   w, h = arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1]
   keep = (w >= MIN_BOX_SIZE_NORM * W) & (h >= MIN_BOX_SIZE_NORM * H)
   if (~keep).sum(): print(f"   [min_size]    elim. {(~keep).sum()}")
   return arr[keep].tolist(), scores[keep]


def _filtre_aspect_ratio(boxes, scores):
   if len(boxes) == 0: return boxes, scores
   arr = np.array(boxes, dtype=np.float32)
   w, h = arr[:, 2] - arr[:, 0], arr[:, 3] - arr[:, 1]
   aspect = np.maximum(w, h) / np.clip(np.minimum(w, h), 1e-6, None)
   keep = aspect <= MAX_BOX_ASPECT_RATIO
   if (~keep).sum(): print(f"   [aspect]      elim. {(~keep).sum()}")
   return arr[keep].tolist(), scores[keep]


def _filtre_containment(boxes, scores):
   if len(boxes) == 0: return boxes, scores
   arr = np.array(boxes, dtype=np.float32)
   x1 = np.maximum(arr[:, None, 0], arr[None, :, 0])
   y1 = np.maximum(arr[:, None, 1], arr[None, :, 1])
   x2 = np.minimum(arr[:, None, 2], arr[None, :, 2])
   y2 = np.minimum(arr[:, None, 3], arr[None, :, 3])
   inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
   areas = (arr[:, 2] - arr[:, 0]) * (arr[:, 3] - arr[:, 1])
   cont  = np.where(areas[:, None] > 0, inter / areas[:, None], 0.0)
   is_group = np.zeros(len(arr), dtype=bool)
   for j in range(len(arr)):
       smaller = areas < areas[j]
       if np.any(smaller & (cont[:, j] >= CONTAINMENT_THRESHOLD)):
           is_group[j] = True
   if is_group.sum(): print(f"   [containment] elim. {is_group.sum()} (grups)")
   return arr[~is_group].tolist(), scores[~is_group]


def _filtre_dist_centres(boxes, scores, img_shape):
   if len(boxes) == 0: return boxes, scores
   H, W = img_shape[:2]
   thr  = CENTER_DIST_THRESHOLD_NORM * np.hypot(W, H)
   arr  = np.array(boxes, dtype=np.float32)
   cx   = (arr[:, 0] + arr[:, 2]) / 2
   cy   = (arr[:, 1] + arr[:, 3]) / 2
   order  = np.argsort(scores)[::-1]
   active = np.ones(len(arr), dtype=bool)
   kept   = []
   for idx in order:
       if not active[idx]: continue
       kept.append(idx)
       ai = np.where(active)[0]
       d  = np.hypot(cx[ai] - cx[idx], cy[ai] - cy[idx])
       active[ai[(d < thr) & (ai != idx)]] = False
   kept = sorted(kept)
   if len(arr) - len(kept): print(f"   [dist_centres] elim. {len(arr)-len(kept)}")
   return arr[kept].tolist(), scores[kept]


def _filtre_nms(boxes, scores):
   if len(boxes) == 0: return boxes, scores
   arr = np.array(boxes, dtype=np.float32)
   x1 = np.maximum(arr[:, None, 0], arr[None, :, 0])
   y1 = np.maximum(arr[:, None, 1], arr[None, :, 1])
   x2 = np.minimum(arr[:, None, 2], arr[None, :, 2])
   y2 = np.minimum(arr[:, None, 3], arr[None, :, 3])
   inter = np.maximum(0, x2 - x1) * np.maximum(0, y2 - y1)
   areas = (arr[:, 2] - arr[:, 0]) * (arr[:, 3] - arr[:, 1])
   union = areas[:, None] + areas[None, :] - inter
   iou   = np.where(union > 0, inter / union, 0.0)
   order = np.argsort(scores)[::-1].tolist()
   kept  = []
   while order:
       best = order.pop(0)
       kept.append(best)
       order = [i for i in order if iou[best, i] < IOU_THRESHOLD]
   kept = sorted(kept)
   if len(arr) - len(kept): print(f"   [NMS]         elim. {len(arr)-len(kept)}")
   return arr[kept].tolist(), scores[kept]


def aplicar_filtres(boxes, scores, img_bgr):
   """Cascada: beam_zone -> min_size -> aspect -> containment -> dist_centres -> NMS."""
   img_shape = img_bgr.shape
   print(f"   [FILTRES] inici: {len(boxes)} deteccions")
   boxes, scores = _filtre_beam_zone(boxes, scores, img_bgr)
   boxes, scores = _filtre_min_size(boxes, scores, img_shape)
   boxes, scores = _filtre_aspect_ratio(boxes, scores)
   boxes, scores = _filtre_containment(boxes, scores)
   boxes, scores = _filtre_dist_centres(boxes, scores, img_shape)
   boxes, scores = _filtre_nms(boxes, scores)
   print(f"   [FILTRES] final: {len(boxes)} deteccions")
   return boxes, scores


# ============================================================
#  TRACKING (idèntic a la versió YOLO)
# ============================================================

DISTANCIA_REF_CM   = 150.0
TRACKING_REF_PX    = 400.0
MAX_FRAMES_MISSING = 3

següent_id_caixa = 1
caixes_actives_amb_memoria = {}


def obtenir_color_aleatori():
   return (int(np.random.randint(50, 255)),
           int(np.random.randint(50, 255)),
           int(np.random.randint(50, 255)))


def tracking_robust_amb_memoria(deteccions_actuals, distancia_lidar_cm):
   global següent_id_caixa, caixes_actives_amb_memoria

   id_actuals_assignats = []
   radi_tracking_dinamic = TRACKING_REF_PX * (DISTANCIA_REF_CM / distancia_lidar_cm)

   ids_ja_assignats         = set()
   deteccions_ja_assignades = set()

   parelles = []
   for idx, (cx_nova, cy_nova) in enumerate(deteccions_actuals):
       for id_vell, info_vella in caixes_actives_amb_memoria.items():
           cx_antic, cy_antic = info_vella['centroide']
           dist = math.hypot(cx_nova - cx_antic, cy_nova - cy_antic)
           if dist < radi_tracking_dinamic:
               parelles.append((dist, idx, id_vell))

   parelles.sort(key=lambda x: x[0])

   for dist, idx, id_vell in parelles:
       if idx in deteccions_ja_assignades: continue
       if id_vell in ids_ja_assignats:     continue

       cx_nova, cy_nova = deteccions_actuals[idx]
       caixes_actives_amb_memoria[id_vell]['centroide'] = (cx_nova, cy_nova)
       caixes_actives_amb_memoria[id_vell]['misses']    = 0
       info = caixes_actives_amb_memoria[id_vell]
       id_actuals_assignats.append({'id': id_vell, 'centroide': (cx_nova, cy_nova), 'color': info['color']})
       ids_ja_assignats.add(id_vell)
       deteccions_ja_assignades.add(idx)

   for idx, (cx_nova, cy_nova) in enumerate(deteccions_actuals):
       if idx in deteccions_ja_assignades: continue
       nou_id = següent_id_caixa
       color  = obtenir_color_aleatori()
       caixes_actives_amb_memoria[nou_id] = {'centroide': (cx_nova, cy_nova), 'misses': 0, 'color': color}
       id_actuals_assignats.append({'id': nou_id, 'centroide': (cx_nova, cy_nova), 'color': color})
       següent_id_caixa += 1
       ids_ja_assignats.add(nou_id)

   ids_a_eliminar = []
   for id_vell in caixes_actives_amb_memoria:
       if id_vell not in ids_ja_assignats:
           caixes_actives_amb_memoria[id_vell]['misses'] += 1
           if caixes_actives_amb_memoria[id_vell]['misses'] > MAX_FRAMES_MISSING:
               ids_a_eliminar.append(id_vell)

   for i_d in ids_a_eliminar:
       del caixes_actives_amb_memoria[i_d]

   return id_actuals_assignats


# ============================================================
#  FUNCIO PUBLICA (mateixa signatura, mateix format de sortida)
# ============================================================

def extreure_ids_i_posicions(img, detector, segmentador, distancia_lidar_cm):
   """
   Entry point que crida BLOC0.

   Args:
       img:                imatge BGR (np.ndarray) llegida amb cv2.imread
       detector:           model GroundingDINO carregat amb load_model(...).to(device)
       segmentador:        model SAM (Ultralytics)
       distancia_lidar_cm: distancia del LIDAR per ajustar el radi de tracking

   Returns:
       Llista de dicts amb les mateixes claus que la versio YOLO:
       [{'id', 'bbox', 'color', 'contorn', 'cx', 'cy'}, ...]
   """
   caixes_detectades_frame = []

   # 1) Deteccio amb GroundingDINO
   boxes_xyxy, scores, phrases = _predir_groundingdino(img, detector)

   if len(boxes_xyxy) == 0:
       return caixes_detectades_frame

   # 1b) Separacio caixes / pallets segons l'etiqueta de GroundingDINO.
   #     Els pallets s'exclouen de la cascada (no es segmenten ni es mesura volum).
   box_idx, pallet_idx = split_boxes_pallets(phrases)
   boxes_caixes  = boxes_xyxy[box_idx]
   scores_caixes = scores[box_idx]

   # 2) Filtres en cascada (beam_zone + els existents) nomes sobre les caixes
   caixes_dino, scores = aplicar_filtres(boxes_caixes.tolist(), scores_caixes, img)

   if len(caixes_dino) == 0:
       return caixes_detectades_frame

   # 2b) Filtre de pallets: descarta pallets vuits/ocupats. No modifica les caixes
   #     (els pallets supervivents no es retornen a BLOC0), pero es manté la passada
   #     per fidelitat amb prueba_detector_almacen2.py.
   caixes_arr = np.array(caixes_dino, dtype=np.float32).reshape(-1, 4)
   all_boxes  = np.concatenate([caixes_arr, boxes_xyxy[pallet_idx]], axis=0)
   kept_box_idx, _ = apply_pallet_filter(
       all_boxes,
       box_idx=np.arange(len(caixes_arr)),
       pallet_idx=np.arange(len(caixes_arr), len(caixes_arr) + len(pallet_idx)),
   )
   caixes_dino = [caixes_dino[i] for i in kept_box_idx]
   scores      = scores[kept_box_idx]

   # 3) Segmentació SAM + centroides (idèntic a la versió YOLO)
   centroides_actuals = []
   info_caixes        = []

   for box in caixes_dino:
       x1, y1, x2, y2 = map(int, box)
       marge          = 60
       box_ampliada   = [
           max(0, x1 - marge),
           max(0, y1 - marge),
           min(img.shape[1], x2 + marge),
           min(img.shape[0], y2 + marge),
       ]

       resultats_sam = segmentador.predict(img, bboxes=box_ampliada, verbose=False)

       if resultats_sam[0].masks is not None and len(resultats_sam[0].masks.xy) > 0:
           contorn_np = np.array(resultats_sam[0].masks.xy[0], dtype=np.int32)
           moments    = cv2.moments(contorn_np)
           if moments["m00"] != 0:
               cx = int(moments["m10"] / moments["m00"])
               cy = int(moments["m01"] / moments["m00"])
           else:
               cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)

           centroides_actuals.append((cx, cy))
           info_caixes.append({
               'bbox_ampliada': box_ampliada,
               'cx': cx, 'cy': cy,
               'contorn': contorn_np,
           })

   # 4) Tracking amb memòria (idèntic)
   ids_assignats_finals = tracking_robust_amb_memoria(centroides_actuals, distancia_lidar_cm)

   # 5) Format de sortida idèntic al BLOC2 original
   for caixa in info_caixes:
       for id_info in ids_assignats_finals:
           if math.hypot(caixa['cx'] - id_info['centroide'][0],
                         caixa['cy'] - id_info['centroide'][1]) < 5:
               caixes_detectades_frame.append({
                   'id':      id_info['id'],
                   'bbox':    caixa['bbox_ampliada'],
                   'color':   id_info['color'],
                   'contorn': caixa['contorn'],
                   'cx':      caixa['cx'],
                   'cy':      caixa['cy'],
               })
               break

   return caixes_detectades_frame


