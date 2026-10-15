# Limpieza y verificación del código

**Borrador EDISA — 15/10/2026 — `feature/AiM` / `2c90052e85dcc2e2cd317c6500de3a78371526c3`.** Esta tarea solo crea documentación. Ninguna corrección descrita como pendiente se ha implementado. Fuentes: [07](07_Matriz_Evidencias.md).

## Base Git y cambios recientes

El estado inicial no mostraba archivos preparados, modificados ni nuevos. Se han inspeccionado el historial y los archivos actuales, sin modificar el índice ni cambiar de rama.

| Commit | Cambio comprobado | Evaluación |
|---|---|---|
| `58b1f1d` | Captura protegida por sesiones y pruebas; base de comparación anterior | La lógica se conserva byte a byte en `vision/app/captura_segura.py`. |
| `216655f` | Exclusión de sesiones generadas | Reglas trasladadas después a rutas `vision/`; no sustituyen una política de copia de seguridad. |
| `9bfd8be` | Retirada de duplicados, modelos alternativos, metadatos y prototipos CDR | Se conserva la copia del PDF en `docs/entregables/` y los pesos que usan las pipelines principales. La eliminación de modelos alternativos no demuestra equivalencia de inferencia. |
| `c2ae251` | Retirada de `gcs_node`, `gui_node`, `lidar_node`, `simulacion_interactiva`, `test_comms` y configuración SLAM Toolbox | Revisados objetos históricos y entradas actuales. La UI Qt tenía botones de parada/home/velocidad, pero no se ha acreditado que fueran un sistema de seguridad integrado. Planificar esas responsabilidades en GCS, sin restaurar toda la UI. |
| `f7bd24a` | Nueva guía de montaje y prueba de PX4 SITL | Aporta procedimiento y resultados declarados, no una ejecución certificada por esta revisión. |
| `32bab0a` | Agrupación de documentos y resultados en `docs/` y `sim/` | Los documentos históricos mantienen numerosas rutas antiguas. |
| `e6e7ab8` | Paquetes ROS2 y drivers trasladados a `ros2/` | El paquete de control sigue llamándose `dron_control_sistema`. |
| `1584e6d` | Nuevos paquetes `dron_percepcion`, `dron_gcs_bridge`, estructura `dron_bringup`; scripts en `raspberry/` y `tools/` | Añade seis entradas de los dos paquetes nuevos y `logic_bridge` a control. Cambia ejecución a `ros2 run`, búsqueda de scripts y despliegue. |
| `53d9cdb`, `240b1f4`, `2c90052` | Electron a `gcs/`, visión a `vision/`, actualización de mapas/README | La captura y los dos BLOC0 no cambian de contenido respecto de `c2ae251`; el test cambia import y ruta documentada. |

Comparación `c2ae251..HEAD`, con detección de renombres: **566 renombres, 20 altas, dos modificaciones y dos bajas**. Son resultados de la heurística de Git, no una medida del número de funcionalidades cambiadas. Las dos bajas de esa comparación son `WP2/.gitignore` y el antiguo `WP2/ros2/deploy.sh`: sus responsabilidades aparecen en `.gitignore` y `raspberry/deploy.sh`. Algunas altas son archivos vacíos o registros, no nuevos componentes operativos.

La retirada de ArUco y la separación de calibradores pertenecen a cambios anteriores y no se repiten. Los calibradores siguen en `vision/calibration/`. Los modelos disponibles son:

| Archivo actual | Tamaño | Comprobación |
|---|---|---|
| `vision/volumetria/models/yolov8s-world.pt` | 27 169 314 bytes | Existe; SHA-256 `095f5266bb9b654bd5ad9e21e9cdeda78e0f2c8460f5d652eaf04bab7ee251cf`. No cargado. |
| `vision/volumetria/models/mobile_sam.pt` | 40 728 226 bytes | Existe; SHA-256 `6dbb90523a35330fedd7f1d3dfc66f995213d81b29a5ca8108dbcdd4e37d6c2f`. No cargado. |
| `vision/deteccion_cajas/models/mobile_sam.pt` | 40 728 226 bytes | Mismo hash que la copia anterior; todavía existe duplicación. |
| `vision/deteccion_cajas/weights/groundingdino_swint_ogc.pth` | No encontrado | Requerido por la configuración y las entradas GroundingDINO; no se ha descargado. |

No hay etiquetas locales en el momento de la consulta. La etiqueta de estructura anterior mencionada en `docs/estado/REORGANIZACION.md` no está disponible localmente; usar commits comprobados para trazabilidad, sin asumir que existe en un remoto no consultado.

## Mejoras conservadas y límites

La captura compartida valida fuente, primera imagen y FPS de archivo antes de crear una sesión. Reserva directorios de forma exclusiva y escribe JPEG con `xb`. Conserva sesiones parciales ante fallos, libera recursos en `finally` y diferencia mensajes de EOF verificado, fin incierto e interrupción. Metadatos coherentes con más de un frame pendiente provocan `CaptureError`; metadatos ausentes/inconsistentes no acreditan EOF. Una estimación estable pero errónea del número de frames todavía puede originar una alarma conservadora.

Ambos BLOC0 procesan la sesión devuelta y crean otra sesión de resultados. Las pruebas cubren `--no-grabar-video` a nivel de variable/configuración del orquestador, repetición y entrada=salida. **No ejecutan el import completo con ML ni el recorrido CLI completo con modelos.** Al reutilizar fotos, se enumera solo el directorio indicado; para una captura nueva anterior hay que seleccionar su subcarpeta concreta. La estructura de resultados por sesión es un cambio intencional; consumidores externos que esperen JPEG directamente en la base deben actualizarse. No se han encontrado consumidores integrados que resuelvan automáticamente la última sesión.

La protección no cubre todo `vision/`: BLOC1 visual y detectores independientes conservan salidas fijas; `detect_CB.py` vacía carpetas de entrada/salida. Los calibradores aún escriben el mismo JSON con modo `w`. No se han ejecutado estas rutas.

## Problemas confirmados y riesgos de regresión

| Hallazgo | Evidencia | Consecuencia / siguiente comprobación |
|---|---|---|
| Despliegue compila con Humble; arranque y guía usan Jazzy | `raspberry/deploy.sh`, `rosbridge_boot.sh`, guía SITL | Instalación no homogénea. `bash -n` no detecta entorno equivocado ni valida ejecución remota. |
| Manifiestos insuficientes | `dron_control/package.xml` solo declara `mavros_msgs` como dependencia de ejecución; nuevos paquetes no declaran todo lo importado | `pymavlink`, Picamera2 y pyzbar requieren gestión adicional; inventariar también dependencias nativas. `rosdep` no prueba lo que no se declara. |
| Reempaquetado sin prueba de despliegue local | Nuevos `setup.py`, scripts `ros2 run` y `PAE_RASPBERRY_DIR` | Trece destinos estáticos válidos no acreditan instalación en la Pi. `deploy.sh` copia paquetes propios, no drivers ni scripts y no elimina copias remotas retiradas. |
| Nuevo acceso a `logic_bridge` mediante punto de entrada | `dron_control/setup.py` | Su nombre parece un adaptador de pose, pero al recibir pose también publica velocidades. No incorporarlo a un arranque pasivo. |
| Topic/frames y setpoints incompatibles | C02–C09 de [02](02_Arquitectura_y_Decisiones.md) | No se puede considerar integrado Point-LIO→misión→vuelo. |
| UI y backend no coinciden | `cmdGoto`, `cmdVelStop` frente a `_on_cmd` | La GCS muestra `SENT` aunque no exista gestor; falta acuse y rechazo explícito. |
| Estado de enlace puede quedar obsoleto | `_mav_loop` continúa cuando `recv_match` devuelve `None`; no hay vencimiento por heartbeat recibido | El estado `connected` no prueba enlace reciente. Debe probarse la pérdida silenciosa de comunicación. |
| Parada local o proceso terminado no equivalen a parada global | `pixhawk_menu_node._parada_emergencia`, `gcs_control._stop` | Otros emisores pueden seguir activos; hace falta autoridad única y cancelación verificable. |
| Rutas aún destructivas | `detect_CB.netejar_carpeta`, `receptordron.image_callback`, calibradores | Pueden borrar fotografías/resultados o sobrescribir configuración. La garantía de captura segura es específica de las dos pipelines. |
| Volumen sin contrato físico calibrado | Ambos BLOC3, `configure_volumetria` | `--distancia-lidar` cambia BLOC0/tracking, pero los motores BLOC3 conservan su propia constante de 120 cm. No se propaga a ellos ni se carga el JSON de calibración. |
| Persistencia anunciada, no implementada de extremo a extremo | SQLite solo misión; GCS array+CSV | Corregir futuras afirmaciones antes de difundir; no se ha modificado README histórico. |
| Importaciones con efectos laterales | Monte Carlo, MJPEG y generadores de documentos | Monte Carlo escribe `mision.json` del directorio actual y genera gráficos sin guardia; MJPEG abre cámara; generadores preparan/escriben archivos. Solo inspeccionados como texto/AST. |
| Registro y memoria sin política robusta | `lidar_bridge_node` CSV con resolución de segundos; `start_all.sh` logs a segundos; `unilidar_l2.yaml` PCD sin intervalo | Colisiones de logs posibles y crecimiento de memoria del mapa. No corregidos ni ensayados aquí. |

## Verificación realizada

Entorno: Python **3.9.6**, `/usr/bin/python3`. No disponibles en el intérprete/PATH examinado: OpenCV, NumPy, Torch, pytest, rclpy, ament_flake8, ament_pep257, PyYAML, ROS2, colcon, Node y npm. No se han instalado dependencias.

Todos los comandos se ejecutaron desde la raíz del repositorio. No se importaron los módulos operativos con efectos laterales. Los archivos creados por las pruebas se limitaron a directorios temporales.

| ID | Comando o procedimiento exacto | Resultado | Qué comprueba | Qué no comprueba |
|---|---|---|---|---|
| T01 | `/usr/bin/python3 -B -m unittest discover -s vision/tests -v` | **46/46**, `Ran 46 tests in 0.618s`, `OK` | 42 métodos de captura: errores, EOF/metadatos, q/Ctrl+C, recursos, colisiones, hashes; cuatro de encaminamiento sobre ambas pipelines | No hay códec, cámara ni inferencia reales. Las subpruebas no se cuentan como pruebas adicionales. |
| T02 | `ast.parse(path.read_bytes(), filename=str(path))`, para todos los `.py` de `ros2/`, `raspberry/`, `tools/`, `vision/`, `docs/` y `gcs/` | **108/108** sin errores | Sintaxis sin importar ni generar `.pyc` | No resuelve imports, ABI, dependencias ni lógica. |
| T03 | `bash -n` sobre cada `raspberry/*.sh` | **5/5** | Sintaxis | No ejecuta scripts, red ni servicios. `deploy.sh` usa arrays asociativos: necesita Bash compatible, no lo prueba esta comprobación. |
| T04 | `python3 -B vision/programa_unificado.py --help` y ayudas de `volumetria`, `detectar-imagenes`, `detectar-video` | **4/4**, salida 0 | Entrada CLI y parsing sin cargar modelos | No ejecuta procesamiento. |
| T05 | AST de los tres `ros2/*/setup.py`: extraer `console_scripts`, resolver archivo del módulo y buscar `FunctionDef main` | **13/13** | 7 entradas de control, 3 GCS y 3 percepción existentes | No instala paquetes ni lanza nodos; no prueba imports. |
| T06 | `json.loads` de `gcs/package.json`, `gcs/package-lock.json`, misión; `ElementTree.parse` de todos los `ros2/**/package.xml` | **3 JSON y 6 XML** válidos; misión 233 hitos | Formato de archivos | No valida contenido ROS2 completo, esquema semántico ni YAML. |
| T07 | `git diff --check`; `git diff --cached --check`; `git diff --check c2ae251 HEAD` | **3/3**, salida 0 | Errores de whitespace en cambios versionados | No acredita funcionamiento; no incluye documentos nuevos sin seguimiento. |
| T08 | Comparación de SHA-256 y AST/búsquedas de interfaces; comparación de blobs anteriores con rutas nuevas | Misión y modelos leídos; captura/BLOC0 idénticos a base; acciones UI/gestor contrastadas | Conservación e interfaces por código | No ejecución ROS ni validación visual del navegador. |
| T09 | Comprobación de enlaces Markdown mediante `Path.exists`, tablas y bloques de código; búsqueda de términos excluidos; espacios finales y duración de diapositivas | **104 enlaces locales válidos**, siete archivos; 12 diapositivas, **18 minutos** | Integridad documental y alcance profesional de los borradores | Mermaid no se ha renderizado; la documentación necesita revisión humana antes de publicar. |

Receta reproducible de T02/T03/T06, sin escribir en el árbol:

```bash
/usr/bin/python3 -B - <<'PY'
import ast, json, subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
files = [p for r in ('ros2', 'raspberry', 'tools', 'vision', 'docs', 'gcs')
         for p in Path(r).rglob('*.py')]
for p in files:
    ast.parse(p.read_bytes(), filename=str(p))
print('Python:', len(files))
for p in Path('raspberry').glob('*.sh'):
    subprocess.run(['bash', '-n', str(p)], check=True)
for p in (Path('gcs/package.json'), Path('gcs/package-lock.json'),
          Path('ros2/dron_control/dron_control_sistema/mision.json')):
    json.loads(p.read_text())
for p in Path('ros2').rglob('package.xml'):
    ET.parse(p)
PY
```

T05 se puede repetir sin ejecutar `setup.py`:

```bash
/usr/bin/python3 -B - <<'PY'
import ast
from pathlib import Path
total = 0
for setup in Path('ros2').glob('*/setup.py'):
    tree = ast.parse(setup.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, 'id', '') == 'setup':
            ep = next(ast.literal_eval(k.value) for k in node.keywords
                      if k.arg == 'entry_points')
            for spec in ep['console_scripts']:
                _, target = spec.split('=')
                module, function = target.strip().split(':')
                source = setup.parent / Path(*module.split('.')).with_suffix('.py')
                parsed = ast.parse(source.read_text())
                assert any(isinstance(n, ast.FunctionDef) and n.name == function
                           for n in parsed.body), spec
                total += 1
print('Entradas:', total)
PY
```

Los tests de `ros2/dron_control/test/` son linters ament; el de copyright está marcado para omisión. No se ejecutaron por ausencia de pytest/ament. La guía SITL declara fallos de estilo, sin que aquí se reproduzca su cifra. Tampoco se ejecutaron ejemplos de GroundingDINO, generadores de informes, Monte Carlo, `docker_test.py`, los calibradores ni scripts de arranque.

**Niveles de evidencia:** comprobación estática, realizada; pruebas unitarias con dobles, realizadas; integración offline con imágenes/códec/ML reales, pendiente; validación ROS/SITL, declarada en otro equipo pero no reproducida aquí; validación de hardware, pendiente.

Se calculó una huella inicial de todos los **589 archivos existentes** fuera de `.git` y `__pycache__`, incorporando ruta y SHA-256 de contenido: `2d8989ad18cc3c56254e8dc060bfcf54f34598f84bb7671a6cc5575326c23e9c`. La repetición final, excluyendo esta carpeta documental nueva, no llegó a completarse: hubo un `TimeoutError` de lectura, un reintento sobre un GIF de terceros y otra lectura prolongada en `vision/`; se interrumpió esa comprobación. **No se afirma una igualdad de hashes global antes/después que no se haya obtenido.**

La última consulta Git completada muestra únicamente los siete documentos nuevos sin seguimiento; no hay cambios preparados ni diferencias de código. Rama y HEAD siguen siendo los indicados. Las tres comprobaciones T07 iniciales aprobaron; repeticiones finales de `git diff --check` agotaron límites de 30 y 90 segundos. Son incidencias de acceso observadas, sin causa determinada, no evidencia de un error de código ni de corrupción. No se han aplicado reparaciones al índice ni al sistema de archivos. La revisión solo ha escrito en esta carpeta nueva.

## Clasificación de limpieza pendiente

Las etiquetas `KEEP`, `REFACTOR`, `MERGE`, `ARCHIVE`, `REMOVE`, `UNDECIDED` son decisiones propuestas; **no se ha borrado, movido ni corregido nada**.

| Candidato | Clasificación | Justificación y dependencia | Riesgo / momento |
|---|---|---|---|
| Captura segura y tests | KEEP | Protección localizada y pruebas conservadas; extender cobertura real sin cambiar algoritmos | Mantener ahora. |
| Drivers y Point-LIO | KEEP | Responsabilidad central reutilizable; separar configuración del montaje y cambios locales | No actualizar ni editar terceros durante limpieza documental. |
| Calibradores | KEEP + REFACTOR | Necesarios; posteriormente salida explícita/versionada y prueba temporal sin cámara | Evitar sobrescritura del JSON; no confundir conservación con integración métrica. |
| Dos coordinadores de misión | MERGE | Elegir uno tras prueba comparativa; conservar lectura de misión y progreso | Riesgo alto si se retira antes de migrar la semántica de misión. |
| `logic_bridge` | REFACTOR | Útil reenvío de pose; extraer transformación/validación del ensayo de movimiento | Prioritario antes de cualquier arranque con controladora. |
| `mavlink_bridge` frente a MAVROS | UNDECIDED | Depende del firmware/contrato; conservar telemetría aprovechable | No mantener dos autoridades activas; no borrar por ausencia de referencias internas. |
| `receptordron` y `telemetry_publisher` | MERGE | Conservar responsabilidad imagen+pose dentro de captura integrada | Corregir política de datos antes de usar con originales; confirmar ejecución manual/externa. |
| `detect_CB.py` independiente | UNDECIDED | Lógica de estantería útil, pero adquisición y borrado separados | Confirmar usuarios y equivalencia con BLOC0; archivar si no operativo o proteger de forma localizada si lo es. |
| Monte Carlo | ARCHIVE | Experimento con escritura al importar, geometría XY y simulación no equivalente a vuelo | Confirmar dependencia del generador `densificar` y del JSON; preservar misión actual y, si hace falta, extraer solo generador puro. No refactorizar todo el experimento. |
| `simulador_dron`, imágenes artificiales y monitores | KEEP | Diagnóstico y contratos; etiquetar como pruebas sintéticas | No usarlos como evidencia de dinámica o de seguridad. |
| MJPEG y adquisición duplicada | MERGE | Reutilizar interfaz HTTP alimentada por productor único | Confirmar consumidores externos antes de retirar el servidor. |
| Dos copias MobileSAM | MERGE | Hash idéntico; centralizar configuración de ruta si se confirma uso | Conservar ambas hasta prueba de todos los consumidores. |
| Servicios/arranques alternativos | UNDECIDED | Podrían estar instalados manualmente | Inventariar despliegue y elegir perfil antes de retirar. |
| Registros vacíos, metadatos, referencias rotas | REMOVE o ARCHIVE tras comprobar | Solo si no aportan configuración ni trazabilidad | Baja prioridad; nunca borrar resultados/datasets por criterio estético. |

## Plan priorizado de limpieza y validación

P0 bloquea una decisión o preservación importante; P1 habilita la primera integración; P2 es mejora posterior. Complejidad `LOW / MEDIUM / HIGH`. Las estimaciones son orientativas y excluyen compras, instalación de entornos y esperas externas.

| ID | Prioridad | Componente / tarea y archivos afectados | Complejidad | Dependencias | Pruebas necesarias | Criterio de finalización |
|---|---|---|---|---|---|---|
| N01 | P0 | Confirmar inventario/firmware/SO; ficha [04](04_Inventario_Componentes_Dron.md) | LOW | Acceso y responsable EDISA | Inspección registrada, sin vuelo | Modelos, versiones, conexiones y pendientes firmados por responsable. |
| N02 | P0 | Validar reempaquetado y coherencia distro: `ros2/*/{setup.py,package.xml}`, `raspberry/deploy.sh` | MEDIUM | Entorno Linux aislado acordado; N01 para despliegue real | Build/install y resolución de 13 ejecutables; imports sin crear nodos; dependencias declaradas | Instalación limpia reproducible sin cámara, serie ni procesos de control. |
| N03 | P0 | Decidir uso y proteger/aislar rutas destructivas: `detect_CB.py`, `tools/receptordron.py`, calibradores | MEDIUM | Usuarios manuales confirmados | Directorios temporales, hashes, error inicial, repetición | No se pierde ningún original ni resultado/configuración previo; scripts obsoletos fuera del flujo operativo. |
| N04 | P0 | Confirmar función de Monte Carlo y destino histórico; generador `densificar`, `mision.json` | LOW | Confirmación de dependencia externa y copia de misión | Comparación de misión, importación aislada del eventual extractor | Experimento no se importa en runtime; misión actual intacta y generación explícita si sigue necesaria. |
| N05 | P1 | Contrato de pose: Point-LIO, consumidores de `/Odometry`, adaptador propio | MEDIUM | Convenio de frames/tiempo | Pose conocida, movimiento de ejes, datos antiguos/ausentes; reproducción sin vuelo | Un topic tipado; transformación y validez documentadas y verificadas. |
| N06 | P1 | Primera observación durable: nuevo adaptador, esquema de inventario y GCS | MEDIUM | N05 o pose reproducida explícita; definición EDISA de código/ubicación | Imagen/pose fijas, transacción, reinicio, consulta GCS, hashes | Dos ejecuciones aisladas; dato trazable persistente visible tras reiniciar. |
| N07 | P1 | Cámara única: `camera_publisher`, MJPEG, grabador | MEDIUM | N01 y contrato imagen/pose | Reproducción, dos consumidores simultáneos, timestamps y fallo de escritura | Una adquisición; sin colisión; sesión e imagen asociadas correctamente. |
| N08 | P1 | Validación ML offline: dos BLOC0, modelos/configuración | MEDIUM | Dependencias preparadas y conjunto autorizado; checkpoint GroundingDINO si se compara | Entradas inmutables, métricas de código/caja/ID y latencia | Una pipeline de referencia con resultados reproducibles, versión y límites medidos. |
| N09 | P1 | Contrato UI/backend: `gcs/renderer/app.js`, adaptador de órdenes | MEDIUM | Decisión provisional de backend | Dobles para acción válida/desconocida, acuse, error, desconexión | `SENT` no se presenta como ejecución; botones coherentes con capacidades disponibles. |
| N10 | P1 | Elegir coordinador: `brain_node`, `cerebro_node`, misión | HIGH | N05; contrato misión | Un waypoint XYZ, start/pause/resume/cancel, pose caducada, progreso | Una autoridad de misión y migración de datos demostrada. |
| N11 | P1 | Adaptador de vuelo y supervisión: MAVROS/puente propio, `logic_bridge` | HIGH | N01/N10; entorno SITL | Sin emisores duplicados; límites, continuidad, ACK, pérdida de pose/enlace, parada global | Criterios de seguridad medidos y registrados en SITL; sin movimiento real. |
| N12 | P2 | Arranque único por perfil: `dron_bringup`, `raspberry/*.sh`, `*.service` | MEDIUM | N02/N07/N11 | Instalación, arranque/cierre, procesos duplicados, fallo parcial | Perfiles offline/SITL/banco explícitos; ningún control activado por perfil offline. |
| N13 | P2 | Calibración, distancia y unidades: BLOC3, CLI, adaptador de volumen | HIGH | N01/N08, muestras con medidas fiables | Variación de distancia, lectura JSON, error métrico, conversión a SI | Medidas con error cuantificado y unidades coherentes; sin precisión inventada. |
| N14 | P2 | Centralizar pesos y registros; actualizar documentos de uso activo | LOW | N08/N12 y revisión de consumidores | Rutas y hashes; conservación; enlaces | Ningún consumidor roto y material histórico claramente separado. |

**Siguiente tarea técnica manejable propuesta: N02**, empezando por una validación aislada de empaquetado y una lista cerrada de dependencias, sin iniciar nodos. Después, la primera integración de producto es N06. La prioridad de N03 impide usar las rutas destructivas con datos reales mientras no se decida su destino. No se inicia ninguna de estas tareas en esta revisión.
