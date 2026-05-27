
# BLOC 0: ORQUESTRADOR CENTRAL
import os
import sys
import cv2
import time
import csv
import threading
import torch
import numpy as np
from ultralytics import SAM   # ya no se importa YOLO

# Rutas
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
VOLUMETRIA_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "volumetria"))
DETECCION_DIR  = os.path.normpath(os.path.join(BASE_DIR, "..", "deteccion_cajas"))

# sys.path: VOLUMETRIA_DIR para encontrar 'groundingdino' como paquete
# (no hace falta para LECTOR_CODIS porque está en la misma carpeta que BLOC0)
if VOLUMETRIA_DIR not in sys.path:
   sys.path.insert(0, VOLUMETRIA_DIR)

# Imports locales (DESPUÉS del sys.path.insert)
from groundingdino.util.inference import load_model
from LECTOR_CODIS import detectar_codis
from BLOC2 import extreure_ids_i_posicions
from BLOC1 import detectar_qualsevol_caixa
from BLOC3 import calcular_volumetria

# Config GroundingDINO
GD_CONFIG_PATH  = os.path.join(VOLUMETRIA_DIR, "groundingdino", "config", "GroundingDINO_SwinT_OGC.py")
GD_WEIGHTS_PATH = os.path.join(DETECCION_DIR,  "weights", "groundingdino_swint_ogc.pth")
DEVICE          = "cuda" if torch.cuda.is_available() else "cpu"

# ==========================================
# CONFIGURACIÓ GENERAL
# ==========================================
CARPETA_FOTOS = os.path.join(VOLUMETRIA_DIR, "fotos_capturades")
DISTANCIA_LIDAR_CM = 120.0
CARPETA_RESULTATS = os.path.join(BASE_DIR, "resultados_fotos_capturades")
MARGE_BORDE_VALIDACIO = 10

MANIFEST_CSV = os.path.join(VOLUMETRIA_DIR, "etiquetes_magatzem_simulades_manifest.csv")

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
       raise FileNotFoundError(f"No s'ha trobat el manifest a: {path_csv}")

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
   Detecta tots els codis CODE39 i CODE128 d'un frame.

   Estrategia:
     1. Passada sobre el frame complet a escales x1 i x2.
        - x1: codis grans/propers (productes a la caixa).
        - x2: codis petits o llunyans (estanteries al fons).
     2. Per cada caixa segmentada, crop ampliat x4 per llegir
        codis molt petits sobre la caixa.

   Retorna llista de codis amb format:
       {
         'tipus':    'CODE39' | 'CODE128',
         'text':     contingut net del codi,
         'producte': nom del producte si esta al manifest, sino igual a text,
         'bbox':     (x1, y1, x2, y2)  en coordenades originals,
         'cx', 'cy': centre del codi en coordenades originals,
       }
   Deduplicat per (tipus, text).
   """
   ESCALA_CROP = 4.0

   deteccions = []
   vistos = set()

   def _afegir(dets, offset_x=0, offset_y=0, factor_crop=1.0):
       for d in dets:
           clau = (d["tipus"], d["text"])
           if clau in vistos:
               continue
           vistos.add(clau)
           x1, y1, x2, y2 = d["bbox"]
           # Si el crop estava escalat, tornem al espai del crop original
           if factor_crop != 1.0:
               x1, y1, x2, y2 = (int(x1 / factor_crop), int(y1 / factor_crop),
                                 int(x2 / factor_crop), int(y2 / factor_crop))
           # Mou al espai del frame complet
           x1 += offset_x; x2 += offset_x
           y1 += offset_y; y2 += offset_y
           deteccions.append({
               "tipus":    d["tipus"],
               "text":     d["text"],
               "producte": sscc_a_producte.get(d["text"], d["text"]),
               "bbox":     (x1, y1, x2, y2),
               "cx":       (x1 + x2) // 2,
               "cy":       (y1 + y2) // 2,
           })

   # 1. Frame complet a x1 i x2 (la x2 captura les estanteries llunyanes)
   _afegir(detectar_codis(img, escales=(1.0, 2.0)))

   # 2. Crop ampliat de cada caixa per codis molt petits
   if caixes_frame:
       H, W = img.shape[:2]
       for caixa in caixes_frame:
           bbox = caixa["bbox"]
           x1 = max(0, int(bbox[0]))
           y1 = max(0, int(bbox[1]))
           x2 = min(W, int(bbox[2]))
           y2 = min(H, int(bbox[3]))
           if x2 <= x1 or y2 <= y1:
               continue
           crop = img[y1:y2, x1:x2]
           crop_gran = cv2.resize(crop, None, fx=ESCALA_CROP, fy=ESCALA_CROP,
                                  interpolation=cv2.INTER_LANCZOS4)
           _afegir(detectar_codis(crop_gran, escales=(1.0,)),
                   offset_x=x1, offset_y=y1, factor_crop=ESCALA_CROP)

   return deteccions

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
   print(f"Manifest carregat: {len(estanteries)} estanteries, {len(sscc_productes)} SSCC.")

   if GRAVAR_NOU_VIDEO:
       if not capturar_frames_de_video(CARPETA_FOTOS, FONT_VIDEO, INTERVAL_CAPTURA_SEG): return
   else:
       if not os.path.exists(CARPETA_FOTOS): return

   print("\nCarregant models d'Intel·ligència Artificial...")
   detector = load_model(GD_CONFIG_PATH, GD_WEIGHTS_PATH).to(DEVICE)
   print(f"GroundingDINO carregat a {DEVICE.upper()}")
   segmentador = SAM(os.path.join(VOLUMETRIA_DIR, "mobile_sam.pt"))

   os.makedirs(CARPETA_RESULTATS, exist_ok=True)
   arxius = sorted([f for f in os.listdir(CARPETA_FOTOS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
  
   if not arxius: return

   dades_caixes = {}
   dades_codis = {}
   dades_estanteries = set()  # Codis de barres de tipus 'shelf' detectats als frames

   for nom_arxiu in arxius:
       ruta_completa = os.path.join(CARPETA_FOTOS, nom_arxiu)
       img = cv2.imread(ruta_completa)
       H, W = img.shape[:2]
       img_visual = img.copy()
      
       # Detectem caixes primer, després passem les ROIs completes per la lectura de codis
       caixes_frame = extreure_ids_i_posicions(img, detector, segmentador, DISTANCIA_LIDAR_CM)
       codis_al_frame = extreure_codis_imatge(img, sscc_productes, caixes_frame=caixes_frame)

       # Logica caixa-codi:
       #   - CODE39 amb text al manifest d'estanteries -> codi d'estanteria
       #   - Resta (CODE128, etc.) -> codi de producte, s'assigna a la caixa
       #     que conté el centre del codi.
       for codi in codis_al_frame:
           if codi['tipus'] == 'CODE39' and codi['text'] in estanteries:
               dades_estanteries.add(codi['text'])
               # Dibuixem l'estanteria en groc per distingir-la dels productes
               x1, y1, x2, y2 = codi['bbox']
               cv2.rectangle(img_visual, (x1, y1), (x2, y2), (0, 255, 255), 3)
               cv2.putText(img_visual, f"EST: {codi['text']}", (x1, max(20, y1 - 10)),
                           cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

       for caixa in caixes_frame:
           id_actual = caixa['id']
           bbox_actual = caixa['bbox']
           color = caixa['color']
           contorn = caixa['contorn']
           cx, cy = caixa['cx'], caixa['cy']

           for codi in codis_al_frame:
               # Saltem els codis d'estanteria: ja s'han processat a sobre
               if codi['tipus'] == 'CODE39' and codi['text'] in estanteries:
                   continue
               # Comprovem si el centre del codi cau dins el contorn de la caixa
               distancia = cv2.pointPolygonTest(contorn,
                                                (float(codi['cx']), float(codi['cy'])),
                                                False)
               if distancia >= 0:
                   dades_codis.setdefault(id_actual, set()).add(codi['producte'])
                   # Dibuixem el codi de producte en magenta
                   x1, y1, x2, y2 = codi['bbox']
                   cv2.rectangle(img_visual, (x1, y1), (x2, y2), (255, 0, 255), 3)
                   cv2.putText(img_visual, codi['producte'], (x1, max(20, y1 - 10)),
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
                   for (x, y) in vertexs:
                       cv2.circle(img_visual, (x, y), 8, (0, 0, 255), -1)
               else:
                   cv2.drawContours(img_visual, [vertexs_dibuix], -1, (0, 0, 255), 3)
                   cv2.putText(img_visual, "PARCIAL", (cx - 40, cy + 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

       cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_visual)

   print(f"\n=== EXTRACCIÓ COMPLETADA ===")

   # Estanteria detectada als frames (pot ser buida si no s'ha llegit cap codi)
   if dades_estanteries:
       text_estanteria = " | ".join(sorted(dades_estanteries))
   else:
       text_estanteria = "[NO DETECTADA]"

   for id_caixa, diccionari_fotos in dades_caixes.items():
       print(f"\n==========================================")
       print(f" RESULTATS DE LA CAIXA [ID {id_caixa}]")

       # Producte
       codis_associats = dades_codis.get(id_caixa, set())
       text_codis = " | ".join(sorted(codis_associats)) if codis_associats else "[NO DETECTAT]"
       print(f" > Codi / Producte:   {text_codis}")

       # Estanteria
       print(f" > Codi / Estanteria: {text_estanteria}")

       print(f"==========================================")

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


