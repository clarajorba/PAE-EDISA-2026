import cv2
import numpy as np
import math
import glob
import os
import statistics

# ==========================================
# CONFIGURACIÓ DE L'ENTORN
# ==========================================
CARPETA_FOTOS = "fotos_caixa" 
DISTANCIA_LIDAR_CM = 60.0  
DISTANCIA_FOCAL_PX = 2976.74 

punts_usuari = []

def capturar_clics(event, x, y, flags, param):
    global punts_usuari
    if event == cv2.EVENT_LBUTTONDOWN:
        if len(punts_usuari) < 6:
            punts_usuari.append((x, y))
            img_mostrar = param[0]
            cv2.circle(img_mostrar, (x, y), 10, (0, 0, 255), -1)
            
            n = len(punts_usuari)
            color = (0, 255, 0)
            if n == 2: cv2.line(img_mostrar, punts_usuari[0], punts_usuari[1], color, 3)
            elif n == 3: cv2.line(img_mostrar, punts_usuari[0], punts_usuari[2], color, 3)
            elif n == 4: 
                cv2.line(img_mostrar, punts_usuari[2], punts_usuari[3], color, 3)
                cv2.line(img_mostrar, punts_usuari[1], punts_usuari[3], color, 3)
            elif n == 5: cv2.line(img_mostrar, punts_usuari[2], punts_usuari[4], color, 3)
            elif n == 6: 
                cv2.line(img_mostrar, punts_usuari[4], punts_usuari[5], color, 3)
                cv2.line(img_mostrar, punts_usuari[3], punts_usuari[5], color, 3)
            cv2.imshow(param[1], img_mostrar)

def processar_fotograma_parallax(ruta_imatge, nom_finestra):
    global punts_usuari
    punts_usuari = []
    
    img = cv2.imread(ruta_imatge)
    if img is None: return None
        
    img_mostrar = img.copy()
    cv2.namedWindow(nom_finestra, cv2.WINDOW_NORMAL)
    alt, ample = img.shape[:2]
    cv2.resizeWindow(nom_finestra, 1000, int(alt * (1000 / ample)))
    
    cv2.imshow(nom_finestra, img_mostrar)
    cv2.setMouseCallback(nom_finestra, capturar_clics, [img_mostrar, nom_finestra])
    
    print(f"Fes els 6 clics d'esquerra a dreta a: {nom_finestra} (o 'q' per saltar)")
    
    while len(punts_usuari) < 6:
        if cv2.waitKey(1) & 0xFF == ord('q'): break
            
    if len(punts_usuari) == 6: cv2.waitKey(800) 
    cv2.destroyWindow(nom_finestra)
    
    if len(punts_usuari) == 6:
        x_esq = (punts_usuari[0][0] + punts_usuari[1][0]) / 2
        x_cen = (punts_usuari[2][0] + punts_usuari[3][0]) / 2
        x_dre = (punts_usuari[4][0] + punts_usuari[5][0]) / 2
        
        y_dalt = punts_usuari[2][1]
        y_baix = punts_usuari[3][1]
        
        w_cara_1_px = abs(x_cen - x_esq)
        w_cara_2_px = abs(x_dre - x_cen)
        h_caixa_px = abs(y_baix - y_dalt)
        
        # El centre òptic de la imatge (cx) on convergeix la profunditat
        cx = ample / 2.0
        
        return {
            "arxiu": nom_finestra,
            "x_esq": x_esq, "x_cen": x_cen, "x_dre": x_dre,
            "cx": cx, "w_1": w_cara_1_px, "w_2": w_cara_2_px, "h_px": h_caixa_px
        }
    return None

def calcular_volumetria_dron():
    patro_busqueda = os.path.join(CARPETA_FOTOS, "*.*")
    rutes_fotos = [f for f in glob.glob(patro_busqueda) if f.lower().endswith(('.png', '.jpg', '.jpeg'))]
    
    if not rutes_fotos:
        print(f"Posa fotos a la carpeta '{CARPETA_FOTOS}'!")
        return
        
    print("\n--- MOTOR PARAL·LAXI (DRON PARAL·LEL) ACTIVAT ---")
    
    resultats_amplada = []
    resultats_profunditat = []
    resultats_alcada = []
    
    for ruta in rutes_fotos:
        nom_arxiu = os.path.basename(ruta)
        dades = processar_fotograma_parallax(ruta, nom_arxiu)
        
        if not dades: continue
            
        # Determinar quina és la cara frontal i quina és la lateral
        if dades["w_1"] < dades["w_2"]:
            # Cara esquerra és la lateral, dreta és la frontal
            amplada_px = dades["w_2"]
            u_front = abs(dades["x_cen"] - dades["cx"])
            u_back = abs(dades["x_esq"] - dades["cx"])
        else:
            # Cara dreta és la lateral, esquerra és la frontal
            amplada_px = dades["w_1"]
            u_front = abs(dades["x_cen"] - dades["cx"])
            u_back = abs(dades["x_dre"] - dades["cx"])
            
        # Filtre de seguretat òptica
        if u_back >= u_front:
            print(f"[{nom_arxiu}] DESCARTADA: Càmera rotada. Les fotos han de ser estrictament paral·leles.")
            continue
            
        if u_back < 1: u_back = 1 # Evitar divisió per zero
        
        # Càlculs físics
        profunditat_cm = DISTANCIA_LIDAR_CM * ((u_front / u_back) - 1.0)
        amplada_cm = (amplada_px * DISTANCIA_LIDAR_CM) / DISTANCIA_FOCAL_PX
        alcada_cm = (dades["h_px"] * DISTANCIA_LIDAR_CM) / DISTANCIA_FOCAL_PX
        
        resultats_amplada.append(amplada_cm)
        resultats_profunditat.append(profunditat_cm)
        resultats_alcada.append(alcada_cm)
        
        print(f"[{nom_arxiu}] OK -> Translació detectada. Profunditat Z estirada a: {profunditat_cm:.1f} cm")
        
    if not resultats_profunditat:
        print("\nError: Cap de les fotos ha superat el filtre de paral·lelisme.")
        return
        
    # Resultats Finals (Mediana)
    amp_final = statistics.median(resultats_amplada)
    prof_final = statistics.median(resultats_profunditat)
    alc_final = statistics.median(resultats_alcada)
    volum_final = amp_final * prof_final * alc_final
    
    print("\n==========================================")
    print(f" RESULTATS FINALS DRON ({len(resultats_profunditat)} FOTOS VÀLIDES)")
    print("==========================================")
    print(f"Amplada (Frontal):    {amp_final:.1f} cm")
    print(f"Profunditat (Lateral):{prof_final:.1f} cm")
    print(f"Alçada estimada:      {alc_final:.1f} cm")
    print("------------------------------------------")
    print(f"VOLUM TOTAL:          {volum_final:.2f} cm³")
    print("==========================================")

if __name__ == "__main__":
    calcular_volumetria_dron()