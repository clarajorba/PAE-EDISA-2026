"""
detector_almacen.py
===================
GroundingDINO + NMS para detección de cajas de almacén
"""

import os
import cv2
import torch
import numpy as np
from pathlib import Path
from groundingdino.util.inference import load_model, load_image, predict, annotate

# ============================================================
#  ⚙️  PARÁMETROS - MODIFICA AQUÍ PARA TUS PRUEBAS
# ============================================================

CONFIG_PATH  = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "weights/groundingdino_swint_ogc.pth"
INPUT_PATH   = "../fotos_caixa/"
OUTPUT_DIR   = "resultados/"

# Qué detectar (separado por " . ")
TEXT_PROMPT  = "cardboard box . box . carton . stacked cardboard box . carton . werehouse package"

# --- Umbrales de detección (bajos para no perderse cajas) ---
BOX_THRESHOLD  = 0.20   # bajo → detecta más cosas (más falsos positivos)
TEXT_THRESHOLD = 0.15

# --- NMS: controla el solapamiento permitido entre cajas ---
# IOU_THRESHOLD: % de solapamiento máximo permitido entre dos cajas (0.0 - 1.0)
#   · 0.1 → muy estricto, elimina cajas que se solapan poco
#   · 0.5 → moderado, elimina solo si se solapan bastante (recomendado)
#   · 0.8 → permisivo, solo elimina si casi se superponen del todo
IOU_THRESHOLD  = 0.2    # <-- ajusta este valor según tus pruebas

# --- Filtro de contenimiento ---
# Si una caja grande contiene X% o más del área de una caja pequeña, se elimina la grande
# Útil para eliminar detecciones "conjunto" que engloban varias cajas individuales
#   · 0.7 → elimina la caja grande si contiene el 70% de una pequeña (recomendado)
#   · 0.9 → solo elimina si casi contiene completamente a otra
#   · 0.0 → desactiva el filtro
CONTAINMENT_THRESHOLD = 0.7  # <-- ajusta este valor según tus pruebas

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ============================================================
#  🔧  FUNCIONES NMS
# ============================================================

def compute_iou(box1, box2):
    """
    Calcula el IoU (Intersection over Union) entre dos cajas.
    Las cajas están en formato [cx, cy, w, h] normalizadas (0-1).
    """
    # Convertir de centro a esquinas
    def to_corners(b):
        cx, cy, w, h = b
        return cx - w/2, cy - h/2, cx + w/2, cy + h/2

    x1a, y1a, x2a, y2a = to_corners(box1)
    x1b, y1b, x2b, y2b = to_corners(box2)

    # Área de intersección
    ix1 = max(x1a, x1b)
    iy1 = max(y1a, y1b)
    ix2 = min(x2a, x2b)
    iy2 = min(y2a, y2b)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)

    # Área de unión
    area_a = (x2a - x1a) * (y2a - y1a)
    area_b = (x2b - x1b) * (y2b - y1b)
    union = area_a + area_b - inter

    return inter / union if union > 0 else 0.0


def apply_nms(boxes, logits, phrases, iou_threshold):
    """
    Aplica NMS: si dos cajas se solapan más del iou_threshold,
    se queda solo la que tiene mayor score (logit).
    """
    if len(boxes) == 0:
        return boxes, logits, phrases

    boxes_np  = boxes.numpy()
    scores_np = logits.numpy()

    order = np.argsort(scores_np)[::-1]

    kept = []
    while len(order) > 0:
        best = order[0]
        kept.append(best)
        rest = order[1:]
        ious = np.array([compute_iou(boxes_np[best], boxes_np[i]) for i in rest])
        order = rest[ious < iou_threshold]

    kept_idx = sorted(kept)
    return (
        boxes[kept_idx],
        logits[kept_idx],
        [phrases[i] for i in kept_idx],
    )


def compute_containment(box_small, box_large):
    """
    Calcula qué porcentaje del área de box_small está dentro de box_large.
    Si es alto, significa que box_large "contiene" a box_small.
    Cajas en formato [cx, cy, w, h] normalizadas.
    """
    def to_corners(b):
        cx, cy, w, h = b
        return cx - w/2, cy - h/2, cx + w/2, cy + h/2

    x1a, y1a, x2a, y2a = to_corners(box_small)
    x1b, y1b, x2b, y2b = to_corners(box_large)

    ix1 = max(x1a, x1b)
    iy1 = max(y1a, y1b)
    ix2 = min(x2a, x2b)
    iy2 = min(y2a, y2b)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)

    area_small = (x2a - x1a) * (y2a - y1a)
    return inter / area_small if area_small > 0 else 0.0


def apply_containment_filter(boxes, logits, phrases, containment_threshold):
    """
    Elimina cajas grandes que contienen a otras más pequeñas.
    Si una caja contiene más del containment_threshold del área
    de otra caja más pequeña, se considera 'caja conjunto' y se elimina.
    """
    if len(boxes) == 0 or containment_threshold == 0.0:
        return boxes, logits, phrases

    boxes_np = boxes.numpy()
    n = len(boxes_np)

    # Calcular áreas de cada caja
    areas = np.array([b[2] * b[3] for b in boxes_np])  # w * h

    to_remove = set()
    for i in range(n):
        for j in range(n):
            if i == j or i in to_remove:
                continue
            # Si i es más grande que j, comprobar si contiene a j
            if areas[i] > areas[j]:
                containment = compute_containment(boxes_np[j], boxes_np[i])
                if containment >= containment_threshold:
                    to_remove.add(i)  # eliminar la caja grande (conjunto)
                    break

    kept_idx = [i for i in range(n) if i not in to_remove]
    removed = len(to_remove)
    if removed > 0:
        print(f"   Filtro contenimiento: eliminadas {removed} caja(s) 'conjunto'")

    return (
        boxes[kept_idx],
        logits[kept_idx],
        [phrases[i] for i in kept_idx],
    )


# ============================================================
#  🚀  CÓDIGO PRINCIPAL
# ============================================================

def get_image_paths(input_path):
    p = Path(input_path)
    extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    if p.is_file() and p.suffix.lower() in extensions:
        return [p]
    elif p.is_dir():
        return sorted([f for f in p.iterdir() if f.suffix.lower() in extensions])
    else:
        raise FileNotFoundError(f"No se encontró imagen ni carpeta en: {input_path}")


def run_detection(model, image_paths, output_dir):
    output_dir.mkdir(parents=True, exist_ok=True)
    all_results = []

    for img_path in image_paths:
        print(f"\n🔍 Procesando: {img_path.name}")

        image_source, image = load_image(str(img_path))

        # --- Detección bruta (umbrales bajos) ---
        boxes, logits, phrases = predict(
            model=model,
            image=image,
            caption=TEXT_PROMPT,
            box_threshold=BOX_THRESHOLD,
            text_threshold=TEXT_THRESHOLD,
            device=DEVICE,
        )
        print(f"   Detecciones antes de NMS : {len(boxes)}")

        # --- Aplicar NMS ---
        boxes, logits, phrases = apply_nms(boxes, logits, phrases, IOU_THRESHOLD)
        print(f"   Detecciones después de NMS: {len(boxes)}  (IoU threshold={IOU_THRESHOLD})")

        # --- Eliminar cajas conjunto ---
        boxes, logits, phrases = apply_containment_filter(boxes, logits, phrases, CONTAINMENT_THRESHOLD)
        print(f"   Detecciones finales       : {len(boxes)}")

        for i, (box, score, phrase) in enumerate(zip(boxes, logits, phrases)):
            print(f"      [{i+1}] '{phrase}'  score={score:.3f}")

        # --- Guardar imagen anotada ---
        annotated = annotate(
            image_source=image_source,
            boxes=boxes,
            logits=logits,
            phrases=phrases,
        )
        out_path = output_dir / f"resultado_{img_path.stem}.jpg"
        cv2.imwrite(str(out_path), annotated)
        print(f"   💾 Guardado en: {out_path}")

        all_results.append({
            "imagen": img_path.name,
            "detecciones": len(boxes),
            "objetos": list(zip(phrases, logits.tolist())),
        })

    return all_results


def print_summary(results):
    print("\n" + "="*55)
    print("📊  RESUMEN FINAL")
    print("="*55)
    total = 0
    for r in results:
        print(f"  {r['imagen']:30s}  →  {r['detecciones']} caja(s)")
        for phrase, score in r["objetos"]:
            print(f"      • {phrase} ({score:.2f})")
        total += r["detecciones"]
    print(f"\n  TOTAL: {total} detecciones en {len(results)} imagen(s)")
    print(f"  BOX_THRESHOLD  = {BOX_THRESHOLD}")
    print(f"  TEXT_THRESHOLD = {TEXT_THRESHOLD}")
    print(f"  IOU_THRESHOLD  = {IOU_THRESHOLD}")
    print("="*55)


def main():
    print(f"⚡ Usando dispositivo: {DEVICE.upper()}")
    print(f"📦 Cargando modelo...")
    model = load_model(CONFIG_PATH, WEIGHTS_PATH)
    model = model.to(DEVICE)

    image_paths = get_image_paths(INPUT_PATH)
    print(f"🖼️  {len(image_paths)} imagen(s) encontrada(s)")
    print(f"🔎 Prompt : {TEXT_PROMPT}")
    print(f"   BOX={BOX_THRESHOLD} | TEXT={TEXT_THRESHOLD} | IOU={IOU_THRESHOLD}")

    results = run_detection(model, image_paths, Path(OUTPUT_DIR))
    print_summary(results)


if __name__ == "__main__":
    main()