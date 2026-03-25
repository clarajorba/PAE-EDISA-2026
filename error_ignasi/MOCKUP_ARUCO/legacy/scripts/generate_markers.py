"""
scripts/generate_markers.py
----------------------------
Genera las imágenes PNG de los marcadores ArUco definidos en warehouse_config.json
y las guarda en assets/warehouse_markers/png/.

Uso:
    python scripts/generate_markers.py
    python scripts/generate_markers.py --config config/warehouse_config.json
                                        --output assets/warehouse_markers/png
                                        --dpi 300 --size-cm 15
"""

import sys
import json
import argparse
import cv2
import numpy as np
from pathlib import Path

# Asegurarse de que el root del proyecto esté en el path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


DICT_MAP = {
    "DICT_4X4_50":        cv2.aruco.DICT_4X4_50,
    "DICT_4X4_100":       cv2.aruco.DICT_4X4_100,
    "DICT_4X4_250":       cv2.aruco.DICT_4X4_250,
    "DICT_5X5_50":        cv2.aruco.DICT_5X5_50,
    "DICT_5X5_250":       cv2.aruco.DICT_5X5_250,
    "DICT_6X6_50":        cv2.aruco.DICT_6X6_50,
    "DICT_6X6_100":       cv2.aruco.DICT_6X6_100,
    "DICT_6X6_250":       cv2.aruco.DICT_6X6_250,
    "DICT_7X7_250":       cv2.aruco.DICT_7X7_250,
    "DICT_ARUCO_ORIGINAL":cv2.aruco.DICT_ARUCO_ORIGINAL,
}


def generate_marker_image(
    aruco_dict,
    marker_id: int,
    size_px: int,
    border_bits: int = 1,
) -> np.ndarray:
    """Genera la imagen de un marcador con borde blanco de impresión."""
    marker_img = cv2.aruco.generateImageMarker(aruco_dict, marker_id, size_px)

    # Añadir borde blanco (quiet zone) proporcional al tamaño
    border = max(20, size_px // 12)
    final_size = size_px + 2 * border
    canvas = np.full((final_size, final_size), 255, dtype=np.uint8)
    canvas[border:border + size_px, border:border + size_px] = marker_img
    return canvas


def generate_sheet(
    aruco_dict,
    marker_ids: list,
    size_px: int,
    cols: int = 4,
    dpi: int = 300,
) -> np.ndarray:
    """
    Genera una hoja con varios marcadores dispuestos en una cuadrícula.
    """
    # Generar una imagen de prueba para conocer el tamaño real (con borde)
    sample = generate_marker_image(aruco_dict, marker_ids[0], size_px)
    cell_size = sample.shape[0]   # el marcador es cuadrado
    pad  = 20
    label_h = 20
    cell = cell_size + pad + label_h

    rows    = (len(marker_ids) + cols - 1) // cols
    sheet_w = cols * (cell_size + pad) + pad
    sheet_h = rows * cell + pad
    sheet   = np.full((sheet_h, sheet_w), 255, dtype=np.uint8)

    for idx, mid in enumerate(marker_ids):
        row = idx // cols
        col = idx % cols
        x   = col * (cell_size + pad) + pad // 2
        y   = row * cell + pad // 2
        img = generate_marker_image(aruco_dict, mid, size_px)
        h, w = img.shape
        # Copiar sin desbordar el canvas
        y_end = min(y + h, sheet_h)
        x_end = min(x + w, sheet_w)
        sheet[y:y_end, x:x_end] = img[:y_end - y, :x_end - x]

        # ID del marcador debajo
        label_y = y + h + 14
        if label_y < sheet_h:
            cv2.putText(sheet, f"ID: {mid}", (x + cell_size // 4, label_y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, 0, 1)

    return sheet


def main():
    parser = argparse.ArgumentParser(
        description="Generador de marcadores ArUco para el almacén"
    )
    parser.add_argument("--config",   default="config/warehouse_config.json",
                        help="Ruta al archivo de configuración del almacén")
    parser.add_argument("--output",   default="assets/warehouse_markers/png",
                        help="Directorio de salida para las imágenes")
    parser.add_argument("--dpi",      type=int,   default=300,
                        help="Resolución de impresión en DPI (default 300)")
    parser.add_argument("--size-cm",  type=float, default=15.0,
                        help="Tamaño del marcador en cm (default 15)")
    parser.add_argument("--sheet",    action="store_true",
                        help="Generar también una hoja con todos los marcadores")
    args = parser.parse_args()

    # Cargar configuración
    config_path = ROOT / args.config
    if not config_path.exists():
        print(f"[ERROR] Config no encontrado: {config_path}")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    dict_name = config["aruco"]["dictionary"]
    dict_id   = DICT_MAP.get(dict_name)
    if dict_id is None:
        print(f"[ERROR] Diccionario desconocido: {dict_name}")
        sys.exit(1)

    aruco_dict = cv2.aruco.getPredefinedDictionary(dict_id)

    # Tamaño en píxeles
    size_px = int(args.size_cm / 2.54 * args.dpi)

    # Directorio de salida
    out_dir = ROOT / args.output
    out_dir.mkdir(parents=True, exist_ok=True)

    marker_ids = [m["id"] for m in config["markers"]]

    print(f"\n{'═'*55}")
    print(f"  Generando marcadores ArUco │ {dict_name}")
    print(f"  Tamaño: {args.size_cm}cm → {size_px}px  │  DPI: {args.dpi}")
    print(f"  Salida: {out_dir}")
    print(f"{'─'*55}")

    for m in config["markers"]:
        mid      = m["id"]
        location = m.get("location", "")
        img      = generate_marker_image(aruco_dict, mid, size_px)

        filename = out_dir / f"marker_{mid:03d}.png"
        cv2.imwrite(str(filename), img)
        print(f"  ✓ ID {mid:>3d} │ {filename.name}  │ {location}")

    if args.sheet:
        sheet = generate_sheet(aruco_dict, marker_ids, size_px // 2)
        sheet_path = out_dir / "markers_sheet.png"
        cv2.imwrite(str(sheet_path), sheet)
        print(f"\n  ✓ Hoja completa → {sheet_path.name}")

    print(f"{'═'*55}")
    print(f"  {len(marker_ids)} marcadores generados correctamente.\n")


if __name__ == "__main__":
    main()
