import cv2
import socket
import struct
import time
import numpy as np  # <--- ESTO FALTABA

# Configuración
DEST_IP = '127.0.0.1' # La IP real del servidor
PORT = 9999             # El puerto del SSH

def main():
    # Intentamos abrir la cámara, pero si falla no detendremos el script
    cap = cv2.VideoCapture(2)
    
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    
    print("Intentando conectar con el servidor vía túnel...")
    try:
        client_socket.connect((DEST_IP, PORT))
        print("¡CONECTADO!")
    except Exception as e:
        print(f"ERROR: No se pudo conectar. Detalle: {e}")
        print("Asegúrate de que en OTRA terminal tienes el SSH abierto con: ssh -L 9999:localhost:9999 ...")
        return

    try:
        while True:
            # PRUEBA DE RED: Generamos imagen sintética
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, "PROBANDO RED", (150, 240), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

            result, frame_encoded = cv2.imencode('.jpg', frame)
            data = frame_encoded.tobytes()
            size = len(data)

            # Enviar tamaño (4 bytes) y luego los datos
            client_socket.sendall(struct.pack(">L", size) + data)
            print(f"Enviado frame de prueba: {size} bytes")
            time.sleep(1) 
    except KeyboardInterrupt:
        print("Detenido por el usuario")
    except Exception as e:
        print(f"Error durante el envío: {e}")
    finally:
        cap.release()
        client_socket.close()

if __name__ == '__main__':
    main()