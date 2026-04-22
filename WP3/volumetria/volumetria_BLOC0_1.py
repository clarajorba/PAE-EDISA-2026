import os
import cv2
import time
import numpy as np
from ultralytics import YOLO, SAM

# Importem les eines dels nostres mòduls
from volumetria_BLOC2 import extreure_ids_i_posicions
from volumetria_BLOC1 import detectar_qualsevol_caixa
from volumetria_BLOC3_1 import calcular_volumetria

# ==========================================
# CONFIGURACIÓ GENERAL DE VOL
# ==========================================
CARPETA_FOTOS = "fotos_capturades" 
DISTANCIA_LIDAR_CM = 150.0
CARPETA_RESULTATS = "Resultats_BLOC0"
MARGE_BORDE_VALIDACIO = 10 

# ==========================================
# CONFIGURACIÓ DE CAPTURA DE VÍDEO
# ==========================================
GRAVAR_NOU_VIDEO = True      # True per obrir càmera, False per utilitzar la carpeta existent
FONT_VIDEO = "tcp://172.20.10.2:8888"  # Ruta per a la càmera IP
INTERVAL_CAPTURA_SEG = 1.0      # Cada quants segons guardem un fotograma (ex: 1.0, 0.5...)
# ==========================================

def capturar_frames_de_video(carpeta_desti, font_video, interval_seg):
    """
    Obre la webcam, mostra el vídeo en directe i guarda un frame cada X segons.
    S'atura al prémer la lletra 'q'.
    """
    print(f"\n--- INICIANT FASE DE CAPTURA DE VÍDEO ---")
    print(f"Preparant càmera (Font: {font_video})...")
    
    # Crear carpeta si no existeix i buidar-la d'extraccions anteriors
    os.makedirs(carpeta_desti, exist_ok=True)
    for arxiu in os.listdir(carpeta_desti):
        ruta_arxiu = os.path.join(carpeta_desti, arxiu)
        if os.path.isfile(ruta_arxiu):
            os.remove(ruta_arxiu)

    cap = cv2.VideoCapture(font_video)
    if not cap.isOpened():
        print("ERROR: No s'ha pogut obrir la font de vídeo (Webcam).")
        return False

    print(f"GRAVANT... Es guardarà un fotograma cada {interval_seg} segons.")
    print(">>> PREM LA LLETRA 'q' A LA FINESTRA DE VÍDEO PER ATURAR I ANALITZAR <<<")

    ultim_temps_guardat = time.time()
    comptador_frames = 1

    while True:
        ret, frame = cap.read()
        if not ret:
            print("Avís: No es poden rebre més fotogrames (fi del vídeo o error).")
            break

        temps_actual = time.time()
        
        # Mostrem el vídeo en directe amb instruccions
        frame_visual = frame.copy()
        cv2.putText(frame_visual, "Gravant... Prem 'q' per aturar", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("Captura en Directe (BLOC 0)", frame_visual)

        # Si ha passat l'interval de temps, guardem la foto neta (sense text)
        if (temps_actual - ultim_temps_guardat) >= interval_seg:
            nom_arxiu = f"frame_{comptador_frames:04d}.jpg"
            ruta_guardar = os.path.join(carpeta_desti, nom_arxiu)
            cv2.imwrite(ruta_guardar, frame)
            print(f" [VÍDEO] Capturat: {nom_arxiu}")
            
            ultim_temps_guardat = temps_actual
            comptador_frames += 1

        # Sortir del bucle si es prem 'q'
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Captura aturada per l'usuari.")
            break

    cap.release()
    cv2.destroyAllWindows()
    return True

def executar_pipeline_orquestrat():
    print(f"\n=== INICIANT ORQUESTRADOR CENTRAL (MULTICAIXA) ===")
    
    # PAS 1: CAPTURA DE FOTOGRAMES (Condicional)
    if GRAVAR_NOU_VIDEO:
        exit_captura = capturar_frames_de_video(CARPETA_FOTOS, FONT_VIDEO, INTERVAL_CAPTURA_SEG)
        if not exit_captura:
            return
    else:
        print(f"\n[INFO] Mode GRAVAR_NOU_VIDEO = False. Utilitzant imatges existents a '{CARPETA_FOTOS}'.")

    # PAS 2: CÀRREGA DE MODELS IA
    print("\nCarregant models d'Intel·ligència Artificial (Càrrega única)...")
    detector = YOLO("yolov8s-world.pt")
    detector.set_classes(["box"]) 
    segmentador = SAM("mobile_sam.pt") 

    os.makedirs(CARPETA_RESULTATS, exist_ok=True)
    arxius = sorted([f for f in os.listdir(CARPETA_FOTOS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not arxius:
        print("No s'han trobat imatges capturades per analitzar.")
        return

    dades_caixes = {}

    print(f"\n[BLOC 0] Analitzant {len(arxius)} fotogrames...")

    # PAS 3: PROCESSAMENT
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
            
            mascara_binaria = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
            cv2.fillPoly(mascara_binaria, [contorn], 255)
            color_capa = np.zeros_like(img)
            color_capa[:] = color
            mescla = cv2.addWeighted(img_visual, 0.6, color_capa, 0.4, 0)
            img_visual[mascara_binaria == 255] = mescla[mascara_binaria == 255]
            
            cv2.drawContours(img_visual, [contorn], -1, color, 2)
            
            text_id = f"ID_CAIXA_{id_actual}"
            cv2.putText(img_visual, text_id, (cx - 60, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 0, 0), 4)
            cv2.putText(img_visual, text_id, (cx - 60, cy - 20), cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
            
            vertexs = detectar_qualsevol_caixa(
                ruta_o_img=img, 
                mostrar_visualment=False, 
                bbox_objectiu=bbox_actual, 
                segmentador=segmentador, 
                detector=detector
            )
            
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
                    cv2.putText(img_visual, "PARCIAL", (cx - 40, cy + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_visual)

    print(f"\n=== EXTRACCIÓ COMPLETADA ===")
    print(f"-> Totes les imatges de diagnòstic s'han guardat a la carpeta '{CARPETA_RESULTATS}'")
    print(f"-> S'han identificat {len(dades_caixes)} caixes diferents amb dades vàlides.")

    # PAS 4: BLOC 3.1
    for id_caixa, diccionari_fotos in dades_caixes.items():
        print(f"\n==========================================")
        print(f" RESULTATS DE VOLUM PER A LA CAIXA [ID {id_caixa}]")
        print(f"==========================================")
        if len(diccionari_fotos) > 1: 
            calcular_volumetria(CARPETA_FOTOS, diccionari_fotos) 
        else:
            print(f"No hi ha prou fotogrames vàlids (sencers) per calcular el volum de la caixa {id_caixa}.")

if __name__ == "__main__":
    executar_pipeline_orquestrat()