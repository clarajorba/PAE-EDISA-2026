import json

def load_marker_config(config_path='config/markers_config.json'):
    """Carga la configuración de marcadores."""
    with open(config_path, 'r') as f:
        return json.load(f)

def design_flight_sequence(config):
    """
    Diseña la secuencia de vuelo del dron para recorrer todas las estanterías y pisos.
    
    Estructura:
    - 28 estanterías (E1-E28) espaciadas horizontalmente cada 2.8m
    - 7 pisos por estantería (P0-P6) con alturas específicas
    - El dron sube por cada estantería visitando todos los pisos, luego se traslada a la siguiente
    """
    assignments = config['assignments']
    shelves = config['shelves']['ids']
    floors = config['floors']['ids']
    floor_heights = [h / 1000.0 for h in config['floors']['heights_mm']]  # Convertir mm a metros

    # Parámetros del pasillo
    start_x = 0.0  # Posición inicial en metros
    shelf_spacing = 2.8  # Distancia entre estanterías en metros
    y_pos = 1.0  # Posición Y (fija, 1m frente a la estantería)
    flight_speed = 0.5  # Velocidad en m/s

    waypoints = []
    waypoint_id = 0

    # Para cada estantería
    for shelf_idx, shelf in enumerate(shelves):
        x_pos = start_x + shelf_idx * shelf_spacing

        # Para cada piso de esa estantería
        for floor_idx, (floor, height) in enumerate(zip(floors, floor_heights)):
            shelf_floor_key = f"{shelf}-{floor}"

            if shelf_floor_key in assignments:
                marker_id = assignments[shelf_floor_key]

                waypoint = {
                    'id': waypoint_id,
                    'shelf': shelf,
                    'floor': floor,
                    'shelf_floor': shelf_floor_key,
                    'marker_id': marker_id,
                    'position': [x_pos, y_pos, height],  # [x, y, z] en metros
                    'action': 'take_photo',
                    'description': f'Detectar {shelf_floor_key} (ID {marker_id}), tomar foto y enviar coordenadas locales + orientación'
                }
                waypoints.append(waypoint)
                waypoint_id += 1

    return waypoints

def save_flight_sequence(waypoints, output_path='scripts/flight_sequence.json'):
    """Guarda la secuencia de vuelo en un archivo JSON."""
    with open(output_path, 'w') as f:
        json.dump(waypoints, f, indent=2)
    print(f'Secuencia de vuelo guardada en {output_path}')
    print(f'Total de waypoints: {len(waypoints)}')

if __name__ == "__main__":
    config = load_marker_config()
    waypoints = design_flight_sequence(config)
    save_flight_sequence(waypoints)

    print("\nSecuencia de vuelo diseñada:")
    print(f"Total waypoints: {len(waypoints)}")
    print("\nPrimeros 10 waypoints:")
    for wp in waypoints[:10]:
        print(f"  {wp['id']:3d}. {wp['shelf_floor']}: Posición {wp['position']}, ID {wp['marker_id']}")
    print("...")
    print("Últimos 5 waypoints:")
    for wp in waypoints[-5:]:
        print(f"  {wp['id']:3d}. {wp['shelf_floor']}: Posición {wp['position']}, ID {wp['marker_id']}")