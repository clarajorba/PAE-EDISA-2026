from __future__ import annotations

import csv
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

try:
    import cv2
except ImportError as exc:
    CV2_IMPORT_ERROR = exc
    cv2 = None
else:
    CV2_IMPORT_ERROR = None

try:
    import numpy as np
except ImportError as exc:
    NUMPY_IMPORT_ERROR = exc
    np = None
else:
    NUMPY_IMPORT_ERROR = None

try:
    from pyzbar.pyzbar import ZBarSymbol, decode
except ImportError as exc:
    ZBAR_IMPORT_ERROR = exc
    ZBarSymbol = None
    decode = None
else:
    ZBAR_IMPORT_ERROR = None


# ============================================================
# 1. CONFIGURACION
# ============================================================

DEBUG = False

CARPETA_ENTRADA = Path("..") / ".." / "data" / "fotos_capturades"
CARPETA_SORTIDA = "demo_output_detected"
NOM_MANIFEST = "etiquetes_magatzem_simulades_manifest.csv"

FRAME_INTERVAL_SECONDS = 0.5
COOLDOWN_TANCAMENT = 4.0
COOLDOWN_ENTRE_ESTANTERIES = 3.0
AUTO_CERRAR_ESTANTERIA_AL_FINAL = True

QUALITAT_JPEG = 92

EXTENSIONS_IMATGE = {
    ".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"
}

TIPUS_SUPORTATS = {
    "QRCODE", "EAN13", "EAN8", "UPCA", "UPCE", "CODE128", "CODE39", "I25"
}

# En offline no se usa tiempo real. Cada frame recibe un tiempo simulado.
# Como enumeramos los frames desde 1, el primero queda en t=0.0:
# temps_actual = (index_frame - 1) * FRAME_INTERVAL_SECONDS.
# Asi se conservan los cooldowns originales sin depender de camara ni streaming.
ESCALAS_DETECCION = (1.0, 1.5, 2.0, 0.75)


# ============================================================
# 2. MODELOS DE DATOS
# ============================================================

@dataclass
class Detection:
    tipus: str
    text: str
    polygon: np.ndarray
    cx: int
    cy: int
    x: int
    y: int
    w: int
    h: int
    origen: str


@dataclass
class CodeRecord:
    tipus: str
    text: str
    primer_frame: int
    primer_fitxer: str
    temps_simulat: float
    es_estanteria_valida: bool
    es_producte_sscc: bool
    es_producte_registrable: bool
    producte: str | None
    consta_manifest: bool


# ============================================================
# 3. UTILIDADES DE TEXTO, RUTAS Y MANIFEST
# ============================================================

def netejar_text_codi(text: str) -> str:
    text = text.strip().replace("\x1d", "")
    text = text.lstrip("ñ")

    # Algunos lectores devuelven identificadores de simbologia GS1.
    # Los retiramos para que el SSCC pueda compararse con el manifest.
    if text.startswith("]C1"):
        text = text[3:]

    return text.strip()


def clau_ordenacio_natural(path: Path) -> list[object]:
    parts = re.split(r"(\d+)", path.name.lower())
    return [int(part) if part.isdigit() else part for part in parts]


def carregar_manifest(path_csv: Path) -> tuple[set[str], dict[str, str]]:
    if not path_csv.is_file():
        raise FileNotFoundError(
            f"No existe el manifest requerido: {path_csv}"
        )

    estanteries_valides: set[str] = set()
    sscc_a_producte: dict[str, str] = {}

    with path_csv.open(newline="", encoding="utf-8") as fitxer:
        reader = csv.DictReader(fitxer)
        columnes_requerides = {"category", "encoded_value", "label_name"}
        if not reader.fieldnames or not columnes_requerides.issubset(reader.fieldnames):
            raise RuntimeError(
                "El manifest no tiene las columnas requeridas: "
                "category, encoded_value, label_name"
            )

        for row in reader:
            categoria = row["category"].strip()
            valor = netejar_text_codi(row["encoded_value"])
            nom = row["label_name"].strip()

            if categoria == "shelf":
                estanteries_valides.add(valor)
            elif categoria == "box" and valor.startswith("00"):
                sscc_a_producte[valor] = nom

    return estanteries_valides, sscc_a_producte


def obtenir_simbols_zbar():
    if ZBarSymbol is None:
        return None

    simbols = []
    for nom in sorted(TIPUS_SUPORTATS):
        simbol = getattr(ZBarSymbol, nom, None)
        if simbol is not None:
            simbols.append(simbol)

    return simbols or None


# ============================================================
# 4. LECTURA Y GUARDADO ROBUSTOS
# ============================================================

def llistar_imatges(entrada_dir: Path) -> list[Path]:
    if not entrada_dir.is_dir():
        raise FileNotFoundError(
            f"No existe la carpeta de entrada: {entrada_dir}"
        )

    imatges = [
        path
        for path in entrada_dir.iterdir()
        if path.is_file() and path.suffix.lower() in EXTENSIONS_IMATGE
    ]
    imatges.sort(key=clau_ordenacio_natural)
    return imatges


def preparar_carpeta_sortida(sortida_dir: Path) -> None:
    if sortida_dir.exists():
        shutil.rmtree(sortida_dir)
    sortida_dir.mkdir(parents=True, exist_ok=True)


def llegir_imatge(path: Path) -> np.ndarray | None:
    try:
        data = np.frombuffer(path.read_bytes(), dtype=np.uint8)
    except OSError as exc:
        print(f"Aviso: no se pudo leer el archivo {path}: {exc}")
        return None

    if data.size == 0:
        print(f"Aviso: archivo vacio, se salta: {path}")
        return None

    frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if frame is None:
        print(f"Aviso: imagen no decodificable, se salta: {path}")
        return None

    return frame


def guardar_imatge(path: Path, frame: np.ndarray) -> bool:
    extensio = path.suffix.lower()
    if extensio not in {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}:
        extensio = ".jpg"
        path = path.with_suffix(extensio)

    params: list[int] = []
    if extensio in {".jpg", ".jpeg"}:
        params = [cv2.IMWRITE_JPEG_QUALITY, QUALITAT_JPEG]
    elif extensio == ".png":
        params = [cv2.IMWRITE_PNG_COMPRESSION, 3]

    ok, buffer = cv2.imencode(extensio, frame, params)
    if not ok:
        print(f"Aviso: no se pudo codificar la imagen de salida: {path}")
        return False

    try:
        path.write_bytes(buffer.tobytes())
    except OSError as exc:
        print(f"Aviso: no se pudo guardar {path}: {exc}")
        return False

    return True


# ============================================================
# 5. PREPROCESADO Y DETECCION
# ============================================================

def redimensionar(frame: np.ndarray, escala: float) -> np.ndarray:
    if abs(escala - 1.0) < 1e-6:
        return frame

    interpolacio = cv2.INTER_AREA if escala < 1.0 else cv2.INTER_CUBIC
    return cv2.resize(
        frame,
        (0, 0),
        fx=escala,
        fy=escala,
        interpolation=interpolacio,
    )


def preparar_imatges_deteccio(gray: np.ndarray) -> list[tuple[str, np.ndarray]]:
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    sharpen_kernel = np.array(
        [[0, -1, 0], [-1, 5, -1], [0, -1, 0]],
        dtype=np.float32,
    )
    sharpen = cv2.filter2D(gray, -1, sharpen_kernel)

    imatges = [
        ("gris", gray),
        ("histograma_ecualizado", cv2.equalizeHist(gray)),
        ("otsu", cv2.threshold(
            blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]),
        ("adaptativo", cv2.adaptiveThreshold(
            gray,
            255,
            cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
            cv2.THRESH_BINARY,
            31,
            7,
        )),
        ("sharpen", sharpen),
        ("sharpen_otsu", cv2.threshold(
            sharpen, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
        )[1]),
    ]

    return imatges


def obtenir_rectangle_codi(codi) -> tuple[int, int, int, int]:
    rect = codi.rect
    x = getattr(rect, "left", rect[0])
    y = getattr(rect, "top", rect[1])
    w = getattr(rect, "width", rect[2])
    h = getattr(rect, "height", rect[3])
    return int(x), int(y), int(w), int(h)


def obtenir_poligon_i_centre(codi, x: int, y: int, w: int, h: int):
    if codi.polygon and len(codi.polygon) >= 4:
        punts = []
        for punt in codi.polygon:
            px = getattr(punt, "x", punt[0])
            py = getattr(punt, "y", punt[1])
            punts.append([int(px), int(py)])
        polygon = np.array(punts, dtype=np.int32)
    else:
        polygon = np.array(
            [[x, y], [x + w, y], [x + w, y + h], [x, y + h]],
            dtype=np.int32,
        )

    moments = cv2.moments(polygon)
    if moments["m00"] != 0:
        cx = int(moments["m10"] / moments["m00"])
        cy = int(moments["m01"] / moments["m00"])
    else:
        cx = x + w // 2
        cy = y + h // 2

    return polygon, cx, cy


def construir_deteccio(codi, escala: float, origen: str) -> Detection | None:
    try:
        text = netejar_text_codi(codi.data.decode("utf-8", errors="replace"))
    except Exception:
        return None

    tipus = codi.type
    if not text or tipus not in TIPUS_SUPORTATS:
        return None

    x, y, w, h = obtenir_rectangle_codi(codi)
    polygon, cx, cy = obtenir_poligon_i_centre(codi, x, y, w, h)

    if abs(escala - 1.0) >= 1e-6:
        x = int(round(x / escala))
        y = int(round(y / escala))
        w = int(round(w / escala))
        h = int(round(h / escala))
        cx = int(round(cx / escala))
        cy = int(round(cy / escala))
        polygon = np.rint(polygon.astype(np.float32) / escala).astype(np.int32)

    return Detection(
        tipus=tipus,
        text=text,
        polygon=polygon,
        cx=cx,
        cy=cy,
        x=x,
        y=y,
        w=max(1, w),
        h=max(1, h),
        origen=origen,
    )


def rect_iou(a: Detection, b: Detection) -> float:
    ax1, ay1 = a.x, a.y
    ax2, ay2 = a.x + a.w, a.y + a.h
    bx1, by1 = b.x, b.y
    bx2, by2 = b.x + b.w, b.y + b.h

    inter_x1 = max(ax1, bx1)
    inter_y1 = max(ay1, by1)
    inter_x2 = min(ax2, bx2)
    inter_y2 = min(ay2, by2)

    inter_w = max(0, inter_x2 - inter_x1)
    inter_h = max(0, inter_y2 - inter_y1)
    inter_area = inter_w * inter_h

    area_a = max(1, a.w * a.h)
    area_b = max(1, b.w * b.h)
    return inter_area / float(area_a + area_b - inter_area)


def es_deteccio_duplicada(det: Detection, deteccions: list[Detection]) -> bool:
    # La deduplicacion combina tipo, texto, posicion y tamano. Asi se fusiona
    # la misma lectura aparecida en varios preprocesados, pero no se eliminan
    # codigos distintos aunque esten cerca.
    for existent in deteccions:
        if det.tipus != existent.tipus or det.text != existent.text:
            continue

        distancia_centre = np.hypot(det.cx - existent.cx, det.cy - existent.cy)
        marge_posicio = max(18.0, min(det.w, det.h, existent.w, existent.h) * 0.45)
        amplades_similars = abs(det.w - existent.w) <= max(20, existent.w * 0.45)
        alcades_similars = abs(det.h - existent.h) <= max(20, existent.h * 0.45)

        if rect_iou(det, existent) >= 0.45:
            return True
        if distancia_centre <= marge_posicio and amplades_similars and alcades_similars:
            return True

    return False


def detectar_codis_frame(frame: np.ndarray) -> list[Detection]:
    if decode is None:
        raise RuntimeError(
            "pyzbar no esta disponible. Instala pyzbar y la libreria nativa zbar."
        )

    simbols = obtenir_simbols_zbar()
    deteccions: list[Detection] = []

    for escala in ESCALAS_DETECCION:
        frame_escalat = redimensionar(frame, escala)
        gray = cv2.cvtColor(frame_escalat, cv2.COLOR_BGR2GRAY)

        for nom_preprocesat, imatge in preparar_imatges_deteccio(gray):
            origen = f"escala_{escala:g}_{nom_preprocesat}"
            try:
                codis_raw = decode(imatge, symbols=simbols)
            except Exception as exc:
                if DEBUG:
                    print(f"[DEBUG] Error pyzbar en {origen}: {exc}")
                continue

            for codi in codis_raw:
                det = construir_deteccio(codi, escala, origen)
                if det is None:
                    continue
                if es_deteccio_duplicada(det, deteccions):
                    if DEBUG:
                        print(f"[DEBUG] Duplicado ignorado: {det.tipus} | {det.text}")
                    continue
                deteccions.append(det)

    return deteccions


# ============================================================
# 6. ANOTACION
# ============================================================

def color_deteccio(det: Detection) -> tuple[int, int, int]:
    if det.tipus == "CODE39":
        return (0, 220, 0)
    if det.tipus == "CODE128" and det.text.startswith("00"):
        return (255, 120, 0)
    return (0, 200, 255)


def dibuixar_etiqueta(frame: np.ndarray, det: Detection, color: tuple[int, int, int]) -> None:
    h_img, w_img = frame.shape[:2]
    x = max(5, min(det.x, w_img - 20))
    y = max(20, det.y - 10)

    linies = [det.tipus, det.text]
    font = cv2.FONT_HERSHEY_SIMPLEX
    escala_font = 0.48
    gruix = 1

    for index, linia in enumerate(linies):
        y_linia = min(h_img - 8, y + index * 18)
        cv2.putText(
            frame,
            linia,
            (x, y_linia),
            font,
            escala_font,
            color,
            gruix + 2,
            cv2.LINE_AA,
        )
        cv2.putText(
            frame,
            linia,
            (x, y_linia),
            font,
            escala_font,
            (0, 0, 0),
            gruix,
            cv2.LINE_AA,
        )


def anotar_frame(frame: np.ndarray, deteccions: list[Detection]) -> np.ndarray:
    anotat = frame.copy()
    for det in deteccions:
        color = color_deteccio(det)
        cv2.polylines(anotat, [det.polygon], isClosed=True, color=color, thickness=2)
        cv2.circle(anotat, (det.cx, det.cy), 5, (0, 0, 255), -1)
        dibuixar_etiqueta(anotat, det, color)
    return anotat


# ============================================================
# 7. LOGICA DE INVENTARIO OFFLINE
# ============================================================

def crear_estat_inventari(estanteries_valides: set[str], sscc_a_producte: dict[str, str]):
    return {
        "estanteria_actual": None,
        "temps_obertura": 0.0,
        "temps_tancament": -float("inf"),
        "productes_temporals": {},
        "sscc_vistos_actuals": set(),
        "inventari_global": {},
        "estanteries_valides": estanteries_valides,
        "sscc_a_producte": sscc_a_producte,
        "codis_globals": {},
        "registre_codis": [],
        "frames_processats": 0,
        "frames_amb_deteccions": 0,
        "ultim_index_frame": 0,
        "ultim_temps_simulat": 0.0,
        "transaccions": [],
    }


def es_estanteria_valida(det: Detection, estat: dict) -> bool:
    return det.tipus == "CODE39" and det.text in estat["estanteries_valides"]


def es_producte_sscc(det: Detection) -> bool:
    return det.text.startswith("00")


def es_producte_registrable(det: Detection) -> bool:
    return det.tipus == "CODE128" and det.text.startswith("00")


def producte_de_sscc(text: str, estat: dict) -> str:
    return estat["sscc_a_producte"].get(text, f"SSCC no consta en manifest ({text})")


def registrar_codis_globals(
    deteccions: list[Detection],
    estat: dict,
    index_frame: int,
    nom_fitxer: str,
    temps_actual: float,
) -> None:
    for det in deteccions:
        clau = (det.tipus, det.text)
        if clau in estat["codis_globals"]:
            continue

        producte = estat["sscc_a_producte"].get(det.text)
        consta_manifest = (
            det.text in estat["estanteries_valides"]
            or det.text in estat["sscc_a_producte"]
        )

        registre = CodeRecord(
            tipus=det.tipus,
            text=det.text,
            primer_frame=index_frame,
            primer_fitxer=nom_fitxer,
            temps_simulat=temps_actual,
            es_estanteria_valida=es_estanteria_valida(det, estat),
            es_producte_sscc=es_producte_sscc(det),
            es_producte_registrable=es_producte_registrable(det),
            producte=producte,
            consta_manifest=consta_manifest,
        )
        estat["codis_globals"][clau] = registre
        estat["registre_codis"].append(registre)


def prioritat_inventari(det: Detection, estat: dict) -> int:
    if estat["estanteria_actual"] is None:
        if es_estanteria_valida(det, estat):
            return 0
        if es_producte_registrable(det):
            return 1
        return 2

    if es_producte_registrable(det):
        return 0
    if det.tipus == "CODE39" and det.text == estat["estanteria_actual"]:
        return 1
    if es_estanteria_valida(det, estat):
        return 2
    return 3


def obrir_estanteria(estat: dict, estanteria: str, temps_actual: float, index_frame: int) -> None:
    estat["estanteria_actual"] = estanteria
    estat["temps_obertura"] = temps_actual
    estat["productes_temporals"] = {}
    estat["sscc_vistos_actuals"] = set()
    print(f"[frame {index_frame:04d}] [+] abierta estanteria: {estanteria}")


def fusionar_productes_en_inventari(estat: dict, estanteria: str) -> None:
    inventari_estanteria = estat["inventari_global"].setdefault(estanteria, {})

    for producte, ssccs in estat["productes_temporals"].items():
        inventari_estanteria.setdefault(producte, set()).update(ssccs)


def tancar_estanteria(
    estat: dict,
    temps_actual: float,
    index_frame: int,
    automatica: bool = False,
) -> None:
    estanteria = estat["estanteria_actual"]
    if estanteria is None:
        return

    fusionar_productes_en_inventari(estat, estanteria)
    estat["transaccions"].append({
        "estanteria": estanteria,
        "frame_tancament": index_frame,
        "temps_tancament": temps_actual,
        "automatica": automatica,
        "productes": {
            producte: sorted(ssccs)
            for producte, ssccs in estat["productes_temporals"].items()
        },
    })

    mode = "cierre automatico final" if automatica else "cerrada"
    print(f"[frame {index_frame:04d}] [-] {mode}: {estanteria}")

    estat["estanteria_actual"] = None
    estat["productes_temporals"] = {}
    estat["sscc_vistos_actuals"] = set()
    estat["temps_tancament"] = temps_actual


def registrar_producte_actual(estat: dict, det: Detection, index_frame: int) -> None:
    if estat["estanteria_actual"] is None:
        return
    if not es_producte_registrable(det):
        return

    sscc = det.text
    if sscc in estat["sscc_vistos_actuals"]:
        if DEBUG:
            print(f"[DEBUG] SSCC repetido en la transaccion, ignorado: {sscc}")
        return

    producte = producte_de_sscc(sscc, estat)
    estat["sscc_vistos_actuals"].add(sscc)
    estat["productes_temporals"].setdefault(producte, set()).add(sscc)

    if DEBUG:
        print(
            f"[DEBUG] Producto registrado frame {index_frame}: "
            f"{producte} | {sscc} | estanteria {estat['estanteria_actual']}"
        )


def processar_deteccions_inventari(
    deteccions: list[Detection],
    estat: dict,
    temps_actual: float,
    index_frame: int,
) -> None:
    deteccions_ordenades = sorted(
        deteccions,
        key=lambda det: prioritat_inventari(det, estat),
    )

    for det in deteccions_ordenades:
        if es_estanteria_valida(det, estat):
            if estat["estanteria_actual"] is None:
                temps_des_del_tancament = temps_actual - estat["temps_tancament"]
                if temps_des_del_tancament >= COOLDOWN_ENTRE_ESTANTERIES:
                    obrir_estanteria(estat, det.text, temps_actual, index_frame)
                elif DEBUG:
                    print(
                        f"[DEBUG] Estanteria ignorada por cooldown: {det.text} "
                        f"({temps_des_del_tancament:.1f}s)"
                    )
                continue

            if det.text == estat["estanteria_actual"]:
                temps_oberta = temps_actual - estat["temps_obertura"]
                if temps_oberta >= COOLDOWN_TANCAMENT:
                    tancar_estanteria(estat, temps_actual, index_frame)
                continue

        registrar_producte_actual(estat, det, index_frame)


def finalizar_inventario_si_hace_falta(estat: dict) -> None:
    if not AUTO_CERRAR_ESTANTERIA_AL_FINAL:
        return
    if estat["estanteria_actual"] is None:
        return

    tancar_estanteria(
        estat,
        temps_actual=estat["ultim_temps_simulat"],
        index_frame=estat["ultim_index_frame"],
        automatica=True,
    )


# ============================================================
# 8. PROCESADO OFFLINE
# ============================================================

def processar_imatges(
    entrada_dir: Path,
    sortida_dir: Path,
    estanteries_valides: set[str],
    sscc_a_producte: dict[str, str],
) -> dict:
    imatges = llistar_imatges(entrada_dir)
    if not imatges:
        raise RuntimeError(f"No se encontraron imagenes en: {entrada_dir}")

    preparar_carpeta_sortida(sortida_dir)
    estat = crear_estat_inventari(estanteries_valides, sscc_a_producte)

    for index_frame, image_path in enumerate(imatges, start=1):
        frame = llegir_imatge(image_path)
        if frame is None:
            continue

        temps_actual = (index_frame - 1) * FRAME_INTERVAL_SECONDS
        deteccions = detectar_codis_frame(frame)

        estat["frames_processats"] += 1
        estat["ultim_index_frame"] = index_frame
        estat["ultim_temps_simulat"] = temps_actual
        if deteccions:
            estat["frames_amb_deteccions"] += 1

        registrar_codis_globals(
            deteccions,
            estat,
            index_frame=index_frame,
            nom_fitxer=image_path.name,
            temps_actual=temps_actual,
        )
        processar_deteccions_inventari(
            deteccions,
            estat,
            temps_actual=temps_actual,
            index_frame=index_frame,
        )

        frame_anotat = anotar_frame(frame, deteccions)
        sortida_path = sortida_dir / image_path.name
        guardar_imatge(sortida_path, frame_anotat)

        if DEBUG:
            print(f"[DEBUG] frame {index_frame}: {len(deteccions)} detecciones")

    finalizar_inventario_si_hace_falta(estat)
    return estat


# ============================================================
# 9. SALIDA POR TERMINAL
# ============================================================

def si_no(valor: bool) -> str:
    return "Si" if valor else "No"


def imprimir_codis_detectats(estat: dict) -> None:
    registres: list[CodeRecord] = estat["registre_codis"]

    print("\n--- Codigos unicos detectados ---")
    if not registres:
        print("No se ha detectado ningun codigo.")
        return

    for index, registre in enumerate(registres, start=1):
        producte = registre.producte
        if registre.es_producte_sscc and producte is None:
            producte = "No consta en manifest"
        elif producte is None:
            producte = "-"

        print(f"\n[{index}]")
        print(f"  Tipo: {registre.tipus}")
        print(f"  Texto: {registre.text}")
        print(f"  Estanteria valida: {si_no(registre.es_estanteria_valida)}")
        print(f"  Producto/SSCC: {si_no(registre.es_producte_sscc)}")
        print(f"  Producto: {producte}")
        print(f"  Consta en manifest: {si_no(registre.consta_manifest)}")
        print(
            "  Primer frame: "
            f"{registre.primer_frame} ({registre.primer_fitxer}, "
            f"t={registre.temps_simulat:.1f}s)"
        )


def imprimir_resum_inventari(estat: dict) -> None:
    print("\n--- Resumen de inventario por estanteria ---")
    inventari = estat["inventari_global"]

    if not inventari:
        print("No se ha registrado ningun producto en estanterias.")
        return

    for estanteria in sorted(inventari):
        print(f"\nEstanteria: {estanteria}")
        productes = inventari[estanteria]
        if not productes:
            print("  Sin productos registrados.")
            continue

        for producte in sorted(productes):
            ssccs = sorted(productes[producte])
            print(f"  Producto: {producte}")
            print(f"  Cantidad: {len(ssccs)}")
            print(f"  SSCC detectados: {', '.join(ssccs)}")


def imprimir_resum_general(estat: dict, sortida_dir: Path) -> None:
    print("\n=== Resultado offline ===")
    print(f"Frames procesados: {estat['frames_processats']}")
    print(f"Frames con detecciones: {estat['frames_amb_deteccions']}")
    print(f"Codigos unicos detectados: {len(estat['registre_codis'])}")
    print(f"Frames anotados guardados en: {sortida_dir}")

    imprimir_codis_detectats(estat)
    imprimir_resum_inventari(estat)


# ============================================================
# 10. MAIN
# ============================================================

def main() -> int:
    errores_dependencias = []
    if CV2_IMPORT_ERROR is not None:
        errores_dependencias.append(f"OpenCV/cv2: {CV2_IMPORT_ERROR}")
    if NUMPY_IMPORT_ERROR is not None:
        errores_dependencias.append(f"NumPy: {NUMPY_IMPORT_ERROR}")
    if ZBAR_IMPORT_ERROR is not None:
        errores_dependencias.append(f"pyzbar/zbar: {ZBAR_IMPORT_ERROR}")

    if errores_dependencias:
        print("Error: faltan dependencias necesarias para ejecutar el detector.")
        for error in errores_dependencias:
            print(f"  - {error}")
        print(
            "Instala las dependencias de requirements.txt y la libreria nativa "
            "zbar antes de ejecutar este script."
        )
        return 1

    base_dir = Path(__file__).resolve().parent
    entrada_dir = base_dir / CARPETA_ENTRADA
    sortida_dir = base_dir / CARPETA_SORTIDA
    manifest_path = base_dir / NOM_MANIFEST

    try:
        estanteries_valides, sscc_a_producte = carregar_manifest(manifest_path)
        estat = processar_imatges(
            entrada_dir=entrada_dir,
            sortida_dir=sortida_dir,
            estanteries_valides=estanteries_valides,
            sscc_a_producte=sscc_a_producte,
        )
    except Exception as exc:
        print(f"Error: {exc}")
        return 1

    imprimir_resum_general(estat, sortida_dir)
    return 0


if __name__ == "__main__":
    sys.exit(main())
