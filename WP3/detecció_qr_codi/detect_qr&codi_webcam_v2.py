import cv2
import numpy as np
import time
import csv
import os
import threading
from pyzbar.pyzbar import decode

# ============================================================
# CONFIGURACIÓ
# ============================================================

# FONT_VIDEO = "tcp://172.20.10.3:8888"
# Si vols provar la webcam local del PC:
FONT_VIDEO = "tcp://172.20.10.3:8888"

DEBUG = False
PROCESSAR_CADA_N_FRAMES = 3     # Processa 1 de cada 3 frames
ESCALA_DETECCIO_RAPIDA = 0.75   # Redueix poc la mida per no perdre detalls dels codis 1D
ESCALA_DETECCIO_FINE = 1.0      # Fallback a resolució completa per CODE128/EAN/GS1
TITOL_FINESTRA = "Gestio d'Inventari Drons"

COOLDOWN_TANCAMENT = 4.0
COOLDOWN_ENTRE_ESTANTERIES = 3.0

TIPUS_SUPORTATS = {
    "QRCODE", "EAN13", "EAN8", "UPCA", "UPCE", "CODE128", "CODE39", "I25"
}


# ============================================================
# STREAM DE CÀMERA AMB FIL SEPARAT
# ============================================================

class CameraStream:
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.frame = None
        self.ret = False
        self.running = True
        self.lock = threading.Lock()

        self.thread = threading.Thread(target=self.update, daemon=True)
        self.thread.start()

    def update(self):
        while self.running:
            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.ret = True
                    self.frame = frame

    def read(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return self.ret, self.frame.copy()

    def is_opened(self):
        return self.cap.isOpened()

    def release(self):
        self.running = False
        self.thread.join(timeout=1)
        self.cap.release()


# ============================================================
# UTILITATS
# ============================================================

def netejar_text_codi(text):
    """
    Neteja possibles caràcters especials de GS1/FNC1.
    """
    return text.strip().lstrip("ñ").replace("\x1d", "")


def carregar_manifest(path_csv):
    """
    Llegeix el CSV i separa:
    - estanteries vàlides (CODE39)
    - codis SSCC de caixa (CODE128 que comencen per 00) -> nom del producte
    """
    if not os.path.exists(path_csv):
        raise FileNotFoundError(f"No s'ha trobat el manifest a: {path_csv}")

    estanteries_valides = set()
    sscc_a_producte = {}

    with open(path_csv, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            categoria = row["category"].strip()
            valor = netejar_text_codi(row["encoded_value"])
            nom = row["label_name"].strip()

            if categoria == "shelf":
                estanteries_valides.add(valor)

            elif categoria == "box":
                if valor.startswith("00"):
                    sscc_a_producte[valor] = nom

    return estanteries_valides, sscc_a_producte


def obtenir_rect(codi):
    r = codi.rect
    x = getattr(r, "left", r[0])
    y = getattr(r, "top", r[1])
    w = getattr(r, "width", r[2])
    h = getattr(r, "height", r[3])
    return x, y, w, h


def construir_deteccio(codi, escala):
    """
    Converteix una detecció de pyzbar a un diccionari amb:
    - tipus
    - text
    - pts (polígon)
    - cx, cy
    - x, y, w, h
    Tot escalat al frame original.
    """
    try:
        text = netejar_text_codi(codi.data.decode("utf-8"))
    except:
        return None

    if not text or codi.type not in TIPUS_SUPORTATS:
        return None

    x, y, w, h = obtenir_rect(codi)

    if codi.polygon and len(codi.polygon) >= 4:
        punts = []
        for p in codi.polygon:
            px = getattr(p, "x", p[0])
            py = getattr(p, "y", p[1])
            punts.append([px, py])

        pts = np.array([punts], dtype=np.int32)

        M = cv2.moments(pts)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            cx = x + w // 2
            cy = y + h // 2
    else:
        pts = np.array([[
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h]
        ]], dtype=np.int32)
        cx = x + w // 2
        cy = y + h // 2

    # Escalat al frame original
    if escala != 1.0:
        x = int(x / escala)
        y = int(y / escala)
        w = int(w / escala)
        h = int(h / escala)
        cx = int(cx / escala)
        cy = int(cy / escala)
        pts = np.array((pts / escala).astype(np.int32), dtype=np.int32)

    return {
        "tipus": codi.type,
        "text": text,
        "pts": pts,
        "cx": cx,
        "cy": cy,
        "x": x,
        "y": y,
        "w": w,
        "h": h,
    }


def preparar_imatges_deteccio(gray, incloure_otsu=False, incloure_adaptativa=False):
    imatges = [gray, cv2.equalizeHist(gray)]

    if incloure_otsu:
        blur = cv2.GaussianBlur(gray, (3, 3), 0)
        imatges.append(
            cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        )

    if incloure_adaptativa:
        imatges.append(
            cv2.adaptiveThreshold(
                gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
            )
        )

    return imatges


def afegir_deteccions(deteccions_raw, escala, deteccions_final, vistos):
    for codi in deteccions_raw:
        det = construir_deteccio(codi, escala)
        if det is None:
            continue

        clau = (
            det["tipus"],
            det["text"],
            det["x"] // 20,
            det["y"] // 20,
            det["w"] // 20,
            det["h"] // 20
        )

        if clau in vistos:
            continue

        vistos.add(clau)
        deteccions_final.append(det)


def conte_tipus(deteccions, tipus_objectiu):
    if not tipus_objectiu:
        return bool(deteccions)

    return any(det["tipus"] in tipus_objectiu for det in deteccions)


def preparar_gray(frame, escala):
    if escala != 1.0:
        interpolacio = cv2.INTER_AREA if escala < 1.0 else cv2.INTER_LINEAR
        frame = cv2.resize(frame, (0, 0), fx=escala, fy=escala, interpolation=interpolacio)

    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def detectar_codis_mixtos(frame, tipus_prioritaris=None):
    """
    Detecció optimitzada amb dues fases:
    1) Passada ràpida a escala lleugerament reduïda
    2) Si no apareix el tipus rellevant, fallback a resolució completa
       amb preprocessats més agressius per recuperar CODE128/EAN/GS1.
    """
    tipus_prioritaris = set(tipus_prioritaris or [])
    deteccions_final = []
    vistos = set()

    gray_rapid = preparar_gray(frame, ESCALA_DETECCIO_RAPIDA)
    for img in preparar_imatges_deteccio(gray_rapid):
        afegir_deteccions(
            decode(img), ESCALA_DETECCIO_RAPIDA, deteccions_final, vistos
        )
        if conte_tipus(deteccions_final, tipus_prioritaris):
            return deteccions_final

    gray_fine = preparar_gray(frame, ESCALA_DETECCIO_FINE)
    reutilitzem_mateixa_escala = abs(ESCALA_DETECCIO_FINE - ESCALA_DETECCIO_RAPIDA) < 1e-6
    imatges_fine = preparar_imatges_deteccio(
        gray_fine, incloure_otsu=True, incloure_adaptativa=True
    )

    if reutilitzem_mateixa_escala:
        imatges_fine = imatges_fine[2:]

    for img in imatges_fine:
        afegir_deteccions(
            decode(img), ESCALA_DETECCIO_FINE, deteccions_final, vistos
        )
        if conte_tipus(deteccions_final, tipus_prioritaris):
            break

    return deteccions_final


def dibuixar_estat(frame, estat_inventari):
    temps_actual = time.time()

    if estat_inventari['estanteria_actual'] is None:
        if (temps_actual - estat_inventari['temps_tancament']) < COOLDOWN_ENTRE_ESTANTERIES:
            estat_text = "Estat: COOLDOWN (Ignorant estanteries)"
            color_estat = (0, 165, 255)
        else:
            estat_text = "Estat: ESPERANT ESTANTERIA"
            color_estat = (255, 255, 255)
    else:
        estat_text = "LLEGINT: " + estat_inventari['estanteria_actual']
        color_estat = (0, 255, 0)

    estat_inventari["estat_text"] = estat_text
    estat_inventari["estat_color"] = color_estat

    cv2.putText(frame, estat_text, (20, 40),
                cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_estat, 2)


# ============================================================
# PROCESSAMENT D'INVENTARI
# ============================================================

def processar_frame_inventari(frame, estat_inventari):
    """
    Detecta codis i gestiona:
    - estanteries (CODE39 del manifest)
    - caixes (CODE128 SSCC)
    """
    tipus_prioritaris = {"CODE39"}
    if estat_inventari['estanteria_actual'] is not None:
        tipus_prioritaris = {"CODE128"}

    codis_detectats = detectar_codis_mixtos(frame, tipus_prioritaris=tipus_prioritaris)
    temps_actual = time.time()

    for det in codis_detectats:
        tipus = det["tipus"]
        text = det["text"]
        pts = det["pts"]
        cx = det["cx"]
        cy = det["cy"]
        x = det["x"]
        y = det["y"]

        etiqueta = f"{tipus}: {text}"

        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
        cv2.putText(frame, etiqueta, (x, max(20, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # ========================================================
        # 1) LÒGICA D'ESTANTERIES
        # ========================================================
        if tipus == "CODE39" and text in estat_inventari['estanteries_valides']:

            if estat_inventari['estanteria_actual'] is None:
                temps_des_del_tancament = temps_actual - estat_inventari['temps_tancament']

                if temps_des_del_tancament > COOLDOWN_ENTRE_ESTANTERIES:
                    estat_inventari['estanteria_actual'] = text
                    estat_inventari['temps_obertura'] = temps_actual
                    estat_inventari['productes_temporals'] = {}
                    estat_inventari['sscc_vistos_actuals'] = set()
                    print(f"\n[+] OBERTA TRANSACCIÓ: {text}")

                else:
                    cv2.putText(frame, "COOLDOWN ESTANTERIA...", (x, max(40, y - 30)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

            elif estat_inventari['estanteria_actual'] == text:
                temps_passat = temps_actual - estat_inventari['temps_obertura']

                if temps_passat > COOLDOWN_TANCAMENT:
                    resum_quantitats = {
                        prod: len(ssccs)
                        for prod, ssccs in estat_inventari['productes_temporals'].items()
                    }

                    estat_inventari['inventari_global'][text] = resum_quantitats

                    print(f"[-] TANCADA TRANSACCIÓ: {text}\n")

                    estat_inventari['estanteria_actual'] = None
                    estat_inventari['productes_temporals'] = {}
                    estat_inventari['sscc_vistos_actuals'] = set()
                    estat_inventari['temps_tancament'] = temps_actual

        # ========================================================
        # 2) LÒGICA DE PRODUCTES
        # ========================================================
        else:
            if estat_inventari['estanteria_actual'] is not None:

                # Només comptem CODE128 SSCC
                if not (tipus == "CODE128" and text.startswith("00")):
                    continue

                inventari_temp = estat_inventari['productes_temporals']
                sscc_vistos = estat_inventari['sscc_vistos_actuals']

                # No recomptar el mateix SSCC
                if text in sscc_vistos:
                    if DEBUG:
                        print(f"SSCC repetit ignorat: {text}")
                    continue

                sscc_vistos.add(text)

                # SSCC -> nom del producte
                clau_producte = estat_inventari['sscc_a_producte'].get(text, text)

                if clau_producte not in inventari_temp:
                    inventari_temp[clau_producte] = set()

                inventari_temp[clau_producte].add(text)

                if DEBUG:
                    print(
                        f"producte: {clau_producte} | "
                        f"SSCC: {text} | "
                        f"estanteria: {estat_inventari['estanteria_actual']}"
                    )

    dibuixar_estat(frame, estat_inventari)
    return frame


# ============================================================
# MAIN
# ============================================================

def main():
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MANIFEST_PATH = os.path.join(BASE_DIR, "etiquetes_magatzem_simulades_manifest.csv")

    print("Buscant manifest a:", MANIFEST_PATH)
    estanteries_valides, sscc_a_producte = carregar_manifest(MANIFEST_PATH)

    stream = CameraStream(FONT_VIDEO)

    if not stream.is_opened():
        print("Error: No s'ha pogut obrir la càmera.")
        return

    # Espera breu perquè el fil de captura carregui algun frame
    t0 = time.time()
    ret_inicial = False
    while time.time() - t0 < 5:
        ret_inicial, _ = stream.read()
        if ret_inicial:
            break
        time.sleep(0.05)

    if not ret_inicial:
        print("Error: No s'ha rebut cap frame de la càmera.")
        stream.release()
        return

    memoria_inventari = {
        'estanteria_actual': None,
        'temps_obertura': 0,
        'temps_tancament': 0,
        'productes_temporals': {},
        'inventari_global': {},
        'estanteries_valides': estanteries_valides,
        'sscc_a_producte': sscc_a_producte,
        'sscc_vistos_actuals': set(),
        'estat_text': "Estat: ESPERANT ESTANTERIA",
        'estat_color': (255, 255, 255),
    }

    print("Sistema actiu.")
    print("Enfoca una estanteria CODE39 del manifest per començar.")
    print(f"Estanteries carregades: {sorted(estanteries_valides)}")

    comptador_frames = 0

    try:
        while True:
            ret, frame = stream.read()
            if not ret or frame is None:
                continue

            comptador_frames += 1
            frame_mostrar = frame.copy()

            # Només processem 1 de cada N frames
            if comptador_frames % PROCESSAR_CADA_N_FRAMES == 0:
                frame_mostrar = processar_frame_inventari(frame_mostrar, memoria_inventari)
            else:
                # Als altres frames, només mostrem l'estat per reduir latència
                dibuixar_estat(frame_mostrar, memoria_inventari)

            cv2.imshow(TITOL_FINESTRA, frame_mostrar)

            tecla = cv2.waitKey(1) & 0xFF
            if tecla == ord('q'):
                break

    finally:
        stream.release()
        cv2.destroyAllWindows()

    print("\n--- RESUM DE L'INVENTARI (ESTANTERIA -> PRODUCTE : QUANTITAT) ---")
    for estanteria, productes in memoria_inventari['inventari_global'].items():
        print(f"[{estanteria}]")
        for codi_prod, quantitat in productes.items():
            print(f"  - {codi_prod}: {quantitat} unitats")


if __name__ == "__main__":
    main()
