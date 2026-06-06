import socket
import struct
import cv2
import numpy as np
import os
from datetime import datetime

# Configuración
HOST = '127.0.0.1' # Escucha al túnel
PORT = 9999scp -P 60001 receptordron_cdr.py user@147.83.46.71:/home/user/PAE/
SAVE_DIR = os.path.expanduser('~/PAE/demo_output')
os.makedirs(SAVE_DIR, exist_ok=True)

def main():
    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.bind((HOST, PORT))
    server_socket.listen(1)
    print(f">>> RECEPTOR BLINDADO LISTO EN PUERTO {PORT} <<<")

    while True:
        conn, addr = server_socket.accept()
        print(f"Conectado con: {addr}")
        try:
            while True:
                # 1. Leer tamaño de la imagen (4 bytes)
                raw_size = conn.recv(4)
                if not raw_size: break
                size = struct.unpack('>L', raw_size)[0]

                # 2. Leer la imagen comprimida
                data = b""
                while len(data) < size:
                    packet = conn.recv(size - len(data))
                    if not packet: break
                    data += packet
                
                # 3. Decodificar y guardar
                nparr = np.frombuffer(data, np.uint8)
                frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                
                timestamp = datetime.now().strftime("%H%M%S_%f")
                fname = os.path.join(SAVE_DIR, f"frame_{timestamp}.jpg")
                cv2.imwrite(fname, frame)
                print(f"Guardado: {fname} ({size} bytes)")

        except Exception as e:
            print(f"Conexión cerrada: {e}")
        finally:
            conn.close()

if __name__ == '__main__':
    main()