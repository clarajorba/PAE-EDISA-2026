# vision (antes WP3) - Programa unificado

Ejecutar desde la carpeta `vision`:

```powershell
python programa_unificado.py --help
```

Modos disponibles:

```powershell
python programa_unificado.py volumetria
python programa_unificado.py detectar-imagenes
python programa_unificado.py detectar-video
```

Ejemplos utiles:

```powershell
python programa_unificado.py volumetria --no-grabar-video --fotos data/fotos_capturades
python programa_unificado.py detectar-imagenes --imagen Imagenpegada.png
python programa_unificado.py detectar-video --fuente-video tcp://172.20.10.2:8888 --no-sam
```

Dependencias:

```powershell
pip install -r config/requirements_unificado.txt
```

Notas:

- El lanzador mantiene los modulos originales y ejecuta cada pipeline desde su carpeta para respetar rutas relativas.
- Para `volumetria`, los modelos esperados son `volumetria/models/yolov8s-world.pt` y `volumetria/models/mobile_sam.pt`.
- Para `detectar-imagenes` y `detectar-video`, falta en este repositorio el archivo `deteccion_cajas/weights/groundingdino_swint_ogc.pth`. Debe copiarse ahi o indicarse con `--weights`.
- `pyzbar` requiere ZBar instalado en el sistema, no solo en `pip`.
