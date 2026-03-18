import cv2
import numpy as np
import time
import math
from pyzbar.pyzbar import decode

def processar_frame_inventari(frame, estat_inventari):
    """
    Detecta els QRs, obre/tanca estanteries i llegeix productes.
    Inclou tracking espacial (centroides) per comptar QRs repetits.
    """
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    codis_detectats = decode(gray)
    
    temps_actual = time.time()
    
    # Configuració
    COOLDOWN_TANCAMENT = 4.0   
    COOLDOWN_ENTRE_ESTANTERIES = 3.0 
    DISTANCIA_MAXIMA = 80.0 # Píxels de tolerància per considerar que és la mateixa caixa

    for codi in codis_detectats:
        text = codi.data.decode('utf-8')
        pts = np.array([codi.polygon], np.int32)
        
        # 1. Calcular el centre exacte (Centroide) del QR
        M = cv2.moments(pts)
        if M["m00"] != 0:
            cx = int(M["m10"] / M["m00"])
            cy = int(M["m01"] / M["m00"])
        else:
            cx, cy = pts[0][0][0], pts[0][0][1] # Fallback de seguretat

        x, y = pts[0][0] # Coordenades per posar el text a dalt

        # Dibuixem el contorn i un punt vermell al centre per entendre el tracking
        cv2.polylines(frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
        cv2.circle(frame, (cx, cy), 5, (0, 0, 255), -1) # Punt vermell
        cv2.putText(frame, text, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        # 2. LÒGICA ESTANTERIES (LOC-)
        if text.startswith("LOC-"):
            if estat_inventari['estanteria_actual'] is None:
                temps_des_del_tancament = temps_actual - estat_inventari['temps_tancament']
                if temps_des_del_tancament > COOLDOWN_ENTRE_ESTANTERIES:
                    estat_inventari['estanteria_actual'] = text
                    estat_inventari['temps_obertura'] = temps_actual
                    # ARA ÉS UN DICCIONARI: {'Codi_Producte': [(cx1, cy1), (cx2, cy2)]}
                    estat_inventari['productes_temporals'] = {} 
                    print(f"\n[+] OBERTA TRANSACCIÓ: {text}")
                else:
                    cv2.putText(frame, "COOLDOWN ESTANTERIA...", (x, y - 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)

            elif estat_inventari['estanteria_actual'] == text:
                temps_passat = temps_actual - estat_inventari['temps_obertura']
                if temps_passat > COOLDOWN_TANCAMENT: 
                    # Guardem a l'inventari global (convertim les coordenades en 'quantitats')
                    # Ex: {'PRODUCTE_A': 2 unitats, 'PRODUCTE_B': 1 unitat}
                    resum_quantitats = {prod: len(centres) for prod, centres in estat_inventari['productes_temporals'].items()}
                    estat_inventari['inventari_global'][text] = resum_quantitats
                    
                    print(f"[-] TANCADA TRANSACCIÓ: {text}\n")
                    
                    estat_inventari['estanteria_actual'] = None
                    estat_inventari['productes_temporals'] = {}
                    estat_inventari['temps_tancament'] = temps_actual

        # 3. LÒGICA PRODUCTES (Qualsevol altre codi)
        else:
            if estat_inventari['estanteria_actual'] is not None:
                inventari_temp = estat_inventari['productes_temporals']
                
                # A: Mai havíem vist aquest codi en aquesta estanteria
                if text not in inventari_temp:
                    inventari_temp[text] = [(cx, cy)]
                    print(f"codi producte: {text} estanteria: {estat_inventari['estanteria_actual']}")
                
                # B: Ja tenim aquest codi registrat. És el mateix o és una caixa nova?
                else:
                    centres_coneguts = inventari_temp[text]
                    distancia_minima = float('inf')
                    index_mes_proper = -1
                    
                    # Calculem la distància respecte a totes les caixes conegudes d'aquest producte
                    for i, centre_guardat in enumerate(centres_coneguts):
                        dist = math.hypot(cx - centre_guardat[0], cy - centre_guardat[1])
                        if dist < distancia_minima:
                            distancia_minima = dist
                            index_mes_proper = i
                    
                    # Si està molt a prop d'un de conegut (< 80 px), és el MATEIX producte que s'ha mogut
                    if distancia_minima < DISTANCIA_MAXIMA:
                        # Actualitzem la coordenada perquè si el dron avança, el centre se n'anirà movent de mica en mica
                        centres_coneguts[index_mes_proper] = (cx, cy)
                    
                    # Si està lluny de tots (>= 80 px), és una NOVA CAIXA física amb el mateix codi!
                    else:
                        centres_coneguts.append((cx, cy))
                        print(f"codi producte: {text} estanteria: {estat_inventari['estanteria_actual']} (NOVA UNITAT DETECTADA)")

    # Interfície visual d'estat
    if estat_inventari['estanteria_actual'] is None:
        if (temps_actual - estat_inventari['temps_tancament']) < COOLDOWN_ENTRE_ESTANTERIES:
            estat_text = "Estat: COOLDOWN (Ignorant estanteries)"
            color_estat = (0, 165, 255)
        else:
            estat_text = "Estat: ESPERANT ESTANTERIA"
            color_estat = (255, 255, 255)
    else:
        estat_text = "LLEGINT: " + estat_inventari['estanteria_actual']
        color_estat = (0, 255, 0)

    cv2.putText(frame, estat_text, (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.8, color_estat, 2)
    return frame

def main():
    FONT_VIDEO = "tcp://172.20.10.3:8888"  # 0: webcam de l'ordinador
                    #"tcp://192.168.137.10:8888" : raspberry
    cap = cv2.VideoCapture(FONT_VIDEO)
    if not cap.isOpened():
        print("Error: No s'ha pogut obrir la webcam.")
        return

    # Memòria del sistema (productes_temporals ara és un diccionari)
    memoria_inventari = {
        'estanteria_actual': None,
        'temps_obertura': 0,
        'temps_tancament': 0, 
        'productes_temporals': {}, 
        'inventari_global': {} 
    }

    print("Sistema actiu. Posa un QR d'estanteria (LOC-) per començar.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_resultat = processar_frame_inventari(frame, memoria_inventari)
        cv2.imshow("Gestio d'Inventari Drons", frame_resultat)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()
    
    # En tancar el programa, imprimim el resum final agrupat per quantitats
    print("\n--- RESUM DE L'INVENTARI (ESTANTERIA -> PRODUCTE : QUANTITAT) ---")
    for estanteria, productes in memoria_inventari['inventari_global'].items():
        print(f"[{estanteria}]")
        for codi_prod, quantitat in productes.items():
            print(f"  - {codi_prod}: {quantitat} unitats")

if __name__ == "__main__":
    main()

    #hola