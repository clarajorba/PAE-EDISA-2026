import os
import cv2
import numpy as np
import math
from ultralytics import YOLO, SAM

# ==========================================
# CONFIGURACIÓ PRINCIPAL (BLOC 2)
# ==========================================
CARPETA_FOTOS_SEQ = "../fotos_caixa" 
CARPETA_RESULTATS = "Resultats_BLOC2"

# Paràmetres del LIDAR per al Tracking Dinàmic
DISTANCIA_REF_CM = 150.0
TRACKING_REF_PX = 400.0 

# PERSISTÈNCIA: Quants fotogrames seguits podem "perdre" la caixa abans d'oblidar-la?
MAX_FRAMES_MISSING = 1
# ==========================================

# Variables globals per a la memòria amb persistència
següent_id_caixa = 1
caixes_actives_amb_memoria = {}

def obtenir_color_aleatori():
    return (int(np.random.randint(50, 255)), 
            int(np.random.randint(50, 255)), 
            int(np.random.randint(50, 255)))

def tracking_robust_amb_memoria(deteccions_actuals, distancia_lidar_cm):
    """
    Algorisme de seguiment amb memòria i persistència
    """
    global següent_id_caixa, caixes_actives_amb_memoria
    
    id_actuals_assignats = []
    
    # Tolerància dinàmica basada en el LIDAR
    radi_tracking_dinamic = TRACKING_REF_PX * (DISTANCIA_REF_CM / distancia_lidar_cm)
    
    ids_aparellats = {}

    # 1. ASSOCIACIÓ
    for cx_nova, cy_nova in deteccions_actuals:
        id_conegut_mes_proper = None
        distancia_minima = float('inf')
        
        for id_vell, info_vella in caixes_actives_amb_memoria.items():
            if id_vell in ids_aparellats: continue 

            cx_antic, cy_antic = info_vella['centroide']
            dist = math.hypot(cx_nova - cx_antic, cy_nova - cy_antic)
            
            if dist < distancia_minima and dist < radi_tracking_dinamic:
                distancia_minima = dist
                id_conegut_mes_proper = id_vell
                
        # 2. ACTUALITZACIÓ
        if id_conegut_mes_proper is not None:
            caixes_actives_amb_memoria[id_conegut_mes_proper]['centroide'] = (cx_nova, cy_nova)
            caixes_actives_amb_memoria[id_conegut_mes_proper]['misses'] = 0 
            
            info = caixes_actives_amb_memoria[id_conegut_mes_proper]
            id_actuals_assignats.append({'id': id_conegut_mes_proper, 'centroide': (cx_nova, cy_nova), 'color': info['color']})
            ids_aparellats[id_conegut_mes_proper] = True
        
        # 3. CREACIÓ
        else:
            nou_id = següent_id_caixa
            color = obtenir_color_aleatori()
            caixes_actives_amb_memoria[nou_id] = {'centroide': (cx_nova, cy_nova), 'misses': 0, 'color': color}
            
            id_actuals_assignats.append({'id': nou_id, 'centroide': (cx_nova, cy_nova), 'color': color})
            següent_id_caixa += 1
            ids_aparellats[nou_id] = True

    # 4. GESTIÓ DELS "MISSES"
    ids_a_eliminar = []
    for id_vell in caixes_actives_amb_memoria:
        if id_vell not in ids_aparellats:
            caixes_actives_amb_memoria[id_vell]['misses'] += 1
            if caixes_actives_amb_memoria[id_vell]['misses'] > MAX_FRAMES_MISSING:
                ids_a_eliminar.append(id_vell)
                
    for i_d in ids_a_eliminar:
        del caixes_actives_amb_memoria[i_d]
        
    return id_actuals_assignats

def processar_sequencia():
    print(f"\n--- INICIANT BLOC 2 ESTABLE: SEGUIMENT AMB MEMÒRIA ---")
    
    # Carreguem els models DINS la funció perquè no hi hagi problemes d'abast
    print("Carregant models d'Intel·ligència Artificial...")
    detector = YOLO("yolov8s-world.pt")
    detector.set_classes(["box"]) 
    segmentador = SAM("mobile_sam.pt") 

    if not os.path.exists(CARPETA_FOTOS_SEQ):
        print(f"Error: No trobo la carpeta {CARPETA_FOTOS_SEQ}.")
        return
        
    os.makedirs(CARPETA_RESULTATS, exist_ok=True)
    arxius = [f for f in os.listdir(CARPETA_FOTOS_SEQ) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    arxius.sort() 
    
    distancia_actual_lidar = 150.0 

    for nom_arxiu in arxius:
        ruta_imatge = os.path.join(CARPETA_FOTOS_SEQ, nom_arxiu)
        img = cv2.imread(ruta_imatge)
        img_resultat = img.copy()
        
        print(f"Processant fotograma: {nom_arxiu}...")
        
        resultats_det = detector.predict(img, conf=0.2, verbose=False) 
        info_caixes_visuals = [] 

        if resultats_det[0].boxes is not None and len(resultats_det[0].boxes) > 0:
            caixes_detectades = resultats_det[0].boxes.xyxy.cpu().numpy().tolist()
            centroides_deteccions_actuals = []

            for box in caixes_detectades:
                x1, y1, x2, y2 = map(int, box)
                marge = 60 
                box_ampliada = [max(0, x1-marge), max(0, y1-marge), min(img.shape[1], x2+marge), min(img.shape[0], y2+marge)]
                
                resultats_sam = segmentador.predict(img, bboxes=box_ampliada, verbose=False)
                
                if resultats_sam[0].masks is not None and len(resultats_sam[0].masks.xy) > 0:
                    contorn_np = np.array(resultats_sam[0].masks.xy[0], dtype=np.int32)
                    moments = cv2.moments(contorn_np)
                    if moments["m00"] != 0:
                        cx = int(moments["m10"] / moments["m00"])
                        cy = int(moments["m01"] / moments["m00"])
                    else:
                        cx, cy = int((x1+x2)/2), int((y1+y2)/2)
                    
                    centroides_deteccions_actuals.append((cx, cy))
                    info_caixes_visuals.append({'contorn': contorn_np})

            ids_assignats_finals = tracking_robust_amb_memoria(centroides_deteccions_actuals, distancia_actual_lidar)
            
            for i, caixa_seg in enumerate(info_caixes_visuals):
                cx_seg, cy_seg = centroides_deteccions_actuals[i]
                contorn_np = caixa_seg['contorn']
                
                for id_info in ids_assignats_finals:
                    cx_id, cy_id = id_info['centroide']
                    if math.hypot(cx_seg - cx_id, cy_seg - cy_id) < 5: 
                        id_caixa = id_info['id']
                        color = id_info['color']
                        
                        mascara_binaria = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
                        cv2.fillPoly(mascara_binaria, [contorn_np], 255)
                        color_capa = np.zeros_like(img)
                        color_capa[:] = color
                        mescla = cv2.addWeighted(img_resultat, 0.6, color_capa, 0.4, 0)
                        img_resultat[mascara_binaria == 255] = mescla[mascara_binaria == 255]
                        
                        cv2.drawContours(img_resultat, [contorn_np], -1, color, 3)
                        cv2.circle(img_resultat, (cx_seg, cy_seg), 8, color, -1)
                        
                        text_id = f"ID_CAIXA_{id_caixa}"
                        cv2.putText(img_resultat, text_id, (cx_seg - 60, cy_seg - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
                        break 

        cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_resultat)
        
    print(f"\n[OK] Seqüència processada. Revisa la carpeta '{CARPETA_RESULTATS}'.")

if __name__ == "__main__":
    processar_sequencia()