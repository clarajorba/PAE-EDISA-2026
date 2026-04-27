import os
import cv2
import time
import numpy as np
from ultralytics import YOLO, SAM
from pyzbar.pyzbar import decode  # NOU: Importem el lector de codis

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
GRAVAR_NOU_VIDEO = False      # True per obrir càmera, False per utilitzar la carpeta existent
FONT_VIDEO = 0                  # 0 per webcam local, o ruta "tcp://..." per IP
INTERVAL_CAPTURA_SEG = 1.0      # Cada quants segons guardem un fotograma
# ==========================================

def capturar_frames_de_video(carpeta_desti, font_video, interval_seg):
    """
    Obre la webcam, mostra el vídeo en directe i guarda un frame cada X segons.
    S'atura al prémer la lletra 'q'.
    """
    print(f"\n--- INICIANT FASE DE CAPTURA DE VÍDEO ---")
    print(f"Preparant càmera (Font: {font_video})...")
    
    os.makedirs(carpeta_desti, exist_ok=True)
    for arxiu in os.listdir(carpeta_desti):
        ruta_arxiu = os.path.join(carpeta_desti, arxiu)
        if os.path.isfile(ruta_arxiu):
            os.remove(ruta_arxiu)

    cap = cv2.VideoCapture(font_video)
    if not cap.isOpened():
        print("ERROR: No s'ha pogut obrir la font de vídeo.")
        return False

    print(f"GRAVANT... Es guardarà un fotograma cada {interval_seg} segons.")
    print(">>> PREM LA LLETRA 'q' A LA FINESTRA DE VÍDEO PER ATURAR I ANALITZAR <<<")

    ultim_temps_guardat = time.time()
    comptador_frames = 1

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        temps_actual = time.time()
        frame_visual = frame.copy()
        cv2.putText(frame_visual, "Gravant... Prem 'q' per aturar", (10, 30), 
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)
        cv2.imshow("Captura en Directe (BLOC 0)", frame_visual)

        if (temps_actual - ultim_temps_guardat) >= interval_seg:
            nom_arxiu = f"frame_{comptador_frames:04d}.jpg"
            ruta_guardar = os.path.join(carpeta_desti, nom_arxiu)
            cv2.imwrite(ruta_guardar, frame)
            print(f" [VÍDEO] Capturat: {nom_arxiu}")
            ultim_temps_guardat = temps_actual
            comptador_frames += 1

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    return True

def extreure_codis_imatge(img):
    """Funció d'ajuda per extreure tots els codis d'una imatge."""
    codis = decode(img)
    resultats = []
    for codi in codis:
        rect = codi.rect
        # Calculem el centre geomètric del codi de barres
        cx = rect.left + rect.width / 2
        cy = rect.top + rect.height / 2
        dades = codi.data.decode('utf-8')
        resultats.append({'data': dades, 'cx': cx, 'cy': cy, 'rect': rect})
    return resultats

def executar_pipeline_orquestrat():
    print(f"\n=== INICIANT ORQUESTRADOR CENTRAL (MULTICAIXA + CODIS) ===")
    
    if GRAVAR_NOU_VIDEO:
        exit_captura = capturar_frames_de_video(CARPETA_FOTOS, FONT_VIDEO, INTERVAL_CAPTURA_SEG)
        if not exit_captura:
            return
    else:
        print(f"\n[INFO] Mode GRAVAR_NOU_VIDEO = False. Utilitzant imatges existents a '{CARPETA_FOTOS}'.")
        if not os.path.exists(CARPETA_FOTOS):
            print(f"\n[ERROR] La carpeta '{CARPETA_FOTOS}' no existeix!")
            return

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
    dades_codis = {}  # NOU DICCIONARI: Guardarà els codis associats a cada ID de caixa

    print(f"\n[BLOC 0] Analitzant {len(arxius)} fotogrames...")

    for nom_arxiu in arxius:
        ruta_completa = os.path.join(CARPETA_FOTOS, nom_arxiu)
        img = cv2.imread(ruta_completa)
        H, W = img.shape[:2]
        img_visual = img.copy() 
        
        # 1. Detectar TOTS els codis de barres/QR en el fotograma actual
        codis_al_frame = extreure_codis_imatge(img)

        # 2. Extreure caixes
        caixes_frame = extreure_ids_i_posicions(img, detector, segmentador, DISTANCIA_LIDAR_CM)
        
        for caixa in caixes_frame:
            id_actual = caixa['id']
            bbox_actual = caixa['bbox']
            color = caixa['color']
            contorn = caixa['contorn']
            cx, cy = caixa['cx'], caixa['cy']
            
            # --- ASSOCIACIÓ DE CODI DE BARRES A LA CAIXA ---
            for codi in codis_al_frame:
                # Comprovem si el centre del codi detectat cau a dins de la segmentació d'aquesta caixa
                distancia = cv2.pointPolygonTest(contorn, (float(codi['cx']), float(codi['cy'])), False)
                if distancia >= 0: # 1 (dins) o 0 (vora)
                    if id_actual not in dades_codis:
                        dades_codis[id_actual] = set() # Usem un 'set' per no tenir codis duplicats
                    dades_codis[id_actual].add(codi['data'])
                    
                    # Dibuixem el codi a la imatge visual en color magenta
                    rect = codi['rect']
                    cv2.rectangle(img_visual, (rect.left, rect.top), (rect.left + rect.width, rect.top + rect.height), (255, 0, 255), 3)
                    cv2.putText(img_visual, codi['data'], (rect.left, rect.top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 0, 255), 3)

            # Pintar màscares i text
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
            
            # BLOC 1: Vèrtexs
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
                    cv2.putText(img_visual, "PARCIAL", (cx - 40, cy + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_visual)

    print(f"\n=== EXTRACCIÓ COMPLETADA ===")
    
    # PAS 4: BLOC 3.1 i Mostrar Codis
    for id_caixa, diccionari_fotos in dades_caixes.items():
        print(f"\n==========================================")
        print(f" RESULTATS DE LA CAIXA [ID {id_caixa}]")
        
        # Mostrar el codi de barres si n'hi ha algun associat
        codis_associats = dades_codis.get(id_caixa, set())
        if codis_associats:
            text_codis = " | ".join(codis_associats)
            print(f" > Codi de Barres / QR: {text_codis}")
        else:
            print(f" > Codi de Barres / QR: [NO DETECTAT]")
            
        print(f"==========================================")
        
        if len(diccionari_fotos) > 1: 
            calcular_volumetria(CARPETA_FOTOS, diccionari_fotos) 
        else:
            print(f"No hi ha prou fotogrames vàlids (sencers) per calcular el volum de la caixa {id_caixa}.")

if __name__ == "__main__":
    executar_pipeline_orquestrat()