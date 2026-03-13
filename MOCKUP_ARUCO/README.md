# Sistema de Localización de Drones mediante ArUco en Almacén

Programa de visión por computadora que identifica marcadores **ArUco** 
instalados en un almacén para que un dron se ubique a sí mismo en tiempo real.

---

## Arquitectura del sistema

```
main.py                    ← Punto de entrada y bucle principal
│
├── src/
│   ├── aruco_detector.py  ← Detección de marcadores + estimación de pose
│   ├── warehouse_map.py   ← Mapa del almacén (posiciones conocidas de marcadores)
│   ├── localization.py    ← Motor de localización 3-D + filtro de Kalman
│   ├── visualizer.py      ← Visualización en tiempo real (cámara + mapa cenital)
│   └── camera_calibration.py ← Calibración de cámara con tablero de ajedrez
│
├── config/
│   ├── warehouse_config.json ← Dimensiones del almacén y posición de marcadores
│   └── camera_params.json    ← Parámetros intrínsecos de la cámara
│
├── scripts/
│   └── generate_markers.py   ← Genera las imágenes PNG para imprimir
│
└── assets/markers/           ← Imágenes generadas de los marcadores
```

---

## Instalación rápida

```bash
pip install -r requirements.txt
```

---

## Uso

### 1. Generar e imprimir los marcadores

```bash
python scripts/generate_markers.py --sheet
```
Genera en `assets/markers/` un PNG por marcador y una hoja completa para impresión.

### 2. Calibrar la cámara *(solo la primera vez)*

```bash
python -m src.camera_calibration --source 0 --output config/camera_params.json
```
Usa un tablero de ajedrez (9×6 cuadrados de 2.5 cm). Mueve el tablero ante la 
cámara; las capturas se realizan automáticamente cuando el tablero está inmóvil.

### 3. Configurar el almacén

Edita `config/warehouse_config.json` con las **dimensiones reales** y la 
**posición exacta** de cada marcador instalado en el almacén.

### 4. Ejecutar el sistema

```bash
# Con webcam real del dron
python main.py --source 0

# Con archivo de vídeo grabado
python main.py --source vuelo.mp4

# Modo simulación (sin cámara)
python main.py --simulate

# Guardar log de poses en pose_log.json
python main.py --simulate --save-log
```

### Controles durante la ejecución

| Tecla | Acción |
|-------|--------|
| `q`   | Salir  |
| `r`   | Borrar trayectoria del mapa |

---

## Sistema de coordenadas

```
        Y (Norte)
        ↑
        │
O───────┼────────── X (Este)
(0,0,0) │
        │
Origen: esquina inferior-izquierda del almacén
Z = altura (metros)
```

---

## Cómo funciona la localización

1. **Detección**: OpenCV detecta los marcadores ArUco en el frame de la cámara.
2. **Pose relativa**: Para cada marcador, `solvePnP` calcula su posición y 
   orientación respecto a la cámara (tvec, rvec).
3. **Inversión de pose**: Se invierte la transformación para obtener la posición 
   de la cámara (dron) relativa al marcador.
4. **Transformación al mundo**: Usando la posición conocida del marcador en el 
   mapa, se obtiene la posición del dron en coordenadas globales.
5. **Fusión multi-marcador**: Con ≥4 marcadores se usa `solvePnPRansac` global; 
   con menos, se aplica media ponderada por distancia.
6. **Filtro de Kalman**: Suaviza la estimación y predice la posición entre frames.

---

## Marcadores del almacén (configuración por defecto)

| ID | Posición (m)        | Ubicación           |
|----|---------------------|---------------------|
| 0  | (0, 0, 2.5)         | Esquina NO – Pared N |
| 1  | (10, 0, 2.5)        | Centro – Pared N     |
| 2  | (20, 0, 2.5)        | Esquina NE – Pared N |
| 3  | (20, 7.5, 2.5)      | Centro – Pared E     |
| 4  | (20, 15, 2.5)       | Esquina SE – Pared S |
| 5  | (10, 15, 2.5)       | Centro – Pared S     |
| 6  | (0, 15, 2.5)        | Esquina SO – Pared S |
| 7  | (0, 7.5, 2.5)       | Centro – Pared O     |
| 8  | (10, 7.5, 5.0)      | Centro – Techo       |
| 9–12 | Zonas A-D        | Techo               |

Almacén de **20 × 15 × 5 m**. Marcadores de **15 cm** de lado.
