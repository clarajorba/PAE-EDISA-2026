# MOCKUP_ARUCO

Sistema modular para deteccion ArUco, localizacion 3D de camara y benchmark de error de pose.

Este proyecto esta pensado para poder trabajar hoy con la camara de un portatil o una Raspberry Pi y, mas adelante, reutilizar la misma base logica en otros dispositivos como un dron. La idea principal es que la parte importante ya no dependa de un mock-up concreto: la camara, el layout de marcadores, la deteccion, la estimacion de pose, la visualizacion y el analisis estadistico estan separados y se pueden ampliar sin rehacer todo el proyecto.

## Que hace el proyecto

El repositorio ofrece tres flujos principales:

1. `camera_setup.py`
   Detecta las camaras del dispositivo, permite previsualizar la seleccionada, cargar o generar una calibracion y guardar un perfil reutilizable.

2. `detector_3d.py`
   Ejecuta el detector ArUco en vivo usando un layout conocido de marcadores y muestra la posicion 3D estimada de la camara en un dashboard visual.

3. `error_benchmark.py`
   Ejecuta un benchmark interactivo y visual para comparar el error de posicion de la camara en dos escenarios:
   - Test 1: un solo marcador ArUco.
   - Test 2: varios marcadores ArUco visibles a la vez.

El benchmark guarda muestras crudas, resumenes numericos y graficas finales para poder analizar si la estimacion mejora con varios marcadores respecto a uno solo.

## Estructura del proyecto

```text
MOCKUP_ARUCO/
├─ detector_3d.py
├─ camera_setup.py
├─ error_benchmark.py
├─ calibration/
│  └─ calibrar_camara.py
├─ config/
│  ├─ markers_3d.json
│  └─ camera_profiles/
├─ mockup_aruco/
│  ├─ app/
│  ├─ camera/
│  ├─ core/
│  └─ viz/
├─ results/
└─ legacy/
```

### Significado de cada carpeta

- `mockup_aruco/app/`
  Flujos de alto nivel que usa el usuario final.

- `mockup_aruco/camera/`
  Descubrimiento de camaras, apertura de video, calibracion y perfiles.

- `mockup_aruco/core/`
  Modelos de datos, deteccion ArUco, estimacion de pose, configuracion y estadistica.

- `mockup_aruco/viz/`
  Dashboard en vivo y graficas finales.

- `config/markers_3d.json`
  Layout base de marcadores que usa el detector en vivo.

- `config/camera_profiles/`
  Perfiles locales guardados con fuente de video, resolucion y calibracion.

- `results/`
  Resultados del benchmark, organizados por timestamp.

- `legacy/`
  Versiones y prototipos antiguos conservados como referencia historica.

## Requisitos

- Python 3.10 o superior recomendado.
- Una camara accesible por OpenCV.
- Marcadores ArUco impresos.
- Para calibracion precisa: un tablero de ajedrez de calibracion impreso y medido.

Dependencias:

```bash
pip install -r requirements.txt
```

Contenido actual de `requirements.txt`:

- `opencv-contrib-python`
- `numpy`
- `matplotlib`

## Instalacion

Desde la carpeta del proyecto:

```bash
cd MOCKUP_ARUCO
pip install -r requirements.txt
```

En Windows, si `python` no apunta bien, puedes usar:

```bash
py -3 -m pip install -r requirements.txt
```

## Flujo recomendado de uso

El flujo recomendado para empezar desde cero es este:

1. Configurar la camara.
2. Calibrar la camara o cargar una calibracion existente.
3. Guardar un perfil.
4. Probar el detector en vivo.
5. Ejecutar el benchmark de error con uno y varios marcadores.

En resumen:

```bash
python camera_setup.py
python detector_3d.py
python error_benchmark.py
```

## 1. Configurar la camara

Archivo:

```bash
python camera_setup.py
```

### Que hace

El asistente de camara:

- busca camaras disponibles en el dispositivo,
- muestra la resolucion y el backend detectado,
- te deja escribir manualmente un indice o ruta si hace falta,
- abre una vista previa,
- te permite confirmar la camara correcta,
- te deja cargar una calibracion existente o generar una nueva,
- guarda todo en un perfil reutilizable dentro de `config/camera_profiles/`.

### Flujo esperado

Al arrancar, el programa:

1. Lista las camaras detectadas.
2. Te pide la fuente de camara.
3. Abre una vista previa.
4. En la vista previa:
   - pulsa `s` para confirmar la camara,
   - pulsa `q` para cancelar.
5. Te pide un nombre de perfil.
6. Te pregunta que hacer con la calibracion:
   - usar una calibracion existente,
   - calibrar ahora con tablero,
   - guardar sin calibracion.

### Donde se guarda el perfil

Cada perfil se guarda como:

```text
config/camera_profiles/<nombre_del_perfil>.json
```

Ese perfil guarda:

- fuente de video,
- ancho y alto,
- FPS objetivo,
- notas,
- calibracion asociada, si existe.

### Recomendacion importante

Para el benchmark de error es muy recomendable usar una camara calibrada. Sin calibracion, la pose puede salir, pero la precision sera peor y las conclusiones sobre el error seran menos fiables.

## 2. Calibrar la camara

Hay dos formas:

### Opcion A. Desde `camera_setup.py`

Es la mas recomendable porque deja el perfil preparado en un solo flujo.

### Opcion B. Desde la ruta historica

```bash
python calibration/calibrar_camara.py
```

Este script mantiene compatibilidad con la organizacion anterior y genera:

```text
config/camera_calibration.json
```

### Como se calibra

La calibracion usa un tablero de ajedrez. Durante el proceso:

- se abre la camara,
- se detectan las esquinas del tablero,
- pulsas `ESPACIO` para guardar capturas utiles,
- pulsas `q` para terminar cuando tengas suficientes.

### Recomendaciones para calibrar bien

- Usa buena iluminacion.
- Evita reflejos fuertes.
- Mueve el tablero por toda la imagen.
- Inclinalo y rotalo en distintos angulos.
- Mide bien el lado real de cada cuadrado.
- Toma al menos 15 capturas buenas.

## 3. Ejecutar el detector 3D en vivo

Archivo principal:

```bash
python detector_3d.py
```

### Para que sirve

Sirve para comprobar rapidamente que:

- la camara esta bien configurada,
- la calibracion es usable,
- el layout de marcadores es correcto,
- la pose 3D se esta estimando de forma razonable.

### Que muestra por pantalla

El detector enseña un dashboard con:

- la imagen de la camara anotada,
- los ArUco detectados,
- un mapa de referencias,
- la posicion estimada de la camara,
- la orientacion aproximada,
- el metodo usado y el error de reproyeccion.

### Controles

- `q`: salir

### Layout usado

Por defecto usa:

```text
config/markers_3d.json
```

Ese archivo define:

- nombre del espacio,
- diccionario ArUco,
- tamano del marcador,
- posiciones 3D conocidas de los marcadores.

### Opciones avanzadas

El detector tambien acepta argumentos:

```bash
python detector_3d.py --layout config/markers_3d.json --profile mi_camara
```

Argumentos disponibles:

- `--layout`: JSON con el layout de marcadores.
- `--profile`: nombre o ruta del perfil de camara.
- `--source`: indice o ruta de video.
- `--calibration`: JSON de calibracion.
- `--width`: ancho objetivo.
- `--height`: alto objetivo.
- `--fps`: FPS objetivo.

Ejemplo sin perfil, indicando fuente y calibracion:

```bash
python detector_3d.py --source 0 --calibration config/camera_calibration.json
```

## 4. Ejecutar el benchmark de error

Archivo principal:

```bash
python error_benchmark.py
```

Este es el programa mas importante del proyecto si lo que quieres es responder a la pregunta:

> La posicion de la camara se estima con menos error viendo un solo ArUco o viendo varios a la vez.

### Que hace el benchmark

El programa construye una sesion completa de analisis con dos tests:

#### Test 1. Un solo marcador

Te pide:

- diccionario ArUco,
- tamano real del marcador,
- ID del marcador,
- duracion del test,
- posicion esperada de la camara en `x, y, z`.

Internamente crea un layout con un unico marcador en el origen.

#### Test 2. Varios marcadores

Te pide:

- si quieres reutilizar diccionario y tamano del test 1,
- numero de marcadores,
- IDs de los marcadores,
- distribucion de marcadores:
  - en rejilla XY,
  - o manual,
- posicion esperada de la camara,
- duracion,
- minimo de marcadores visibles para aceptar una muestra.

### Flujo visual del benchmark

Para cada test, el programa sigue esta secuencia:

1. Vista previa del test.
2. Plano cenital del montaje.
3. Comprobacion visual de los IDs visibles.
4. Confirmacion del usuario con `ESPACIO`.
5. Cuenta atras `3, 2, 1`.
6. Captura durante el tiempo definido.
7. Calculo online de media, desviacion y error instantaneo.
8. Guardado de resultados.
9. Apertura de la grafica del test.

Al finalizar los dos tests, genera una grafica extra de comparacion.

### Controles durante el benchmark

En la vista previa:

- `ESPACIO`: iniciar el test.
- `q`: cancelar.

Durante la captura:

- `q`: abortar el test actual.

### Que metricas calcula

El benchmark calcula, entre otras:

- disponibilidad del sistema,
- numero de muestras validas,
- media de posicion,
- mediana,
- varianza por eje,
- desviacion estandar por eje,
- rango por eje,
- bias respecto a la posicion esperada,
- norma del bias 3D,
- RMSE por eje,
- MAE por eje,
- error 3D medio,
- percentil 95 del error 3D,
- error de reproyeccion,
- numero medio de marcadores visibles,
- distribucion de visibilidad,
- comparativa entre el test simple y el multi-marcador.

### Que archivos genera

Cada ejecucion crea una carpeta nueva con timestamp:

```text
results/pose_error_benchmark_YYYYMMDD_HHMMSS/
```

Dentro guarda algo parecido a esto:

```text
results/pose_error_benchmark_YYYYMMDD_HHMMSS/
├─ test_01_single_marker/
│  ├─ layout.json
│  ├─ samples.csv
│  ├─ summary.json
│  └─ report.png
├─ test_02_multi_marker/
│  ├─ layout.json
│  ├─ samples.csv
│  ├─ summary.json
│  └─ report.png
├─ comparison.json
└─ comparison.png
```

### Que significa cada archivo

- `layout.json`
  La geometria exacta del test usado.

- `samples.csv`
  Todas las muestras validas frame a frame.

- `summary.json`
  Resumen numerico del test.

- `report.png`
  Grafica profesional del test individual.

- `comparison.json`
  Resumen comparativo entre ambos tests.

- `comparison.png`
  Grafica final comparando un marcador vs varios marcadores.

## Como funciona internamente

## Deteccion ArUco

La deteccion se hace con OpenCV ArUco usando:

- refinamiento de esquinas,
- estimacion de pose del marcador,
- calculo de error de reproyeccion.

## Pose con un solo marcador

Cuando solo se usa un marcador:

- se estima la pose local del marcador con `solvePnP`,
- se invierte la transformacion,
- se obtiene la pose global de la camara,
- si hay varias estimaciones simples se puede fusionar usando el error de reproyeccion como peso.

## Pose con varios marcadores

Cuando hay varios marcadores visibles:

- se construye un conjunto global de puntos 3D conocidos,
- se asocian con sus esquinas 2D detectadas en la imagen,
- se resuelve una pose global con `solvePnPRansac`,
- eso da una estimacion mas robusta que depender de un solo marcador.

## Por que este enfoque sirve para vuestra pregunta

Vuestra pregunta no es solo "donde esta la camara", sino:

> Cuanto se mueve la estimacion cuando en realidad la camara esta quieta.

Por eso el benchmark no se queda en una posicion puntual. Lo que mide es:

- cuanto sesgo tiene la media respecto a la posicion esperada,
- cuanta dispersion hay entre muestras,
- cuan estable es la estimacion,
- cuanta disponibilidad real tiene el sistema,
- y si todo eso mejora cuando se ven varios ArUco a la vez.

## Archivos clave para ampliar el proyecto

- `mockup_aruco/app/error_benchmark.py`
  Flujo principal del benchmark.

- `mockup_aruco/app/live_detector.py`
  Detector en vivo.

- `mockup_aruco/app/camera_setup.py`
  Asistente de camara.

- `mockup_aruco/core/aruco.py`
  Deteccion y pose local de marcadores.

- `mockup_aruco/core/pose.py`
  Logica de pose global simple y multi-marcador.

- `mockup_aruco/core/statistics.py`
  Calculo de metricas del benchmark.

- `mockup_aruco/viz/dashboard.py`
  Dashboard visual en vivo.

- `mockup_aruco/viz/plots.py`
  Graficas finales.

## Ejemplos de uso rapido

### Caso 1. Primer arranque completo

```bash
cd MOCKUP_ARUCO
pip install -r requirements.txt
python camera_setup.py
python detector_3d.py
python error_benchmark.py
```

### Caso 2. Ya tengo perfil guardado

```bash
python detector_3d.py --profile mi_camara
python error_benchmark.py
```

### Caso 3. Quiero usar una fuente concreta

```bash
python detector_3d.py --source 1 --calibration config/camera_calibration.json
```

### Caso 4. Solo quiero recalibrar la camara

```bash
python calibration/calibrar_camara.py
```

## Problemas habituales

### No detecta la camara

- Prueba con otro indice.
- Cierra otras apps que esten usando la webcam.
- Si estas en Raspberry Pi, comprueba que la camara este habilitada y accesible por OpenCV.

### Detecta la camara pero la pose es mala

- Recalibra la camara.
- Revisa el tamano real del marcador.
- Comprueba que el diccionario ArUco sea el correcto.
- Asegurate de que el layout tiene posiciones correctas.

### El benchmark da pocas muestras validas

- Aumenta la iluminacion.
- Acerca la camara o usa marcadores mas grandes.
- Reduce el minimo de marcadores visibles en el test 2 si el montaje lo necesita.
- Asegurate de que los IDs configurados coinciden con los impresos.

### El detector no encuentra el perfil

- Revisa que el JSON exista en `config/camera_profiles/`.
- Pasa la ruta completa con `--profile`.

## Estado actual

El flujo principal actual ya esta preparado para:

- configurar camaras,
- calibrar,
- detectar en vivo,
- medir error de pose,
- comparar uno vs varios ArUco,
- guardar resultados listos para analisis.

La carpeta `legacy/` sigue presente, pero ya no es la base recomendada para continuar el desarrollo.
