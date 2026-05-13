import numpy as np
import plotly.graph_objects as go

# 1. Definición del patrón exacto (3 veces la "Z" de tu dibujo)
def generar_mision_exacta():
    mision = []
    for i in range(3):
        x_off = i * 5  # Separación entre estanterías
        z = 1.0        # Altura fija (Movimiento X, Y)
        
        # Puntos de la "Z" siguiendo el orden de las flechas:
        # (A) Arriba-Izquierda -> (B) Arriba-Derecha -> (C) Abajo-Izquierda -> (D) Abajo-Derecha
        p1 = [0 + x_off, 3, z] # Arriba Izq
        p2 = [3 + x_off, 3, z] # Arriba Der
        p3 = [0 + x_off, 0, z] # Abajo Izq
        p4 = [3 + x_off, 0, z] # Abajo Der
        
        mision.append({'pos': p1, 'next': p2}) # Tramo superior
        mision.append({'pos': p2, 'next': p3}) # Tramo diagonal
        mision.append({'pos': p3, 'next': p4}) # Tramo inferior
        
        # Conector a la siguiente Z
        if i < 2:
            mision.append({'pos': p4, 'next': [0 + (i+1)*5, 3, z]})
            
    return mision

mapa = generar_mision_exacta()

# 2. Parámetros Montecarlo
NUM_SIM = 15
RUIDO_LIDAR = 0.15   # Error percepción
RUIDO_MOTOR = 0.10   # Micro-variaciones aleatorias (Error movimiento)
MARGEN = 0.4
DT = 0.1
K_P = 0.7

fig = go.Figure()

# 3. Bucle de Simulación
for s in range(NUM_SIM):
    pos_real = np.array([0.0, 3.0, 1.0]) # Empezamos en la esquina superior izq
    camino = [pos_real.copy()]
    
    for hito in mapa:
        target = np.array(hito['next'])
        for _ in range(150):
            # Percepción con ruido
            percibida = pos_real + np.random.normal(0, RUIDO_LIDAR, 3)
            if np.linalg.norm(percibida - np.array(hito['pos'])) < MARGEN:
                break
            
            # Control proporcional + Ruido de movimiento físico
            error = target - percibida
            vel = K_P * error
            # Aquí es donde el dron genera las microvariaciones aleatorias
            variacion_aleatoria = np.random.normal(0, RUIDO_MOTOR, 3)
            
            pos_real = pos_real + (vel * DT) + (variacion_aleatoria * DT)
            camino.append(pos_real.copy())

    c = np.array(camino)
    # CORRECCIÓN: opacity va fuera de line=dict()
    fig.add_trace(go.Scatter3d(
        x=c[:,0], y=c[:,1], z=c[:,2],
        mode='lines',
        opacity=0.4, 
        line=dict(color='royalblue', width=3),
        name=f'Sim {s}'
    ))

# 4. Ruta Ideal en Negro
ideal_puntos = [mapa[0]['pos']] + [h['next'] for h in mapa]
ideal = np.array(ideal_puntos)
fig.add_trace(go.Scatter3d(
    x=ideal[:,0], y=ideal[:,1], z=ideal[:,2],
    mode='lines+markers',
    line=dict(color='black', width=6),
    marker=dict(size=4, color='red'),
    name='RUTA IDEAL (Z)'
))

# 5. Configuración de vista cenital (Desde arriba)
fig.update_layout(
    scene=dict(
        aspectmode='data',
        xaxis_title="X (Pasillo)",
        yaxis_title="Y (Escaneo)",
        zaxis_title="Z (Altura)",
        camera=dict(eye=dict(x=0, y=0, z=2.5)) # Cámara mirando desde arriba
    ),
    title="Simulación Triple Z: Error Percepción vs Movimiento"
)

fig.write_html("resultado_interactivo.html")
print("Éxito. Abre 'resultado_interactivo.html' para ver el patrón.")