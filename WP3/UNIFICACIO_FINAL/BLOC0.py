
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
       if clau in estat["codis_globals"]:
           continue

       producte_registrable = es_producte_registrable(codi, estat)
       producte = estat["codi_a_producte"].get(codi["text"])
       consta_manifest = (
           codi["text"] in estat["estanteries_valides"]
           or producte_registrable
       )

       registre = CodeRecord(
           tipus=codi["tipus"],
           text=codi["text"],
           primer_frame=index_frame,
           primer_fitxer=nom_fitxer,
           temps_simulat=temps_actual,
           es_estanteria_valida=es_estanteria_valida(codi, estat),
           es_producte_registrable=producte_registrable,
           producte=producte,
           consta_manifest=consta_manifest,
       )
       estat["codis_globals"][clau] = registre
       estat["registre_codis"].append(registre)


def prioritat_inventari(codi, estat):
   if estat["estanteria_actual"] is None:
       if es_estanteria_valida(codi, estat):
           return 0
       if es_producte_registrable(codi, estat):
           return 1
       return 2

   if es_producte_registrable(codi, estat):
       return 0
   if codi["tipus"] == "CODE39" and codi["text"] == estat["estanteria_actual"]:
       return 1
   if es_estanteria_valida(codi, estat):
       return 2
   return 3


def obrir_estanteria(estat, estanteria, temps_actual, index_frame):
   estat["estanteria_actual"] = estanteria
   estat["temps_obertura"] = temps_actual
   estat["productes_temporals"] = {}
   estat["codis_producte_vistos_actuals"] = set()
   print(f"[frame {index_frame:04d}] [+] abierta estanteria: {estanteria}")


def fusionar_productes_en_inventari(estat, estanteria):
   inventari_estanteria = estat["inventari_global"].setdefault(estanteria, {})

   for producte, codis_producte in estat["productes_temporals"].items():
       inventari_estanteria.setdefault(producte, set()).update(codis_producte)


def tancar_estanteria(estat, temps_actual, index_frame, automatica=False):
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
           producte: sorted(codis_producte)
           for producte, codis_producte in estat["productes_temporals"].items()
       },
   })

   mode = "cierre automatico final" if automatica else "cerrada"
   print(f"[frame {index_frame:04d}] [-] {mode}: {estanteria}")

   estat["estanteria_actual"] = None
   estat["productes_temporals"] = {}
   estat["codis_producte_vistos_actuals"] = set()
   estat["temps_tancament"] = temps_actual


def registrar_producte_actual(estat, codi, index_frame):
   if estat["estanteria_actual"] is None:
       return
   if not es_producte_registrable(codi, estat):
       return

   codi_producte = codi["text"]
   if codi_producte in estat["codis_producte_vistos_actuals"]:
       if DEBUG_CODIS:
           print(
               "[DEBUG] Producto repetido en la transaccion, ignorado: "
               f"{codi_producte}"
           )
       return

   producte = producte_de_codi(codi_producte, estat)
   estat["codis_producte_vistos_actuals"].add(codi_producte)
   estat["productes_temporals"].setdefault(producte, set()).add(codi_producte)

   if DEBUG_CODIS:
       print(
           f"[DEBUG] Producto registrado frame {index_frame}: "
           f"{producte} | {codi_producte} | estanteria {estat['estanteria_actual']}"
       )


def processar_codis_inventari(codis, estat, temps_actual, index_frame):
   codis_ordenats = sorted(
       codis,
       key=lambda codi: prioritat_inventari(codi, estat),
   )

   for codi in codis_ordenats:
       if es_estanteria_valida(codi, estat):
           if estat["estanteria_actual"] is None:
               temps_des_del_tancament = temps_actual - estat["temps_tancament"]
               if temps_des_del_tancament >= COOLDOWN_ENTRE_ESTANTERIES:
                   obrir_estanteria(estat, codi["text"], temps_actual, index_frame)
               elif DEBUG_CODIS:
                   print(
                       f"[DEBUG] Estanteria ignorada por cooldown: {codi['text']} "
                       f"({temps_des_del_tancament:.1f}s)"
                   )
               continue

           if codi["text"] == estat["estanteria_actual"]:
               temps_oberta = temps_actual - estat["temps_obertura"]
               if temps_oberta >= COOLDOWN_TANCAMENT:
                   tancar_estanteria(estat, temps_actual, index_frame)
               continue

       registrar_producte_actual(estat, codi, index_frame)


def finalizar_inventario_si_hace_falta(estat):
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


def si_no(valor):
   return "Si" if valor else "No"


def imprimir_codis_detectats(estat):
   registres = estat["registre_codis"]

   print("\n--- Codigos unicos detectados ---")
   if not registres:
       print("No se ha detectado ningun codigo.")
       return

   for index, registre in enumerate(registres, start=1):
       producte = registre.producte or "-"

       print(f"\n[{index}]")
       print(f"  Tipo: {registre.tipus}")
       print(f"  Texto: {registre.text}")
       print(f"  Estanteria valida: {si_no(registre.es_estanteria_valida)}")
       print(f"  Producto registrable: {si_no(registre.es_producte_registrable)}")
       print(f"  Producto: {producte}")
       print(f"  Consta en manifest: {si_no(registre.consta_manifest)}")
       print(
           "  Primer frame: "
           f"{registre.primer_frame} ({registre.primer_fitxer}, "
           f"t={registre.temps_simulat:.1f}s)"
       )


def imprimir_resum_inventari(estat):
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
           codis_producte = sorted(productes[producte])
           print(f"  Producto: {producte}")
           print(f"  Cantidad: {len(codis_producte)}")
           print(f"  Codigos detectados: {', '.join(codis_producte)}")


def imprimir_resum_general_inventari(estat, sortida_dir):
   print("\n=== Resultado inventario codigos ===")
   print(f"Frames procesados: {estat['frames_processats']}")
   print(f"Frames con detecciones: {estat['frames_amb_deteccions']}")
   print(f"Codigos unicos detectados: {len(estat['registre_codis'])}")
   print(f"Frames anotados guardados en: {sortida_dir}")

   imprimir_codis_detectats(estat)
   imprimir_resum_inventari(estat)


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

   if ZBAR_IMPORT_ERROR is not None:
       print("Error: falta la dependencia pyzbar/zbar para detectar codis.")
       print(f"  - pyzbar/zbar: {ZBAR_IMPORT_ERROR}")
       return

   estanteries, codi_a_producte = carregar_manifest(MANIFEST_CSV)
   print(f"Manifest carregat: {len(estanteries)} estanteries, {len(codi_a_producte)} productes.")

   if GRAVAR_NOU_VIDEO:
       if not capturar_frames_de_video(CARPETA_FOTOS, FONT_VIDEO, INTERVAL_CAPTURA_SEG): return
   else:
       if not os.path.exists(CARPETA_FOTOS): return

   print("\nCarregant models d'Intel·ligència Artificial...")
   detector = load_model(GD_CONFIG_PATH, GD_WEIGHTS_PATH).to(DEVICE)
   print(f"GroundingDINO carregat a {DEVICE.upper()}")
   segmentador = SAM(os.path.join(VOLUMETRIA_DIR, "models", "mobile_sam.pt"))

   os.makedirs(CARPETA_RESULTATS, exist_ok=True)
   arxius = sorted([f for f in os.listdir(CARPETA_FOTOS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
  
   if not arxius: return

   dades_caixes = {}
   dades_codis = {}
   dades_estanteries = set()  # Codis de barres de tipus 'shelf' detectats als frames
   estat_inventari = crear_estat_inventari(estanteries, codi_a_producte)

   for index_frame, nom_arxiu in enumerate(arxius, start=1):
       ruta_completa = os.path.join(CARPETA_FOTOS, nom_arxiu)
       img = cv2.imread(ruta_completa)
       img = cv2.rotate(img, cv2.ROTATE_180)
       H, W = img.shape[:2]
       img_visual = img.copy()
       temps_actual = (index_frame - 1) * FRAME_INTERVAL_SECONDS
      
       caixes_frame = extreure_ids_i_posicions(img, detector, segmentador, DISTANCIA_LIDAR_CM)
       codis_al_frame = extreure_codis_imatge(img, codi_a_producte, caixes_frame=caixes_frame)

       estat_inventari["frames_processats"] += 1
       estat_inventari["ultim_index_frame"] = index_frame
       estat_inventari["ultim_temps_simulat"] = temps_actual
       if codis_al_frame:
           estat_inventari["frames_amb_deteccions"] += 1

       registrar_codis_globals(
           codis_al_frame,
           estat_inventari,
           index_frame=index_frame,
           nom_fitxer=nom_arxiu,
           temps_actual=temps_actual,
       )
       processar_codis_inventari(
           codis_al_frame,
           estat_inventari,
           temps_actual=temps_actual,
           index_frame=index_frame,
       )
       anotar_codis_frame(img_visual, codis_al_frame)

       # Logica caixa-codi:
       #   - CODE39 amb text al manifest d'estanteries -> codi d'estanteria.
       #   - Resta de codis detectats -> producte/codi associat a la caixa
       #     que conte el centre del codi.
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

   finalizar_inventario_si_hace_falta(estat_inventari)

   print(f"\n=== EXTRACCIÓ COMPLETADA ===")
   imprimir_resum_general_inventari(estat_inventari, CARPETA_RESULTATS)

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
