# Inventario offline por codigos

Esta carpeta contiene el demo offline `detect_CB.py`.

El script procesa imagenes ya capturadas, detecta codigos de barras/QR con
OpenCV y pyzbar, y genera un resumen de inventario por estanteria.

## Entradas

- Imagenes: `WP3/volumetria/data/fotos_capturades`
- Manifest: `WP3/volumetria/data/etiquetes_magatzem_manifest.csv`

El manifest esperado usa estas columnas:

- `category`
- `label_name`
- `barcode_type`
- `encoded_value`
- `product_code`

Las filas `category=shelf` definen estanterias validas. Las filas
`category=product` definen productos registrables.

## Salidas

Las imagenes anotadas se guardan en:

`WP3/volumetria/barcode/deteccio_qr_codi/demo_output_detected`

## Ejecucion

Desde la raiz del repo:

```bash
python3 WP3/volumetria/barcode/deteccio_qr_codi/detect_CB.py
```

Si el Python global no tiene las dependencias, usa el entorno virtual del WP3:

```bash
WP3/detecció_qr_codi/.venv/bin/python WP3/volumetria/barcode/deteccio_qr_codi/detect_CB.py
```

## Dependencias

Las dependencias Python estan en `requirements.txt`.

`pyzbar` tambien necesita la libreria nativa `zbar`:

```bash
brew install zbar
```
