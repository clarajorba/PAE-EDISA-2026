import cv2
import numpy as np
import time

def detectar_qr(gray, detector):

    textos = []
    punts_retorn = []

    if hasattr(detector, 'detectAndDecodeMulti'):
        res = detector.detectAndDecodeMulti(gray)
        if isinstance(res, tuple):
            if len(res) == 4:
                _, decoded_infos, points, _ = res
            elif len(res) == 3:
                decoded_infos, points, _ = res
            else:
                decoded_infos, points = [], None
        else:
            decoded_infos, points = [], None
    else:
        data, pts = detector.detectAndDecode(gray)
        if pts is not None and data:
            decoded_infos = [data]
            points = np.array([pts])
        else:
            decoded_infos, points = [], None

    if points is not None and len(decoded_infos) > 0:
        for i, info in enumerate(decoded_infos):
            if info: # Si no està buit
                textos.append(info)
                punts_retorn.append(points[i])
                
    return textos, punts_retorn

def open_camera(max_index=4):
    # Try V4L2 backend first, then default
    for backend in (cv2.CAP_V4L2, cv2.CAP_ANY):
        for i in range(max_index):
            cap = cv2.VideoCapture(i, backend)
            if cap.isOpened():
                print(f"Opened camera index={i} backend={backend}")
                return cap
            cap.release()
    return None

def main():
    cap = open_camera()
    if cap is None or not cap.isOpened():
        print("Error: No /dev/video* device found or camera cannot be opened.")
        return

    detector = cv2.QRCodeDetector()

    interval_processament = 0.2 # segons
    ultim_temps_proces = 0
    
    # Variables per guardar l'última posició coneguda del QR
    ultims_textos = []
    ultims_punts = []

    print("Prem la tecla 'q' per sortir.")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        temps_actual = time.time()

        # 1. DETECCIÓ (Només 1 cop per segon)
        if temps_actual - ultim_temps_proces >= interval_processament:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            ultims_textos, ultims_punts = detectar_qr(gray, detector)
            
            # --- AFEGIM LA NOTIFICACIÓ DE "NO HI HA QR" AQUÍ ---
            if ultims_textos:
                for text in ultims_textos:
                    print(f"[{time.strftime('%H:%M:%S')}] QR Detectat: {text}")
            else:
                print(f"[{time.strftime('%H:%M:%S')}] No es detecta cap QR")
            # ---------------------------------------------------
            
            ultim_temps_proces = temps_actual

        # 2. DIBUIX I PANTALLA (A cada frame, per mantenir el vídeo fluid)
        if ultims_punts:
            for i, pts in enumerate(ultims_punts):
                # Formatejar punts i dibuixar requadre verd
                pts_int = pts.astype(int).reshape(-1, 2)
                x, y, w, h = cv2.boundingRect(pts_int)
                cv2.rectangle(frame, (x, y), (x + w, y + h), (0, 255, 0), 4)
                
                # Posar el text a sobre
                if i < len(ultims_textos):
                    cv2.putText(frame, ultims_textos[i], (x, y - 10), 
                                cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 0), 2)

        # Mostrar el vídeo fluid
        cv2.imshow("Lectura QR en Viu", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()