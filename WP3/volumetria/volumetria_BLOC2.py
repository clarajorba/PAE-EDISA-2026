import os
import cv2
import numpy as np
import math
from ultralytics import YOLO, SAM

# ==========================================
# CONFIGURACIÓ PRINCIPAL
# ==========================================
CARPETA_FOTOS_SEQ = "../fotos_caixa" 
CARPETA_RESULTATS = "Resultats_BLOC2"

# Paràmetres del LIDAR per al Tracking Dinàmic
DISTANCIA_REF_CM = 150.0  # A quina distància hem fet les proves base?
TRACKING_REF_PX = 200.0   # A aquesta distància base, quants píxels de marge donem?

print("Carregant models d'Intel·ligència Artificial (BLOC 2)...")
detector = YOLO("yolov8s-world.pt")
detector.set_classes(["box"]) 
segmentador = SAM("mobile_sam.pt") 
# ==========================================

# Variables globals per a la memòria a curt termini
següent_id_caixa = 1
caixes_actives = {} # Format: { ID: (cx, cy) }
colors_id = {}      # Format: { ID: (B, G, R) }

def obtenir_color(id_caixa):
    """Genera un color aleatori però fix i constant per a cada ID de caixa"""
    if id_caixa not in colors_id:
        # Usem l'ID com a llavor perquè el random doni sempre el mateix color per aquest ID
        np.random.seed(id_caixa * 142) 
        colors_id[id_caixa] = (int(np.random.randint(50, 255)), 
                               int(np.random.randint(50, 255)), 
                               int(np.random.randint(50, 255)))
    return colors_id[id_caixa]

def assignar_id_per_centroide(cx, cy, distancia_lidar_cm):
    """Compara el centroide actual amb els de l'historial adaptant-se a la profunditat"""
    global següent_id_caixa, caixes_actives
    
    id_assignat = None
    distancia_minima = float('inf')
    
    # Tolerància dinàmica: si estem més a prop, donem més marge de píxels; si estem lluny, menys.
    radi_tracking_dinamic = TRACKING_REF_PX * (DISTANCIA_REF_CM / distancia_lidar_cm)
    
    # Busquem la caixa coneguda més propera
    for id_conegut, (cx_antic, cy_antic) in caixes_actives.items():
        dist = math.hypot(cx - cx_antic, cy - cy_antic)
        
        if dist < distancia_minima and dist < radi_tracking_dinamic:
            distancia_minima = dist
            id_assignat = id_conegut
            
    # Actualitzem o creem la caixa
    if id_assignat is not None:
        caixes_actives[id_assignat] = (cx, cy) # Actualitzem la posició
    else:
        id_assignat = següent_id_caixa
        caixes_actives[id_assignat] = (cx, cy) # En registrem una de nova
        següent_id_caixa += 1
        
    return id_assignat

def processar_sequencia():
    print(f"\n--- INICIANT BLOC 2: DETECCIÓ I SEGUIMENT MULTICAIXA ---")
    
    if not os.path.exists(CARPETA_FOTOS_SEQ):
        print(f"Error: No trobo la carpeta {CARPETA_FOTOS_SEQ}. Si us plau, crea-la i posa-hi les fotos en seqüència.")
        return
        
    os.makedirs(CARPETA_RESULTATS, exist_ok=True)
    
    # Llegim i ORDENEM les fotos per simular el vol del dron en el temps
    arxius = [f for f in os.listdir(CARPETA_FOTOS_SEQ) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    arxius.sort() 
    
    if not arxius:
        print("La carpeta està buida.")
        return

    # MOCKUP: Simulació de la dada que rebrem del sensor LIDAR (es pot canviar fotograma a fotograma en el futur)
    distancia_actual_lidar = 150.0 

    for nom_arxiu in arxius:
        ruta_imatge = os.path.join(CARPETA_FOTOS_SEQ, nom_arxiu)
        img = cv2.imread(ruta_imatge)
        img_resultat = img.copy()
        
        print(f"Processant fotograma: {nom_arxiu}...")
        
        # 1. Detecció de totes les caixes
        resultats_det = detector.predict(img, conf=0.1, verbose=False) 
        
        if resultats_det[0].boxes is not None and len(resultats_det[0].boxes) > 0:
            caixes_detectades = resultats_det[0].boxes.xyxy.cpu().numpy().tolist()
            
            # 2. Iterem cada caixa independentment
            for box in caixes_detectades:
                x1, y1, x2, y2 = map(int, box)
                marge = 40
                box_ampliada = [max(0, x1-marge), max(0, y1-marge), min(img.shape[1], x2+marge), min(img.shape[0], y2+marge)]
                
                # 3. Segmentació (Només aquesta caixa concreta)
                resultats_sam = segmentador.predict(img, bboxes=box_ampliada, verbose=False)
                
                if resultats_sam[0].masks is not None and len(resultats_sam[0].masks.xy) > 0:
                    contorn_sam = resultats_sam[0].masks.xy[0]
                    contorn_np = np.array(contorn_sam, dtype=np.int32)
                    
                    # 4. Càlcul del Centroide (Centre de gravetat de la màscara)
                    moments = cv2.moments(contorn_np)
                    if moments["m00"] != 0:
                        cx = int(moments["m10"] / moments["m00"])
                        cy = int(moments["m01"] / moments["m00"])
                    else:
                        cx, cy = int((x1+x2)/2), int((y1+y2)/2)
                        
                    # 5. Tracking: Recuperem l'ID i el color
                    id_caixa = assignar_id_per_centroide(cx, cy, distancia_actual_lidar)
                    color = obtenir_color(id_caixa)
                    
                    # 6. Visualització
                    # 6.1 Pintem la màscara semitransparent amb el color de l'ID
                    mascara_binaria = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
                    cv2.fillPoly(mascara_binaria, [contorn_np], 255)
                    
                    color_capa = np.zeros_like(img)
                    color_capa[:] = color
                    mescla = cv2.addWeighted(img_resultat, 0.6, color_capa, 0.4, 0)
                    img_resultat[mascara_binaria == 255] = mescla[mascara_binaria == 255]
                    
                    # 6.2 Resseguim el contorn
                    cv2.drawContours(img_resultat, [contorn_np], -1, color, 3)
                    
                    # 6.3 Marquem el centroide
                    cv2.circle(img_resultat, (cx, cy), 8, (255, 255, 255), -1)
                    cv2.circle(img_resultat, (cx, cy), 4, color, -1)
                    
                    # 6.4 Etiqueta de text estilitzada
                    text_id = f"ID_CAIXA_{id_caixa}"
                    cv2.putText(img_resultat, text_id, (cx - 60, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 4) # Ombra negra
                    cv2.putText(img_resultat, text_id, (cx - 60, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2) # Text blanc
                    
        # Guardem la foto processada
        ruta_guardat = os.path.join(CARPETA_RESULTATS, nom_arxiu)
        cv2.imwrite(ruta_guardat, img_resultat)
        
    print(f"\n[OK] Bloc2 completat")

if __name__ == "__main__":
    processar_sequencia()