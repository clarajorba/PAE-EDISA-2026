"""
prueba_detector_almacen.py
==========================
GroundingDINO + filtros en cascada para detección de cajas de almacén.

Orden de filtros:
  1. Containment  — elimina detecciones "grupo" que engloban varias cajas
  2. Center dist  — elimina duplicados ligeramente desplazados
  3. NMS          — elimina solapamientos directos
  4. Pallet       — descarta pallets vacíos (aspect ratio) y ocupados (cajas encima)

Por cada imagen se guardan 5 archivos:
  _0_sinfiltros.jpg
  _1_containment.jpg
  _2_center.jpg
  _3_nms.jpg
  _4_pallet.jpg
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
FOTOS_DIR    = "mis_imagenes/"
IMAGE_NAME   = "20260218_131608.jpg"   # None → procesa todas
OUTPUT_BASE  = "comparacion_resultados/"

TEXT_PROMPT  = "cardboard box . box . carton . stacked cardboard box . warehouse package . pallet ."

BOX_THRESHOLD         = 0.19
TEXT_THRESHOLD        = 0.3
IOU_THRESHOLD         = 0.7
CONTAINMENT_THRESHOLD = 0.3
CENTER_DIST_THRESHOLD = 0.05

PALLET_KEYWORDS       = {"pallet"}
PALLET_MIN_ASPECT_RATIO = 2.5   # lado_largo / lado_corto (ajusta entre 2.0 y 3.0)

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
    """
    Fase 1 — pallets vacíos: descarta si aspect ratio >= PALLET_MIN_ASPECT_RATIO.
    Fase 2 — pallets ocupados: descarta si alguna caja está contenida >= threshold.
    Las cajas nunca se modifican.
    """
    if len(pallet_idx) == 0:
        return box_idx, pallet_idx

    pw = boxes[pallet_idx, 2]
    ph = boxes[pallet_idx, 3]
    aspect       = np.maximum(pw, ph) / np.clip(np.minimum(pw, ph), 1e-6, None)
    empty_pallet = aspect >= PALLET_MIN_ASPECT_RATIO

    if empty_pallet.sum():
        print(f"   Filtro pallet vacío  : descartados {empty_pallet.sum()} pallet(s) "
              f"(aspect ratio≥{PALLET_MIN_ASPECT_RATIO})")

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

def draw_params_overlay(image, n_final):
    lines = [
        f"BOX: {BOX_THRESHOLD}",
        f"TEXT: {TEXT_THRESHOLD}",
        f"IOU: {IOU_THRESHOLD}",
        f"CONT: {CONTAINMENT_THRESHOLD}",
        f"CENTER: {CENTER_DIST_THRESHOLD}",
    ]
    font, fs, th, pad = cv2.FONT_HERSHEY_SIMPLEX, 1.4, 3, 14
    line_h  = int(cv2.getTextSize("A", font, fs, th)[0][1] + pad * 2)
    block_h = line_h * len(lines) + pad
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (320, block_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, image)
    for i, line in enumerate(lines):
        y = pad + line_h * i + line_h - pad
        cv2.putText(image, line, (12, y), font, fs, (0, 0, 0), th + 3)
        cv2.putText(image, line, (10, y), font, fs, (255, 255, 255), th)
    return image


def _save_step(image_source, boxes, logits, phrases, stem, run_dir, step, label):
    """Anota y guarda la imagen tras un paso del pipeline."""
    annotated = annotate(
        image_source=image_source,
        boxes=torch.from_numpy(boxes),
        logits=torch.from_numpy(logits),
        phrases=phrases,
    )
    annotated = draw_params_overlay(annotated, len(boxes))
    out_path  = run_dir / f"{stem}_{step}_{label}.jpg"
    cv2.imwrite(str(out_path), annotated)
    print(f"   💾 [{label}] {len(boxes)} detecc. → {out_path.name}")


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
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 0, "0_sinfiltros")

        # 1 — containment
        b, l, ph = apply_containment_filter(b, l, ph, CONTAINMENT_THRESHOLD)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 1, "1_containment")

        # 2 — center distance
        b, l, ph = apply_center_distance_filter(b, l, ph, CENTER_DIST_THRESHOLD)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 2, "2_center")

        # 3 — NMS
        b, l, ph = apply_nms(b, l, ph, IOU_THRESHOLD)
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 3, "3_nms")

        # 4 — pallet (construimos arrays combinados para la función)
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
        _save_step(image_source, b, l, ph, img_path.stem, run_dir, 4, "4_pallet")

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