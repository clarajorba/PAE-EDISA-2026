import cv2
import numpy as np
import time
import csv
import os   # >>> AFEGIT
from pyzbar.pyzbar import decode

TIPUS_SUPORTATS = {
    "QRCODE", "EAN13", "EAN8", "UPCA", "UPCE", "CODE128", "CODE39", "I25"
}

# >>> AFEGIT
def netejar_text_codi(text):
    """
    Neteja possibles caràcters especials de GS1/FNC1.
    Alguns CODE128/GS1 poden portar caràcters estranys al principi o separadors.
    """
    return text.strip().lstrip("ñ").replace("\x1d", "")

# >>> AFEGIT
def carregar_manifest(path_csv):
    """
    Llegeix el CSV i separa:
    - estanteries vàlides (CODE39)
    - codis SSCC de caixa (CODE128 que comencen per 00) -> nom del producte
    """
    if not os.path.exists(path_csv):   # >>> AFEGIT
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
                # Només ens quedem amb el codi SSCC per comptar caixes
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

def obtenir_punts_i_centre(codi):
    """
    Retorna:
    - pts: polígon per dibuixar
    - cx, cy: centre del codi
    - x, y, w, h: rectangle bounding box
    """
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

    return pts, cx, cy, x, y, w, h

def detectar_codis_mixtos(frame):
    """
    Prova a detectar codis sobre diverses versions del frame
    per millorar la lectura de codis de barres 1D.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    equalitzat = cv2.equalizeHist(gray)
    blur = cv2.GaussianBlur(gray, (3, 3), 0)
    thresh_otsu = cv2.threshold(blur, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
    thresh_adapt = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 31, 7
    )

    imatges = [gray, equalitzat, thresh_otsu, thresh_adapt]

    deteccions_final = []
    vistos = set()

    for img in imatges:
        deteccions = decode(img)
        for codi in deteccions:
            if codi.type not in TIPUS_SUPORTATS:
                continue

            try:
                text = netejar_text_codi(codi.data.decode("utf-8"))   # >>> CANVIAT
            except:
                continue

            if not text:
                continue

            x, y, w, h = obtenir_rect(codi)

            clau = (codi.type, text, x // 20, y // 20, w // 20, h // 20)
            if clau in vistos:
                continue

            vistos.add(clau)
            deteccions_final.append(codi)

    return deteccions_final

def processar_frame_inventari(frame, estat_inventari):
    """
    Detecta codis de l'inventari simulat:
    - estanteries: CODE39 presents al manifest
    - caixes: CODE128 que comencen per 00 (SSCC)
    """
    codis_detectats = detectar_codis_mixtos(frame)
    temps_actual = time.time()

    COOLDOWN_TANCAMENT = 4.0
    COOLDOWN_ENTRE_ESTANTERIES = 3.0
    # DISTANCIA_MAXIMA = 180.0   # >>> ELIMINAT: ja no comptem per distància

    for codi in codis_detectats:
        try:
            text = netejar_text_codi(codi.data.decode('utf-8'))   # >>> CANVIAT
        except:
            continue

        tipus = codi.type
        pts, cx, cy, x, y, w, h = obtenir_punts_i_centre(codi)

        etiqueta = f"{tipus}: {text}"
        print(f"Tipus detectat: {tipus}, Contingut: {text}")

        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1)
        cv2.putText(frame, etiqueta, (x, max(20, y - 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 0), 2)

        # ============================================================
        # 1) LÒGICA D'ESTANTERIES
        # >>> CANVIAT:
        # Ara: CODE39 que estigui dins del manifest d'estanteries
        # ============================================================
        if tipus == "CODE39" and text in estat_inventari['estanteries_valides']:

            if estat_inventari['estanteria_actual'] is None:
                temps_des_del_tancament = temps_actual - estat_inventari['temps_tancament']

                if temps_des_del_tancament > COOLDOWN_ENTRE_ESTANTERIES:
                    estat_inventari['estanteria_actual'] = text
                    estat_inventari['temps_obertura'] = temps_actual
                    estat_inventari['productes_temporals'] = {}
                    estat_inventari['sscc_vistos_actuals'] = set()   # >>> AFEGIT
                    print(f"\n[+] OBERTA TRANSACCIÓ: {text}")
                else:
                    cv2.putText(frame, "COOLDOWN ESTANTERIA...", (x, max(40, y - 30)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

            elif estat_inventari['estanteria_actual'] == text:
                temps_passat = temps_actual - estat_inventari['temps_obertura']

                if temps_passat > COOLDOWN_TANCAMENT:
                    # >>> CANVIAT: ara cada producte guarda un set d'SSCCs únics
                    resum_quantitats = {
                        prod: len(ssccs)
                        for prod, ssccs in estat_inventari['productes_temporals'].items()
                    }

                    estat_inventari['inventari_global'][text] = resum_quantitats

                    print(f"[-] TANCADA TRANSACCIÓ: {text}\n")

                    estat_inventari['estanteria_actual'] = None
                    estat_inventari['productes_temporals'] = {}
                    estat_inventari['sscc_vistos_actuals'] = set()   # >>> AFEGIT
                    estat_inventari['temps_tancament'] = temps_actual

        # ============================================================
        # 2) LÒGICA DE PRODUCTES
        # >>> CANVIAT COMPLETAMENT:
        # Ara comptem per SSCC únic, no per distància
        # ============================================================
        else:
            if estat_inventari['estanteria_actual'] is not None:

                # Ignorem tot el que no sigui el CODE128 SSCC de caixa
                if not (tipus == "CODE128" and text.startswith("00")):
                    continue

                inventari_temp = estat_inventari['productes_temporals']
                sscc_vistos = estat_inventari['sscc_vistos_actuals']   # >>> AFEGIT

                # >>> AFEGIT
                # Si aquest SSCC ja s'ha vist en aquesta estanteria, no el recomptem
                if text in sscc_vistos:
                    print(f"SSCC repetit ignorat: {text}")
                    continue

                # >>> AFEGIT
                # Marquem l'SSCC com a vist
                sscc_vistos.add(text)

                # Convertim SSCC -> nom del producte segons el manifest
                clau_producte = estat_inventari['sscc_a_producte'].get(text, text)

                # >>> CANVIAT
                # Ara guardem un set d'SSCCs únics per producte
                if clau_producte not in inventari_temp:
                    inventari_temp[clau_producte] = set()

                inventari_temp[clau_producte].add(text)

                print(f"producte: {clau_producte} | SSCC: {text} | estanteria: {estat_inventari['estanteria_actual']}")

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

    cv2.putText(frame, estat_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_estat, 2)
    return frame

def main():
    FONT_VIDEO = "tcp://172.20.10.3:8888"
    # o per exemple:
    # FONT_VIDEO = "tcp://192.168.137.10:8888"

    # >>> CANVIAT
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    MANIFEST_PATH = os.path.join(BASE_DIR, "etiquetes_magatzem_simulades_manifest.csv")

    print("Buscant manifest a:", MANIFEST_PATH)   # >>> AFEGIT

    estanteries_valides, sscc_a_producte = carregar_manifest(MANIFEST_PATH)

    cap = cv2.VideoCapture(FONT_VIDEO)
    if not cap.isOpened():
        print("Error: No s'ha pogut obrir la càmera.")
        return

    memoria_inventari = {
        'estanteria_actual': None,
        'temps_obertura': 0,
        'temps_tancament': 0,
        'productes_temporals': {},
        'inventari_global': {},
        'estanteries_valides': estanteries_valides,
        'sscc_a_producte': sscc_a_producte,
        'sscc_vistos_actuals': set(),   # >>> AFEGIT
    }

    print("Sistema actiu.")
    print("Enfoca una estanteria CODE39 del PDF per començar.")
    print(f"Estanteries carregades: {sorted(estanteries_valides)}")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_resultat = processar_frame_inventari(frame, memoria_inventari)
        cv2.imshow("Gestio d'Inventari Drons", frame_resultat)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

    print("\n--- RESUM DE L'INVENTARI (ESTANTERIA -> PRODUCTE : QUANTITAT) ---")
    for estanteria, productes in memoria_inventari['inventari_global'].items():
        print(f"[{estanteria}]")
        for codi_prod, quantitat in productes.items():
            print(f"  - {codi_prod}: {quantitat} unitats")

if __name__ == "__main__":
    main()