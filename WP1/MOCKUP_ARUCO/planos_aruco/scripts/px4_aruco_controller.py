import asyncio
import cv2
import cv2.aruco as aruco
import numpy as np
import json
import time
from mavsdk import System
from mavsdk.mission import MissionItem, MissionPlan

class PX4ArucoDroneController:
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
        self.camera_matrix = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=np.float32)
        self.dist_coeffs = np.zeros((5, 1), dtype=np.float32)

        # Tamaño del marcador en metros
        self.marker_size = self.config['marker_size_mm'] / 1000.0

        # Estado del dron
        self.drone = System()
        self.current_waypoint = 0
        self.detected_markers = {}

    async def connect_drone(self, connection_string="udp://:14540"):
        """Conecta al dron PX4."""
        print(f"Conectando al dron en {connection_string}...")
        await self.drone.connect(system_address=connection_string)

        print("Esperando conexión...")
        async for state in self.drone.core.connection_state():
            if state.is_connected:
                print("Dron conectado!")
                break

    async def upload_mission(self):
        """Sube la misión (waypoints) al dron."""
        mission_items = []
        for wp in self.flight_sequence:
            pos = wp['position']
            mission_items.append(MissionItem(
                latitude_deg=0.0,  # Usar coordenadas GPS reales
                longitude_deg=0.0,
                relative_altitude_m=pos[2],
                speed_m_s=0.5,
                is_fly_through=True,
                gimbal_pitch_deg=0.0,
                gimbal_yaw_deg=0.0,
                camera_action=MissionItem.CameraAction.NONE,
                loiter_time_s=0.0,
                camera_photo_interval_s=0.0
            ))

        mission_plan = MissionPlan(mission_items)
        await self.drone.mission.upload_mission(mission_plan)
        print("Misión subida al dron")

    async def start_mission(self):
        """Inicia la misión."""
        await self.drone.mission.start_mission()
        print("Misión iniciada")

    async def detect_and_control(self):
        """Bucle principal de detección y control."""
        cap = cv2.VideoCapture(0)  # Ajustar según la cámara del dron

        if not cap.isOpened():
            print("Error: No se puede abrir la cámara")
            return

        print("Iniciando detección de ArUco con PX4. Presiona 'q' para salir.")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detected = self.detect_markers(frame)

            for marker in detected:
                shelf = marker['shelf']
                floor = marker['floor']
                shelf_floor = marker['shelf_floor']
                position = marker['position']
                print(f"Marcador detectado: {shelf_floor} (ID {marker['id']}) en posición {position}")

                # Tomar una foto la primera vez que se detecta este ID
                if shelf_floor not in self.detected_markers:
                    await self.take_photo_and_report(frame, shelf_floor, position, self.flight_sequence[self.current_waypoint]['position'])
                    self.detected_markers[shelf_floor] = True

                # Avanzar al siguiente waypoint si coincide con el actual
                if self.current_waypoint < len(self.flight_sequence):
                    current_wp = self.flight_sequence[self.current_waypoint]
                    if current_wp['shelf_floor'] == shelf_floor:
                        self.current_waypoint += 1

            cv2.imshow('PX4 ArUco Detection', frame)

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

    def detect_markers(self, frame):
        """Detecta marcadores ArUco en el frame."""
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        corners, ids, rejected = aruco.detectMarkers(gray, self.dictionary, parameters=self.parameters)

        if ids is not None:
            rvecs, tvecs, _ = aruco.estimatePoseSingleMarkers(corners, self.marker_size, self.camera_matrix, self.dist_coeffs)

            detected = []
            for i, marker_id in enumerate(ids.flatten()):
                if marker_id in self.config['assignments'].values():
                    # Obtener la clave (E1-P0, E2-P3, etc.)
                    shelf_floor = [k for k, v in self.config['assignments'].items() if v == marker_id][0]
                    # Separar estantería y piso
                    parts = shelf_floor.split('-')
                    shelf = parts[0]  # E1, E2, etc.
                    floor = parts[1]  # P0, P1, etc.
                    
                    position = tvecs[i].flatten()
                    rotation = rvecs[i].flatten()

                    detected.append({
                        'shelf': shelf,
                        'floor': floor,
                        'shelf_floor': shelf_floor,
                        'id': marker_id,
                        'position': position.tolist(),
                        'rotation': rotation.tolist()
                    })

                    # Dibujar en el frame
                    aruco.drawDetectedMarkers(frame, [corners[i]], np.array([[marker_id]]))
                    aruco.drawAxis(frame, self.camera_matrix, self.dist_coeffs, rvecs[i], tvecs[i], 0.1)

            return detected
        return []

    async def take_photo_and_report(self, frame, shelf_floor, aruco_position, waypoint_position):
        """Toma foto y reporta posición al sistema."""
        filename = f"photos/{shelf_floor}_{int(time.time())}.jpg"
        cv2.imwrite(filename, frame)
        print(f"Foto tomada: {filename}")

        # Usar coordenadas del waypoint (sin GPS)
        local_position = {
            'x': waypoint_position[0],
            'y': waypoint_position[1],
            'z': waypoint_position[2]
        }

        # Reportar datos (aquí podrías enviar a un servidor o base de datos)
        report = {
            'shelf_floor': shelf_floor,
            'timestamp': time.time(),
            'local_position': local_position,
            'aruco_position': aruco_position,
            'photo_path': filename
        }

        print(f"Reporte generado: {report}")

    async def run(self):
        """Ejecuta el sistema completo."""
        await self.connect_drone()
        await self.upload_mission()
        await self.start_mission()

        # Ejecutar detección en paralelo
        await self.detect_and_control()

async def main():
    controller = PX4ArucoDroneController()
    await controller.run()

if __name__ == "__main__":
    asyncio.run(main())