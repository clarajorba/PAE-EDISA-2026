"""
lector_codis_barres.py
======================
Lector simple i robust de codis de barres CODE39 i CODE128.

Filosofia:
- Una sola funcio publica: detectar_codis(img) -> list[dict]
- Sense logica de negoci: aixo es feina del modul que el crida.
- Combina pyzbar (rapid, ZBar) i zxing-cpp (mes tolerant amb CODE39).
- Multiples preprocessats i escales per maximitzar la deteccio.

Dependencies:
    pip install pyzbar zxing-cpp opencv-python

Format de sortida:
    [
        {
            'tipus':    'CODE39' | 'CODE128',
            'text':     contingut decodificat (net, sense FNC1 ni espais),
            'bbox':     (x1, y1, x2, y2)  en coordenades de la imatge original,
            'cx':       int,                centre X,
            'cy':       int,                centre Y,
        },
        ...
    ]
"""

import cv2
import numpy as np
from pyzbar.pyzbar import decode as _pyzbar_decode

try:
    import zxingcpp
    _ZXING_OK = True
except ImportError:
    _ZXING_OK = False
    print("[lector_codis_barres] AVIS: zxing-cpp no instal·lat. "
          "Algunes etiquetes CODE39 podrien no detectar-se. "
          "Instal·la amb: pip install zxing-cpp")

# Tipus que ens interessen segons el manifest del magatzem
TIPUS_ACCEPTATS = {"CODE39", "CODE128"}


# -----------------------------------------------------------------
# 1. Neteja de text
# -----------------------------------------------------------------

def _netejar_text(text: str) -> str:
    """Treu prefix FNC1 (n latina) i caracters de control."""
    return text.strip().lstrip("ñ").replace("\x1d", "")


# -----------------------------------------------------------------
# 2. Preprocessats
# -----------------------------------------------------------------

def _preprocessats(gray: np.ndarray):
    """
    Genera variants preprocessades del frame en gris.
    Cada variant es una oportunitat mes per al decodificador.
    """
    yield gray
    yield cv2.equalizeHist(gray)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    yield clahe.apply(gray)


# -----------------------------------------------------------------
# 3. Decodificadors
# -----------------------------------------------------------------

def _decodificar_pyzbar(img: np.ndarray) -> list:
    """Decodifica amb pyzbar (ZBar)."""
    deteccions = []
    for r in _pyzbar_decode(img):
        if r.type not in TIPUS_ACCEPTATS:
            continue
        try:
            text = _netejar_text(r.data.decode("utf-8"))
        except Exception:
            continue
        if not text:
            continue
        deteccions.append({
            "tipus": r.type,
            "text": text,
            "bbox": (
                r.rect.left,
                r.rect.top,
                r.rect.left + r.rect.width,
                r.rect.top + r.rect.height,
            ),
        })
    return deteccions


def _decodificar_zxing(img: np.ndarray) -> list:
    """Decodifica amb zxing-cpp. Mes tolerant que pyzbar amb CODE39."""
    if not _ZXING_OK:
        return []
    deteccions = []
    try:
        resultats = zxingcpp.read_barcodes(img)
    except Exception:
        return []
    for r in resultats:
        tipus = str(r.format).split(".")[-1].upper().replace(" ", "")
        if tipus not in TIPUS_ACCEPTATS:
            continue
        text = _netejar_text(r.text)
        if not text:
            continue
        xs = [r.position.top_left.x, r.position.top_right.x,
              r.position.bottom_left.x, r.position.bottom_right.x]
        ys = [r.position.top_left.y, r.position.top_right.y,
              r.position.bottom_left.y, r.position.bottom_right.y]
        deteccions.append({
            "tipus": tipus,
            "text": text,
            "bbox": (int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))),
        })
    return deteccions


# -----------------------------------------------------------------
# 4. Pipeline a una escala
# -----------------------------------------------------------------

def _detectar_a_escala(img_color: np.ndarray, escala: float) -> list:
    """
    Aplica tots els preprocessats i decodificadors a una escala donada.
    Les bboxes resultants es retornen en coordenades de la imatge ORIGINAL
    (no de la versio escalada).
    """
    if escala != 1.0:
        interp = cv2.INTER_LANCZOS4 if escala > 1 else cv2.INTER_AREA
        img_color = cv2.resize(img_color, None, fx=escala, fy=escala,
                               interpolation=interp)

    gray = cv2.cvtColor(img_color, cv2.COLOR_BGR2GRAY) \
        if len(img_color.shape) == 3 else img_color

    deteccions = []
    for img_pp in _preprocessats(gray):
        deteccions.extend(_decodificar_pyzbar(img_pp))
        deteccions.extend(_decodificar_zxing(img_pp))

    # Reescalar bboxes a coordenades originals
    for d in deteccions:
        x1, y1, x2, y2 = d["bbox"]
        d["bbox"] = (
            int(x1 / escala),
            int(y1 / escala),
            int(x2 / escala),
            int(y2 / escala),
        )

    return deteccions


# -----------------------------------------------------------------
# 5. API publica
# -----------------------------------------------------------------

def detectar_codis(img: np.ndarray, escales=(1.0, 2.0)) -> list:
    """
    Detecta tots els codis CODE39 i CODE128 d'una imatge.

    Args:
        img: imatge BGR (sortida de cv2.imread).
        escales: tupla d'escales a provar. Per defecte (1.0, 2.0) cobreix
                 codis grans (cru) i codis llunyans/petits com els
                 d'estanteria al fons (escalat x2).

    Returns:
        Llista de diccionaris amb claus 'tipus', 'text', 'bbox', 'cx', 'cy'.
        Deduplicat per (tipus, text): cada codi nomes apareix una vegada.
    """
    if img is None or img.size == 0:
        return []

    totes = []
    for esc in escales:
        totes.extend(_detectar_a_escala(img, esc))

    # Deduplicar per (tipus, text), conservant la primera aparicio
    vistos = set()
    finals = []
    for d in totes:
        clau = (d["tipus"], d["text"])
        if clau in vistos:
            continue
        vistos.add(clau)
        x1, y1, x2, y2 = d["bbox"]
        d["cx"] = (x1 + x2) // 2
        d["cy"] = (y1 + y2) // 2
        finals.append(d)

    return finals


# -----------------------------------------------------------------
# 6. Mode standalone per testar a ull
# -----------------------------------------------------------------

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Us: python lector_codis_barres.py <ruta_imatge>")
        sys.exit(1)

    img = cv2.imread(sys.argv[1])
    if img is None:
        print(f"No he pogut llegir {sys.argv[1]}")
        sys.exit(1)

    codis = detectar_codis(img)
    print(f"\n{len(codis)} codi(s) detectat(s) a {sys.argv[1]}:\n")
    for i, c in enumerate(codis, start=1):
        print(f"  [{i}] {c['tipus']}  '{c['text']}'  "
              f"bbox={c['bbox']}  centre=({c['cx']}, {c['cy']})")
