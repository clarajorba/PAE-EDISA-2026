"""
detector_almacen.py
===================
GroundingDINO - Detector de objetos para almacén
=================================================
INSTALACIÓN (ejecutar una sola vez en terminal):
    git clone https://github.com/IDEA-Research/GroundingDINO.git
    cd GroundingDINO
    pip install -e .
    mkdir weights
    wget -q https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth -P weights/

Coloca este script dentro de la carpeta GroundingDINO/ y ejecútalo.
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

# --- Rutas ---
CONFIG_PATH  = "groundingdino/config/GroundingDINO_SwinT_OGC.py"
WEIGHTS_PATH = "weights/groundingdino_swint_ogc.pth"

# --- Carpeta con tus imágenes del almacén ---
# Puede ser una sola imagen o una carpeta entera
INPUT_PATH   = "mis_imagenes/"   # carpeta o ruta a un archivo .jpg/.png

# --- Carpeta donde se guardan los resultados ---
OUTPUT_DIR   = "resultados/"

# --- Texto de búsqueda (qué quieres detectar) ---
# Separa categorías con " . "  →  el modelo detecta TODAS a la vez
# Ejemplos:
#   "cardboard box ."                    → solo cajas de cartón
#   "cardboard box . pallet . person ."  → cajas + palés + personas
#TEXT_PROMPT  = "cardboard box . box . carton . pallet ."
TEXT_PROMPT  = "Stacked cardboard box . box . carton . werehouse package ."

# --- Umbrales de confianza ---
# BOX_THRESHOLD:  confianza mínima para mostrar una detección (0.0 - 1.0)
#   · Valor alto (0.5+) → menos detecciones pero más precisas
#   · Valor bajo (0.2)  → más detecciones pero más falsos positivos
BOX_THRESHOLD  = 0.2

# TEXT_THRESHOLD: confianza mínima para asignar una etiqueta de texto (0.0 - 1.0)
#   · Generalmente se pone igual o menor que BOX_THRESHOLD
TEXT_THRESHOLD = 0.25

# --- Dispositivo ---
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# ============================================================
#  🚀  CÓDIGO PRINCIPAL (no hace falta tocar nada de aquí)
# ============================================================

def get_image_paths(input_path: str) -> list[Path]:
    """Devuelve lista de imágenes (admite fichero único o carpeta)."""
    p = Path(input_path)
    extensions = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    if p.is_file() and p.suffix.lower() in extensions:
        return [p]
    elif p.is_dir():
        return sorted([f for f in p.iterdir() if f.suffix.lower() in extensions])
    else:
        raise FileNotFoundError(f"No se encontró imagen ni carpeta en: {input_path}")


def run_detection(model, image_paths: list[Path], output_dir: Path):
    """Ejecuta la detección sobre todas las imágenes y guarda los resultados."""
    output_dir.mkdir(parents=True, exist_ok=True)
    
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

        n_detected = len(boxes)
        print(f"   ✅ Detecciones: {n_detected}")

        # Mostrar detalle de cada detección
        for i, (box, score, phrase) in enumerate(zip(boxes, logits, phrases)):
            print(f"      [{i+1}] '{phrase}'  score={score:.3f}  box={box.tolist()}")

        # Guardar imagen anotada
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
            "detecciones": n_detected,
            "objetos": list(zip(phrases, logits.tolist())),
        })

    return all_results


def print_summary(results: list[dict]):
    """Imprime un resumen final de todas las imágenes."""
    print("\n" + "="*55)
    print("📊  RESUMEN FINAL")
    print("="*55)
    total = 0
    for r in results:
        print(f"  {r['imagen']:30s}  →  {r['detecciones']} detección(es)")
        for phrase, score in r["objetos"]:
            print(f"      • {phrase} ({score:.2f})")
        total += r["detecciones"]
    print(f"\n  TOTAL: {total} detecciones en {len(results)} imagen(s)")
    print(f"  Parámetros usados:")
    print(f"    TEXT_PROMPT    = \"{TEXT_PROMPT}\"")
    print(f"    BOX_THRESHOLD  = {BOX_THRESHOLD}")
    print(f"    TEXT_THRESHOLD = {TEXT_THRESHOLD}")
    print(f"    DEVICE         = {DEVICE}")
    print("="*55)


def main():
    print(f"⚡ Usando dispositivo: {DEVICE.upper()}")
    print(f"📦 Cargando modelo...")
    model = load_model(CONFIG_PATH, WEIGHTS_PATH)
    model = model.to(DEVICE)

    image_paths = get_image_paths(INPUT_PATH)
    print(f"🖼️  {len(image_paths)} imagen(s) encontrada(s) en '{INPUT_PATH}'")
    print(f"🔎 Buscando: {TEXT_PROMPT}")
    print(f"   BOX_THRESHOLD={BOX_THRESHOLD}  |  TEXT_THRESHOLD={TEXT_THRESHOLD}")

    results = run_detection(model, image_paths, Path(OUTPUT_DIR))
    print_summary(results)


if __name__ == "__main__":
    main()
