import os
import cv2
import numpy as np
from ultralytics import YOLO, SAM

# ==========================================
# CONFIGURACIÓ
# ==========================================
IMATGE_PROVA = "../fotos_caixa/IMG_0944.jpg" 

print("Carregant models d'Intel·ligència Artificial...")
detector = YOLO("yolov8s-world.pt")
detector.set_classes(["box"]) 
segmentador = SAM("mobile_sam.pt") 
# ==========================================

# FUNCIÓ: Lògica Pura d'Intersecció de Línies
def calcular_interseccio(line1, line2):
    vx1, vy1, x1, y1 = line1[0][0], line1[1][0], line1[2][0], line1[3][0]
    vx2, vy2, x2, y2 = line2[0][0], line2[1][0], line2[2][0], line2[3][0]

    # Producte creuat per veure si són paral·leles
    cross = vx1 * vy2 - vy1 * vx2
    if abs(cross) < 1e-6:
        return None 

    # Càlcul del punt de xoc
    t1 = ((x2 - x1) * vy2 - (y2 - y1) * vx2) / cross
    inter_x = x1 + t1 * vx1
    inter_y = y1 + t1 * vy1
    return (int(inter_x), int(inter_y))

def detectar_qualsevol_caixa(ruta_imatge, mostrar_visualment=True):
    print(f"\n--- BLOC 1: SAM + INTERSECCIÓ DE RECTES (Silenciós) ---")
    img = cv2.imread(ruta_imatge)
    if img is None:
        print("Error: No trobo la imatge.")
        return None

    img_sam_visual = img.copy() 
    img_resultat = img.copy()

    # PAS 1: DETECCIÓ AMB YOLO
    print("1. YOLO-World: Localitzant la capsa...")
    resultats_det = detector.predict(img, conf=0.05, verbose=False)
    
    if resultats_det[0].boxes is None or len(resultats_det[0].boxes) == 0:
        return None

    box_yolo = resultats_det[0].boxes.xyxy[0].cpu().numpy().tolist()
    x1, y1, x2, y2 = map(int, box_yolo)
    
    marge = 40
    box_ampliada = [max(0, x1-marge), max(0, y1-marge), min(img.shape[1], x2+marge), min(img.shape[0], y2+marge)]

    # PAS 2: SAM
    print("2. SAM: Extraient la silueta...")
    resultats_sam = segmentador.predict(img, bboxes=box_ampliada, verbose=False)
    
    if resultats_sam[0].masks is None or len(resultats_sam[0].masks.xy) == 0:
        return None

    contorn_sam = resultats_sam[0].masks.xy[0] 
    mascara_binaria = np.zeros((img.shape[0], img.shape[1]), dtype=np.uint8)
    cv2.fillPoly(mascara_binaria, [np.array(contorn_sam, dtype=np.int32)], 255)

    kernel = np.ones((20, 20), np.uint8)
    mascara_binaria = cv2.morphologyEx(mascara_binaria, cv2.MORPH_CLOSE, kernel)
    mascara_binaria = cv2.dilate(mascara_binaria, kernel, iterations=1)

    # Visualització SAM (Blau)
    color_blau_sam = np.zeros_like(img)
    color_blau_sam[:] = (255, 144, 30)
    mescla = cv2.addWeighted(img_sam_visual, 0.5, color_blau_sam, 0.5, 0)
    img_sam_visual[mascara_binaria == 255] = mescla[mascara_binaria == 255]

    # PAS 3: OBTENCIÓ DELS VÈRTEXS ARRODONITS (BRUTS)
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

    # PAS 4: RECONSTRUCCIÓ MATEMÀTICA (ESMOLANT LES CANTONADES)
    print("3. Matemàtiques: Esmolant cantonades per intersecció de línies...")
    
    vora_mascara = np.zeros_like(mascara_binaria)
    cv2.drawContours(vora_mascara, [contorn_principal], -1, 255, 1)

    rectes_matematiques = []
    n = len(coordenades_brutes)
    
    for i in range(n):
        p1 = np.array(coordenades_brutes[i])
        p2 = np.array(coordenades_brutes[(i + 1) % n])
        direccio = p2 - p1
        
        p_inici = p1 + direccio * 0.20
        p_fi = p1 + direccio * 0.80
        
        mascara_linia = np.zeros_like(mascara_binaria)
        cv2.line(mascara_linia, (int(p_inici[0]), int(p_inici[1])), (int(p_fi[0]), int(p_fi[1])), 255, 15)
                                
        punts_vora = cv2.bitwise_and(vora_mascara, mascara_linia)
        coords_y, coords_x = np.where(punts_vora == 255)
        
        if len(coords_x) > 10:
            punts_fit = np.column_stack((coords_x, coords_y))
            recta = cv2.fitLine(punts_fit, cv2.DIST_L2, 0, 0.01, 0.01)
            rectes_matematiques.append(recta)
        else:
            norma = np.linalg.norm(direccio) + 1e-6
            vx, vy = direccio[0]/norma, direccio[1]/norma
            rectes_matematiques.append([np.array([vx]), np.array([vy]), np.array([p1[0]]), np.array([p1[1]])])

    coordenades_esmolades = []
    for i in range(n):
        recta_anterior = rectes_matematiques[(i - 1) % n]
        recta_actual = rectes_matematiques[i]
        
        interseccio = calcular_interseccio(recta_anterior, recta_actual)
        
        if interseccio is not None and 0 <= interseccio[0] <= img.shape[1]*2 and 0 <= interseccio[1] <= img.shape[0]*2:
            coordenades_esmolades.append(interseccio)
        else:
            coordenades_esmolades.append(coordenades_brutes[i]) 

    print(f"ÈXIT! Cantonades refetes.")

    # PAS 5: PINTAR I GUARDAR (SENSE FINESTRES EMERGENTS)
    if mostrar_visualment:
        
        # --- 5.1 DIBUIXAR LÍNIES TARONJA SOBRE EL SAM (img_sam_visual) ---
        n_vertices = len(coordenades_esmolades)
        extend_dist = 100 # Fem la línia prou llarga perquè es vegi bé
        
        for i in range(n_vertices):
            inter_x, inter_y = coordenades_esmolades[i]

            # Dibuixar extensió Recta Anterior sobre SAM
            recta_anterior = rectes_matematiques[(i - 1) % n_vertices]
            vx_pre, vy_pre = recta_anterior[0][0], recta_anterior[1][0]
            p_start1 = (int(inter_x - extend_dist * vx_pre), int(inter_y - extend_dist * vy_pre))
            p_end1 = (int(inter_x + extend_dist * vx_pre), int(inter_y + extend_dist * vy_pre))
            cv2.line(img_sam_visual, p_start1, p_end1, (0, 165, 255), 2) # Línia taronja

            # Dibuixar extensió Recta Actual sobre SAM
            recta_actual = rectes_matematiques[i]
            vx_curr, vy_curr = recta_actual[0][0], recta_actual[1][0]
            p_start2 = (int(inter_x - extend_dist * vx_curr), int(inter_y - extend_dist * vy_curr))
            p_end2 = (int(inter_x + extend_dist * vx_curr), int(inter_y + extend_dist * vy_curr))
            cv2.line(img_sam_visual, p_start2, p_end2, (0, 165, 255), 2) # Línia taronja
            
            # (Opcional) Dibuixar el punt d'intersecció en vermell també al SAM perquè quedi clar on xoquen
            cv2.circle(img_sam_visual, (inter_x, inter_y), 5, (0, 0, 255), -1)

        # --- 5.2 DIBUIXAR RESULTAT FINAL NET SOBRE BLOC1 (img_resultat) ---
        vertexs_dibuix = np.array(coordenades_esmolades, dtype=np.int32).reshape((-1, 1, 2))
        cv2.drawContours(img_resultat, [vertexs_dibuix], -1, (0, 255, 0), 3) # Verd gruixut
        
        for i, (x, y) in enumerate(coordenades_esmolades):
            cv2.circle(img_resultat, (x, y), 8, (0, 0, 255), -1)
            cv2.putText(img_resultat, f"P{i+1}", (x+15, y-10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

        nom_arxiu = os.path.basename(ruta_imatge)
        
        # --- 5.3 GUARDAR ---
        os.makedirs("resultats_SAM", exist_ok=True)
        cv2.imwrite(os.path.join("resultats_SAM", nom_arxiu), img_sam_visual)
        print(f"-> Guardat a resultats_SAM/{nom_arxiu}")

        os.makedirs("Resultats_BLOC1", exist_ok=True)
        cv2.imwrite(os.path.join("Resultats_BLOC1", nom_arxiu), img_resultat)
        print(f"-> Guardat a Resultats_BLOC1/{nom_arxiu}")

    return coordenades_esmolades

if __name__ == "__main__":
    punts = detectar_qualsevol_caixa(IMATGE_PROVA)