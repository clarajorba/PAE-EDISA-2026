import cv2
import numpy as np
from ultralytics import YOLO

# ==========================================
# CONFIGURACIÓ
# ==========================================
imatge= "IMG_0844.jpeg" 

# Carreguem el model de segmentació preentrenat
print("Carregant model YOLOv8 Seg...")
model = YOLO("yolov8n-seg.pt")
# ==========================================

def detectar_arestes_zeroshot(ruta_imatge):
    print(f"\n--- BLOC 1 (ZERO-SHOT): {ruta_imatge} ---")
    img = cv2.imread(ruta_imatge)
    if img is None:
        print(f"Error: Imatge '{ruta_imatge}' no trobada.")
        return None

    # PAS 1: IA - SEGMENTACIÓ FILTRADA
    # Busquem objectes que s'assemblin a caixes (Maleta=28, Televisió=62, Llibre=73)
    # Baixem la confiança (conf=0.1) perquè forci a trobar l'objecte encara que dubti
    print("Buscant l'objecte amb la IA...")
    resultats = model.predict(img, conf=0.1, classes=[28, 62, 73])
    resultat = resultats[0]

    if resultat.masks is None:
        print("La IA no ha trobat res que s'assembli a una caixa.")
        return None

    # PAS 2: TRADUCCIÓ IA -> MATEMÀTICA
    # Extraiem la màscara (la taca blanca) i la fem de la mateixa mida que la foto
    mascara_ia = resultat.masks.data[0].cpu().numpy()
    mascara_redimensionada = cv2.resize(mascara_ia, (img.shape[1], img.shape[0]))
    mascara_binaria = (mascara_redimensionada * 255).astype(np.uint8)

    # PAS 3: OPENCV - EXTRACCIÓ DE GEOMETRIA
    # Busquem el contorn exterior d'aquesta taca blanca
    contorns, _ = cv2.findContours(mascara_binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    contorn_caixa = max(contorns, key=cv2.contourArea)

    # Apliquem la màgia matemàtica: simplifiquem el contorn a línies rectes
    perimetre = cv2.arcLength(contorn_caixa, True)
    # Aquest 0.04 és la clau. Si detecta massa punts, puja'l (ex: 0.05). Si en detecta pocs, baixa'l (ex: 0.02).
    tolerancia = 0.04 * perimetre 
    vertexs = cv2.approxPolyDP(contorn_caixa, tolerancia, True)

    coordenades = [(int(p[0][0]), int(p[0][1])) for p in vertexs]
    print(f"\nÈXIT! S'han calculat {len(coordenades)} vèrtexs a la silueta exterior.")

    # PAS 4: PINTAR EL RESULTAT PER COMPROVAR-HO
    img_resultat = img.copy()
    
    # Dibuixem el polígon verd
    cv2.drawContours(img_resultat, [vertexs], -1, (0, 255, 0), 3)
    
    # Marquem els punts en vermell i els hi posem un número
    for i, (x, y) in enumerate(coordenades):
        cv2.circle(img_resultat, (x, y), 8, (0, 0, 255), -1)
        cv2.putText(img_resultat, f"P{i+1}", (x+15, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)
        print(f"Vèrtex {i+1}: X={x}, Y={y}")

    # Mostrem què veu la IA (màscara) i què calculem nosaltres (resultat)
    cv2.namedWindow("1. Mascara IA", cv2.WINDOW_NORMAL)
    cv2.namedWindow("2. Vertexs Calculats", cv2.WINDOW_NORMAL)
    cv2.imshow("1. Mascara IA", mascara_binaria)
    cv2.imshow("2. Vertexs Calculats", img_resultat)
    cv2.waitKey(0)
    cv2.destroyAllWindows()

    return coordenades

if __name__ == "__main__":
    punts_detectats = detectar_arestes_zeroshot(imatge)