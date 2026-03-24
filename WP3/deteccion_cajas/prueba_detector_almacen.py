"""
prueba_detector_almacen.py
===================
GroundingDINO + NMS para detección de cajas de almacén
- Selecciona la imagen que quieres probar
- Cada ejecución crea una carpeta nueva con timestamp
- Los parámetros usados se muestran en la imagen resultado
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

# --- Carpeta con todas las fotos disponibles ---
FOTOS_DIR    = "../fotos_caixa/"

# --- Imagen que quieres procesar en esta ejecución ---
# Escribe el nombre del archivo (con extensión) que quieres probar
# Ejemplos:
#   IMAGE_NAME = "foto1.jpg"
#   IMAGE_NAME = "20260218_131604.jpg"
#   IMAGE_NAME = None   ← procesa TODAS las imágenes de la carpeta
IMAGE_NAME   = "20260218_131604.jpg"

# --- Carpeta base donde se guardan los resultados ---
# Cada ejecución crea una subcarpeta nueva con timestamp
OUTPUT_BASE  = "comparacion_resultados/"

# --- Texto de búsqueda ---
TEXT_PROMPT  = "cardboard box . box . carton . stacked cardboard box . warehouse package ."

# --- Umbrales ---
BOX_THRESHOLD       = 0.19
TEXT_THRESHOLD      = 0.3
IOU_THRESHOLD       = 0.7
CONTAINMENT_THRESHOLD = 0.3
CENTER_DIST_THRESHOLD = 0.05

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ============================================================
#  🔧  FUNCIONES NMS Y CONTENIMIENTO
# ============================================================

def compute_iou(box1, box2):
    def to_corners(b):
        cx, cy, w, h = b
        return cx - w/2, cy - h/2, cx + w/2, cy + h/2
    x1a, y1a, x2a, y2a = to_corners(box1)
    x1b, y1b, x2b, y2b = to_corners(box2)
    ix1, iy1 = max(x1a, x1b), max(y1a, y1b)
    ix2, iy2 = min(x2a, x2b), min(y2a, y2b)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_a = (x2a - x1a) * (y2a - y1a)
    area_b = (x2b - x1b) * (y2b - y1b)
    union = area_a + area_b - inter
    return inter / union if union > 0 else 0.0


def apply_nms(boxes, logits, phrases, iou_threshold):
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
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


def compute_containment(box_small, box_large):
    def to_corners(b):
        cx, cy, w, h = b
        return cx - w/2, cy - h/2, cx + w/2, cy + h/2
    x1a, y1a, x2a, y2a = to_corners(box_small)
    x1b, y1b, x2b, y2b = to_corners(box_large)
    ix1, iy1 = max(x1a, x1b), max(y1a, y1b)
    ix2, iy2 = min(x2a, x2b), min(y2a, y2b)
    inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
    area_small = (x2a - x1a) * (y2a - y1a)
    return inter / area_small if area_small > 0 else 0.0


def apply_containment_filter(boxes, logits, phrases, containment_threshold):
    if len(boxes) == 0 or containment_threshold == 0.0:
        return boxes, logits, phrases
    boxes_np = boxes.numpy()
    n = len(boxes_np)
    areas = np.array([b[2] * b[3] for b in boxes_np])
    to_remove = set()
    for i in range(n):
        for j in range(n):
            if i == j or i in to_remove:
                continue
            if areas[i] > areas[j]:
                if compute_containment(boxes_np[j], boxes_np[i]) >= containment_threshold:
                    to_remove.add(i)
                    break
    kept_idx = [i for i in range(n) if i not in to_remove]
    if to_remove:
        print(f"   Filtro contenimiento: eliminadas {len(to_remove)} caja(s) 'conjunto'")
    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]


# ============================================================
#  🖊️  AÑADIR INFO DE PARÁMETROS EN LA IMAGEN
# ============================================================

def draw_params_overlay(image, n_final):
    """Escribe los umbrales usados en la imagen en grande y bien visible."""
    h, w = image.shape[:2]

    lines = [
        f"BOX: {BOX_THRESHOLD}",
        f"TEXT: {TEXT_THRESHOLD}",
        f"IOU: {IOU_THRESHOLD}",
        f"CONT: {CONTAINMENT_THRESHOLD}",
        f"CENTER: {CENTER_DIST_THRESHOLD}"
        #f"Cajas: {n_final}",
    ]

    font       = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 1.4
    thickness  = 3
    padding    = 14

    # Calcular altura total del bloque de texto
    line_h = int((cv2.getTextSize("A", font, font_scale, thickness)[0][1]) + padding * 2)
    block_h = line_h * len(lines) + padding
    block_w = 320

    # Fondo semitransparente arriba a la izquierda
    overlay = image.copy()
    cv2.rectangle(overlay, (0, 0), (block_w, block_h), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.55, image, 0.45, 0, image)

    for idx, line in enumerate(lines):
        y = padding + line_h * idx + line_h - padding
        # Sombra negra
        cv2.putText(image, line, (12, y), font, font_scale, (0, 0, 0), thickness + 3)
        # Texto blanco
        cv2.putText(image, line, (10, y), font, font_scale, (255, 255, 255), thickness)

    return image


def apply_center_distance_filter(boxes, logits, phrases, dist_threshold):
    """
    Elimina detecciones cuyo centro está muy cerca de otra con mayor score.
    Útil para duplicados ligeramente desplazados que el NMS no elimina.
    dist_threshold: distancia mínima entre centros en proporción a la imagen (0.0-1.0)
    """
    if len(boxes) == 0 or dist_threshold == 0.0:
        return boxes, logits, phrases

    boxes_np  = boxes.numpy()
    scores_np = logits.numpy()
    order     = np.argsort(scores_np)[::-1]  # ordenar por score descendente
    kept      = []

    while len(order) > 0:
        best = order[0]
        kept.append(best)
        rest = order[1:]

        # Distancia euclidiana entre centros (cx, cy)
        cx_best, cy_best = boxes_np[best][0], boxes_np[best][1]
        dists = np.sqrt(
            (boxes_np[rest][:, 0] - cx_best) ** 2 +
            (boxes_np[rest][:, 1] - cy_best) ** 2
        )
        order = rest[dists >= dist_threshold]

    kept_idx = sorted(kept)
    removed  = len(boxes) - len(kept_idx)
    if removed > 0:
        print(f"   Filtro distancia centros: eliminadas {removed} detección(es) duplicada(s)")

    return boxes[kept_idx], logits[kept_idx], [phrases[i] for i in kept_idx]




def select_image_paths():
    """Devuelve las imágenes a procesar según IMAGE_NAME."""
    fotos = Path(FOTOS_DIR)
    extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}

    if IMAGE_NAME is not None:
        # Imagen concreta elegida por el usuario
        p = fotos / IMAGE_NAME
        if not p.exists():
            # Mostrar las disponibles para ayudar
            available = sorted([f.name for f in fotos.iterdir() if f.suffix.lower() in extensions])
            print(f"\n❌ No se encontró '{IMAGE_NAME}' en {FOTOS_DIR}")
            print(f"   Imágenes disponibles:")
            for name in available:
                print(f"      · {name}")
            raise FileNotFoundError(f"Imagen no encontrada: {p}")
        return [p]
    else:
        # Todas las imágenes de la carpeta
        return sorted([f for f in fotos.iterdir() if f.suffix.lower() in extensions])


def create_run_folder():
    """Usa siempre la misma carpeta de resultados."""
    run_dir = Path(OUTPUT_BASE)
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir


def run_detection(model, image_paths, run_dir):
    all_results = []

    for img_path in image_paths:
        print(f"\n🔍 Procesando: {img_path.name}")

        image_source, image = load_image(str(img_path))

        boxes, logits, phrases = predict(
            model=model,
            image=image,
            caption=TEXT_PROMPT,
            box_threshold=BOX_THRESHOLD,
            text_threshold=TEXT_THRESHOLD,
            device=DEVICE,
        )
        n_before = len(boxes)
        print(f"   Detecciones brutas      : {n_before}")

        boxes, logits, phrases = apply_nms(boxes, logits, phrases, IOU_THRESHOLD)
        n_nms = len(boxes)
        print(f"   Tras NMS                : {n_nms}")

        boxes, logits, phrases = apply_containment_filter(boxes, logits, phrases, CONTAINMENT_THRESHOLD)
        n_final = len(boxes)
        print(f"   Tras contenimiento      : {n_final}")

        boxes, logits, phrases = apply_center_distance_filter(boxes, logits, phrases, CENTER_DIST_THRESHOLD)
        n_final = len(boxes)
        print(f"   Detecciones finales     : {n_final}")

        for i, (box, score, phrase) in enumerate(zip(boxes, logits, phrases)):
            print(f"      [{i+1}] '{phrase}'  score={score:.3f}")

        # Anotar detecciones
        annotated = annotate(
            image_source=image_source,
            boxes=boxes,
            logits=logits,
            phrases=phrases,
        )

        # Añadir overlay con parámetros
        annotated = draw_params_overlay(annotated, n_final)

        out_path = run_dir / f"{img_path.stem}_resultado.jpg"
        cv2.imwrite(str(out_path), annotated)
        print(f"   💾 Guardado en: {out_path}")

        all_results.append({
            "imagen": img_path.name,
            "detecciones": n_final,
            "objetos": list(zip(phrases, logits.tolist())),
        })

    return all_results


def print_summary(results, run_dir):
    print("\n" + "="*60)
    print("📊  RESUMEN FINAL")
    print("="*60)
    total = 0
    for r in results:
        print(f"  {r['imagen']:35s} → {r['detecciones']} caja(s)")
        for phrase, score in r["objetos"]:
            print(f"      • {phrase} ({score:.2f})")
        total += r["detecciones"]
    print(f"\n  TOTAL detecciones : {total}")
    print(f"  Resultados en     : {run_dir}")
    print(f"  BOX={BOX_THRESHOLD} | TEXT={TEXT_THRESHOLD} | IOU={IOU_THRESHOLD} | CONT={CONTAINMENT_THRESHOLD}")
    print("="*60)


def main():
    print(f"⚡ Usando dispositivo: {DEVICE.upper()}")
    print(f"📦 Cargando modelo...")
    model = load_model(CONFIG_PATH, WEIGHTS_PATH)
    model = model.to(DEVICE)

    image_paths = select_image_paths()
    run_dir = create_run_folder()

    print(f"\n🖼️  {len(image_paths)} imagen(s) seleccionada(s)")
    print(f"📁 Carpeta de resultados: {run_dir}")
    print(f"🔎 Prompt : {TEXT_PROMPT}")
    print(f"   BOX={BOX_THRESHOLD} | TEXT={TEXT_THRESHOLD} | IOU={IOU_THRESHOLD} | CONT={CONTAINMENT_THRESHOLD}")

    results = run_detection(model, image_paths, run_dir)
    print_summary(results, run_dir)


if __name__ == "__main__":
    main()