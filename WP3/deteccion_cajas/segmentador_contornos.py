"""
segmentador_contornos.py
========================
Módulo post-pipeline: dado el resultado final del detector (cajas limpias),
usa MobileSAM para extraer la máscara de cada caja y simplifica el contorno
a un polígono de 4-8 vértices para el paso de volumetría.

Incluye mejoras de iluminación local (CLAHE) y extracción geométrica 
(MinAreaRect + ConvexHull) para garantizar aristas rectas en zonas oscuras.
"""

import cv2
import numpy as np
from pathlib import Path

# ============================================================
#  ⚙️  PARÁMETROS DE SEGMENTACIÓN
# ============================================================

SAM_WEIGHTS       = "../volumetria/mobile_sam.pt"   # Ajusta la ruta si es necesario
POLY_MIN_VERTICES = 4
POLY_MAX_VERTICES = 8

# Parámetros para mejora de iluminación en estanterías oscuras
CLAHE_CLIP_LIMIT = 2.0
CLAHE_GRID_SIZE  = (8, 8)

# ============================================================
#  🔧  CARGA DEL MODELO
# ============================================================

def cargar_segmentador(weights_path: str = SAM_WEIGHTS):
    """
    Carga MobileSAM una sola vez.
    Devuelve el objeto predictor listo para usar.
    """
    from ultralytics import SAM
    print(f"📦 Cargando MobileSAM desde {weights_path}...")
    model = SAM(weights_path)
    print("   ✅ MobileSAM cargado")
    return model


# ============================================================
#  🔧  UTILIDADES Y PREPROCESAMIENTO
# ============================================================

def _norm_to_px(boxes_norm: np.ndarray, img_h: int, img_w: int) -> np.ndarray:
    """
    Convierte boxes (cx cy w h) normalizados [0-1] → (x1 y1 x2 y2) en píxeles.
    """
    cx, cy, w, h = boxes_norm[:, 0], boxes_norm[:, 1], boxes_norm[:, 2], boxes_norm[:, 3]
    x1 = np.clip((cx - w / 2) * img_w, 0, img_w).astype(int)
    y1 = np.clip((cy - h / 2) * img_h, 0, img_h).astype(int)
    x2 = np.clip((cx + w / 2) * img_w, 0, img_w).astype(int)
    y2 = np.clip((cy + h / 2) * img_h, 0, img_h).astype(int)
    return np.stack([x1, y1, x2, y2], axis=1)


def aplicar_clahe_roi(image_bgr: np.ndarray, bbox_px: tuple) -> tuple:
    """
    Aplica CLAHE (Contrast Limited Adaptive Histogram Equalization) 
    solo en la región de la caja para revelar aristas en la oscuridad.
    """
    x1, y1, x2, y2 = bbox_px
    roi = image_bgr[y1:y2, x1:x2].copy()
    
    # Convertir a LAB para mejorar solo la luminosidad (canal L) sin alterar colores
    lab = cv2.cvtColor(roi, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)
    
    clahe = cv2.createCLAHE(clipLimit=CLAHE_CLIP_LIMIT, tileGridSize=CLAHE_GRID_SIZE)
    l_clahe = clahe.apply(l)
    
    lab_clahe = cv2.merge((l_clahe, a, b))
    roi_mejorado = cv2.cvtColor(lab_clahe, cv2.COLOR_LAB2BGR)
    
    # Devolver la imagen completa con el ROI mejorado pegado
    imagen_mejorada = image_bgr.copy()
    imagen_mejorada[y1:y2, x1:x2] = roi_mejorado
    
    return imagen_mejorada, roi_mejorado


def _mask_to_polygon_geometric(mask: np.ndarray) -> np.ndarray | None:
    """
    Estrategia mejorada para cajas:
    Busca el contorno de SAM, pero fuerza encajes geométricos orientados a líneas rectas.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if not contours:
        return None

    contour = max(contours, key=cv2.contourArea)
    
    # 1. Intentar Minimum Area Rectangle (ideal si solo se ve la cara frontal/superior)
    rect = cv2.minAreaRect(contour)
    box_points = cv2.boxPoints(rect)
    box_points = np.int0(box_points)
    
    mask_rect = np.zeros_like(mask)
    cv2.drawContours(mask_rect, [box_points], 0, 255, -1)
    
    interseccion = cv2.bitwise_and(mask, mask_rect)
    area_sam = cv2.countNonZero(mask)
    area_rect = cv2.countNonZero(mask_rect)
    
    if area_rect > 0:
        iou = cv2.countNonZero(interseccion) / float(area_rect + area_sam - cv2.countNonZero(interseccion))
        # Si la máscara de SAM es casi un rectángulo perfecto, usamos el matemático
        if iou > 0.85: 
            return box_points.reshape(-1, 2)
            
    # 2. Si vemos varias caras (3D), usamos Convex Hull para tensar la máscara exterior
    hull = cv2.convexHull(contour)
    perimeter = cv2.arcLength(hull, True)
    
    # Epsilon adaptado para forzar líneas rectas y eliminar bordes temblorosos
    poly = cv2.approxPolyDP(hull, 0.04 * perimeter, True) 
    
    if POLY_MIN_VERTICES <= len(poly) <= POLY_MAX_VERTICES:
        return poly.reshape(-1, 2)
        
    # 3. Fallback: contorno original simplificado
    return cv2.approxPolyDP(contour, 0.02 * cv2.arcLength(contour, True), True).reshape(-1, 2)


# ============================================================
#  🟩  SEGMENTACIÓN PRINCIPAL
# ============================================================

def segmentar_cajas(
    image_bgr: np.ndarray,
    boxes: np.ndarray,
    logits: np.ndarray,
    phrases: list[str],
    sam_model,
    run_dir: Path,
    stem: str,
) -> list[dict]:
    """
    Para cada caja detectada:
        - Mejora la iluminación local (CLAHE).
        - Lanza SAM con prompt de bounding box.
        - Extrae el polígono geométrico (aristas rectas).
        - Dibuja el resultado y lo guarda como imagen de debug.
    """
    if len(boxes) == 0:
        print("   Segmentador          : 0 cajas, nada que segmentar")
        return []

    img_h, img_w = image_bgr.shape[:2]
    bboxes_px = _norm_to_px(boxes, img_h, img_w)

    resultados = []
    debug_img  = image_bgr.copy()

    # Paleta de colores por caja
    n = len(boxes)
    colores = [
        tuple(int(c) for c in cv2.cvtColor(
            np.uint8([[[int(i * 180 / n), 220, 220]]]), cv2.COLOR_HSV2BGR
        )[0][0])
        for i in range(n)
    ]

    print(f"\n   🟩 Segmentando {n} caja(s)...")

    for i, (bbox_px, score, phrase) in enumerate(zip(bboxes_px, logits, phrases)):
        x1, y1, x2, y2 = bbox_px
        color = colores[i]

        # 1. MEJORA DE ILUMINACIÓN LOCAL (CLAHE)
        img_mejorada, _ = aplicar_clahe_roi(image_bgr, (x1, y1, x2, y2))

        # 2. INFERENCIA CON SAM (usando la imagen mejorada)
        try:
            results = sam_model(img_mejorada, bboxes=[[x1, y1, x2, y2]], verbose=False)
            mask_data = results[0].masks
            if mask_data is None or len(mask_data) == 0:
                print(f"      [{i+1}] SAM no generó máscara para '{phrase}'")
                continue

            # Máscara binaria uint8
            mask = (mask_data.data[0].cpu().numpy() > 0.5).astype(np.uint8) * 255

        except Exception as e:
            print(f"      [{i+1}] Error SAM: {e}")
            continue

        # 3. EXTRACCIÓN GEOMÉTRICA DE ARISTAS
        vertices = _mask_to_polygon_geometric(mask)
        
        if vertices is None:
            print(f"      [{i+1}] No se pudo extraer polígono para '{phrase}'")
            continue

        resultados.append({
            "idx":      i,
            "phrase":   phrase,
            "score":    float(score),
            "vertices": vertices,
            "bbox_px":  (x1, y1, x2, y2),
        })

        # ── Debug visual ──────────────────────────────────────────
        overlay = debug_img.copy()
        color_layer = np.zeros_like(debug_img)
        color_layer[mask > 0] = color
        cv2.addWeighted(overlay, 0.55, color_layer, 0.45, 0, debug_img)
        debug_img[mask == 0] = overlay[mask == 0]

        # Contorno del polígono
        pts = vertices.reshape((-1, 1, 2))
        cv2.polylines(debug_img, [pts], isClosed=True, color=color, thickness=2)

        # Vértices 
        for vx, vy in vertices:
            cv2.circle(debug_img, (vx, vy), 6, (0, 0, 0), -1)
            cv2.circle(debug_img, (vx, vy), 4, (255, 255, 255), -1)

        # Etiqueta
        label = f"[{i+1}] {phrase} {score:.2f}  {len(vertices)}v"
        cv2.putText(debug_img, label, (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 0, 0), 3)
        cv2.putText(debug_img, label, (x1, max(y1 - 8, 12)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color,    1)

        print(f"      [{i+1}] '{phrase}' score={score:.3f}  →  {len(vertices)} vértices")

    # Guardar imagen de debug
    out_path = run_dir / f"{stem}_8_contornos.jpg"
    cv2.imwrite(str(out_path), debug_img)
    print(f"   💾 [contornos] {len(resultados)} caja(s) segmentadas → {out_path.name}")

    return resultados


# ============================================================
#  📋  UTILIDAD: IMPRIMIR RESUMEN DE VÉRTICES
# ============================================================

def imprimir_vertices(resultados: list[dict]):
    """Muestra por consola los vértices de cada caja (útil para debug)."""
    print("\n" + "=" * 50)
    print("📐  VÉRTICES POR CAJA")
    print("=" * 50)
    for r in resultados:
        print(f"  Caja [{r['idx']+1}] '{r['phrase']}' (score={r['score']:.3f})")
        for j, (vx, vy) in enumerate(r["vertices"]):
            print(f"      v{j+1}: ({vx:4d}, {vy:4d})")
    print("=" * 50)