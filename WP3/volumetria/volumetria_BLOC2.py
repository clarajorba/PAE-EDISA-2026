import os
import cv2
import numpy as np
import math
from ultralytics import YOLO, SAM

# ==========================================
# CONFIGURACIÓ PRINCIPAL (BLOC 2)
# ==========================================
CARPETA_FOTOS_SEQ = "../fotos_caixa" 
CARPETA_RESULTATS = "Resultats_BLOC2" # Ja no l'usarem directament, però ho deixem

DISTANCIA_REF_CM = 150.0
TRACKING_REF_PX = 400.0 
MAX_FRAMES_MISSING = 1
# ==========================================

següent_id_caixa = 1
caixes_actives_amb_memoria = {}

def obtenir_color_aleatori():
    return (int(np.random.randint(50, 255)), 
            int(np.random.randint(50, 255)), 
            int(np.random.randint(50, 255)))

def tracking_robust_amb_memoria(deteccions_actuals, distancia_lidar_cm):
    global següent_id_caixa, caixes_actives_amb_memoria
    
    id_actuals_assignats = []
    radi_tracking_dinamic = TRACKING_REF_PX * (DISTANCIA_REF_CM / distancia_lidar_cm)
    ids_aparellats = {}

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
                
        if id_conegut_mes_proper is not None:
            caixes_actives_amb_memoria[id_conegut_mes_proper]['centroide'] = (cx_nova, cy_nova)
            caixes_actives_amb_memoria[id_conegut_mes_proper]['misses'] = 0 
            
            info = caixes_actives_amb_memoria[id_conegut_mes_proper]
            id_actuals_assignats.append({'id': id_conegut_mes_proper, 'centroide': (cx_nova, cy_nova), 'color': info['color']})
            ids_aparellats[id_conegut_mes_proper] = True
        else:
            nou_id = següent_id_caixa
            color = obtenir_color_aleatori()
            caixes_actives_amb_memoria[nou_id] = {'centroide': (cx_nova, cy_nova), 'misses': 0, 'color': color}
            
            id_actuals_assignats.append({'id': nou_id, 'centroide': (cx_nova, cy_nova), 'color': color})
            següent_id_caixa += 1
            ids_aparellats[nou_id] = True

    ids_a_eliminar = []
    for id_vell in caixes_actives_amb_memoria:
        if id_vell not in ids_aparellats:
            caixes_actives_amb_memoria[id_vell]['misses'] += 1
            if caixes_actives_amb_memoria[id_vell]['misses'] > MAX_FRAMES_MISSING:
                ids_a_eliminar.append(id_vell)
                
    for i_d in ids_a_eliminar:
        del caixes_actives_amb_memoria[i_d]
        
    return id_actuals_assignats

def extreure_ids_i_posicions(img, detector, segmentador, distancia_lidar_cm):
    """Funció de servei per al BLOC 0: Ara retorna també la màscara i el color"""
    resultats_det = detector.predict(img, conf=0.2, verbose=False) 
    caixes_detectades_frame = []
    
    if resultats_det[0].boxes is not None and len(resultats_det[0].boxes) > 0:
        caixes_yolo = resultats_det[0].boxes.xyxy.cpu().numpy().tolist()
        centroides_actuals = []
        info_caixes = []

        for box in caixes_yolo:
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
                
                centroides_actuals.append((cx, cy))
                # Guardem el contorn i el centre per poder-ho pintar després
                info_caixes.append({'bbox_ampliada': box_ampliada, 'cx': cx, 'cy': cy, 'contorn': contorn_np})

        ids_assignats_finals = tracking_robust_amb_memoria(centroides_actuals, distancia_lidar_cm)
        
        for caixa in info_caixes:
            for id_info in ids_assignats_finals:
                if math.hypot(caixa['cx'] - id_info['centroide'][0], caixa['cy'] - id_info['centroide'][1]) < 5: 
                    caixes_detectades_frame.append({
                        'id': id_info['id'],
                        'bbox': caixa['bbox_ampliada'],
                        'color': id_info['color'],
                        'contorn': caixa['contorn'],
                        'cx': caixa['cx'],
                        'cy': caixa['cy']
                    })
                    break 
                    
    return caixes_detectades_frame