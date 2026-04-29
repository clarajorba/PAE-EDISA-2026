# 📦 Detector de Cajas de Almacén con GroundingDINO

Herramienta de detección de objetos en imágenes de almacén basada en [GroundingDINO](https://github.com/IDEA-Research/GroundingDINO). Permite detectar cajas de cartón, palés y otros elementos mediante lenguaje natural, con filtrado NMS para eliminar detecciones duplicadas.

---

## 📋 Requisitos previos

- Python 3.10 o superior
- Git
- Conexión a internet (para descargar el modelo, ~660 MB)
- GPU con CUDA (opcional, también funciona en CPU)

---

## 🛠️ Instalación

### 1. Clonar el repositorio

```bash
git clone https://github.com/IDEA-Research/GroundingDINO.git
cd GroundingDINO
```

### 2. Crear y activar el entorno virtual

```bash
python3 -m venv venv
source venv/bin/activate
```

> ⚠️ **Importante:** cada vez que abras una terminal nueva debes activar el entorno antes de ejecutar el script:
> ```bash
> cd GroundingDINO
> source venv/bin/activate
> ```

### 3. Instalar las dependencias

```bash
pip install -e .
pip install -r requirements.txt
```

### 4. Descargar el modelo preentrenado

```bash
mkdir weights
wget --show-progress https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth -P weights/
```

> Si la descarga se interrumpe, puedes reanudarla con `-c`:
> ```bash
> wget -c --show-progress https://github.com/IDEA-Research/GroundingDINO/releases/download/v0.1.0-alpha/groundingdino_swint_ogc.pth -P weights/
> ```

Verifica que el archivo pese aproximadamente **660 MB**:
```bash
du -sh weights/groundingdino_swint_ogc.pth
```

### 5. Copiar el script detector

Coloca el archivo `detector_almacen.py` dentro de la carpeta `deteccion_cajas/`.

---

## 🗂️ Estructura de carpetas

```
deteccion_cajas/
├── weights/
│   └── groundingdino_swint_ogc.pth   ← modelo descargado
├── groundingdino/
│   └── config/
│       └── GroundingDINO_SwinT_OGC.py
├── mis_imagines/                      ← pon aquí tus fotos
├── resultados/                        ← se crea automáticamente
├── detector_almacen.py
└── venv/
```

---

## 🖼️ Añadir imágenes

Crea la carpeta `mis_imagines` si no existe y copia tus fotos del almacén dentro:

```bash
mkdir mis_imagines
cp /ruta/a/tu/foto.jpg mis_imagines/
```

Se admiten los formatos: `.jpg`, `.jpeg`, `.png`, `.bmp`, `.webp`

Puedes poner tantas imágenes como quieras, el script las procesará todas.

---

## ▶️ Ejecutar el detector

Con el entorno virtual activado, ejecuta:

```bash
python detector_almacen.py
```

Verás en la terminal el progreso de cada imagen:

```
⚡ Usando dispositivo: CPU
📦 Cargando modelo...
🖼️  3 imagen(s) encontrada(s)
🔎 Prompt: cardboard box . box . carton . pallet .

🔍 Procesando: foto1.jpg
   Detecciones antes de NMS : 12
   Detecciones después de NMS: 5  (IoU threshold=0.5)
      [1] 'cardboard box'  score=0.712
      [2] 'cardboard box'  score=0.681
   💾 Guardado en: resultados/resultado_foto1.jpg
```

---

## 📊 Ver los resultados

Las imágenes con las detecciones marcadas se guardan automáticamente en la carpeta `resultados/`. Ábrelas con cualquier visor de imágenes.

---

## ⚙️ Ajustar parámetros

Abre `detector_almacen.py` y modifica estos valores según tus necesidades:

| Parámetro | Descripción | Valor por defecto |
|---|---|---|
| `TEXT_PROMPT` | Qué objetos detectar (en inglés, separados por ` . `) | `"cardboard box . box . carton . pallet ."` |
| `BOX_THRESHOLD` | Confianza mínima de detección (0.0 - 1.0). Más bajo = detecta más | `0.20` |
| `TEXT_THRESHOLD` | Confianza mínima del texto (0.0 - 1.0) | `0.15` |
| `IOU_THRESHOLD` | Solapamiento máximo entre cajas antes de eliminar duplicados (0.0 - 1.0) | `0.50` |

**Guía rápida de ajuste:**
- Se pierden cajas → bajar `BOX_THRESHOLD`
- Hay demasiados duplicados → bajar `IOU_THRESHOLD`
- Se eliminan cajas reales que están cerca → subir `IOU_THRESHOLD`

---

## 🌐 Demo online (sin instalación)

Si quieres hacer pruebas rápidas sin instalar nada:

👉 https://huggingface.co/spaces/ShilongLiu/Grounding_DINO_demo




