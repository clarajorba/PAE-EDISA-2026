from __future__ import annotations

import csv
import os
import time

import cv2
import numpy as np
from pyzbar.pyzbar import decode

TIPOS_SOPORTADOS = {
    "QRCODE",
    "EAN13",
    "EAN8",
    "UPCA",
    "UPCE",
    "CODE128",
    "CODE39",
    "I25",
}

COOLDOWN_CIERRE = 4.0
COOLDOWN_ENTRE_ESTANTERIAS = 3.0
GRID_DEDUP_PX = 20


def netejar_text_codi(text: str) -> str:
    return text.strip().lstrip("ñ").replace("\x1d", "")


def carregar_manifest(path_csv: str) -> tuple[set[str], dict[str, str], dict[str, str]]:
    if not os.path.exists(path_csv):
        raise FileNotFoundError(f"No s'ha trobat el manifest a: {path_csv}")

    estanteries_valides: set[str] = set()
    codigo_a_producto: dict[str, str] = {}
    sscc_a_producto: dict[str, str] = {}

    with open(path_csv, newline="", encoding="utf-8") as file_obj:
        reader = csv.DictReader(file_obj)
        for row in reader:
            categoria = row["category"].strip()
            valor = netejar_text_codi(row["encoded_value"])
            nom = row["label_name"].strip()

            if categoria == "shelf":
                estanteries_valides.add(valor)
            elif categoria == "box":
                codigo_a_producto[valor] = nom
                if valor.startswith("00"):
                    sscc_a_producto[valor] = nom

    return estanteries_valides, codigo_a_producto, sscc_a_producto


def inicializar_estado_inventario(manifest_path: str) -> dict:
    estanteries_valides, codigo_a_producto, sscc_a_producto = carregar_manifest(manifest_path)
    return {
        "estanteria_actual": None,
        "temps_obertura": 0.0,
        "temps_tancament": 0.0,
        "productes_temporals": {},
        "inventari_global": {},
        "estanteries_valides": estanteries_valides,
        "codigo_a_producto": codigo_a_producto,
        "sscc_a_producto": sscc_a_producto,
        "sscc_vistos_actuals": set(),
        "estat_text": "ESPERANT ESTANTERIA",
        "estat_color": (255, 255, 255),
    }


def _obtenir_rect(codi) -> tuple[int, int, int, int]:
    rect = codi.rect
    x = getattr(rect, "left", rect[0])
    y = getattr(rect, "top", rect[1])
    w = getattr(rect, "width", rect[2])
    h = getattr(rect, "height", rect[3])
    return int(x), int(y), int(w), int(h)


def _preparar_gray(frame_bgr: np.ndarray, escala: float) -> np.ndarray:
    frame = frame_bgr
    if escala != 1.0:
        interpolation = cv2.INTER_AREA if escala < 1.0 else cv2.INTER_LINEAR
        frame = cv2.resize(frame_bgr, (0, 0), fx=escala, fy=escala, interpolation=interpolation)
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _preparar_imatges_deteccio(
    gray: np.ndarray,
    incloure_otsu: bool = False,
    incloure_adaptativa: bool = False,
) -> list[np.ndarray]:
    images = [gray, cv2.equalizeHist(gray)]

    if incloure_otsu:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        images.append(
            cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        )

    if incloure_adaptativa:
        images.append(
            cv2.adaptiveThreshold(
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            )
        )

    return images


def _build_detection(codi, escala: float) -> dict | None:
    try:
        valor = netejar_text_codi(codi.data.decode("utf-8"))
    except Exception:
        return None

    if not valor or codi.type not in TIPOS_SOPORTADOS:
        return None

    x, y, w, h = _obtenir_rect(codi)
    if codi.polygon and len(codi.polygon) >= 4:
        points = []
        for point in codi.polygon:
            px = getattr(point, "x", point[0])
            py = getattr(point, "y", point[1])
            points.append([px, py])
        polygon = np.asarray(points, dtype=np.int32)
    else:
        polygon = np.asarray(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            dtype=np.int32,
        )

    moments = cv2.moments(polygon.reshape(-1, 1, 2))
    if moments["m00"] != 0:
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
    else:
        cx = x + w // 2
        cy = y + h // 2

    if escala != 1.0:
        x = int(x / escala)
        y = int(y / escala)
        w = int(w / escala)
        h = int(h / escala)
        cx = int(cx / escala)
        cy = int(cy / escala)
        polygon = (polygon / escala).astype(np.int32)

    tipo = "QR" if codi.type == "QRCODE" else codi.type
    return {
        "tipo": tipo,
        "valor": valor,
        "bbox": (x, y, w, h),
        "polygon": polygon,
        "centro": (cx, cy),
    }


def _append_detections(
    deteccions_raw,
    escala: float,
    out: list[dict],
    vistos: set[tuple],
) -> None:
    for codi in deteccions_raw:
        detection = _build_detection(codi, escala)
        if detection is None:
            continue

        x, y, w, h = detection["bbox"]
        key = (
            detection["tipo"],
            detection["valor"],
            x // GRID_DEDUP_PX,
            y // GRID_DEDUP_PX,
            w // GRID_DEDUP_PX,
            h // GRID_DEDUP_PX,
        )
        if key in vistos:
            continue

        vistos.add(key)
        out.append(detection)


def _contains_priority_type(detections: list[dict], tipos_objetivo: set[str] | None) -> bool:
    if not tipos_objetivo:
        return bool(detections)
    return any(det["tipo"] in tipos_objetivo for det in detections)


def detectar_codigos_frame(
    frame_bgr: np.ndarray,
    escala_rapida: float = 0.75,
    escala_fine: float = 1.0,
    tipos_prioritarios: set[str] | None = None,
) -> list[dict]:
    tipos_prioritarios = set(tipos_prioritarios or [])
    detections: list[dict] = []
    vistos: set[tuple] = set()

    gray_rapid = _preparar_gray(frame_bgr, escala_rapida)
    for image in _preparar_imatges_deteccio(gray_rapid):
        _append_detections(decode(image), escala_rapida, detections, vistos)
        if _contains_priority_type(detections, tipos_prioritarios):
            return detections

    gray_fine = _preparar_gray(frame_bgr, escala_fine)
    images_fine = _preparar_imatges_deteccio(
        gray_fine,
        incloure_otsu=True,
        incloure_adaptativa=True,
    )

    if abs(escala_fine - escala_rapida) < 1e-6:
        images_fine = images_fine[2:]

    for image in images_fine:
        _append_detections(decode(image), escala_fine, detections, vistos)
        if _contains_priority_type(detections, tipos_prioritarios):
            break

    return detections


def tipus_prioritaris_per_estat(estat_inventari: dict) -> set[str]:
    if estat_inventari["estanteria_actual"] is None:
        return {"CODE39"}
    return {"CODE128", "QR", "EAN13", "CODE39"}


def _actualizar_estat_text(estat_inventari: dict, now: float) -> None:
    if estat_inventari["estanteria_actual"] is None:
        if (now - estat_inventari["temps_tancament"]) < COOLDOWN_ENTRE_ESTANTERIAS:
            estat_inventari["estat_text"] = "COOLDOWN ESTANTERIA"
            estat_inventari["estat_color"] = (0, 165, 255)
        else:
            estat_inventari["estat_text"] = "ESPERANT ESTANTERIA"
            estat_inventari["estat_color"] = (255, 255, 255)
    else:
        estat_inventari["estat_text"] = f"LLEGINT {estat_inventari['estanteria_actual']}"
        estat_inventari["estat_color"] = (0, 255, 0)


def actualizar_inventario(
    codigos: list[dict],
    estat_inventari: dict,
    now: float | None = None,
) -> list[str]:
    now = time.time() if now is None else now
    eventos: list[str] = []

    for codigo in codigos:
        tipo = codigo["tipo"]
        valor = codigo["valor"]

        if tipo == "CODE39" and valor in estat_inventari["estanteries_valides"]:
            if estat_inventari["estanteria_actual"] is None:
                if (now - estat_inventari["temps_tancament"]) > COOLDOWN_ENTRE_ESTANTERIAS:
                    estat_inventari["estanteria_actual"] = valor
                    estat_inventari["temps_obertura"] = now
                    estat_inventari["productes_temporals"] = {}
                    estat_inventari["sscc_vistos_actuals"] = set()
                    eventos.append(f"OBERTA TRANSACCIO {valor}")
            elif estat_inventari["estanteria_actual"] == valor:
                if (now - estat_inventari["temps_obertura"]) > COOLDOWN_CIERRE:
                    resumen = {
                        producto: len(ssccs)
                        for producto, ssccs in estat_inventari["productes_temporals"].items()
                    }
                    estat_inventari["inventari_global"][valor] = resumen
                    eventos.append(f"TANCADA TRANSACCIO {valor}")
                    estat_inventari["estanteria_actual"] = None
                    estat_inventari["productes_temporals"] = {}
                    estat_inventari["sscc_vistos_actuals"] = set()
                    estat_inventari["temps_tancament"] = now
            continue

        if estat_inventari["estanteria_actual"] is None:
            continue

        if not (tipo == "CODE128" and valor.startswith("00")):
            continue

        vistos = estat_inventari["sscc_vistos_actuals"]
        if valor in vistos:
            continue

        vistos.add(valor)
        producto = estat_inventari["sscc_a_producto"].get(
            valor,
            estat_inventari["codigo_a_producto"].get(valor, valor),
        )
        temporal = estat_inventari["productes_temporals"]
        temporal.setdefault(producto, set()).add(valor)
        eventos.append(f"PRODUCTE {producto}")

    _actualizar_estat_text(estat_inventari, now)
    return eventos


def dibujar_estado_inventario(frame_bgr: np.ndarray, estat_inventari: dict) -> None:
    text = estat_inventari["estat_text"]
    color = estat_inventari["estat_color"]
    cv2.putText(
        frame_bgr,
        text,
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color,
        2,
    )
