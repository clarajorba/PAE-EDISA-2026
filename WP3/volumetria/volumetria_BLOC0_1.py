import os
import cv2
import time
import csv
import threading
import numpy as np
from ultralytics import YOLO, SAM
from pyzbar.pyzbar import decode
from detecció_qr_codi.detect_CB import detectar_codis_mixtos

# Importem les eines dels nostres mòduls
from volumetria_BLOC2 import extreure_ids_i_posicions
from volumetria_BLOC1 import detectar_qualsevol_caixa
from volumetria_BLOC3_1 import calcular_volumetria

# ==========================================
# CONFIGURACIÓ GENERAL
# ==========================================
CARPETA_FOTOS = "fotos_capturades" 
DISTANCIA_LIDAR_CM = 150.0
CARPETA_RESULTATS = "Resultats_BLOC0"
MARGE_BORDE_VALIDACIO = 10 

MANIFEST_CSV = "etiquetes_magatzem_simulades_manifest.csv"

# ==========================================
# CONFIGURACIÓ DE CAPTURA DE VÍDEO
# ==========================================
GRAVAR_NOU_VIDEO = False        
FONT_VIDEO = "tcp://172.20.10.2:8888"                 
INTERVAL_CAPTURA_SEG = 1.0      
# ==========================================

class CameraStream:
    def __init__(self, src):
        self.cap = cv2.VideoCapture(src)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        self.frame = None
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
            else:
                time.sleep(0.01)

    def read_latest(self):
        with self.lock:
            if self.frame is None:
                return False, None
            return True, self.frame.copy()

    def is_opened(self):
        return self.cap.isOpened()

    def release(self):
        self.running = False
        self.thread.join(timeout=1)
        self.cap.release()

def netejar_text_codi(text):
    return text.strip().lstrip("ñ").replace("\x1d", "")

def carregar_manifest(path_csv):
    estanteries_valides = set()
    sscc_a_producte = {}
    
    if not os.path.exists(path_csv):
        return estanteries_valides, sscc_a_producte

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

def extreure_codis_imatge(img, sscc_a_producte, caixes_frame=None):
    """
    Detecta codis de barres aprofitant les ROIs de les caixes segmentades.
    Estratègia per cada caixa:
      1. Passada ràpida sobre la imatge completa (si la càmera és a prop)
      2. Crop del bbox de cada caixa escalat x4 amb INTER_LANCZOS4
         (màxima qualitat per barcodes petits a distància)
      3. Usa detectar_codis_mixtos() de detect_CB, que ja incorpora
         múltiples preprocessats robustos (equalització, Otsu, adaptativa)
    Les coordenades retornades sempre són en espai de la imatge original.
    """
    ESCALA_CROP = 4  # x4 és el punt òptim per barcodes a ~150cm

    resultats = []
    codis_crus_vistos = set()

    def _registrar_deteccions(deteccions, offset_x=0, offset_y=0, escala=1.0):
        """Converteix deteccions de detect_CB al format intern de BLOC0."""
        for det in deteccions:
            dades_netes = netejar_text_codi(det['text'])
            if dades_netes in codis_crus_vistos:
                continue
            codis_crus_vistos.add(dades_netes)
            nom_etiqueta = sscc_a_producte.get(dades_netes, dades_netes)
            # Coordenades en espai de la imatge original
            cx = offset_x + det['cx'] / escala
            cy = offset_y + det['cy'] / escala
            resultats.append({
                'data':     nom_etiqueta,
                'codi_cru': dades_netes,
                'cx':       cx,
                'cy':       cy,
                # Rect sintètic en coordenades originals per dibuixar
                'offset_x': offset_x,
                'offset_y': offset_y,
                'escala':   escala,
                'det_x':    det['x'],
                'det_y':    det['y'],
                'det_w':    det['w'],
                'det_h':    det['h'],
            })

    # --- Passada 1: imatge completa (detecció ràpida si la càmera és a prop) ---
    _registrar_deteccions(detectar_codis_mixtos(img))

    # --- Passada 2: crop ampliat per cada caixa segmentada ---
    if caixes_frame:
        H, W = img.shape[:2]
        for caixa in caixes_frame:
            bbox = caixa['bbox']
            x1 = max(0, int(bbox[0]))
            y1 = max(0, int(bbox[1]))
            x2 = min(W, int(bbox[2]))
            y2 = min(H, int(bbox[3]))
            if x2 <= x1 or y2 <= y1:
                continue

            crop = img[y1:y2, x1:x2]
            # LANCZOS4: millor interpolació per ampliar imatges amb textures fines
            crop_gran = cv2.resize(crop, None,
                                   fx=ESCALA_CROP, fy=ESCALA_CROP,
                                   interpolation=cv2.INTER_LANCZOS4)

            dets = detectar_codis_mixtos(crop_gran)
            _registrar_deteccions(dets, offset_x=x1, offset_y=y1, escala=float(ESCALA_CROP))

    return resultats

def capturar_frames_de_video(carpeta_desti, font_video, interval_seg):
    os.makedirs(carpeta_desti, exist_ok=True)
    for arxiu in os.listdir(carpeta_desti):
        ruta_arxiu = os.path.join(carpeta_desti, arxiu)
        if os.path.isfile(ruta_arxiu):
            os.remove(ruta_arxiu)

    stream = CameraStream(font_video)
    time.sleep(1.0) 

    if not stream.is_opened():
        return False

    ultim_temps_guardat = time.time()
    comptador_frames = 1

    while True:
        ret, frame = stream.read_latest()
        if not ret or frame is None:
            continue

        temps_actual = time.time()
        frame_visual = frame.copy()
        cv2.putText(frame_visual, "Gravant... Prem 'q' per aturar", (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("Captura en Directe (BLOC 0)", frame_visual)

        if (temps_actual - ultim_temps_guardat) >= interval_seg:
            nom_arxiu = f"frame_{comptador_frames:04d}.jpg"
            ruta_guardar = os.path.join(carpeta_desti, nom_arxiu)
            cv2.imwrite(ruta_guardar, frame)
            ultim_temps_guardat = temps_actual
            comptador_frames += 1

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    stream.release()
    cv2.destroyAllWindows()
    return True

def executar_pipeline_orquestrat():
    print(f"\n=== INICIANT ORQUESTRADOR CENTRAL (AMB DETECCIÓ D'OCLUSIONS) ===")
    
    estanteries, sscc_productes = carregar_manifest(MANIFEST_CSV)

    if GRAVAR_NOU_VIDEO:
        if not capturar_frames_de_video(CARPETA_FOTOS, FONT_VIDEO, INTERVAL_CAPTURA_SEG): return
    else:
        if not os.path.exists(CARPETA_FOTOS): return

    print("\nCarregant models d'Intel·ligència Artificial...")
    detector = YOLO("yolov8s-world.pt")
    detector.set_classes(["box"]) 
    segmentador = SAM("mobile_sam.pt") 

    os.makedirs(CARPETA_RESULTATS, exist_ok=True)
    arxius = sorted([f for f in os.listdir(CARPETA_FOTOS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not arxius: return

    dades_caixes = {}
    dades_codis = {} 

    for nom_arxiu in arxius:
        ruta_completa = os.path.join(CARPETA_FOTOS, nom_arxiu)
        img = cv2.imread(ruta_completa)
        H, W = img.shape[:2]
        img_visual = img.copy() 
        
        # Detectem caixes primer, després passem les ROIs completes per la lectura de codis
        caixes_frame = extreure_ids_i_posicions(img, detector, segmentador, DISTANCIA_LIDAR_CM)
        codis_al_frame = extreure_codis_imatge(img, sscc_productes, caixes_frame=caixes_frame)
        
        for caixa in caixes_frame:
            id_actual = caixa['id']
            bbox_actual = caixa['bbox']
            color = caixa['color']
            contorn = caixa['contorn']
            cx, cy = caixa['cx'], caixa['cy']
            
            for codi in codis_al_frame:
                distancia = cv2.pointPolygonTest(contorn, (float(codi['cx']), float(codi['cy'])), False)
                if distancia >= 0:
                    if id_actual not in dades_codis:
                        dades_codis[id_actual] = set()
                    dades_codis[id_actual].add(codi['data'])
                    # Coordenades del rectangle en espai de la imatge original
                    ox  = codi.get('offset_x', 0)
                    oy  = codi.get('offset_y', 0)
                    esc = codi.get('escala', 1.0)
                    rx1 = int(ox + codi.get('det_x', 0) / esc)
                    ry1 = int(oy + codi.get('det_y', 0) / esc)
                    rx2 = int(rx1 + codi.get('det_w', 50) / esc)
                    ry2 = int(ry1 + codi.get('det_h', 20) / esc)
                    cv2.rectangle(img_visual, (rx1, ry1), (rx2, ry2), (255, 0, 255), 3)
                    cv2.putText(img_visual, codi['data'], (rx1, ry1 - 10),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 3)

            # Pintar màscares
            mascara_binaria = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
            cv2.fillPoly(mascara_binaria, [contorn], 255)
            color_capa = np.zeros_like(img)
            color_capa[:] = color
            mescla = cv2.addWeighted(img_visual, 0.6, color_capa, 0.4, 0)
            img_visual[mascara_binaria == 255] = mescla[mascara_binaria == 255]
            cv2.drawContours(img_visual, [contorn], -1, color, 2)
            
            text_id = f"ID_{id_actual}"
            cv2.putText(img_visual, text_id, (cx - 40, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4)
            cv2.putText(img_visual, text_id, (cx - 40, cy - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)
            
            # Càlcul de les 4 esquines (El BLOC 1 farà la seva feina normal)
            vertexs = detectar_qualsevol_caixa(ruta_o_img=img, mostrar_visualment=False, bbox_objectiu=bbox_actual, segmentador=segmentador, detector=detector)
            
            toca_borde = False

            if vertexs is not None:
                for (vx, vy) in vertexs:
                    if vx <= MARGE_BORDE_VALIDACIO or vx >= (W - MARGE_BORDE_VALIDACIO) or \
                       vy <= MARGE_BORDE_VALIDACIO or vy >= (H - MARGE_BORDE_VALIDACIO):
                        toca_borde = True
                        break

            if vertexs is not None and len(vertexs) >= 4:
                vertexs_dibuix = np.array(vertexs, dtype=np.int32).reshape((-1, 1, 2))

                if not toca_borde:
                    if id_actual not in dades_caixes:
                        dades_caixes[id_actual] = {}
                    dades_caixes[id_actual][nom_arxiu] = vertexs
                    cv2.drawContours(img_visual, [vertexs_dibuix], -1, (0, 255, 0), 3)
                    for i, (x, y) in enumerate(vertexs):
                        cv2.circle(img_visual, (x, y), 8, (0, 0, 255), -1)
                else:
                    cv2.drawContours(img_visual, [vertexs_dibuix], -1, (0, 0, 255), 3)
                    cv2.putText(img_visual, "PARCIAL", (cx - 40, cy + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_visual)

    print(f"\n=== EXTRACCIÓ COMPLETADA ===")
    
    for id_caixa, diccionari_fotos in dades_caixes.items():
        print(f"\n==========================================")
        print(f" RESULTATS DE LA CAIXA [ID {id_caixa}]")
        
        codis_associats = dades_codis.get(id_caixa, set())
        if codis_associats:
            text_codis = " | ".join(codis_associats)
            print(f" > Codi / Producte: {text_codis}")
        else:
            print(f" > Codi / Producte: [NO DETECTAT]")
            
        print(f"==========================================")
        
        if len(diccionari_fotos) > 1: 
            calcular_volumetria(CARPETA_FOTOS, diccionari_fotos) 
        else:
            print(f"Sense prous fotogrames nets per a la caixa {id_caixa} (Oclusa o no detectada).")

if __name__ == "__main__":
    executar_pipeline_orquestrat()