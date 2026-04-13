# Proyecto: Control de Dron con ArUco Markers en Almacén - PX4 + Raspberry Pi

## 📋 Descripción General

Este proyecto implementa un sistema autónomo para que un dron recorra un pasillo de almacén utilizando marcadores ArUco para navegación precisa y captura de imágenes. El sistema está diseñado para ejecutarse en una **Raspberry Pi** conectada a una **Pixhawk** con PX4.

### 🎯 Objetivo
El dron debe volar automáticamente por un pasillo con 28 estanterías, detectando marcadores ArUco únicos en cada una, tomando fotos de las estanterías y reportando posiciones GPS exactas.

### 🏗️ Arquitectura
- **Pixhawk + PX4**: Autopilot que maneja vuelo, navegación y estabilidad
- **Raspberry Pi**: Companion computer que ejecuta detección de ArUco y control de misión
- **Cámara**: Conectada a Raspberry Pi para visión computacional
- **Comunicación**: MAVLink entre Raspberry Pi y Pixhawk

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
│   └── px4_aruco_controller.py      # Controlador principal PX4 + ArUco
├── photos/                          # Fotos tomadas automáticamente
├── requirements.txt                 # Dependencias Python
└── README.md                        # Este archivo
```

### 📄 Descripción de Archivos

#### Configuración
- **`config/markers_config.json`**: Define los 28 marcadores ArUco (IDs 1-28) asignados a estanterías E1-E28, diccionario DICT_5X5_100, tamaño 100mm.

#### Scripts
- **`scripts/generate_markers.py`**: Genera imágenes PNG de los marcadores ArUco para imprimir.
- **`scripts/drone_flight_sequence.py`**: Calcula los waypoints basados en el plano del almacén.
- **`scripts/flight_sequence.json`**: Lista de 28 waypoints con posiciones, acciones y descripciones.
- **`scripts/drone_aruco_detector.py`**: Versión básica de detección ArUco (sin integración PX4).
- **`scripts/px4_aruco_controller.py`**: **Código principal** - integra PX4 con detección ArUco.

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
# Instalar mavproxy (opcional para debugging)
pip3 install mavproxy

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
1. **Conecta** a Pixhawk via MAVLink
2. **Sube misión** (28 waypoints) a PX4
3. **Inicia vuelo** autónomo
4. **Detecta ArUco** mientras vuela
5. **Captura fotos** cuando detecta marcador correcto
6. **Reporta** posición GPS + ArUco

---

## 🔍 Parámetros a Configurar

### En `px4_aruco_controller.py`:
```python
# Conexión al dron
connection_string = "serial:///dev/ttyAMA0:921600"  # Para UART
# o
connection_string = "udp://:14540"  # Para UDP

# Matriz de cámara (¡CALIBRAR!)
self.camera_matrix = np.array([[800, 0, 320], [0, 800, 240], [0, 0, 1]], dtype=np.float32)

# Índice de cámara
cap = cv2.VideoCapture(0)  # Cambiar si tienes múltiples cámaras
```

### Waypoints GPS
Los waypoints actuales usan posiciones relativas. Para vuelo real:
1. Obtener coordenadas GPS del pasillo
2. Actualizar `latitude_deg` y `longitude_deg` en `upload_mission()`

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
pip3 install --upgrade mavsdk
```

### Logs y Debugging
```bash
# Ejecutar con logs
python3 scripts/px4_aruco_controller.py 2>&1 | tee debug.log
```

---

## 📊 Flujo de Datos

1. **Raspberry Pi** detecta marcador ArUco
2. **Calcula pose** (posición x,y,z relativa)
3. **Obtiene GPS** desde Pixhawk via MAVSDK
4. **Toma foto** con timestamp
5. **Genera reporte**:
   ```json
   {
     "shelf": "E1",
     "timestamp": 1640995200.0,
     "gps_position": {"lat": 41.3851, "lon": 2.1734, "alt": 1.5},
     "aruco_position": [0.0, 0.0, 0.0],
     "photo_path": "photos/E1_1640995200.jpg"
   }
   ```

---

## 🎯 Próximos Pasos

1. **Imprimir marcadores** y colocar en estanterías
2. **Calibrar cámara** en el entorno real
3. **Probar en tierra** (dron en suelo, solo detección)
4. **Vuelo de prueba** en área segura
5. **Integrar comunicación** (MQTT/WiFi) para enviar reportes
6. **Añadir seguridad** (RTL en caso de error)

---

## 📞 Soporte

Si encuentras problemas:
1. Verifica logs de PX4 en QGroundControl
2. Revisa conexión MAVLink con `mavproxy`
3. Prueba componentes individualmente
4. Consulta documentación PX4: https://docs.px4.io/

---

## 📝 Notas Importantes

- **Seguridad**: Siempre probar en modo seguro primero
- **Batería**: Asegurar alimentación suficiente para Raspberry Pi
- **GPS**: Necesario para navegación precisa
- **Licencia**: Este código es para uso educativo/research

¡El sistema está listo para revolucionar la inspección de almacenes con drones autónomos! 🚁📦