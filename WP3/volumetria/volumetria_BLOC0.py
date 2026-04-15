import os
import cv2
import numpy as np
from ultralytics import YOLO, SAM

# Importem les eines dels nostres mòduls
# Assegura't que els arxius python es diuen així:
from volumetria_BLOC2 import extreure_ids_i_posicions
from volumetria_BLOC1 import detectar_qualsevol_caixa
from volumetria_BLOC3_1 import calcular_volumetria

# ==========================================
# CONFIGURACIÓ GENERAL DE VOL
# ==========================================
CARPETA_FOTOS = "../fotos_caixa" 
DISTANCIA_LIDAR_CM = 150.0
CARPETA_RESULTATS = "Resultats_BLOC0"

# NOVA CONFIGURACIÓ DE FILTRAT
# Pixels de tolerància per considerar que toca la vora
MARGE_BORDE_VALIDACIO = 10 
# ==========================================

def executar_pipeline_orquestrat():
    print(f"\n=== INICIANT ORQUESTRADOR CENTRAL (MULTICAIXA) ===")
    print("Carregant models d'Intel·ligència Artificial (Càrrega única)...")
    detector = YOLO("yolov8s-world.pt")
    detector.set_classes(["box"]) 
    segmentador = SAM("mobile_sam.pt") 

    if not os.path.exists(CARPETA_FOTOS):
        print(f"Error: La carpeta {CARPETA_FOTOS} no existeix.")
        return

    os.makedirs(CARPETA_RESULTATS, exist_ok=True)
    arxius = sorted([f for f in os.listdir(CARPETA_FOTOS) if f.lower().endswith(('.png', '.jpg', '.jpeg'))])
    
    if not arxius:
        print("No s'han trobat imatges.")
        return

    # L'Estructura mestra: { ID_CAIXA: { "foto1.jpg": [p1,p2,p3,p4], ... } }
    dades_caixes = {}

    print(f"\n[BLOC 0] Processant {len(arxius)} fotogrames del vol del dron...")

    for nom_arxiu in arxius:
        ruta_completa = os.path.join(CARPETA_FOTOS, nom_arxiu)
        img = cv2.imread(ruta_completa)
        H, W = img.shape[:2]
        img_visual = img.copy() # Aquí anirem pintant totes les capes
        
        # 1. BLOC 2: Obtenir les caixes, IDs, màscares i colors
        caixes_frame = extreure_ids_i_posicions(img, detector, segmentador, DISTANCIA_LIDAR_CM)
        
        # 2. Processar caixa per caixa
        for caixa in caixes_frame:
            id_actual = caixa['id']
            bbox_actual = caixa['bbox']
            color = caixa['color']
            contorn = caixa['contorn']
            cx, cy = caixa['cx'], caixa['cy']
            
            # --- A. PINTAR LA MÀSCARA I L'ID DEL BLOC 2 (Sempre es pinta) ---
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
            
            # --- B. EXTREURE ELS VÈRTEXS DEL BLOC 1 ---
            vertexs = detectar_qualsevol_caixa(
                ruta_o_img=img, 
                mostrar_visualment=False, 
                bbox_objectiu=bbox_actual, 
                segmentador=segmentador, 
                detector=detector
            )
            
            # --- C. VALIDACIÓ GEOMÈTRICA (NOU!) ---
            # Comprovem si la caixa està tallada per la vora de la imatge
            toca_borde = False
            if vertexs is not None:
                for (vx, vy) in vertexs:
                    if vx <= MARGE_BORDE_VALIDACIO or vx >= (W - MARGE_BORDE_VALIDACIO) or \
                       vy <= MARGE_BORDE_VALIDACIO or vy >= (H - MARGE_BORDE_VALIDACIO):
                        toca_borde = True
                        break

            # --- D. PINTAR I GUARDAR DADES SEGONS VALIDACIÓ ---
            if vertexs is not None and len(vertexs) >= 4:
                
                vertexs_dibuix = np.array(vertexs, dtype=np.int32).reshape((-1, 1, 2))
                
                if not toca_borde:
                    # Cas bo: La caixa es veu sencera. Guardem dades i pintem en VERD.
                    if id_actual not in dades_caixes:
                        dades_caixes[id_actual] = {}
                    dades_caixes[id_actual][nom_arxiu] = vertexs

                    cv2.drawContours(img_visual, [vertexs_dibuix], -1, (0, 255, 0), 3) # Verd
                    for i, (x, y) in enumerate(vertexs):
                        cv2.circle(img_visual, (x, y), 8, (0, 0, 255), -1) # Punts vermells
                
                else:
                    # Cas dolent: Toca el borde. Pintem en VERMELL i NO guardem dades.
                    # Això soluciona el problema de generar esquines falses al límit de la imatge.
                    cv2.drawContours(img_visual, [vertexs_dibuix], -1, (0, 0, 255), 3) # Vermell
                    # Opcional: Afegir text d'avís visual
                    cv2.putText(img_visual, "PARCIAL", (cx - 40, cy + 20), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2)

        # 3. Guardar la fotografia mestre
        cv2.imwrite(os.path.join(CARPETA_RESULTATS, nom_arxiu), img_visual)

    print(f"\n=== EXTRACCIÓ COMPLETADA ===")
    print(f"-> Totes les imatges de diagnòstic s'han guardat a la carpeta '{CARPETA_RESULTATS}'")
    print(f"-> S'han identificat {len(dades_caixes)} caixes diferents amb dades vàlides.")

    # 3. BLOC 3.1: Passar el testimoni i calcular el volum caixa per caixa
    for id_caixa, diccionari_fotos in dades_caixes.items():
        print(f"\n==========================================")
        print(f" RESULTATS DE VOLUM PER A LA CAIXA [ID {id_caixa}]")
        print(f"==========================================")
        if len(diccionari_fotos) > 1: # Necessitem almenys 2 fotos per la mediana
            calcular_volumetria(CARPETA_FOTOS, diccionari_fotos) 
        else:
            print(f"No hi ha prou fotogrames vàlids (sencers) per calcular el volum de la caixa {id_caixa}.")

if __name__ == "__main__":
    executar_pipeline_orquestrat()