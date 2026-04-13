import json

def load_marker_config(config_path='config/markers_config.json'):
    """Carga la configuración de marcadores."""
    with open(config_path, 'r') as f:
        return json.load(f)

def design_flight_sequence(config):
    """
    Diseña la secuencia de vuelo del dron basada en la detección de ArUco markers.
    Asume un pasillo lineal con estanterías espaciadas uniformemente.
    """
    assignments = config['assignments']
    shelves = list(assignments.keys())

    # Parámetros del pasillo (basados en el plano aproximado)
    # Asumiendo pasillo de ~14m de largo, estanterías cada ~0.5m
    start_x = 0.0  # Posición inicial en metros
    shelf_spacing = 0.5  # Distancia entre estanterías en metros
    flight_height = 1.5  # Altura de vuelo en metros
    flight_speed = 0.5  # Velocidad en m/s

    waypoints = []
    for i, shelf in enumerate(shelves):
        x_pos = start_x + i * shelf_spacing
        waypoint = {
            'shelf': shelf,
            'marker_id': assignments[shelf],
            'position': [x_pos, 0.0, flight_height],  # [x, y, z] en metros
            'action': 'take_photo',  # Acción: detectar marcador, tomar foto, enviar posición
            'description': f'Detectar {shelf} (ID {assignments[shelf]}), tomar foto y enviar posición GPS + orientación'
        }
        waypoints.append(waypoint)

    return waypoints

def save_flight_sequence(waypoints, output_path='scripts/flight_sequence.json'):
    """Guarda la secuencia de vuelo en un archivo JSON."""
    with open(output_path, 'w') as f:
        json.dump(waypoints, f, indent=2)
    print(f'Secuencia de vuelo guardada en {output_path}')

if __name__ == "__main__":
    config = load_marker_config()
    waypoints = design_flight_sequence(config)
    save_flight_sequence(waypoints)

    print("Secuencia de vuelo diseñada:")
    for wp in waypoints:
        print(f"- {wp['shelf']}: Posición {wp['position']}, Acción: {wp['action']}")