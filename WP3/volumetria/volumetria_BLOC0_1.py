import os
import cv2
import time
import threading
import numpy as np
import torch
from ultralytics import SAM
from groundingdino.util.inference import load_model

# Importem les eines dels nostres mòduls
from volumetria_BLOC2 import extreure_ids_i_posicions
from volumetria_BLOC1 import detectar_qualsevol_caixa
from volumetria_BLOC3_1 import calcular_volumetria

# ==========================================
# CONFIGURACIÓ GENERAL
# ==========================================
CARPETA_FOTOS = "data/fotos_capturades"
DISTANCIA_LIDAR_CM = 120.0
CARPETA_RESULTATS = "outputs/Resultats_BLOC0"
MARGE_BORDE_VALIDACIO = 10

# ==========================================
# CONFIGURACIÓ DE CAPTURA DE VÍDEO
# ==========================================
GRAVAR_NOU_VIDEO = True
FONT_VIDEO = "tcp://172.20.10.2:8888"
INTERVAL_CAPTURA_SEG = 1.0

GDINO_CONFIG  = "../deteccion_cajas/groundingdino/config/GroundingDINO_SwinT_OGC.py"
GDINO_WEIGHTS = "../deteccion_cajas/weights/groundingdino_swint_ogc.pth"
DEVICE        = "cuda" if torch.cuda.is_available() else "cpu"
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

    if GRAVAR_NOU_VIDEO:
        if not capturar_frames_de_video(CARPETA_FOTOS, FONT_VIDEO, INTERVAL_CAPTURA_SEG): return
    else:
        if not os.path.exists(CARPETA_FOTOS): return

    print("\nCarregant models d'Intel·ligència Artificial...")
    detector = load_model(GDINO_CONFIG, GDINO_WEIGHTS).to(DEVICE)
    segmentador = SAM("models/mobile_sam.pt")

    os.makedirs(CARPETA_RESULTATS, exist_ok=True)
    arxius = sorted([f for f in os.listdir(CARPETA_FOTOS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not arxius: return

    dades_caixes = {}

    for nom_arxiu in arxius:
        ruta_completa = os.path.join(CARPETA_FOTOS, nom_arxiu)
        img = cv2.imread(ruta_completa)
        H, W = img.shape[:2]
        img_visual = img.copy() 
        
        caixes_frame = extreure_ids_i_posicions(img, detector, segmentador, DISTANCIA_LIDAR_CM)

        for caixa in caixes_frame:
            id_actual = caixa['id']
            bbox_actual = caixa['bbox']
            color = caixa['color']
            contorn = caixa['contorn']
            cx, cy = caixa['cx'], caixa['cy']

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
                    for (x, y) in vertexs:
                        cv2.circle(img_visual, (x, y), 8, (0, 0, 255), -1)
                else:
                    cv2.drawContours(img_visual, [vertexs_dibuix], -1, (0, 0, 255), 3)
                    cv2.putText(img_visual, "PARCIAL", (cx - 40, cy + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_visual)

    print(f"\n=== EXTRACCIÓ COMPLETADA ===")

    for id_caixa, diccionari_fotos in dades_caixes.items():
        print(f"\n==========================================")
        print(f" RESULTATS DE LA CAIXA [ID {id_caixa}]")

        if len(diccionari_fotos) > 1:
            res = calcular_volumetria(CARPETA_FOTOS, diccionari_fotos)
            if res:
                origen = "Frontals" if res['n_frontals'] > 0 else "Perspectiva"
                print(f"\n  [{origen}: {res['n_frontals']} frontals, {res['n_perspectiva']} perspectiva]")
                print(f"  Amplada (Frontal):     {res['amplada_cm']:.1f} cm")
                print(f"  Profunditat (Lateral): {res['profunditat_cm']:.1f} cm")
                print(f"  Alçada estimada:       {res['alcada_cm']:.1f} cm")
                print(f"  ------------------------------------------")
                print(f"  VOLUM TOTAL:           {res['volum_cm3']:.2f} cm³")
            else:
                print(f"  No s'ha pogut calcular el volum (falten fotos en perspectiva).")
        else:
            print(f"  Sense prous fotogrames nets per a la caixa {id_caixa}.")

        print(f"==========================================")

if __name__ == "__main__":
    executar_pipeline_orquestrat()
