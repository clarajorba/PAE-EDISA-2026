
# BLOC 0: ORQUESTRADOR CENTRAL
import os
import sys
import cv2
import time
import csv
import threading
import torch
import numpy as np
from dataclasses import dataclass
from ultralytics import SAM   # ya no se importa YOLO

try:
   from pyzbar.pyzbar import ZBarSymbol, decode
except ImportError as exc:
   ZBAR_IMPORT_ERROR = exc
   ZBarSymbol = None
   decode = None
else:
   ZBAR_IMPORT_ERROR = None

# Rutas
BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
VOLUMETRIA_DIR = os.path.normpath(os.path.join(BASE_DIR, "..", "volumetria"))
DETECCION_DIR  = os.path.normpath(os.path.join(BASE_DIR, "..", "deteccion_cajas"))

# sys.path: DETECCION_DIR per trobar 'groundingdino' com a paquet
# (el paquet groundingdino viu a deteccion_cajas, no a volumetria)
if DETECCION_DIR not in sys.path:
   sys.path.insert(0, DETECCION_DIR)

# Imports locales (DESPUÉS del sys.path.insert)
from groundingdino.util.inference import load_model
from BLOC2 import extreure_ids_i_posicions
from BLOC1 import detectar_qualsevol_caixa
from BLOC3 import calcular_volumetria

# Config GroundingDINO
GD_CONFIG_PATH  = os.path.join(DETECCION_DIR, "groundingdino", "config", "GroundingDINO_SwinT_OGC.py")
GD_WEIGHTS_PATH = os.path.join(DETECCION_DIR,  "weights", "groundingdino_swint_ogc.pth")
DEVICE          = "cuda" if torch.cuda.is_available() else "cpu"

# ==========================================
# CONFIGURACIÓ GENERAL
# ==========================================
CARPETA_FOTOS = os.path.join(VOLUMETRIA_DIR, "data", "fotos_capturades")
DISTANCIA_LIDAR_CM = 120.0
CARPETA_RESULTATS = os.path.join(BASE_DIR, "resultados_fotos_capturades")
MARGE_BORDE_VALIDACIO = 10

MANIFEST_CSV = os.path.join(VOLUMETRIA_DIR, "data", "etiquetes_magatzem_manifest.csv")
DEBUG_CODIS = False
TIPUS_SUPORTATS = {
   "QRCODE", "EAN13", "EAN8", "UPCA", "UPCE", "CODE128", "CODE39", "I25"
}
ESCALAS_DETECCION = (1.0, 1.5, 2.0, 0.75)
ESCALA_CROP_CODIS = 4.0
FRAME_INTERVAL_SECONDS = 0.5
COOLDOWN_TANCAMENT = 4.0
COOLDOWN_ENTRE_ESTANTERIES = 3.0
AUTO_CERRAR_ESTANTERIA_AL_FINAL = True

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
   es_producte_registrable: bool
   producte: str | None
   consta_manifest: bool


def netejar_text_codi(text):
   return text.strip().replace("\x1d", "").strip()


def carregar_manifest(path_csv):
   estanteries_valides = set()
   codi_a_producte = {}

   if not os.path.exists(path_csv):
       raise FileNotFoundError(f"No s'ha trobat el manifest a: {path_csv}")

   with open(path_csv, newline="", encoding="utf-8") as fitxer:
       reader = csv.DictReader(fitxer)
       columnes_requerides = {"category", "encoded_value", "label_name"}
       if not reader.fieldnames or not columnes_requerides.issubset(reader.fieldnames):
           raise RuntimeError(
               "El manifest no te les columnes requerides: "
               "category, encoded_value, label_name"
           )

       for row in reader:
           categoria = row["category"].strip().lower()
           valor = netejar_text_codi(row["encoded_value"])
           nom = (
               row.get("label_name", "").strip()
               or row.get("product_code", "").strip()
               or valor
           )

           if not valor:
               continue

           if categoria == "shelf":
               estanteries_valides.add(valor)
           elif categoria in {"product", "box"}:
               codi_a_producte[valor] = nom

   return estanteries_valides, codi_a_producte


def obtenir_simbols_zbar():
   if ZBarSymbol is None:
       return None

   simbols = []
   for nom in sorted(TIPUS_SUPORTATS):
       simbol = getattr(ZBarSymbol, nom, None)
       if simbol is not None:
           simbols.append(simbol)

   return simbols or None


def redimensionar(frame, escala):
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


def preparar_imatges_deteccio(gray):
   blur = cv2.GaussianBlur(gray, (3, 3), 0)
   sharpen_kernel = np.array(
       [[0, -1, 0], [-1, 5, -1], [0, -1, 0]],
       dtype=np.float32,
   )
   sharpen = cv2.filter2D(gray, -1, sharpen_kernel)

   return [
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


def obtenir_rectangle_codi(codi):
   rect = codi.rect
   x = getattr(rect, "left", rect[0])
   y = getattr(rect, "top", rect[1])
   w = getattr(rect, "width", rect[2])
   h = getattr(rect, "height", rect[3])
   return int(x), int(y), int(w), int(h)


def obtenir_poligon_i_centre(codi, x, y, w, h):
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


def construir_deteccio(codi, escala, origen):
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


def rect_iou(a, b):
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


def es_deteccio_duplicada(det, deteccions):
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


def detectar_codis_frame(frame):
   if decode is None:
       raise RuntimeError(
           "pyzbar no esta disponible. Instal.la pyzbar i la llibreria nativa zbar."
       )

   simbols = obtenir_simbols_zbar()
   deteccions = []

   for escala in ESCALAS_DETECCION:
       frame_escalat = redimensionar(frame, escala)
       gray = cv2.cvtColor(frame_escalat, cv2.COLOR_BGR2GRAY)

       for nom_preprocesat, imatge in preparar_imatges_deteccio(gray):
           origen = f"escala_{escala:g}_{nom_preprocesat}"
           try:
               codis_raw = decode(imatge, symbols=simbols)
           except Exception as exc:
               if DEBUG_CODIS:
                   print(f"[DEBUG] Error pyzbar en {origen}: {exc}")
               continue

           for codi in codis_raw:
               det = construir_deteccio(codi, escala, origen)
               if det is None:
                   continue
               if es_deteccio_duplicada(det, deteccions):
                   if DEBUG_CODIS:
                       print(f"[DEBUG] Codi duplicat ignorat: {det.tipus} | {det.text}")
                   continue
               deteccions.append(det)

   return deteccions


def moure_deteccio_crop(det, offset_x, offset_y, factor_crop):
   x = int(round(det.x / factor_crop)) + offset_x
   y = int(round(det.y / factor_crop)) + offset_y
   w = max(1, int(round(det.w / factor_crop)))
   h = max(1, int(round(det.h / factor_crop)))
   cx = int(round(det.cx / factor_crop)) + offset_x
   cy = int(round(det.cy / factor_crop)) + offset_y
   polygon = np.rint(det.polygon.astype(np.float32) / factor_crop).astype(np.int32)
   polygon[:, 0] += offset_x
   polygon[:, 1] += offset_y

   return Detection(
       tipus=det.tipus,
       text=det.text,
       polygon=polygon,
       cx=cx,
       cy=cy,
       x=x,
       y=y,
       w=w,
       h=h,
       origen=f"crop_{det.origen}",
   )


def deteccio_a_dict(det, codi_a_producte):
   return {
       "tipus": det.tipus,
       "text": det.text,
       "producte": codi_a_producte.get(det.text, det.text),
       "bbox": (det.x, det.y, det.x + det.w, det.y + det.h),
       "cx": det.cx,
       "cy": det.cy,
       "polygon": det.polygon,
       "origen": det.origen,
   }


def color_deteccio(codi):
   if codi["tipus"] == "CODE39":
       return (0, 220, 0)
   if codi["tipus"] == "CODE128" and codi["text"].startswith("00"):
       return (255, 120, 0)
   return (0, 200, 255)


def dibuixar_etiqueta_codi(frame, codi, color):
   h_img, w_img = frame.shape[:2]
   x1, y1, _, _ = codi["bbox"]
   x = max(5, min(x1, w_img - 20))
   y = max(20, y1 - 10)

   linies = [codi["tipus"], codi["text"]]
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


def anotar_codis_frame(frame, codis):
   for codi in codis:
       color = color_deteccio(codi)
       cv2.polylines(frame, [codi["polygon"]], isClosed=True, color=color, thickness=2)
       cv2.circle(frame, (codi["cx"], codi["cy"]), 5, (0, 0, 255), -1)
       dibuixar_etiqueta_codi(frame, codi, color)


def extreure_codis_imatge(img, codi_a_producte, caixes_frame=None):
   """
   Detecta codis/QR amb el mateix pipeline robust de detect_CB.py i conserva
   els crops de caixa per millorar lectures petites sobre productes.
   """
   deteccions = []

   def _afegir(dets):
       for det in dets:
           if es_deteccio_duplicada(det, deteccions):
               continue
           deteccions.append(det)

   _afegir(detectar_codis_frame(img))

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
           crop_gran = cv2.resize(crop, None, fx=ESCALA_CROP_CODIS, fy=ESCALA_CROP_CODIS,
                                  interpolation=cv2.INTER_LANCZOS4)
           deteccions_crop = [
               moure_deteccio_crop(det, x1, y1, ESCALA_CROP_CODIS)
               for det in detectar_codis_frame(crop_gran)
           ]
           _afegir(deteccions_crop)

   return [deteccio_a_dict(det, codi_a_producte) for det in deteccions]


def crear_estat_inventari(estanteries_valides, codi_a_producte):
   return {
       "estanteria_actual": None,
       "temps_obertura": 0.0,
       "temps_tancament": -float("inf"),
       "productes_temporals": {},
       "codis_producte_vistos_actuals": set(),
       "inventari_global": {},
       "estanteries_valides": estanteries_valides,
       "codi_a_producte": codi_a_producte,
       "codis_globals": {},
       "registre_codis": [],
       "frames_processats": 0,
       "frames_amb_deteccions": 0,
       "ultim_index_frame": 0,
       "ultim_temps_simulat": 0.0,
       "transaccions": [],
   }


def es_estanteria_valida(codi, estat):
   return codi["tipus"] == "CODE39" and codi["text"] in estat["estanteries_valides"]


def es_producte_registrable(codi, estat):
   return codi["text"] in estat["codi_a_producte"]


def producte_de_codi(text, estat):
   return estat["codi_a_producte"][text]


def registrar_codis_globals(codis, estat, index_frame, nom_fitxer, temps_actual):
   for codi in codis:
       clau = (codi["tipus"], codi["text"])
    