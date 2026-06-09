import json
import cv2
from cv2 import aruco
import numpy as np

def generate_aruco_markers(config_path='config/markers_config.json'):
    """
    Genera los marcadores ArUco basados en la configuración.
    Si prefieres crearlos manualmente, puedes saltar esta función.
    """
    with open(config_path, 'r') as f:
        config = json.load(f)

    dictionary = aruco.getPredefinedDictionary(getattr(aruco, config['dictionary']))
    marker_size = config['marker_size_mm']

    for shelf, marker_id in config['assignments'].items():
        marker_image = aruco.generateImageMarker(dictionary, marker_id, 200)  # 200x200 pixels
        cv2.imwrite(f'markers/{shelf}_id_{marker_id}.png', marker_image)
        print(f'Marcador generado: {shelf} (ID {marker_id})')

if __name__ == "__main__":
    generate_aruco_markers()