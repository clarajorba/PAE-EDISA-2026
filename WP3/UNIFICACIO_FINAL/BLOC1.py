
# BLOC 1: DETECCIÓ I RECONSTRUCCIÓ DE VÈRTEXS
import os
import cv2
import numpy as np
from ultralytics import YOLO, SAM

# ==========================================
# CONFIGURACIÓ
# ==========================================
IMATGE_PROVA = "../fotos_caixa/IMG_0944.jpg"

# FUNCIÓ: Lògica Pura d'Intersecció de Línies
def calcular_interseccio(line1, line2):
   vx1, vy1, x1, y1 = line1[0][0], line1[1][0], line1[2][0], line1[3][0]
   vx2, vy2, x2, y2 = line2[0][0], line2[1][0], line2[2][0], line2[3][0]

   cross = vx1 * vy2 - vy1 * vx2
   if abs(cross) < 1e-6:
       return None

   t1 = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / cross
   inter_x = x1 + t1 * vx1
   inter_y = y1 + t1 * vy1
   return (int(inter_x), int(inter_y))

def detectar_qualsevol_caixa(ruta_o_img, mostrar_visualment=False, bbox_objectiu=None, segmentador=None, detector=None):
   # 1. Gestió d'entrada — IMPRESCINDIBLE, no esborrar
   if isinstance(ruta_o_img, str):
       img = cv2.imread(ruta_o_img)
       nom_arxiu_guardar = os.path.basename(ruta_o_img)
   else:
       img = ruta_o_img
       nom_arxiu_guardar = "caixa_processada.jpg"

   if img is None: return None
   img_resultat = img.copy()
   img_sam_visual = img.copy()

   # 2. Detecció i Segmentació
   box_ampliada = bbox_objectiu

   if segmentador is None:
       segmentador = SAM("mobile_sam.pt")
      
   resultats_sam = segmentador.predict(img, bboxes=box_ampliada, verbose=False)
   if not resultats_sam[0].masks: return None

   contorn_sam = resultats_sam[0].masks.xy[0]
   mascara_binaria = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
   cv2.fillPoly(mascara_binaria, [np.array(contorn_sam, dtype=np.int32)], 255)

   # --- FIX 1: Quedem-nos només amb el component connectat més gran ---
   # Elimina artefactes i illes desconnectades del cos principal
   num_labels, labels, stats, _ = cv2.connectedComponentsWithStats(mascara_binaria, connectivity=8)
   if num_labels > 1:
       areas = stats[1:, cv2.CC_STAT_AREA]
       idx_mes_gran = int(np.argmax(areas)) + 1
       mascara_binaria = np.where(labels == idx_mes_gran, 255, 0).astype(np.uint8)

   # --- FIX 2: Erosió per trencar filaments fins CONNECTATS al cos principal ---
   # Un filament fi (5-8px d'amplada) no sobreviu una erosió de radi 8,
   # però el cos principal (centenars de px) el recupera el CLOSE posterior.
   kernel_erode = np.ones((8, 8), np.uint8)
   mascara_binaria = cv2.erode(mascara_binaria, kernel_erode, iterations=1)

   # --- FIX 3: CLOSE amb kernel horitzontal allargat per tancar el buit de l'etiqueta ---
   # Un kernel molt ample tanca el gap horitzontal entre el cartró i la full de paper
   # sense expandir excessivament en vertical (cosa que afegiria la taula)
   kernel_close_h = cv2.getStructuringElement(cv2.MORPH_RECT, (60, 20))
   mascara_binaria = cv2.morphologyEx(mascara_binaria, cv2.MORPH_CLOSE, kernel_close_h)

   # --- FIX 4: Retallar la màscara pel límit inferior del bbox de YOLO ---
   # Evita que la sombra/reflexe de la caixa sobre la taula s'inclogui a la màscara.
   # Marge generós (40px) per no tallar la cantonada inferior real de la caixa.
   MARGE_BBOX_INFERIOR = 40
   y_limit = min(img.shape[0], int(box_ampliada[3]) + MARGE_BBOX_INFERIOR)
   mascara_binaria[y_limit:, :] = 0

   # Dilate final reduït: reconstitueix el contorn sense re-expandir cap a la taula
   kernel_dilate = np.ones((10, 10), np.uint8)
   mascara_binaria = cv2.dilate(mascara_binaria, kernel_dilate, iterations=1)

   # 3. Obtenció de vèrtexs bruts
   contorns, _ = cv2.findContours(mascara_binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
   if not contorns: return None
   contorn_principal = max(contorns, key=cv2.contourArea)
   hull = cv2.convexHull(contorn_principal)
   perimetre = cv2.arcLength(hull, True)

   vertexs_ideals = None
   for factor in np.arange(0.01, 0.15, 0.002):
       aproximacio = cv2.approxPolyDP(hull, factor * perimetre, True)
       if len(aproximacio) == 6:
           vertexs_ideals = aproximacio
           break
       elif len(aproximacio) == 5 and vertexs_ideals is None:
           vertexs_ideals = aproximacio

   vertexs_bruts = vertexs_ideals if vertexs_ideals is not None else cv2.approxPolyDP(hull, 0.04 * perimetre, True)
   coordenades_brutes = [(int(p[0][0]), int(p[0][1])) for p in vertexs_bruts]

   # 4. Reconstrucció matemàtica (Esmolat)
   vora_mascara = np.zeros_like(mascara_binaria)
   cv2.drawContours(vora_mascara, [contorn_principal], -1, 255, 1)

   rectes_matematiques = []
   n = len(coordenades_brutes)
   for i in range(n):
       p1, p2 = np.array(coordenades_brutes[i]), np.array(coordenades_brutes[(i + 1) % n])
       direccio = p2 - p1
       p_inici, p_fi = p1 + direccio * 0.20, p1 + direccio * 0.80
       mascara_linia = np.zeros_like(mascara_binaria)
       cv2.line(mascara_linia, (int(p_inici[0]), int(p_inici[1])), (int(p_fi[0]), int(p_fi[1])), 255, 15)
       punts_vora = cv2.bitwise_and(vora_mascara, mascara_linia)
       coords_y, coords_x = np.where(punts_vora == 255)
      
       if len(coords_x) > 10:
           recta = cv2.fitLine(np.column_stack((coords_x, coords_y)), cv2.DIST_L2, 0, 0.01, 0.01)
           rectes_matematiques.append(recta)
       else:
           norma = np.linalg.norm(direccio) + 1e-6
           rectes_matematiques.append([np.array([direccio[0]/norma]), np.array([direccio[1]/norma]), np.array([p1[0]]), np.array([p1[1]])])

   coordenades_esmolades = []
   for i in range(n):
       inter = calcular_interseccio(rectes_matematiques[(i - 1) % n], rectes_matematiques[i])
       coordenades_esmolades.append(inter if inter else coordenades_brutes[i])

   # =================================================================
   # FILTRE DE QUALITAT I IDENTIFICACIÓ DE PUNTS BLAUS
   # =================================================================
   TOLERANCIA_MASCARA_PX = 25
   indexs_corruptes = []
  
   for i, (x, y) in enumerate(coordenades_esmolades):
       distancia = cv2.pointPolygonTest(contorn_principal, (float(x), float(y)), True)
       if distancia < -TOLERANCIA_MASCARA_PX:
           indexs_corruptes.append(i)
  
   fotograma_valid = (len(indexs_corruptes) == 0)
   # =================================================================

   # 5. Pintar i Guardar (S'executa sempre si mostrar_visualment és True)
   if mostrar_visualment:
       # Mescla blava per al SAM
       color_blau_sam = np.zeros_like(img)
       color_blau_sam[:] = (255, 144, 30)
       mescla = cv2.addWeighted(img_sam_visual, 0.5, color_blau_sam, 0.5, 0)
       img_sam_visual[mascara_binaria == 255] = mescla[mascara_binaria == 255]

       # Dibuixar vèrtexs i línies
       for i, (x, y) in enumerate(coordenades_esmolades):
           # Color del punt: Blau si és corruptre, Roig si és correcte
           color_punt = (255, 0, 0) if i in indexs_corruptes else (0, 0, 255)
          
           # Dibuixar creu de línies taronja (prolongacions)
           recta_ant = rectes_matematiques[(i - 1) % n]; recta_act = rectes_matematiques[i]
           for r in [recta_ant, recta_act]:
               vx, vy = r[0][0], r[1][0]
               p1 = (int(x - 100 * vx), int(y - 100 * vy))
               p2 = (int(x + 100 * vx), int(y + 100 * vy))
               cv2.line(img_sam_visual, p1, p2, (0, 165, 255), 2)
          
           # Cercle final
           cv2.circle(img_resultat, (x, y), 8, color_punt, -1)
           cv2.circle(img_sam_visual, (x, y), 5, color_punt, -1)
           cv2.putText(img_resultat, f"P{i+1}", (x+15, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

       # Polígon verd
       vertexs_dibuix = np.array(coordenades_esmolades, dtype=np.int32).reshape((-1, 1, 2))
       cv2.drawContours(img_resultat, [vertexs_dibuix], -1, (0, 255, 0), 3)

       os.makedirs("resultats_SAM", exist_ok=True)
       cv2.imwrite(os.path.join("resultats_SAM", nom_arxiu_guardar), img_sam_visual)
       os.makedirs("Resultats_BLOC1", exist_ok=True)
       cv2.imwrite(os.path.join("Resultats_BLOC1", nom_arxiu_guardar), img_resultat)

   # RETORNAR: Si hi ha punts corruptes, retornem None per invalidar el volum
   return coordenades_esmolades if fotograma_valid else None

if __name__ == "__main__":
   punts = detectar_qualsevol_caixa(IMATGE_PROVA, mostrar_visualment=True)
   if punts: print(f"Vèrtexs vàlids: {punts}")
   else: print("Fotograma descartat (Punts blaus detectats).")


