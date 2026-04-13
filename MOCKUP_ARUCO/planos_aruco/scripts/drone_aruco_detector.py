import cv2
import cv2.aruco as aruco
import numpy as np
import json
import time

class DroneArucoDetector:
    def __init__(self, config_path='config/markers_config.json', flight_sequence_path='scripts/flight_sequence.json'):
        # Cargar configuración
        with open(config_path, 'r') as f:
            self.config = json.load(f)

        # Cargar secuencia de vuelo
        with open(flight_sequence_path, 'r') as f:
            self.flight_sequence = json.load(f)

        # Configurar diccionario ArUco
        self.dictionary = aruco.getPredefinedDictionary(getattr(aruco, self.config['dictionary']))
        self.parameters = aruco.DetectorParameters()

        # Parámetros de la cámara (ajustar según calibración)
        self.camera_matrix = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=np.float32)  # Ejemplo
        self.dist_coeffs = np.zeros((5, 1), dtype=np.float32)  # Sin distorsión para simplificar

        # Tamaño del marcador en metros
        self.marker_size = self.config['marker_size_mm'] / 1000.0  # Convertir a metros

        # Estado del dron
        self.current_waypoint = 0
        self.detected_markers = {}

    def detect_markers(self, frame):
        """Detecta marcadores ArUco en el frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, rejected = aruco.detectMarkers(gray, self.dictionary, parameters=self.parameters)

        if ids is not None:
            # Estimar pose
            rvecs, tvecs, _ = aruco.estimatePoseSingleMarkers(corners, self.marker_size, self.camera_matrix, self.dist_coeffs)

            detected = []
            for i, marker_id in enumerate(ids.flatten()):
                if marker_id in self.config['assignments'].values():
                    shelf = [k for k, v in self.config['assignments'].items() if v == marker_id][0]
                    position = tvecs[i].flatten()
                    rotation = rvecs[i].flatten()

                    detected.append({
                        'shelf': shelf,
                        'id': marker_id,
                        'position': position.tolist(),
                        'rotation': rotation.tolist()
                    })

                    # Dibujar en el frame
                    aruco.drawDetectedMarkers(frame, [corners[i]], np.array([[marker_id]]))
                    aruco.drawAxis(frame, self.camera_matrix, self.dist_coeffs, rvecs[i], tvecs[i], 0.1)

            return detected
        return []

    def navigate_to_next_waypoint(self):
        """Simula navegación al siguiente waypoint (en un dron real, enviar comandos de movimiento)."""
        if self.current_waypoint < len(self.flight_sequence):
            wp = self.flight_sequence[self.current_waypoint]
            print(f"Navegando a waypoint {self.current_waypoint + 1}: {wp['shelf']} en posición {wp['position']}")
            # Aquí iría el código para mover el dron al waypoint
            # Por ejemplo: drone.move_to(wp['position'])
            time.sleep(2)  # Simular movimiento
            self.current_waypoint += 1
            return True
        return False

    def take_photo(self, frame, shelf):
        """Simula tomar una foto (guardar frame)."""
        filename = f"photos/{shelf}_{int(time.time())}.jpg"
        cv2.imwrite(filename, frame)
        print(f"Foto tomada y guardada: {filename}")

    def run(self):
        """Ejecuta el bucle principal de detección."""
        cap = cv2.VideoCapture(0)  # Usar cámara 0 (ajustar según el dron)

        if not cap.isOpened():
            print("Error: No se puede abrir la cámara")
            return

        print("Iniciando detección de ArUco. Presiona 'q' para salir.")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detected = self.detect_markers(frame)

            for marker in detected:
                shelf = marker['shelf']
                position = marker['position']
                print(f"Marcador detectado: {shelf} (ID {marker['id']}) en posición {position}")

                # Si es el waypoint actual, tomar foto y avanzar
                if self.current_waypoint < len(self.flight_sequence):
                    current_wp = self.flight_sequence[self.current_waypoint]
                    if current_wp['shelf'] == shelf:
                        self.take_photo(frame, shelf)
                        self.navigate_to_next_waypoint()

            cv2.imshow('Drone ArUco Detection', frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    detector = DroneArucoDetector()
    detector.run()