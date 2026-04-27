import os
import cv2
import math
import statistics

# ==========================================
# CONFIGURACIÓ DE L'ENTORN
# ==========================================
DISTANCIA_LIDAR_CM = 150.0
DISTANCIA_FOCAL_PX = 1410.71 #2976.74 iphone11

# Factor per compensar l'angle picat del dron a l'eix Z
# De momeent el deixem en 1 (sense correcció), i l'anirem ajustant quan fem les proves amb el dron real.
CORRECCIO_PERSPECTIVA_Z = 1  
# ==========================================

def es_rectangle_frontal(punts, tolerancia_graus=20):
    """Comprova si 4 punts formen un rectangle (angles propers a 90º)"""
    if len(punts) != 4: 
        return False
    
    angles = []
    for i in range(4):
        p1 = punts[i-1]         
        p2 = punts[i]           
        p3 = punts[(i+1) % 4]   
        
        v1 = (p1[0] - p2[0], p1[1] - p2[1])
        v2 = (p3[0] - p2[0], p3[1] - p2[1])
        
        dot = v1[0]*v2[0] + v1[1]*v2[1]
        mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
        
        if mag1 == 0 or mag2 == 0: return False
        
        cos_theta = max(-1.0, min(1.0, dot / (mag1 * mag2))) 
        angle = math.degrees(math.acos(cos_theta))
        angles.append(angle)
        
    for a in angles:
        if abs(a - 90) > tolerancia_graus:
            return False
            
    return True

def calcular_volumetria(ruta_carpeta, diccionari_punts):
    print("\n--- MOTOR PARAL·LAXI (DRON PARAL·LEL) ACTIVAT (AUTOMÀTIC) ---")
    
    if not diccionari_punts:
        print("Error: No s'han rebut dades del BLOC 1.")
        return

    # Llistes separades per classificar les mides segons la fiabilitat de la foto
    resultats_amplada_frontal = []
    resultats_alcada_frontal = []
    
    resultats_amplada_persp = []
    resultats_alcada_persp = []
    resultats_profunditat_persp = []
    
    for nom_imatge, punts in diccionari_punts.items():
        ruta_completa = os.path.join(ruta_carpeta, nom_imatge)
        img = cv2.imread(ruta_completa)
        
        if img is None: continue
            
        ample_img = img.shape[1]
        cx = ample_img / 2.0  

        x_coords = [p[0] for p in punts]
        y_coords = [p[1] for p in punts]

        x_esq, x_dre = min(x_coords), max(x_coords)
        y_dalt, y_baix = min(y_coords), max(y_coords)

        # =======================================================
        # CAS 1: FOTO FRONTAL PERFECTA (4 vèrtexs que fan 90º)
        # =======================================================
        if len(punts) == 4 and es_rectangle_frontal(punts):
            w_px = x_dre - x_esq
            h_px = y_baix - y_dalt
            
            amplada_cm = (w_px * DISTANCIA_LIDAR_CM) / DISTANCIA_FOCAL_PX
            alcada_cm = (h_px * DISTANCIA_LIDAR_CM) / DISTANCIA_FOCAL_PX
            
            resultats_amplada_frontal.append(amplada_cm)
            resultats_alcada_frontal.append(alcada_cm)
            print(f"[{nom_imatge}] CARA FRONTAL OK -> Amplada: {amplada_cm:.1f}cm, Alçada: {alcada_cm:.1f}cm")
            continue

        # =======================================================
        # CAS 2: FOTO EN PERSPECTIVA (5 o 6 vèrtexs)
        # =======================================================
        if len(punts) >= 5:
            # Deduïm l'aresta central pel punt més baix
            p_bottom = punts[y_coords.index(y_baix)]
            x_cen = float(p_bottom[0])

            w_cara_1_px = abs(x_cen - x_esq)
            w_cara_2_px = abs(x_dre - x_cen)
            h_caixa_px = abs(y_baix - y_dalt)

            if w_cara_1_px < w_cara_2_px:
                amplada_px = w_cara_2_px
                u_front = abs(x_cen - cx)
                u_back = abs(x_esq - cx)
            else:
                amplada_px = w_cara_1_px
                u_front = abs(x_cen - cx)
                u_back = abs(x_dre - cx)
                
            if u_back >= u_front:
                print(f"[{nom_imatge}] DESCARTADA: Càmera rotada o asimetria en la segmentació.")
                continue
                
            if u_back < 1: u_back = 1 
            
            # Càlculs Físics originals
            amplada_cm = (amplada_px * DISTANCIA_LIDAR_CM) / DISTANCIA_FOCAL_PX
            alcada_cm = (h_caixa_px * DISTANCIA_LIDAR_CM) / DISTANCIA_FOCAL_PX
            profunditat_cm = DISTANCIA_LIDAR_CM * ((u_front / u_back) - 1.0)
            
            # --- CORRECCIÓ DE PERSPECTIVA A L'EIX Z ---
            profunditat_cm = profunditat_cm * CORRECCIO_PERSPECTIVA_Z
            
            resultats_amplada_persp.append(amplada_cm)
            resultats_alcada_persp.append(alcada_cm)
            resultats_profunditat_persp.append(profunditat_cm)
            
            print(f"[{nom_imatge}] PERSPECTIVA OK -> Profunditat estirada i corregida a: {profunditat_cm:.1f} cm")
            continue
            
        # Si arriba aquí, té menys de 4 punts o és un quadrilàter completament deformat
        print(f"[{nom_imatge}] DESCARTADA: Polígon invàlid ({len(punts)} vèrtexs).")

    # ==========================================
    # CÀLCUL DELS RESULTATS FINALS (INTEL·LIGENT)
    # ==========================================
    if not resultats_profunditat_persp:
        print("\nError: Falten fotos en perspectiva per calcular la profunditat (Z).")
        return
        
    # Per a Amplada i Alçada, prioritzem de forma absoluta les mesures frontals si existeixen
    if len(resultats_amplada_frontal) > 0:
        amp_final = statistics.median(resultats_amplada_frontal)
        alc_final = statistics.median(resultats_alcada_frontal)
        print("\n[INFO] S'han utilitzat les fotos frontals com a 'Ground Truth' per a X i Y.")
    else:
        amp_final = statistics.median(resultats_amplada_persp)
        alc_final = statistics.median(resultats_alcada_persp)
        print("\n[INFO] Sense fotos frontals pures. Extracció de X i Y basada en perspectiva.")

    # La profunditat sempre ve de les fotos en perspectiva (corregides per l'escorç)
    prof_final = statistics.median(resultats_profunditat_persp)
    
    volum_final = amp_final * prof_final * alc_final
    
    print("\n==========================================")
    print(f" RESULTATS FINALS DRON (Frontals: {len(resultats_amplada_frontal)}, Perspectiva: {len(resultats_profunditat_persp)})")
    print("==========================================")
    print(f"Amplada (Frontal):    {amp_final:.1f} cm")
    print(f"Profunditat (Lateral):{prof_final:.1f} cm")
    print(f"Alçada estimada:      {alc_final:.1f} cm")
    print("------------------------------------------")
    print(f"VOLUM TOTAL:          {volum_final:.2f} cm³")
    print("==========================================")