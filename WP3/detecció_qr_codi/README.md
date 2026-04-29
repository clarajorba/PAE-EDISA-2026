# README - detect_qr&codi_webcam_v3.py

Este documento explica el funcionamiento del script `detect_qr&codi_webcam_v3.py`, que usa OpenCV y pyzbar para capturar o analizar fotogramas, detectar codigos de barras/QR y gestionar un inventario temporal por estanterias.

## Objetivo del script

El script sirve para simular o ejecutar un proceso de inventario mediante imagenes:

- Detecta codigos de estanteria, normalmente `CODE39`.
- Detecta codigos de producto, normalmente `CODE128` que empiezan por `00` y representan SSCC.
- Abre una transaccion cuando detecta una estanteria valida.
- Durante la transaccion, acumula los productos detectados.
- Cierra la transaccion cuando vuelve a detectar la misma estanteria despues de un tiempo minimo.
- Guarda un resumen final del inventario por estanteria.
- Imprime tambien todos los codigos unicos detectados durante la prueba, aunque no hayan entrado en el inventario.
- Genera imagenes procesadas con los codigos marcados.

## Dependencias principales

El script usa:

- `opencv-python==4.13.0.92`, importado como `cv2`
- `numpy==2.4.4`
- `pyzbar==0.1.9`
- Modulos estandar de Python: `csv`, `os`, `shutil`, `threading`, `time`

Las dependencias del proyecto estan en `requirements.txt`.

Ademas, `pyzbar` necesita la libreria nativa `zbar` instalada en el sistema:

```bash
# macOS
brew install zbar

# Debian / Raspberry Pi OS
sudo apt install -y libzbar0
```

## Archivos y carpetas importantes

El script trabaja dentro de la misma carpeta donde esta el archivo Python.

### `detect_qr&codi_webcam_v3.py`

Es el script principal. Contiene:

- configuracion general,
- gestion de camara,
- carga del manifest CSV,
- captura de fotogramas,
- deteccion de codigos,
- logica de inventario,
- resumen final por terminal.

### `etiquetes_magatzem_simulades_manifest.csv`

Es el manifest que define:

- que codigos son estanterias validas,
- que codigos SSCC corresponden a cada producto.

El script espera columnas como:

- `category`
- `encoded_value`
- `label_name`

Cuando `category == "shelf"`, el codigo se registra como estanteria valida.

Cuando `category == "box"` y el valor empieza por `00`, se registra como producto/SSCC.

### `CB_in`

Carpeta de entrada.

Si `REGRAVAR_IMATGES = True`, el script:

- borra el contenido de `CB_in`,
- abre la camara,
- guarda ahi los fotogramas capturados.

Si `REGRAVAR_IMATGES = False`, el script:

- no borra `CB_in`,
- no abre la camara,
- analiza las imagenes `.jpg` que ya existen en esa carpeta.

### `CB_out`

Carpeta de salida.

En cada postprocesado, el script:

- borra el contenido anterior de `CB_out`,
- guarda ahi las imagenes procesadas,
- dibuja sobre esas imagenes los codigos detectados, sus contornos, centro y texto.

La carpeta `CB_out` representa siempre el resultado de la ultima ejecucion.

## Configuracion principal

Al inicio del script estan las constantes mas importantes.

### Camara

```python
FONT_VIDEO = 0
```

Usa la camara por defecto del ordenador.

Tambien se puede usar un stream TCP cambiando la variable, por ejemplo:

```python
FONT_VIDEO = "tcp://172.20.10.3:8888"
```

### Modo de trabajo

```python
REGRAVAR_IMATGES = True
```

Controla si se capturan imagenes nuevas o si se analizan imagenes ya existentes.

- `True`: captura de camara y reemplaza `CB_in`.
- `False`: analiza las imagenes existentes en `CB_in`.

### Debug

```python
DEBUG = False
```

Si se cambia a `True`, el script imprime informacion adicional:

- codigos detectados por frame,
- duplicados ignorados,
- SSCC repetidos ignorados,
- nuevos SSCC añadidos,
- nuevos codigos registrados globalmente.

### Frecuencia de captura

```python
INTERVAL_GUARDAT_SEGONS = 0.5
```

Indica cada cuantos segundos se guarda un fotograma durante la captura.

### Cooldowns

```python
COOLDOWN_TANCAMENT = 4.0
COOLDOWN_ENTRE_ESTANTERIES = 3.0
```

- `COOLDOWN_TANCAMENT`: tiempo minimo antes de poder cerrar una transaccion al volver a detectar la misma estanteria.
- `COOLDOWN_ENTRE_ESTANTERIES`: tiempo minimo que debe pasar tras cerrar una estanteria antes de abrir otra.

El estado inicial usa:

```python
"temps_tancament": -float("inf")
```

Esto evita un cooldown falso al principio. Asi, la primera estanteria valida puede abrir transaccion inmediatamente.

## Flujo general de ejecucion

El punto de entrada es:

```python
if __name__ == "__main__":
    main()
```

La funcion `main()` hace lo siguiente:

1. Calcula la carpeta base del script.
2. Carga el manifest CSV.
3. Decide si debe capturar imagenes nuevas o usar las existentes.
4. Define la carpeta de entrada `CB_in`.
5. Define la carpeta de salida `CB_out`.
6. Procesa los fotogramas.
7. Imprime el resumen de inventario.
8. Imprime el resumen de todos los codigos unicos detectados.

## Captura de fotogramas

La captura se realiza solo cuando:

```python
REGRAVAR_IMATGES = True
```

La clase `CameraStream` mantiene un hilo en segundo plano leyendo continuamente la camara. Esto reduce la latencia porque el programa siempre puede acceder al ultimo frame disponible.

Funciones relacionadas:

- `esperar_primer_frame()`: espera a recibir el primer frame valido.
- `preparar_carpeta_captura()`: crea y limpia `CB_in`.
- `guardar_fotograma()`: guarda un frame como `.jpg`.
- `capturar_fotogrames()`: muestra el directo, guarda fotogramas y termina al pulsar `q`.

Durante la captura:

- se muestra la ventana de video,
- se guardan fotogramas cada `INTERVAL_GUARDAT_SEGONS`,
- se sale pulsando `q`.

## Postprocesado de imagenes

La funcion principal de postprocesado es:

```python
processar_fotogrames_guardats(...)
```

Esta funcion:

1. Comprueba que existe `CB_in`.
2. Busca imagenes `.jpg`.
3. Limpia `CB_out`.
4. Lee cada imagen.
5. Ejecuta la deteccion y la logica de inventario.
6. Guarda la imagen procesada en `CB_out` con el mismo nombre.

Las imagenes originales de `CB_in` no se modifican durante el postprocesado.

## Deteccion de codigos

La funcion principal de deteccion es:

```python
detectar_codis_mixtos(frame, tipus_prioritaris=None)
```

Aunque recibe `tipus_prioritaris` por compatibilidad, ya no se detiene al encontrar un tipo prioritario. Procesa todas las variantes disponibles y acumula todas las detecciones validas.

### Tipos soportados

```python
TIPUS_SUPORTATS = {
    "QRCODE", "EAN13", "EAN8", "UPCA", "UPCE", "CODE128", "CODE39", "I25"
}
```

### Estrategia de deteccion

El script mantiene varias pasadas:

1. Escala rapida `ESCALA_DETECCIO_RAPIDA`.
2. Imagen en gris.
3. Imagen ecualizada.
4. Escala fina `ESCALA_DETECCIO_FINE`.
5. Imagen en gris.
6. Imagen ecualizada.
7. Otsu.
8. Threshold adaptativo.

Esto aumenta la probabilidad de leer codigos en condiciones diferentes de luz, enfoque o contraste.

### Deduplicacion

La deteccion puede encontrar el mismo codigo varias veces porque se prueban varios preprocesados.

Para evitar duplicados, el script crea una clave aproximada basada en:

- tipo de codigo,
- texto leido,
- centro aproximado,
- tamaño aproximado.

Ademas, compara detecciones cercanas con el mismo tipo y texto.

Esto evita registrar varias veces el mismo codigo, pero no elimina codigos diferentes aunque esten cerca entre si.

## Logica de inventario

El estado del inventario se crea con:

```python
crear_estat_inventari(estanteries_valides, sscc_a_producte)
```

El estado guarda:

- estanteria actualmente abierta,
- tiempo de apertura,
- tiempo de cierre anterior,
- productos temporales de la transaccion,
- inventario global,
- SSCC vistos durante la transaccion actual,
- registro global de codigos detectados,
- texto/color de estado para dibujar sobre la imagen.

### Apertura de transaccion

Una transaccion se abre cuando:

- se detecta un `CODE39`,
- el texto existe en el conjunto de estanterias validas,
- no hay ninguna estanteria abierta,
- ya ha pasado el cooldown entre estanterias.

Al abrir:

- se asigna `estanteria_actual`,
- se guarda `temps_obertura`,
- se limpian los productos temporales,
- se limpia el conjunto de SSCC vistos en esa transaccion.

### Lectura de productos

Mientras hay una estanteria abierta, se aceptan productos cuando:

- el tipo es `CODE128`,
- el texto empieza por `00`.

El script usa `sscc_vistos_actuals` para no contar dos veces el mismo SSCC dentro de la misma transaccion.

El producto se guarda en:

```python
productes_temporals
```

Si el SSCC existe en el manifest, se usa el nombre del producto. Si no existe, se usa el propio codigo como clave.

### Cierre de transaccion

La transaccion se cierra cuando:

- hay una estanteria abierta,
- se vuelve a detectar la misma estanteria,
- ha pasado mas de `COOLDOWN_TANCAMENT`.

Al cerrar:

- se calcula el resumen de cantidades,
- se guarda en `inventari_global`,
- se limpia la transaccion temporal,
- se actualiza `temps_tancament`.

## Registro global de codigos detectados

Ademas del inventario, el script mantiene un registro de todos los codigos unicos detectados durante la prueba.

Esto sirve para comprobar:

- codigos que se detectan pero no entran en inventario,
- codigos que nunca se detectan,
- codigos leidos mal o incompletos,
- productos que no constan en el manifest.

La clave unica del registro es:

```python
(tipus, text)
```

Por eso, si el mismo `CODE128` aparece en muchos fotogramas, solo se muestra una vez.

El resumen final se imprime con:

```python
imprimir_codis_detectats(estat_inventari)
```

Formato de salida:

```text
--- CODIS DETECTATS DURANT LA PROVA ---

Total codis únics detectats: 2

[1] Tipus: CODE39
    Text: 32213
    Estanteria oberta: Sí
    Estanteria tancada: No
    Producte: No
    Consta al manifest: Sí

[2] Tipus: CODE128
    Text: 00123456789012345678
    Estanteria oberta: No
    Estanteria tancada: No
    Producte: Nom del producte
    Consta al manifest: Sí
```

No se genera ningun CSV ni TXT con este registro. Solo se imprime por terminal.

## Imagenes anotadas

Cada imagen procesada se guarda en `CB_out`.

En cada deteccion, el script dibuja:

- contorno del codigo,
- punto central,
- etiqueta con tipo y texto.

Tambien escribe el estado actual:

- esperando estanteria,
- cooldown,
- leyendo una estanteria concreta.

## Resumen de inventario

Al final se imprime:

```python
imprimir_resum_inventari(estat_inventari)
```

El resumen muestra:

```text
--- RESUM DE L'INVENTARI (ESTANTERIA -> PRODUCTE : QUANTITAT) ---

[32213]
  - Producto A: 2 unitats
  - Producto B: 1 unitats
```

Solo aparecen estanterias cuya transaccion se haya cerrado correctamente.

Si no se ha cerrado ninguna transaccion, aparece:

```text
No s'ha registrat cap inventari tancat.
```

## Uso recomendado

### Capturar una prueba nueva

1. Poner:

```python
REGRAVAR_IMATGES = True
```

2. Ejecutar:

```bash
python3 'detect_qr&codi_webcam_v3.py'
```

3. Mostrar la estanteria para abrir transaccion.
4. Mostrar los productos.
5. Volver a mostrar la misma estanteria despues de `COOLDOWN_TANCAMENT`.
6. Pulsar `q` para finalizar la captura.
7. Revisar:

- resumen por terminal,
- imagenes originales en `CB_in`,
- imagenes anotadas en `CB_out`.

### Analizar imagenes existentes

1. Poner las imagenes `.jpg` en `CB_in`.
2. Poner:

```python
REGRAVAR_IMATGES = False
```

3. Ejecutar:

```bash
python3 'detect_qr&codi_webcam_v3.py'
```

4. Revisar:

- inventario final en terminal,
- codigos detectados en terminal,
- imagenes marcadas en `CB_out`.

## Notas importantes

- `CB_in` solo se borra cuando `REGRAVAR_IMATGES = True`.
- `CB_out` se borra en cada postprocesado.
- La primera estanteria valida no entra en cooldown inicial porque `temps_tancament` empieza en `-float("inf")`.
- Un mismo SSCC no se cuenta dos veces dentro de la misma transaccion.
- Un mismo codigo detectado no se repite en el resumen global si tiene el mismo `(tipus, text)`.
- El inventario solo se consolida cuando la estanteria se cierra.
