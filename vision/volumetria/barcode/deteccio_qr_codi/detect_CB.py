import csv
import os
import shutil
import threading
import time
import cv2
import numpy as np
from pyzbar.pyzbar import decode

# ============================================================
# 1. CONFIGURACIÓ
# ============================================================

FONT_VIDEO = 0
# Si vols provar un stream TCP:
# FONT_VIDEO = "tcp://172.20.10.3:8888"

DEBUG = False
# True: torna a gravar i substitueix les imatges de la carpeta CB_in.
# False: no obre la càmera i analitza les imatges ja existents a CB_in.
REGRAVAR_IMATGES = False
PROCESSAR_CADA_N_FRAMES = 1
INTERVAL_GUARDAT_SEGONS = 0.5
ESCALA_DETECCIO_RAPIDA = 0.75
ESCALA_DETECCIO_FINE = 1.0
CARPETA_ENTRADA = "CB_in"
CARPETA_SORTIDA = "CB_out"
NOM_BASE_CAPTURA = "captura_inventari"
QUALITAT_JPEG = 90
TITOL_FINESTRA = "Gestio d'Inventari Drons"

COOLDOWN_TANCAMENT = 4.0
COOLDOWN_ENTRE_ESTANTERIES = 3.0

TIPUS_SUPORTATS = {
    "QRCODE", "EAN13", "EAN8", "UPCA", "UPCE", "CODE128", "CODE39", "I25"
}

# ============================================================
# 2. CÀMERA
# ============================================================

class CameraStream:
    """
    Manté sempre disponible l'últim frame rebut per minimitzar latència.
    """

    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

        self.frame = None
        self.frame_id = 0
        self.running = True
        self.lock = threading.Lock()

        self.thread = threading.Thread(target=self._update, daemon=True)
        self.thread.start()

    def _update(self):
        while self.running:
            ok, frame = self.cap.read()
            if ok:
                with self.lock:
                    self.frame = frame
                    self.frame_id += 1
            else:
                time.sleep(0.01)

    def read_latest(self):
        with self.lock:
            if self.frame is None:
                return False, None, None
            return True, self.frame.copy(), self.frame_id

    def is_opened(self):
        return self.cap.isOpened()

    def release(self):
        self.running = False
        self.thread.join(timeout=1)
        self.cap.release()

# ============================================================
# 3. MANIFEST CSV
# ============================================================

def netejar_text_codi(text):
    return text.strip().lstrip("ñ").replace("\x1d", "")


def carregar_manifest(path_csv):
    """
    Separa les estanteries vàlides i el mapa SSCC -> producte.
    """
    if not os.path.exists(path_csv):
        raise FileNotFoundError(f"No s'ha trobat el manifest a: {path_csv}")

    estanteries_valides = set()
    sscc_a_producte = {}

    with open(path_csv, newline="", encoding="utf-8") as fitxer:
        reader = csv.DictReader(fitxer)
        for row in reader:
            categoria = row["category"].strip()
            valor = netejar_text_codi(row["encoded_value"])
            nom = row["label_name"].strip()

            if categoria == "shelf":
                estanteries_valides.add(valor)
            elif categoria == "box" and valor.startswith("00"):
                sscc_a_producte[valor] = nom

    return estanteries_valides, sscc_a_producte

# ============================================================
# 4. CAPTURA DE FOTOGRAMES
# ============================================================

def esperar_primer_frame(stream, timeout=5.0):
    inici = time.time()

    while time.time() - inici < timeout:
        ok, frame, frame_id = stream.read_latest()
        if ok and frame is not None:
            return True, frame, frame_id
        time.sleep(0.05)

    return False, None, None


def netejar_carpeta(path_carpeta):
    os.makedirs(path_carpeta, exist_ok=True)

    for nom in os.listdir(path_carpeta):
        ruta = os.path.join(path_carpeta, nom)
        if os.path.isdir(ruta):
            shutil.rmtree(ruta)
        else:
            os.remove(ruta)

def preparar_carpeta_captura(base_dir):
    captura_dir = os.path.join(base_dir, CARPETA_ENTRADA)
    os.makedirs(captura_dir, exist_ok=True)

    # En mode captura, cada execució recrea el contingut de la carpeta CB_in.
    netejar_carpeta(captura_dir)

    marca_temps = time.strftime("%Y%m%d_%H%M%S")
    prefix = f"{NOM_BASE_CAPTURA}_{marca_temps}"
    return captura_dir, prefix

def preparar_carpeta_sortida(sortida_dir):
    # La carpeta CB_out sempre representa l'últim postprocessat.
    netejar_carpeta(sortida_dir)
    return sortida_dir


def guardar_fotograma(frame, captura_dir, prefix, index_frame):
    nom_fitxer = f"{prefix}_{index_frame:06d}.jpg"
    image_path = os.path.join(captura_dir, nom_fitxer)

    ok = cv2.imwrite(
        image_path,
        frame,
        [cv2.IMWRITE_JPEG_QUALITY, QUALITAT_JPEG],
    )
    if not ok:
        return None

    return image_path

def obtenir_fotogrames_guardats(captura_dir, prefix=None):
    noms_fitxer = []

    for nom_fitxer in os.listdir(captura_dir):
        if prefix is not None and not nom_fitxer.startswith(prefix):
            continue
        if not nom_fitxer.lower().endswith(".jpg"):
            continue
        noms_fitxer.append(nom_fitxer)

    noms_fitxer.sort()
    return [os.path.join(captura_dir, nom_fitxer) for nom_fitxer in noms_fitxer]

def capturar_fotogrames(src, base_dir):
    """
    Fase live stream.
    Aquí només es captura, es mostra el directe i es guarden JPGs.
    No hi ha cap detecció ni cap crida a pyzbar.
    """
    stream = CameraStream(src)

    if not stream.is_opened():
        print("Error: No s'ha pogut obrir la càmera.")
        return None

    ok, frame_inicial, frame_id_inicial = esperar_primer_frame(stream)
    if not ok:
        print("Error: No s'ha rebut cap frame de la càmera.")
        stream.release()
        return None

    captura_dir, prefix = preparar_carpeta_captura(base_dir)

    print("Guardando fotogramas...")
    print(f"Carpeta d'entrada: {captura_dir}")
    print("Prem 'q' per finalitzar la captura.")

    frame_actual = frame_inicial
    frame_actual_id = frame_id_inicial
    frames_guardats = 0
    ultim_temps_guardat = None
    inici_captura = time.perf_counter()

    try:
        while True:
            frame_nou = frames_guardats == 0

            ok, frame, frame_id = stream.read_latest()
            if ok and frame is not None and frame_id != frame_actual_id:
                frame_actual = frame
                frame_actual_id = frame_id
                frame_nou = True

            cv2.imshow(TITOL_FINESTRA, frame_actual)

            if frame_nou:
                temps_actual = time.perf_counter() - inici_captura
                if (
                    ultim_temps_guardat is None
                    or (temps_actual - ultim_temps_guardat) >= INTERVAL_GUARDAT_SEGONS
                ):
                    image_path = guardar_fotograma(
                        frame_actual,
                        captura_dir,
                        prefix,
                        frames_guardats,
                    )
                    if image_path is not None:
                        ultim_temps_guardat = temps_actual
                        frames_guardats += 1
                    else:
                        print("Avís: no s'ha pogut guardar un fotograma.")

            if (cv2.waitKey(1) & 0xFF) == ord("q"):
                break
    finally:
        stream.release()
        cv2.destroyAllWindows()

    if frames_guardats == 0:
        print("Error: no s'ha pogut guardar cap fotograma.")
        return None

    print("Captura finalizada.")
    return captura_dir, prefix

# ============================================================
# 5. DETECCIÓ DE CODIS
# ============================================================

def obtenir_rectangle_codi(codi):
    rect = codi.rect
    x = getattr(rect, "left", rect[0])
    y = getattr(rect, "top", rect[1])
    w = getattr(rect, "width", rect[2])
    h = getattr(rect, "height", rect[3])
    return x, y, w, h

def construir_dades_deteccio(codi, escala):
    try:
        text = netejar_text_codi(codi.data.decode("utf-8"))
    except Exception:
        return None

    if not text or codi.type not in TIPUS_SUPORTATS:
        return None

    x, y, w, h = obtenir_rectangle_codi(codi)

    if codi.polygon and len(codi.polygon) >= 4:
        punts = []
        for punt in codi.polygon:
            px = getattr(punt, "x", punt[0])
            py = getattr(punt, "y", punt[1])
            punts.append([px, py])

        pts = np.array([punts], dtype=np.int32)
        moments = cv2.moments(pts)

        if moments["m00"] != 0:
            cx = int(moments["m10"] / moments["m00"])
            cy = int(moments["m01"] / moments["m00"])
        else:
            cx = x + w // 2
            cy = y + h // 2
    else:
        pts = np.array([[
            [x, y],
            [x + w, y],
            [x + w, y + h],
            [x, y + h],
        ]], dtype=np.int32)
        cx = x + w // 2
        cy = y + h // 2

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
                gray,
                255,
                cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                cv2.THRESH_BINARY,
                31,
                7,
            )
        )

    return imatges

def construir_clau_deduccio(det):
    """
    Clau aproximada per evitar repetir el mateix codi llegit amb diferents preprocessats.
    El text forma part de la clau perquè dos codis diferents, encara que estiguin a prop,
    no es descartin entre ells.
    """
    pas_posicio = 30
    pas_mida = 30
    return (
        det["tipus"],
        det["text"],
        det["cx"] // pas_posicio,
        det["cy"] // pas_posicio,
        det["w"] // pas_mida,
        det["h"] // pas_mida,
    )

def es_deteccio_duplicada(det, deteccions_final, vistos):
    clau = construir_clau_deduccio(det)
    if clau in vistos:
        return True

    marge_posicio = 30
    marge_mida = 30

    for det_existent in deteccions_final:
        if det["tipus"] != det_existent["tipus"]:
            continue
        if det["text"] != det_existent["text"]:
            continue

        mateixa_posicio = (
            abs(det["cx"] - det_existent["cx"]) <= marge_posicio
            and abs(det["cy"] - det_existent["cy"]) <= marge_posicio
        )
        mida_similar = (
            abs(det["w"] - det_existent["w"]) <= marge_mida
            and abs(det["h"] - det_existent["h"]) <= marge_mida
        )

        if mateixa_posicio and mida_similar:
            return True

    return False

def afegir_deteccions(deteccions_raw, escala, deteccions_final, vistos):
    for codi in deteccions_raw:
        det = construir_dades_deteccio(codi, escala)
        if det is None:
            continue

        if es_deteccio_duplicada(det, deteccions_final, vistos):
            if DEBUG:
                print(f"[DEBUG] Duplicat ignorat: {det['tipus']} | {det['text']}")
            continue

        vistos.add(construir_clau_deduccio(det))
        deteccions_final.append(det)

def hi_ha_tipus_prioritari(deteccions, tipus_objectiu):
    if not tipus_objectiu:
        return bool(deteccions)

    return any(det["tipus"] in tipus_objectiu for det in deteccions)

def obtenir_frame_gris(frame, escala):
    if escala != 1.0:
        interpolacio = cv2.INTER_AREA if escala < 1.0 else cv2.INTER_LINEAR
        frame = cv2.resize(
            frame,
            (0, 0),
            fx=escala,
            fy=escala,
            interpolation=interpolacio,
        )

    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

def detectar_codis_mixtos(frame, tipus_prioritaris=None):
    """
    Manté exactament l'estratègia actual:
    1. passada ràpida a escala reduïda
    2. passada fina amb preprocessats addicionals

    tipus_prioritaris es conserva per compatibilitat amb la resta del codi,
    però ja no atura la cerca: s'acumulen tots els codis vàlids del frame.
    """
    deteccions_final = []
    vistos = set()

    gray_rapid = obtenir_frame_gris(frame, ESCALA_DETECCIO_RAPIDA)
    for img in preparar_imatges_deteccio(gray_rapid):
        afegir_deteccions(
            decode(img),
            ESCALA_DETECCIO_RAPIDA,
            deteccions_final,
            vistos,
        )

    gray_fine = obtenir_frame_gris(frame, ESCALA_DETECCIO_FINE)
    mateixa_escala = abs(ESCALA_DETECCIO_FINE - ESCALA_DETECCIO_RAPIDA) < 1e-6
    imatges_fine = preparar_imatges_deteccio(
        gray_fine,
        incloure_otsu=True,
        incloure_adaptativa=True,
    )

    if mateixa_escala:
        imatges_fine = imatges_fine[2:]

    for img in imatges_fine:
        afegir_deteccions(
            decode(img),
            ESCALA_DETECCIO_FINE,
            deteccions_final,
            vistos,
        )

    return deteccions_final

# ============================================================
# 6. LÒGICA D'INVENTARI
# ============================================================

def crear_estat_inventari(estanteries_valides, sscc_a_producte):
    return {
        "estanteria_actual": None,
        "temps_obertura": 0.0,
        # Evita un cooldown inicial fals: abans de tancar cap transacció,
        # la primera estanteria detectada ha de poder obrir-se immediatament.
        "temps_tancament": -float("inf"),
        "productes_temporals": {},
        "inventari_global": {},
        "estanteries_valides": estanteries_valides,
        "sscc_a_producte": sscc_a_producte,
        "sscc_vistos_actuals": set(),
        "codis_detectats_globals": set(),
        "registre_codis": [],
        "estat_text": "Estat: ESPERANT ESTANTERIA",
        "estat_color": (255, 255, 255),
    }

def dibuixar_estat_inventari(frame, estat_inventari, temps_actual=None):
    if temps_actual is None:
        temps_actual = time.time()

    if estat_inventari["estanteria_actual"] is None:
        if (temps_actual - estat_inventari["temps_tancament"]) < COOLDOWN_ENTRE_ESTANTERIES:
            estat_text = "Estat: COOLDOWN (Ignorant estanteries)"
            color_estat = (0, 165, 255)
        else:
            estat_text = "Estat: ESPERANT ESTANTERIA"
            color_estat = (255, 255, 255)
    else:
        estat_text = "LLEGINT: " + estat_inventari["estanteria_actual"]
        color_estat = (0, 255, 0)

    estat_inventari["estat_text"] = estat_text
    estat_inventari["estat_color"] = color_estat

    cv2.putText(
        frame,
        estat_text,
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.8,
        color_estat,
        2,
    )

def prioritat_processament_inventari(det, estat_inventari):
    """
    Ordena les deteccions sense filtrar-les:
    - si encara no hi ha estanteria, primer intentem obrir-la
    - si ja n'hi ha una oberta, primer registrem tots els productes visibles
    """
    tipus = det["tipus"]
    text = det["text"]

    if estat_inventari["estanteria_actual"] is None:
        if tipus == "CODE39" and text in estat_inventari["estanteries_valides"]:
            return 0
        if tipus == "CODE128" and text.startswith("00"):
            return 1
        return 2

    if tipus == "CODE128" and text.startswith("00"):
        return 0
    if tipus == "CODE39" and text == estat_inventari["estanteria_actual"]:
        return 1
    return 2

def registrar_codis_detectats(codis_detectats, estat_inventari, temps_actual):
    """
    Desa en memòria tots els codis únics llegits durant la prova.
    No afecta la lògica d'inventari ni escriu cap fitxer.
    """
    for det in codis_detectats:
        tipus = det["tipus"]
        text = det["text"]
        clau = (tipus, text)

        if clau in estat_inventari["codis_detectats_globals"]:
            if DEBUG:
                print(f"[DEBUG] Codi ja registrat globalment: {tipus} | {text}")
            continue

        si_es_estanteria_valida = (
            tipus == "CODE39"
            and text in estat_inventari["estanteries_valides"]
        )
        si_es_producte_code128 = tipus == "CODE128" and text.startswith("00")
        si_consta_al_manifest = (
            text in estat_inventari["estanteries_valides"]
            or text in estat_inventari["sscc_a_producte"]
        )
        producte = "No"
        if si_es_producte_code128:
            producte = estat_inventari["sscc_a_producte"].get(text, "Sí")

        estat_inventari["codis_detectats_globals"].add(clau)
        estat_inventari["registre_codis"].append({
            "tipus": tipus,
            "text": text,
            "temps_detectat": temps_actual,
            "estanteria_actual": estat_inventari["estanteria_actual"],
            "estanteria_oberta": False,
            "estanteria_tancada": False,
            "si_es_estanteria_valida": si_es_estanteria_valida,
            "si_es_producte_code128": si_es_producte_code128,
            "producte": producte,
            "si_consta_al_manifest": si_consta_al_manifest,
        })

        if DEBUG:
            print(f"[DEBUG] Nou codi registrat globalment: {tipus} | {text}")

def marcar_registre_codi(estat_inventari, tipus, text, camp):
    for registre in estat_inventari["registre_codis"]:
        if registre["tipus"] == tipus and registre["text"] == text:
            registre[camp] = True
            return

def processar_fotograma_inventari(frame, estat_inventari, temps_actual=None):
    """
    Aquesta funció només s'utilitza al postprocessat.
    La detecció i la lògica d'inventari es mantenen igual que a V2.
    """
    if temps_actual is None:
        temps_actual = time.time()

    tipus_prioritaris = {"CODE39"}
    if estat_inventari["estanteria_actual"] is not None:
        tipus_prioritaris = {"CODE128"}

    codis_detectats = detectar_codis_mixtos(frame, tipus_prioritaris=tipus_prioritaris)
    hi_ha_deteccions = bool(codis_detectats)
    registrar_codis_detectats(codis_detectats, estat_inventari, temps_actual)

    if DEBUG:
        print(f"[DEBUG] Codis detectats al frame: {len(codis_detectats)}")
        for det in codis_detectats:
            print(f"[DEBUG] - {det['tipus']} | {det['text']}")

    codis_processament = sorted(
        codis_detectats,
        key=lambda det: prioritat_processament_inventari(det, estat_inventari),
    )

    for det in codis_processament:
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
        cv2.putText(
            frame,
            etiqueta,
            (x, max(20, y - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.55,
            (0, 255, 0),
            2,
        )

        if tipus == "CODE39" and text in estat_inventari["estanteries_valides"]:
            if estat_inventari["estanteria_actual"] is None:
                temps_des_del_tancament = temps_actual - estat_inventari["temps_tancament"]

                if temps_des_del_tancament > COOLDOWN_ENTRE_ESTANTERIES:
                    estat_inventari["estanteria_actual"] = text
                    estat_inventari["temps_obertura"] = temps_actual
                    estat_inventari["productes_temporals"] = {}
                    estat_inventari["sscc_vistos_actuals"] = set()
                    marcar_registre_codi(
                        estat_inventari,
                        tipus,
                        text,
                        "estanteria_oberta",
                    )
                    print(f"\n[+] OBERTA TRANSACCIÓ: {text}")
                else:
                    cv2.putText(
                        frame,
                        "COOLDOWN ESTANTERIA...",
                        (x, max(40, y - 30)),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.6,
                        (0, 165, 255),
                        2,
                    )

            elif estat_inventari["estanteria_actual"] == text:
                temps_passat = temps_actual - estat_inventari["temps_obertura"]

                if temps_passat > COOLDOWN_TANCAMENT:
                    resum_quantitats = {
                        prod: len(ssccs)
                        for prod, ssccs in estat_inventari["productes_temporals"].items()
                    }

                    estat_inventari["inventari_global"][text] = resum_quantitats

                    marcar_registre_codi(
                        estat_inventari,
                        tipus,
                        text,
                        "estanteria_tancada",
                    )
                    print(f"[-] TANCADA TRANSACCIÓ: {text}\n")

                    estat_inventari["estanteria_actual"] = None
                    estat_inventari["productes_temporals"] = {}
                    estat_inventari["sscc_vistos_actuals"] = set()
                    estat_inventari["temps_tancament"] = temps_actual

        else:
            if estat_inventari["estanteria_actual"] is not None:
                if not (tipus == "CODE128" and text.startswith("00")):
                    continue

                inventari_temp = estat_inventari["productes_temporals"]
                sscc_vistos = estat_inventari["sscc_vistos_actuals"]

                if text in sscc_vistos:
                    if DEBUG:
                        print(f"[DEBUG] SSCC repetit ignorat: {text}")
                    continue

                sscc_vistos.add(text)

                clau_producte = estat_inventari["sscc_a_producte"].get(text, text)

                if clau_producte not in inventari_temp:
                    inventari_temp[clau_producte] = set()

                inventari_temp[clau_producte].add(text)

                if DEBUG:
                    print(
                        f"[DEBUG] Nou SSCC afegit | "
                        f"producte: {clau_producte} | "
                        f"SSCC: {text} | "
                        f"estanteria: {estat_inventari['estanteria_actual']}"
                    )

    dibuixar_estat_inventari(frame, estat_inventari, temps_actual=temps_actual)
    return frame, hi_ha_deteccions

def processar_fotogrames_guardats(
    entrada_dir,
    sortida_dir,
    prefix,
    estanteries_valides,
    sscc_a_producte,
):
    """
    Fase offline:
    - carrega els JPG guardats a CB_in, o tots els JPG de CB_in si prefix és None
    - executa la detecció
    - desa les imatges processades i marcades a CB_out
    """
    print("Iniciando postprocesado...")

    if not os.path.isdir(entrada_dir):
        raise RuntimeError(f"No s'ha trobat la carpeta d'entrada: {entrada_dir}")

    fotogrames_guardats = obtenir_fotogrames_guardats(entrada_dir, prefix)
    if not fotogrames_guardats:
        raise RuntimeError(f"No s'han trobat fotogrames per processar a: {entrada_dir}")

    preparar_carpeta_sortida(sortida_dir)

    estat_inventari = crear_estat_inventari(estanteries_valides, sscc_a_producte)

    for index_frame, image_path in enumerate(fotogrames_guardats, start=1):
        # Usar imdecode para evitar problemas de encoding Unicode en Windows
        if not os.path.exists(image_path):
            print(f"Avís: el archivo no existe: {image_path}")
            continue
        
        try:
            file_size = os.path.getsize(image_path)
            if file_size == 0:
                print(f"Avís: el archivo está vacío: {image_path}")
                continue
        except OSError as e:
            print(f"Avís: error al acceder al archivo {image_path}: {e}")
            continue
        
        # Leer archivo en bytes y decodificar con imdecode (funciona mejor con Unicode en Windows)
        try:
            with open(image_path, 'rb') as f:
                data = np.frombuffer(f.read(), np.uint8)
            frame = cv2.imdecode(data, cv2.IMREAD_COLOR)
            if frame is None:
                print(f"Avís: no s'ha pogut llegir {image_path} (format inválid o corrompido)")
                continue
        except Exception as e:
            print(f"Avís: error en lectura de {image_path}: {e}")
            continue

        if index_frame % max(PROCESSAR_CADA_N_FRAMES, 1) != 0:
            continue

        temps_captura = (index_frame - 1) * INTERVAL_GUARDAT_SEGONS

        frame_processat, _ = processar_fotograma_inventari(
            frame,
            estat_inventari,
            temps_actual=temps_captura,
        )

        nom_sortida = os.path.basename(image_path)
        image_path_sortida = os.path.join(sortida_dir, nom_sortida)

        # Usar imencode + open() para evitar problemas de encoding Unicode en Windows
        try:
            success, buffer = cv2.imencode('.jpg', frame_processat, [cv2.IMWRITE_JPEG_QUALITY, QUALITAT_JPEG])
            if success:
                with open(image_path_sortida, 'wb') as f:
                    f.write(buffer)
            else:
                print(f"Avís: no s'ha pogut processar {nom_sortida}")
        except Exception as e:
            print(f"Avís: error en guardat de {nom_sortida}: {e}")

    print("Postprocesado finalizado.")
    print(f"Imatges processades guardades a: {sortida_dir}")
    return estat_inventari

def imprimir_resum_inventari(estat_inventari):
    print("Resumen del inventario...")
    print("--- RESUM DE L'INVENTARI (ESTANTERIA -> PRODUCTE : QUANTITAT) ---")

    if not estat_inventari["inventari_global"]:
        print("No s'ha registrat cap inventari tancat.")
        return

    for estanteria, productes in estat_inventari["inventari_global"].items():
        print(f"[{estanteria}]")
        for codi_prod, quantitat in productes.items():
            print(f"  - {codi_prod}: {quantitat} unitats")

def text_si_no(valor):
    return "Sí" if valor else "No"

def imprimir_codis_detectats(estat_inventari):
    registre_codis = estat_inventari["registre_codis"]

    print("\n--- CODIS DETECTATS DURANT LA PROVA ---")

    if not registre_codis:
        print("No s'ha detectat cap codi durant la prova.")
        return

    print(f"\nTotal codis únics detectats: {len(registre_codis)}")

    for index, registre in enumerate(registre_codis, start=1):
        print(f"\n[{index}] Tipus: {registre['tipus']}")
        print(f"    Text: {registre['text']}")
        print(
            "    Estanteria oberta: "
            f"{text_si_no(registre['estanteria_oberta'])}"
        )
        print(
            "    Estanteria tancada: "
            f"{text_si_no(registre['estanteria_tancada'])}"
        )
        print(f"    Producte: {registre['producte']}")
        print(
            "    Consta al manifest: "
            f"{text_si_no(registre['si_consta_al_manifest'])}"
        )

# ============================================================
# 7. MAIN
# ============================================================

def main():
    base_dir = os.path.dirname(os.path.abspath(__file__))
    manifest_path = os.path.join(base_dir, "etiquetes_magatzem_simulades_manifest.csv")

    print("Buscant manifest a:", manifest_path)
    estanteries_valides, sscc_a_producte = carregar_manifest(manifest_path)
    print(f"Estanteries carregades: {sorted(estanteries_valides)}")

    if REGRAVAR_IMATGES:
        print("Mode captura: es tornaran a gravar i substituir les imatges de CB_in.")
        captura = capturar_fotogrames(FONT_VIDEO, base_dir)
        if captura is None:
            return

        entrada_dir, prefix = captura
    else:
        print("Mode anàlisi: es processaran les imatges existents de CB_in.")
        entrada_dir = os.path.join(base_dir, CARPETA_ENTRADA)
        prefix = None

    sortida_dir = os.path.join(base_dir, CARPETA_SORTIDA)

    estat_inventari = processar_fotogrames_guardats(
        entrada_dir,
        sortida_dir,
        prefix,
        estanteries_valides,
        sscc_a_producte,
    )

    imprimir_resum_inventari(estat_inventari)
    imprimir_codis_detectats(estat_inventari)

if __name__ == "__main__":
    main()
