# Proyecto: Control de Dron con ArUco Markers en Almacén - PX4 + Raspberry Pi

## 📋 Descripción General

Este proyecto implementa un **sistema autónomo 3D** para que un dron recorra un almacén con estanterías multiuso, utilizando **marcadores ArUco para visión** y **navegación por waypoints locales sin GPS**. El sistema está diseñado para ejecutarse en una **Raspberry Pi** conectada a una **Pixhawk** con PX4.

### 🔑 Características Clave
- ✅ **196 Waypoints 3D**: 28 estanterías × 7 pisos/niveles
- ✅ **Sin GPS**: Navegación exclusivamente con coordenadas locales y odometría
- ✅ **Visión ArUco**: 196 marcadores únicos para identificación precisa
- ✅ **Foto por Marker**: Una foto automática al detectar cada marcador
- ✅ **Reportes Locales**: Coordenadas (x,y,z) en metros sin dependencia de GPS
- ✅ **Tiempo ~30min**: Cobertura completa en aproximadamente 25-35 minutos

### 🎯 Objetivo
El dron debe volar automáticamente por un pasillo con 28 estanterías y 7 niveles por estantería, detectando marcadores ArUco únicos en cada posición de estantería-piso, tomando fotos y reportando coordenadas locales exactas.

### 🏗️ Arquitectura
- **Pixhawk + PX4**: Autopilot que maneja vuelo, navegación y estabilidad
- **Raspberry Pi**: Companion computer que ejecuta detección de ArUco y control de misión
- **Cámara**: Conectada a Raspberry Pi para visión computacional
- **Comunicación**: MAVLink entre Raspberry Pi y Pixhawk
- **Navegación**: Basada en waypoints predefinidos (sin GPS), utilizando odometría y IMU para posicionamiento relativo

---

## 📁 Estructura del Proyecto

```
planos_aruco/
├── config/
│   └── markers_config.json          # Configuración de marcadores ArUco
├── scripts/
│   ├── generate_markers.py          # Genera imágenes de marcadores
│   ├── drone_flight_sequence.py     # Diseña secuencia de vuelo
│   ├── flight_sequence.json         # Waypoints generados
│   ├── drone_aruco_detector.py      # Detector básico (sin PX4)
│   ├── px4_aruco_controller.py      # Controlador principal PX4 + ArUco
│   └── __temp_calc_path.py          # Calcula distancias del recorrido
├── photos/                          # Fotos tomadas automáticamente
├── requirements.txt                 # Dependencias Python
└── README.md                        # Este archivo
```

### 📄 Descripción de Archivos

#### Configuración
- **`config/markers_config.json`**: Define los 196 marcadores ArUco (IDs 1-196) asignados a posiciones E1-P0 ... E28-P6, diccionario DICT_5X5_100, tamaño 100mm.

#### Scripts
- **`scripts/generate_markers.py`**: Genera imágenes PNG de los 196 marcadores ArUco (DICT_5X5_100, 100mm × 100mm).
- **`scripts/drone_flight_sequence.py`**: Calcula la secuencia de vuelo 3D completa con 196 waypoints y alturas para cada nivel.
- **`scripts/generate_flight_sequence.py`**: Script alternativo para generar secuencia de vuelo (usa paths relativos).
- **`scripts/flight_sequence.json`**: Archivo JSON con los 196 waypoints (id, shelf_floor, marker_id, position[x,y,z], action, description).
- **`scripts/drone_aruco_detector.py`**: Versión básica de detección ArUco sin integración PX4 (para pruebas).
- **`scripts/px4_aruco_controller.py`**: **Código principal** - integra PX4 + MAVSDK con detección ArUco en tiempo real, foto por marker detectado, reportes de coordenadas locales.
- **`scripts/__temp_calc_path.py`**: Utilidad para calcular distancias totales y métricas exactas del recorrido de vuelo.

#### Otros
- **`photos/`**: Directorio donde se guardan las fotos tomadas con timestamp.
- **`requirements.txt`**: Librerías necesarias: `opencv-python`, `numpy`, `mavsdk`.

---

## 🔧 Configuración de Hardware

### Componentes Necesarios
1. **Raspberry Pi 4** (recomendado) con Raspberry Pi OS
2. **Pixhawk** con PX4 firmware
3. **Cámara**: USB Webcam o Raspberry Pi Camera Module
4. **Marcadores ArUco**: 28 marcadores impresos (100mm x 100mm)

### Conexión Física
1. **Raspberry Pi ↔ Pixhawk**:
   - Conectar UART de Raspberry Pi (GPIO 14/15) a TELEM2 de Pixhawk
   - Alimentación: Raspberry Pi puede alimentarse desde Pixhawk o batería separada

2. **Cámara ↔ Raspberry Pi**:
   - USB: Conectar webcam USB
   - CSI: Usar Raspberry Pi Camera Module en puerto CSI

3. **Marcadores**:
   - Imprimir marcadores generados
   - Pegar uno en cada estantería (E1-E28) a altura visible

---

## 🚀 Instalación y Configuración

### 1. Preparar Raspberry Pi

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade

# Instalar Python y pip
sudo apt install python3 python3-pip

# Instalar dependencias del proyecto
pip3 install -r requirements.txt
```

### 2. Configurar PX4 en Pixhawk

#### Opción A: PX4 Firmware (QGroundControl)
1. Instalar QGroundControl en tu PC
2. Conectar Pixhawk y flashear PX4 stable
3. Configurar parámetros:
   - `MAV_1_CONFIG = TELEM2` (para companion computer)
   - `MAV_1_MODE = Onboard`
   - `MAV_1_RATE = 100000` (baudrate)
   - `SER_TEL2_BAUD = 921600`

#### Opción B: PX4 SITL (Simulador - para pruebas)
```bash
# En PC con Ubuntu
sudo apt install px4-simulink
make px4_sitl jmavsim
```

### 3. Configurar MAVLink en Raspberry Pi

```bash
# Configurar serial (ajustar /dev/ttyAMA0 según tu puerto)
sudo raspi-config  # Habilitar serial
```

### 4. Calibrar Cámara

```bash
# Ejecutar calibración de cámara (necesitas patrón de calibración)
python3 -c "
import cv2
# Código de calibración aquí
"
```

Actualizar `camera_matrix` y `dist_coeffs` en `px4_aruco_controller.py` con tus valores calibrados.

---

## 🎮 Cómo Ejecutar

### Prueba Básica (sin dron)
```bash
cd planos_aruco
python3 scripts/drone_aruco_detector.py
```
Esto abre la cámara y detecta ArUco en tiempo real (útil para probar visión).

### Ejecución Completa con PX4
```bash
cd planos_aruco
python3 scripts/px4_aruco_controller.py
```

### Qué hace el código:
1. **Conecta** a Pixhawk via MAVLink (921600 baud)
2. **Sube misión** (196 waypoints con coordenadas locales) a PX4
3. **Inicia vuelo** autónomo basado en waypoints
4. **Detecta ArUco** en tiempo real mientras vuela
5. **Toma una foto la primera vez que detecta cada marcador** (`E1-P0`, `E1-P1`, ..., `E28-P6`)
6. **Reporta** coordenadas locales del waypoint actual + identificador del marcador detectado
7. **Evita duplicados**: una única foto por marcador durante toda la misión

---

## ⏱️ Estimación de Tiempo de Misión

### Distancia Total del Recorrido
- **196 waypoints** en matriz 3D: 28 estanterías × 7 pisos
- **Patrón de vuelo**: Secuencial (E1→E28 × P0→P6)
- **Distancia total aproximada**: ~570 metros en el layout de ejemplo del script
- **Distancia promedio entre waypoints**: ~2.9 metros en el layout de ejemplo del script

### Desglose de Tiempos
- **Velocidad de vuelo**: 0.5 m/s (configurada en `flight_sequence.json`)
- **Tiempo de vuelo puro**: ~19 minutos (569m ÷ 0.5 m/s) en el layout de ejemplo
- **Tiempo por foto/reporte**: ~2-5 segundos por marcador × 196 = 6-16 minutos
- **Transiciones y estabilización**: ~2-3 minutos adicionales (márgenes de seguridad)
- **Tiempo total estimado**: **25-35 minutos**

### Cálculo Gráfico
```
E1 → E2 → ... → E28  (X: 0.0→75.4m para layout real con 2.80m por estantería)
P0 → P1 → ... → P6   (Z: 0.1→10.5m)

Cada transición vertical:
△Z = 1.6m, S = 0.5 m/s → t ≈ 3.2s

Cada transición horizontal:
△X = 2.8m (layout real), S = 0.5 m/s → t ≈ 5.6s
```

### Herramienta de Cálculo
- **`scripts/__temp_calc_path.py`**: Calcula distancias exactas y métricas
- Ejecuta: `python3 scripts/__temp_calc_path.py`

> **⚠️ Nota Importante**: Esta estimación asume:
> - Detección perfecta de cada marcador
> - Sin fallos de comunicación
> - Vuelo estable sin correcciones excesivas
> - Velocidad constante de 0.5 m/s
>
> En vuelo real puede variar ±5 minutos por condiciones de iluminación, interferencias o ajustes dinámicos.

---

## 🔍 Parámetros a Configurar

### En `px4_aruco_controller.py`:
```python
# Conexión al dron
connection_string = "serial:///dev/ttyAMA0:921600"  # Para UART (Raspberry Pi)
# o
connection_string = "udp://:14540"  # Para UDP (Simulador SITL)

# Matriz de cámara (¡CALIBRAR en tu entorno!)
self.camera_matrix = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=np.float32)

# Coeficientes de distorsión (calibrados con tu cámara)
self.dist_coeffs = np.array([0.1, -0.2, 0, 0], dtype=np.float32)

# Índice de cámara
cap = cv2.VideoCapture(0)  # Cambiar si tienes múltiples cámaras

# Velocidad de vuelo
speed = 0.5  # m/s (configurable en flight_sequence.json)
```

### Waypoints Locales
Los waypoints están definidos en coordenadas locales (x, y, z) relativas al punto de origen:
- **X**: 0.0 a 75.4 metros si se usa el layout real de 2.80m por estantería (28 estanterías)
- **Y**: 1.0 metro (posición fija en el pasillo, 1m frente a la estantería)
- **Z**: 0.1, 1.7, 3.4, 5.1, 6.8, 8.5, 10.5 metros (7 alturas para los 7 pisos)

**Nota**: El dron navega sin GPS, únicamente usando waypoints predefinidos en coordenadas locales con odometría e IMU para posicionamiento relativo.

> **Importante**: los scripts ahora usan 2.8m entre estanterías para coincidir con el plano real. Si usas el layout original, la distancia total X será 0.0 a 75.4 metros.

---

## 🐛 Troubleshooting

### Problema: No conecta a Pixhawk
```bash
# Verificar conexión serial
ls /dev/tty*
# Verificar PX4 logs en QGroundControl
```

### Problema: No detecta ArUco
- Verificar iluminación
- Ajustar parámetros de detección en `self.parameters`
- Calibrar cámara correctamente
- Verificar tamaño de marcadores (100mm)

### Problema: Fotos no se guardan
```bash
# Crear directorio photos
mkdir photos
# Verificar permisos
chmod 755 photos
```

### Problema: MAVSDK no instala
```bash
# Instalar dependencias del sistema
sudo apt install libgstreamer1.0-dev libgstreamer-plugins-base1.0-dev
pip3 install -r requirements.txt
```

### Logs y Debugging
```bash
# Ejecutar con logs
python3 scripts/px4_aruco_controller.py 2>&1 | tee debug.log
```

---

## 📊 Flujo de Datos

1. **Raspberry Pi** detecta marcador ArUco en vuelo
2. **Identifica identificador** (E1-P0, E2-P3, etc.)
3. **Toma foto** en el momento de detección
4. **Reporta coordenadas locales** (x, y, z) del waypoint actual
5. **Genera reporte**:
   ```json
   {
     "shelf_floor": "E1-P0",
     "timestamp": 1640995200.0,
     "local_position": {"x": 0.0, "y": 0.0, "z": 0.1},
     "aruco_position": [0.0, 0.0, 0.0],
     "photo_path": "photos/E1-P0_1640995200.jpg"
   }
   ```
6. **Continúa al siguiente waypoint** automáticamente

---

## 🗺️ Sistema de Navegación Local (Sin GPS)

El dron navegue basándose **exclusivamente en waypoints locales definidos** sin dependencia de GPS:

### Cómo Funciona
1. **PX4 gestiona vuelo** entre waypoints usando odometría + IMU
2. **196 waypoints** pre-calculados con coordenadas locales (x, y, z) en metros
3. **Raspberry Pi monitoriza** detección de ArUco en paralelo
4. **Al detectar marker**: toma foto y reporta identificador + coordenadas del waypoint actual
5. **Odometría**: acumula desplazamiento desde el punto de origen

### Ventajas vs GPS
- ✅ **Independencia**: Funciona en interiores sin señal GPS
- ✅ **Precisión**: Coordenadas exactas preconfiguradas
- ✅ **Rapidez**: Sin esperar a fix GPS
- ✅ **Robustez**: Sin interferencias electromagnéticas
- ❌ **Limitación**: Requiere buena calibración IMU/odometría

### Calibración Necesaria
- IMU: Auto-calibración PX4 en bootup
- Odometría: Verificar en QGroundControl con flight logs
- Cámara: Calibración con patrón de tablero de ajedrez (imprescindible)

---

## 🎯 Próximos Pasos

1. **Generar marcadores ArUco** - Ejecutar `generate_markers.py` para crear 196 imágenes PNG
2. **Imprimir y colocar marcadores** - Colocar los 196 marcadores en las estanterías según la configuración (E1-P0 a E28-P6)
3. **Calibrar cámara** - Ejecutar calibración de cámara en el entorno real
4. **Configurar hardware** - Conexión Raspberry Pi ↔ Pixhawk ↔ Cámara
5. **Probar en tierra** - Dron en suelo con detección de ArUco activa
6. **Vuelo de prueba** - Primer vuelo en área segura (sin carga útil)
7. **Validar coordinación** - Verificar que el dron detecta cada marker y toma la foto correctamente
8. **Integración de comunicación** - Añadir MQTT/WiFi para transmisión de reportes en tiempo real
9. **Medidas de seguridad** - Implementar RTL (Return to Launch) en caso de error o fallo de comunicación

---

## 📞 Soporte

Si encuentras problemas:
1. Verifica logs de PX4 en QGroundControl
2. Revisa conexión MAVLink con `mavproxy`
3. Prueba componentes individualmente
4. Consulta documentación PX4: https://docs.px4.io/

---

## � Estructura de Datos 3D

### Parrilla de Waypoints
- **Dimensión X (Estanterías)**: 28 estanterías (E1-E28), espaciadas según el plano real
  - Layout real: 2.80m por estantería → X = 0.0 a 75.4 metros
- **Dimensión Y (Pasillo)**: Posición fija
  - Y = 1.0 metro (1m frente a la estantería)
- **Dimensión Z (Alturas)**: 7 niveles por estantería
  - Z = [0.1, 1.7, 3.4, 5.1, 6.8, 8.5, 10.5] metros

### Identificación de Marcadores
Cada marker se identifica como **E[1-28]-P[0-6]**:
- **E**: Estantería (E1 a E28)
- **P**: Piso/nivel (P0 a P6)
- **ID ArUco**: Número único 1-196 asignado secuencialmente

Ejemplo: `E5-P3` = Estantería 5, Piso 3 = Marker ID 38 = Coordenada [2.0, 0.0, 5.1]

## 📝 Notas Importantes

- **Seguridad**: Siempre probar en modo seguro primero
- **Batería**: Asegurar alimentación suficiente para Raspberry Pi (mínimo 2A @5V)
- **Sin GPS**: El dron navega únicamente con waypoints locales y odometría/IMU
- **Calibración**: IMPRESCINDIBLE calibrar la cámara para detección precisa de ArUco
- **Iluminación**: Los marcadores ArUco requieren buena iluminación
- **Licencia**: Este código es para uso educativo/research

¡El sistema está listo para revolucionar la inspección de almacenes con drones autónomos! 🚁📦