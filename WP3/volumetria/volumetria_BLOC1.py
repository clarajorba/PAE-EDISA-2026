import os
import cv2
import numpy as np
from ultralytics import YOLO, SAM

# ==========================================
# CONFIGURACIÓ
# ==========================================
IMATGE_PROVA = "../fotos_caixa/IMG_0845.jpeg" 

# 1. El Detector: YOLO-World per trobar la capsa
detector = YOLO("yolov8s-world.pt")
detector.set_classes(["box"]) 

# 2. El Segmentador: MobileSAM (Es descarregarà sol el primer cop)
segmentador = SAM("mobile_sam.pt") 
# ==========================================

def detectar_qualsevol_caixa(ruta_imatge, mostrar_visualment=True):
    print(f"\n--- BLOC 1: YOLO-WORLD + SAM ---")
    img = cv2.imread(ruta_imatge)
    if img is None:
        print("Error: No trobo la imatge.")
        return None

    img_resultat = img.copy()

    # PAS 1: DETECCIÓ AMB YOLO-WORLD (Rectangle)
    print("1. YOLO-World: Localitzant la capsa...")
    resultats_det = detector.predict(img, conf=0.05, verbose=False)
    
    if resultats_det[0].boxes is None or len(resultats_det[0].boxes) == 0:
        print("YOLO-World no ha trobat cap caixa.")
        return None

    # Agafem les coordenades del rectangle
    box_yolo = resultats_det[0].boxes.xyxy[0].cpu().numpy().tolist()
    x1, y1, x2, y2 = map(int, box_yolo)
    print(f"   -> Caixa detectada al rectangle: [{x1}, {y1}, {x2}, {y2}]")
    cv2.rectangle(img_resultat, (x1, y1), (x2, y2), (255, 0, 0), 2)

    # PAS 2: SEGMENT ATHING MODEL (SAM)
    # Li passem el rectangle com a "pista" perquè sàpiga què ha de retallar exactament
    print("2. SAM: Extraient la silueta en 3D...")
    resultats_sam = segmentador.predict(img, bboxes=box_yolo, verbose=False)
    
    if resultats_sam[0].masks is None:
        print("SAM no ha pogut generar la silueta.")
        return None

    # Extraiem la màscara (SAM la retorna com un tensor numèric o booleà)
    mascara_sam = resultats_sam[0].masks.data[0].cpu().numpy()
    
    # CORRECCIÓ: Convertim el booleà a valors 0 i 1 (uint8) abans del resize
    mascara_sam = mascara_sam.astype(np.uint8)
    
    # Ara sí, OpenCV pot redimensionar sense problemes
    mascara_sam = cv2.resize(mascara_sam, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_NEAREST)
    
    # Multipliquem per 255 perquè els "1" es tornin blancs purs (255)
    mascara_binaria = mascara_sam * 255

# PAS 3: EXTRACCIÓ INTEL·LIGENT DE VÈRTEXS
    contorns, _ = cv2.findContours(mascara_binaria, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    
    if not contorns:
        print("Error: No s'ha trobat cap contorn a la màscara.")
        return None
        
    contorn_principal = max(contorns, key=cv2.contourArea)

    # 1. Apliquem l'envolupant convexa (Convex Hull) per suavitzar bonys i arrugues
    hull = cv2.convexHull(contorn_principal)
    perimetre = cv2.arcLength(hull, True)

    # 2. Cerca dinàmica de l'hexàgon (6 punts) o pentàgon (5 punts)
    vertexs_ideals = None
    
    # Anem provant toleràncies des d'un 1% fins a un 10%
    for factor in np.arange(0.01, 0.10, 0.002):
        tolerancia = factor * perimetre
        aproximacio = cv2.approxPolyDP(hull, tolerancia, True)
        
        # Ens interessa principalment trobar els 6 vèrtexs de la caixa 3D
        if len(aproximacio) == 6:
            vertexs_ideals = aproximacio
            break 
        # Si en trobem 5, ens ho guardem a la recambra per si no arribem a trobar els 6
        elif len(aproximacio) == 5 and vertexs_ideals is None:
            vertexs_ideals = aproximacio

    # Si després de tot el bucle no hem trobat ni 5 ni 6 punts, fem una aproximació per defecte
    if vertexs_ideals is not None:
        vertexs = vertexs_ideals
    else:
        print("Avís: No s'ha pogut forçar un polígon de 5 o 6 costats. S'usa l'aproximació base.")
        vertexs = cv2.approxPolyDP(hull, 0.04 * perimetre, True)

    coordenades = [(int(p[0][0]), int(p[0][1])) for p in vertexs]
    print(f"ÈXIT! S'han calculat {len(coordenades)} vèrtexs a la silueta suavitzada.")
    
    # PAS 4: PINTAR I GUARDAR EL RESULTAT
    if mostrar_visualment:
        # 1. Convertim la llista normal al format matriu que demana OpenCV
        vertexs_dibuix = np.array(coordenades, dtype=np.int32).reshape((-1, 1, 2))
        
        # 2. Ara sí, dibuixem les línies verdes usant la matriu convertida
        cv2.drawContours(img_resultat, [vertexs_dibuix], -1, (0, 255, 0), 3)
        
        # 3. Dibuixem els punts vermells i els textos (això sí que accepta tuples normals)
        for i, (x, y) in enumerate(coordenades):
            cv2.circle(img_resultat, (x, y), 8, (0, 0, 255), -1)
            cv2.putText(img_resultat, f"P{i+1}", (x+15, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        # Creem la carpeta (ara l'anomenem resultats_SAM)
        carpeta_sortida = "resultats_SAM"
        os.makedirs(carpeta_sortida, exist_ok=True)

        nom_arxiu = os.path.basename(ruta_imatge)
        ruta_guardat = os.path.join(carpeta_sortida, nom_arxiu)
        cv2.imwrite(ruta_guardat, img_resultat)
        print(f"-> Imatge de debug guardada a: {ruta_guardat}")

        # Les finestres emergents per comprovar-ho en viu
        cv2.namedWindow("1. Mascara SAM", cv2.WINDOW_NORMAL)
        cv2.namedWindow("2. Resultat Final", cv2.WINDOW_NORMAL)
        cv2.imshow("1. Mascara SAM", mascara_binaria)
        cv2.imshow("2. Resultat Final", img_resultat)
        cv2.waitKey(1) # S'esperarà una mica o requerirà tecla si canvies a 0
        cv2.destroyAllWindows()

    return coordenades

if __name__ == "__main__":
    punts = detectar_qualsevol_caixa(IMATGE_PROVA)