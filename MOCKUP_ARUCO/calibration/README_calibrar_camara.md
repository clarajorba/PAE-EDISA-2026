# calibrar_camara.py — Guía de uso

Script de calibración para la **Raspberry Pi Camera Module 2 NoIR** conectada a una **Raspberry Pi 4 Model B**. Genera los parámetros intrínsecos de la cámara (`camera_matrix` y `dist_coeffs`) necesarios para el detector 3D de ArUco.

---

## Hardware necesario

| Elemento | Detalles |
|---|---|
| Raspberry Pi 4 Model B | Con Raspberry Pi OS instalado (Bullseye o Bookworm) |
| Camera Module 2 NoIR | Conectada al puerto CSI mediante el cable ribbon |
| Monitor + teclado | Conectados a la Pi directamente, **o** conexión SSH con X11 |
| Tablero de ajedrez impreso | 8×8 cuadrados (ver sección más abajo) |
| Regla | Para medir el tamaño real de un cuadrado impreso |

---

## Paso 1 — Conectar la cámara a la Raspberry Pi

1. **Apaga** la Raspberry Pi antes de conectar la cámara.
2. Localiza el puerto **CSI** (ranura de plástico entre el puerto HDMI y el jack de audio).
3. Levanta suavemente el pestillo del conector CSI.
4. Inserta el cable ribbon de la cámara con los **contactos metálicos mirando hacia el conector HDMI** (hacia la placa, no hacia afuera).
5. Baja el pestillo para fijarlo.
6. Enciende la Raspberry Pi.

---

## Paso 2 — Habilitar la cámara en la Raspberry Pi

Abre un terminal en la Raspberry Pi y ejecuta:

```bash
sudo raspi-config
```

Navega con las flechas del teclado:

```
Interface Options  →  Camera  →  Yes  →  OK  →  Finish
```

Cuando pregunte si quieres reiniciar, selecciona **Yes**.

> En **Raspberry Pi OS Bookworm** la cámara suele estar habilitada por defecto. Si tienes Bookworm, puedes saltarte este paso y verificar directamente en el Paso 3.

### Verificar que la cámara funciona

Después de reiniciar, comprueba que la cámara está activa:

```bash
libcamera-hello --timeout 3000
```

Debería abrirse una ventana de previsualización durante 3 segundos. Si ves la imagen de la cámara, todo está correcto. Si da error, revisa la conexión del cable ribbon.

---

## Paso 3 — Instalar las dependencias

Abre un terminal en la Raspberry Pi y ejecuta los siguientes comandos **en orden**:

### Actualizar el sistema

```bash
sudo apt update && sudo apt upgrade -y
```

### Instalar picamera2 y OpenCV

```bash
sudo apt install -y python3-picamera2 python3-opencv python3-numpy
```

> `picamera2` es la librería oficial de Raspberry Pi para acceder a la Camera Module 2 con el stack moderno `libcamera`. No uses `opencv-python` de pip en la Pi — usa el paquete `apt` para evitar conflictos con libcamera.

### Verificar la instalación

```bash
python3 -c "from picamera2 import Picamera2; print('picamera2 OK')"
python3 -c "import cv2; print('OpenCV OK:', cv2.__version__)"
python3 -c "import numpy; print('NumPy OK:', numpy.__version__)"
```

Los tres comandos deben imprimir `OK` sin errores.

---

## Paso 4 — Transferir el proyecto a la Raspberry Pi

Si el proyecto está en tu ordenador, cópialo a la Pi con `scp`. Desde tu Mac/PC:

```bash
scp -r /ruta/local/MOCKUP_ARUCO pi@<IP_DE_LA_PI>:/home/pi/MOCKUP_ARUCO
```

Sustituye `<IP_DE_LA_PI>` por la dirección IP de tu Raspberry Pi (puedes verla con `hostname -I` en la Pi).

Si ya tienes el proyecto en la Pi, asegúrate de estar en el directorio correcto:

```bash
cd /home/pi/MOCKUP_ARUCO
```

---

## Paso 5 — Preparar el tablero de ajedrez

El script detecta un tablero con **7×7 esquinas interiores**, que equivale a un tablero de **8×8 cuadrados**.

### Descargar el patrón

1. Ve a [https://calib.io/pages/camera-calibration-pattern-generator](https://calib.io/pages/camera-calibration-pattern-generator)
2. Configura:
   - **Rows:** 8
   - **Columns:** 8
   - Formato: **PDF**
3. Descarga e imprime en **A4**, asegurándote de que la impresora **no escala** el contenido (opción "tamaño real" o "100%").

### Medir el cuadrado

Después de imprimir, **mide con regla** el lado de uno de los cuadrados en metros.

Abre el script y edita la línea 48:

```python
SQUARE_SIZE = 0.025  # cámbialo por tu medida real en metros
```

Por ejemplo:
- Si el cuadrado mide 2.5 cm → `SQUARE_SIZE = 0.025`
- Si mide 3.0 cm → `SQUARE_SIZE = 0.030`

> Esta medición afecta directamente a la precisión de la estimación de posición 3D. Mídela con cuidado.

---

## Paso 6 — Ejecutar el script

### Opción A — Con monitor conectado a la Pi

Abre un terminal directamente en la Raspberry Pi y ejecuta:

```bash
cd /home/pi/MOCKUP_ARUCO
python3 calibration/calibrar_camara.py
```

### Opción B — Por SSH con pantalla gráfica (X11 forwarding)

Desde tu Mac o PC, conecta por SSH habilitando X11:

```bash
ssh -X pi@<IP_DE_LA_PI>
```

Una vez dentro de la Pi:

```bash
cd /home/pi/MOCKUP_ARUCO
python3 calibration/calibrar_camara.py
```

La ventana de vídeo aparecerá en tu pantalla local aunque el script corra en la Pi.

> En macOS necesitas tener instalado [XQuartz](https://www.xquartz.org/) para que funcione X11 forwarding.

---

## Paso 7 — Proceso de calibración

Al ejecutar el script se abre una ventana con el feed en directo de la Camera Module 2 NoIR.

### Indicadores en pantalla

| Mensaje | Color | Significado |
|---|---|---|
| `Buscando tablero...` | Naranja | Tablero no visible o no detectado |
| `TABLERO DETECTADO - pulsa ESPACIO` | Verde | Tablero reconocido, listo para capturar |
| `Capturas: X/15` | Naranja/Verde | Progreso de capturas |
| `Suficientes! Pulsa 'q' para calibrar` | Verde azulado | Puedes terminar |

### Teclas

| Tecla | Acción |
|---|---|
| `ESPACIO` | Captura el frame (solo si el tablero está detectado — texto verde) |
| `q` | Finaliza y lanza la calibración (solo si tienes ≥ 15 capturas) |
| `Ctrl+C` | Aborta el script en cualquier momento |

### Cómo mover el tablero para una buena calibración

Necesitas **mínimo 15 capturas**, idealmente 20-30. En cada captura coloca el tablero en una posición diferente. Intenta cubrir estas posiciones:

1. Centro de la imagen, tablero de frente y recto
2. Esquina superior izquierda de la imagen
3. Esquina superior derecha
4. Esquina inferior izquierda
5. Esquina inferior derecha
6. Inclinado ~30° hacia la izquierda
7. Inclinado ~30° hacia la derecha
8. Inclinado ~30° hacia arriba (parte superior del tablero más lejos)
9. Inclinado ~30° hacia abajo
10. Rotado ~45° en el plano de la imagen
11. Más cerca de la cámara (tablero grande en pantalla)
12. Más lejos (tablero pequeño en pantalla)
13–30. Combinaciones de las anteriores en distintas zonas de la imagen

> Espera el **flash verde** de confirmación antes de mover el tablero a la siguiente posición.

---

## Paso 8 — Resultado

Cuando pulses `q` con suficientes capturas, el script:

1. **Imprime en el terminal** los parámetros calculados y el bloque de código listo para pegar.
2. **Guarda el resultado** automáticamente en:
   ```
   MOCKUP_ARUCO/config/camera_calibration.json
   ```

### Interpretación del error de reproyección

| Valor | Calidad |
|---|---|
| < 0.5 px | Excelente |
| 0.5 – 1.0 px | Bueno, suficiente para usar |
| > 1.0 px | Repetir con más capturas o mejor iluminación |

---

## Paso 9 — Copiar los valores a detector_3d.py

El script imprime directamente el bloque de código que tienes que copiar y pegar en la clase `AppConfig` de [detector_3d.py](../detector_3d.py). Ejemplo de salida:

```python
camera_matrix: np.ndarray = field(default_factory=lambda: np.array([
    [   620.00,      0.00,    640.00],
    [     0.00,    620.00,    360.00],
    [     0.00,      0.00,      1.00],
], dtype=np.float64))

dist_coeffs: np.ndarray = field(default_factory=lambda: np.array([
    [-0.123456],
    [ 0.045678],
    [ 0.000123],
    [-0.000456],
    [ 0.012345],
], dtype=np.float64))
```

Sustituye los valores actuales en `detector_3d.py` por los que ha generado tu calibración.

---

## Solución de problemas

### `ModuleNotFoundError: No module named 'picamera2'`

```bash
sudo apt install -y python3-picamera2
```

Si ya está instalado y sigue fallando, asegúrate de usar `python3` (no `python`):

```bash
python3 calibration/calibrar_camara.py
```

### `libcamera-hello` da error / cámara no detectada

- Revisa que el cable ribbon esté bien insertado (contactos hacia la placa).
- En Bullseye: ejecuta `sudo raspi-config` y confirma que la cámara está habilitada.
- En Bookworm: comprueba `/boot/firmware/config.txt` y verifica que tiene `camera_auto_detect=1`.

```bash
grep camera /boot/firmware/config.txt
```

### La ventana de vídeo no se abre (por SSH sin X11)

Asegúrate de conectarte con `ssh -X` (no solo `ssh`). En macOS instala **XQuartz** primero.

### El tablero no se detecta (siempre en naranja)

- Asegúrate de que el tablero impreso es de **8×8 cuadrados** (7×7 esquinas interiores). Un tablero distinto no funcionará.
- Mejora la iluminación — la Camera Module 2 NoIR es muy sensible al infrarrojo; en interior puede ayudar añadir luz blanca directa sobre el tablero.
- Mantén el tablero completamente dentro del encuadre, sin partes cortadas.
- Evita reflejos sobre el papel (ángulo ligeramente oblicuo puede ayudar).

### `Necesitas al menos 15 capturas`

Sigue capturando sin salir. Solo pulsa `q` cuando el contador llegue a 15 o más.

### La calibración tarda mucho

Es normal en la Raspberry Pi 4 — el cálculo puede tardar entre 10 y 30 segundos dependiendo del número de capturas. Espera sin cerrar el terminal.
