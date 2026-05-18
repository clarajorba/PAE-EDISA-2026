import os
import cv2
import numpy as np
import math
import torch
from PIL import Image
import torchvision.transforms.functional as TF
from ultralytics import SAM
from groundingdino.util.inference import predict as gdino_predict

# ==========================================
# CONFIGURACIÓ GROUNDINGDINO
# ==========================================
GDINO_PROMPT  = "cardboard box . box . carton . stacked cardboard box . warehouse package . pallet ."
GDINO_BOX_THR = 0.19
GDINO_TXT_THR = 0.3
DEVICE        = "cuda" if torch.cuda.is_available() else "cpu"

# ==========================================
# CONFIGURACIÓ PRINCIPAL (BLOC 2)
# ==========================================
CARPETA_FOTOS_SEQ = "../fotos_caixa"
CARPETA_RESULTATS = "outputs/Resultats_BLOC2"


def _prepare_gdino_image(img_bgr: np.ndarray) -> torch.Tensor:
    """Convierte imagen BGR numpy al tensor normalizado que espera GroundingDINO."""
    rgb = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    w, h = pil.size
    scale = 800 / min(w, h)
    if max(w, h) * scale > 1333:
        scale = 1333 / max(w, h)
    pil = pil.resize((int(round(w * scale)), int(round(h * scale))), Image.BILINEAR)
    tensor = TF.to_tensor(pil)
    return TF.normalize(tensor, [0.485, 0.456, 0.406], [0.229, 0.224, 0.225])

# ==========================================
# CONFIGURACIÓ DE FILTRES GEOMÈTRICS
# ==========================================
MIN_BOX_SIZE_NORM          = 0.06   # fracció de la dim. de la imatge
MAX_BOX_ASPECT_RATIO       = 2.2
CONTAINMENT_THRESHOLD      = 0.5
CENTER_DIST_THRESHOLD_NORM = 0.05   # fracció de la diagonal
IOU_THRESHOLD              = 0.7
# ==========================================


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
    thr = CENTER_DIST_THRESHOLD_NORM * np.hypot(W, H)
    arr = np.array(boxes, dtype=np.float32)
    cx = (arr[:, 0] + arr[:, 2]) / 2
    cy = (arr[:, 1] + arr[:, 3]) / 2
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


def aplicar_filtres(boxes, scores, img_shape):
    """Cascada: min_size → aspect → containment → dist_centres → NMS."""
    print(f"   [FILTRES] inici: {len(boxes)} deteccions")
    boxes, scores = _filtre_min_size(boxes, scores, img_shape)
    boxes, scores = _filtre_aspect_ratio(boxes, scores)
    boxes, scores = _filtre_containment(boxes, scores)
    boxes, scores = _filtre_dist_centres(boxes, scores, img_shape)
    boxes, scores = _filtre_nms(boxes, scores)
    print(f"   [FILTRES] final: {len(boxes)} deteccions")
    return boxes, scores


DISTANCIA_REF_CM = 150.0
TRACKING_REF_PX = 400.0 
MAX_FRAMES_MISSING = 3 #1 (estic fent proves)
# ==========================================

següent_id_caixa = 1
caixes_actives_amb_memoria = {}

def obtenir_color_aleatori():
    return (int(np.random.randint(50, 255)), 
            int(np.random.randint(50, 255)), 
            int(np.random.randint(50, 255)))

def tracking_robust_amb_memoria(deteccions_actuals, distancia_lidar_cm):
    """
    Assignació òptima global: construïm totes les parelles possibles
    (detecció_nova, id_conegut) ordenades per distància de menor a major,
    i les assignem en ordre. Això garanteix que la parella més clara
    (la Epson ja coneguda) sempre s'assigna primer, independentment de
    l'ordre en què YOLO retorna les deteccions.
    """
    global següent_id_caixa, caixes_actives_amb_memoria

    id_actuals_assignats = []
    radi_tracking_dinamic = TRACKING_REF_PX * (DISTANCIA_REF_CM / distancia_lidar_cm)

    ids_ja_assignats = set()      # IDs antics ja aparellats
    deteccions_ja_assignades = set()  # Índexs de deteccions ja aparellades

    # 1. Construïm la matriu de distàncies entre totes les deteccions i tots els IDs coneguts
    parelles = []  # (distancia, idx_deteccio, id_vell)
    for idx, (cx_nova, cy_nova) in enumerate(deteccions_actuals):
        for id_vell, info_vella in caixes_actives_amb_memoria.items():
            cx_antic, cy_antic = info_vella['centroide']
            dist = math.hypot(cx_nova - cx_antic, cy_nova - cy_antic)
            if dist < radi_tracking_dinamic:
                parelles.append((dist, idx, id_vell))

    # 2. Ordenem per distància: les parelles més clares s'assignen primer
    parelles.sort(key=lambda x: x[0])

    # 3. Assignació greedy sobre la matriu ordenada (equivalent a l'algoritme hongrès
    #    per a casos sense ambigüitat, però molt més simple i ràpid)
    for dist, idx, id_vell in parelles:
        if idx in deteccions_ja_assignades:
            continue  # Aquesta detecció ja té ID
        if id_vell in ids_ja_assignats:
            continue  # Aquest ID ja té detecció

        # Parella vàlida: assignem
        cx_nova, cy_nova = deteccions_actuals[idx]
        caixes_actives_amb_memoria[id_vell]['centroide'] = (cx_nova, cy_nova)
        caixes_actives_amb_memoria[id_vell]['misses'] = 0
        info = caixes_actives_amb_memoria[id_vell]
        id_actuals_assignats.append({'id': id_vell, 'centroide': (cx_nova, cy_nova), 'color': info['color']})
        ids_ja_assignats.add(id_vell)
        deteccions_ja_assignades.add(idx)

    # 4. Deteccions sense aparellar → ID nou
    for idx, (cx_nova, cy_nova) in enumerate(deteccions_actuals):
        if idx in deteccions_ja_assignades:
            continue
        nou_id = següent_id_caixa
        color = obtenir_color_aleatori()
        caixes_actives_amb_memoria[nou_id] = {'centroide': (cx_nova, cy_nova), 'misses': 0, 'color': color}
        id_actuals_assignats.append({'id': nou_id, 'centroide': (cx_nova, cy_nova), 'color': color})
        següent_id_caixa += 1
        ids_ja_assignats.add(nou_id)

    # 5. IDs sense detecció → incrementem misses o eliminem
    ids_a_eliminar = []
    for id_vell in caixes_actives_amb_memoria:
        if id_vell not in ids_ja_assignats:
            caixes_actives_amb_memoria[id_vell]['misses'] += 1
            if caixes_actives_amb_memoria[id_vell]['misses'] > MAX_FRAMES_MISSING:
                ids_a_eliminar.append(id_vell)

    for i_d in ids_a_eliminar:
        del caixes_actives_amb_memoria[i_d]

    return id_actuals_assignats

def extreure_ids_i_posicions(img, detector, segmentador, distancia_lidar_cm):
    """Funció de servei per al BLOC 0: Ara retorna també la màscara i el color"""
    caixes_detectades_frame = []
    H, W = img.shape[:2]

    gdino_img = _prepare_gdino_image(img)
    raw_boxes, raw_logits, raw_phrases = gdino_predict(
        model=detector, image=gdino_img,
        caption=GDINO_PROMPT,
        box_threshold=GDINO_BOX_THR,
        text_threshold=GDINO_TXT_THR,
        device=DEVICE,
    )

    if len(raw_boxes) == 0:
        return caixes_detectades_frame

    # Separem pallets de caixes i ens quedem només amb caixes
    pallet_mask = np.array(["pallet" in p.lower() for p in raw_phrases])
    box_mask    = ~pallet_mask
    boxes_norm  = raw_boxes.numpy()[box_mask]
    scores      = raw_logits.numpy()[box_mask]

    if len(boxes_norm) == 0:
        return caixes_detectades_frame

    # Convertim de cx cy w h normalitzat a x1 y1 x2 y2 en píxels
    cx, cy, bw, bh = boxes_norm[:, 0], boxes_norm[:, 1], boxes_norm[:, 2], boxes_norm[:, 3]
    caixes_yolo = np.stack([
        (cx - bw / 2) * W, (cy - bh / 2) * H,
        (cx + bw / 2) * W, (cy + bh / 2) * H,
    ], axis=1).tolist()

    # Filtres geomètrics + duplicats abans del SAM
    caixes_yolo, scores = aplicar_filtres(caixes_yolo, scores, img.shape)

    if len(caixes_yolo) == 0:
        return caixes_detectades_frame

    centroides_actuals = []
    info_caixes = []

    for box in caixes_yolo:
        x1, y1, x2, y2 = map(int, box)
        marge = 60
        box_ampliada = [max(0, x1-marge), max(0, y1-marge), min(img.shape[1], x2+marge), min(img.shape[0], y2+marge)]

        resultats_sam = segmentador.predict(img, bboxes=box_ampliada, verbose=False)

        if resultats_sam[0].masks is not None and len(resultats_sam[0].masks.xy) > 0:
            contorn_np = np.array(resultats_sam[0].masks.xy[0], dtype=np.int32)
            moments = cv2.moments(contorn_np)
            if moments["m00"] != 0:
                cx = int(moments["m10"] / moments["m00"])
                cy = int(moments["m01"] / moments["m00"])
            else:
                cx, cy = int((x1+x2)/2), int((y1+y2)/2)

            centroides_actuals.append((cx, cy))
            info_caixes.append({'bbox_ampliada': box_ampliada, 'cx': cx, 'cy': cy, 'contorn': contorn_np})

    ids_assignats_finals = tracking_robust_amb_memoria(centroides_actuals, distancia_lidar_cm)

    for caixa in info_caixes:
        for id_info in ids_assignats_finals:
            if math.hypot(caixa['cx'] - id_info['centroide'][0], caixa['cy'] - id_info['centroide'][1]) < 5:
                caixes_detectades_frame.append({
                    'id': id_info['id'],
                    'bbox': caixa['bbox_ampliada'],
                    'color': id_info['color'],
                    'contorn': caixa['contorn'],
                    'cx': caixa['cx'],
                    'cy': caixa['cy']
                })
                break

    return caixes_detectades_frame
