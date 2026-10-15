# Estado actual del proyecto PAE-EDISA

**Revisión documental del 15/10/2026:** auditoría técnica original en `2c90052e85dcc2e2cd317c6500de3a78371526c3`; rama actual `feature/AiM`, HEAD verificado antes de editar `ad9b23a70247cfa09c84e9301f7e64975fd2fda4`. Se incorpora información comunicada por el equipo el 14/10/2026 (E33/E34) y se contrastan solo correcciones posteriores relevantes (E36). Las pruebas originales no se han repetido; no hay inspección física ni validación operacional nuevas.

**Borrador para revisión técnica de EDISA — 15/10/2026.**

La auditoría original examinó `feature/AiM` en `2c90052e85dcc2e2cd317c6500de3a78371526c3` y creó estos siete documentos. Esta actualización modifica los borradores existentes, incorpora información del equipo y corrige únicamente los cambios posteriores contrastados en E36. El árbol de trabajo estaba limpio al comenzar ambas tareas. Las referencias E01–E36 se desarrollan en [la matriz de evidencias](07_Matriz_Evidencias.md).

## Objetivo y resumen ejecutivo

El objetivo es inspeccionar un almacén con un dron, identificar cajas o productos y generar un inventario persistente con ubicación y evidencia trazables.

El repositorio contiene piezas reutilizables de localización LiDAR, navegación, comunicación con la controladora, cámara, lectura de códigos, detección y volumetría, además de una GCS Electron. **No se ha acreditado una cadena autónoma completa desde una misión hasta un inventario persistente visible en la GCS.** Hay dos coordinadores de misión, dos alternativas de comunicación y varias interfaces que todavía no encajan.

La reorganización del 15/10 mejora la separación por responsabilidades y convierte nodos antes sueltos en paquetes ROS2. Conserva las dos pipelines principales de volumetría y su captura segura. Sin embargo, mover y empaquetar código no demuestra su funcionamiento. La guía nueva de simulación declara pruebas PX4/SITL en otro equipo; esta revisión no las ha reproducido ni dispone de registros de ejecución asociados que permitan certificarlas.

La verificación ejecutada en la auditoría original incluyó **46 pruebas automatizadas con dobles**, sintaxis de **108 archivos Python**, **cinco scripts de shell**, coherencia estática de **13 puntos de entrada ROS2**, JSON/XML y las cuatro ayudas CLI de visión. No se ha iniciado ROS2, Electron, inferencia ML, un simulador de vuelo ni hardware. Véase [el detalle reproducible y sus límites](03_Limpieza_y_Verificacion.md).

## Mapa del repositorio

```text
ros2/
  dron_control/             Paquete dron_control_sistema: misión JSON, control,
                           puente de localización y prototipos de simulación.
  dron_gcs_bridge/          Gestor de servicios, puente pymavlink y misión SQLite.
  dron_percepcion/          Cámara Picamera2, códigos de barras, imagen+pose.
  dron_bringup/             Estructura vacía de launch/config; sin arranque integrado.
  third_party/
    point_lio_ros2/         Estimación LiDAR-inercial y mapa; modificaciones locales.
    unilidar_sdk2/          SDK y nodo ROS2 Unitree; configuración para L2.
raspberry/                 Despliegue, arranque, systemd y servidor MJPEG.
gcs/                      Electron, renderer/app.js, ROSLIB y material anterior.
vision/
  programa_unificado.py    Entrada CLI hacia app/programa_unificado.py.
  app/captura_segura.py    Captura y reserva de sesiones independientes.
  volumetria/              YOLO-World + SAM, tracking, códigos y medidas.
  UNIFICACIO_FINAL/        GroundingDINO + SAM y lógica de inventario en memoria.
  deteccion_cajas/         Detectores, filtros y copia de GroundingDINO.
  calibration/            Calibradores de cámara conservados.
  tests/                  Pruebas de captura y encaminamiento sin hardware.
sim/                      Resultados históricos y enlace a la guía SITL.
tools/                    Receptor imagen+pose y utilidades de diagnóstico.
docs/                     Arquitectura, estado, configuración y entregables previos.
data/                     Política para datos grandes; solo README en esta revisión.
```

La carpeta vacía `Documentation/` fue retirada después de la auditoría original (`ad9b23a`); no era una aplicación. Los nombres físicos `WP2/`, `WP3/` y `src/` ya no describen la estructura activa. `ros2/dron_control/` mantiene el nombre de paquete `dron_control_sistema`; no debe inferirse el nombre ROS2 a partir de la carpeta. E01–E03.

## Estados utilizados

| Clave | Categoría | Interpretación |
|---|---|---|
| V | IMPLEMENTADO Y VERIFICADO FUNCIONALMENTE | Solo para el comportamiento y entorno realmente ensayados. |
| I | IMPLEMENTADO, SIN VERIFICACIÓN FUNCIONAL | Existe código; las comprobaciones estáticas o con dobles no certifican la ejecución real. |
| P | PARCIALMENTE IMPLEMENTADO | Faltan responsabilidades o conexiones esenciales. |
| E | EXPERIMENTAL / PROTOTIPO | Comportamiento limitado o de demostración. |
| N | NO IMPLEMENTADO | No se encuentra una implementación de la responsabilidad indicada. |
| H | OBSOLETO / HISTÓRICO | Material anterior, retirado o conservado como referencia. |
| D | DESCONOCIDO / REQUIERE CONFIRMACIÓN | La evidencia disponible no permite determinarlo. |

## Matriz de estado por componente

Los archivos se indican desde la raíz del repositorio. Una fila I puede tener pruebas unitarias aprobadas sin disponer de verificación funcional de su integración real.

| Componente | Archivos principales | Funcionalidad implementada y entrada → salida | Evidencia de verificación | Estado | Funcionalidad pendiente / limitación | Dependencias de integración | Próxima acción |
|---|---|---|---|---|---|---|---|
| Hardware y ordenador embarcado | Información del equipo del 14/10/2026 y referencias software E28/E33–E35 | Equipo declarado: Holybro X500 V2, Pixhawk 6X, Raspberry Pi 5 (kit DB-TRONIC), Unitree 4D LiDAR L2 y Raspberry Pi Camera Module 3 — variante pendiente de confirmar | Declaración del equipo; componentes de kit descritos por separado; sin inspección física independiente | D | Modelos principales identificados por el equipo; firmware, SO, RAM, montaje y funcionamiento pendientes; cantidades declaradas solo donde constan | Confirmación documental y física por EDISA | Completar y contrastar inventario, sin elevar el estado funcional del software |
| Driver LiDAR | `ros2/third_party/unilidar_sdk2/` | SDK/UDP o serie → `PointCloud2` e `Imu` | Configuración y código inspeccionados E04; sin compilación/ejecución | I | Validar dispositivo, red, timestamps y funcionamiento sin pantalla | Unitree real, SDK y ROS2 | Reproducir con datos grabados y después banco |
| Localización y mapa | `ros2/third_party/point_lio_ros2/` | Nube+IMU → `/slam/odom`, `/slam/pose`, TF, nube registrada | Revisión C++/configuración E05; sintaxis Python de launch | I | Calibración extrínseca al dron, calidad, frescura y contrato de frames | Driver y datos representativos | Fijar contrato de pose y reproducir una grabación |
| Adaptación TF a misión | `ros2/dron_control/dron_control_sistema/lidar_bridge_node.py` | TF → array `[x,y,z,yaw]` y CSV | E06; análisis estático | P | Pierde timestamp/frame; no rechaza TF antigua; CSV con nombre a segundos | TF `camera_init` → `aft_mapped` | Conservar responsabilidad y definir interfaz tipada |
| Misión JSON | `.../cerebro_node.py`, `.../mision.json` | Pose array+233 hitos → siguiente objetivo | JSON válido, hash E07; sin misión ejecutada | P | Avance solo XY, envío puntual, sin pausa/reanudar ni confirmación de captura | `/drone/pose`, controlador | Comparar con coordinador SQLite antes de elegir uno |
| Misión SQLite | `ros2/dron_gcs_bridge/dron_gcs_bridge/brain_node.py` | SQLite+`/slam/odom` parametrizable → setpoints y progreso JSON | Esquema SQL y `_tick` inspeccionados E08; corrección del topic contrastada estáticamente E36 | P | Avance solo XY; misión por defecto; sin control de frescura ni integración de vuelo verificada | MAVROS real, pose normalizada, autoridad de misión | Probar contrato sin salida de vuelo |
| Control mediante MAVROS | `.../mavros_node.py`, `.../pixhawk_menu_node.py` | Objetivo/teclado → velocidad y servicios MAVROS | E09–E10; guía SITL declarada E25 | E | Nodo automático sin flujo continuo ni límites; menú no sustituye controlador ni parada global | MAVROS y firmware confirmado | Validar en SITL aislado, con un único emisor |
| Puente propio MAVLink | `ros2/dron_gcs_bridge/dron_gcs_bridge/mavlink_bridge.py` | Serie MAVLink ↔ telemetría ROS y cinco órdenes JSON | Gestores inspeccionados E11; sin enlace ejecutado | P | Tabla de modos ArduCopter, sin setpoints autónomos, sin ACK de órdenes a GCS | Firmware, puerto y contrato de órdenes | Mantener alternativa hasta confirmar controladora |
| Pose externa para controladora | `.../logic_bridge.py` | `/slam/pose` → `/mavros/vision_pose/pose` | E12; nuevo punto de entrada estáticamente válido | E | Reenvío sin transformación ni validez; también emite movimiento de prueba | TF cuerpo/sensor y configuración del estimador | Separar responsabilidades en una tarea posterior |
| Cámara ROS2 | `ros2/dron_percepcion/dron_percepcion/camera_publisher.py` | Picamera2 → JPEG comprimido con header | E13; código y QoS inspeccionados | I | Cámara, orientación, enfoque y latencia no verificados | Pi/cámara confirmadas, ROS2 | Una sola adquisición compartida por consumidores |
| Vídeo HTTP | `raspberry/mjpeg_server.py` | OpenCV dispositivo → MJPEG HTTP | E14; sintaxis únicamente | E | Abre cámara al importar; puede competir con Picamera2 | Dispositivo y Flask/OpenCV | Sustituir adquisición duplicada por consumo de imágenes |
| Reserva de sesiones | `vision/app/captura_segura.py:crear_directori_sessio` | Base+nombre → directorio nuevo | Pruebas temporales de colisiones y conservación E15/T01 | V | Alcance limitado al sistema de archivos local probado | Permisos y espacio disponible | Conservar |
| Captura de vídeo segura | `vision/app/captura_segura.py` | Vídeo/URL → JPEG en sesión única | 42 pruebas de captura con dobles dentro de T01 | I | Códecs/streams sin verificar; estado de finalización solo por mensajes | OpenCV/backend y disco | Añadir prueba offline con vídeo conocido en entorno preparado |
| Detección/segmentación/tracking | `vision/volumetria/volumetria_BLOC{0_1,1,2}.py` | Fotos → cajas, IDs, contornos y anotaciones | Encaminamiento real probado con inferencia simulada E16/T01 | I | Calidad ML y asociación de IDs no medidas aquí | Pesos, dependencias y conjunto etiquetado | Validar una pipeline de referencia con entradas fijas |
| Pipeline alternativa GroundingDINO | `vision/UNIFICACIO_FINAL/BLOC{0,1,2,3}.py` | Fotos+manifest → detecciones e inventario por estantería en memoria | Cuatro pruebas de encaminamiento cubren ambas variantes E17 | I | Falta checkpoint `.pth`; no expuesta como variante de volumetría en la CLI unificada | GroundingDINO, SAM y ZBar | Mantener hasta comparar resultados, sin duplicar integración |
| Volumetría | `vision/volumetria/volumetria_BLOC3_1.py`, `vision/UNIFICACIO_FINAL/BLOC3.py` | Vértices frontales/perspectiva → medidas cm y volumen cm³ | Fórmulas inspeccionadas E18; sin ensayo métrico | E | Distancia/focal/resolución fijas; no usa LiDAR en vivo ni JSON de calibración | Calibración y distancia reales | Aplazar precisión volumétrica a después de la primera cadena de inventario |
| Códigos ROS2 | `ros2/dron_percepcion/dron_percepcion/barcode_detector.py` | JPEG+última pose → `/barcode/detection` y ROI | E19; sin ZBar/cámara ejecutados | P | No sincroniza timestamps; posición inicial cero; JSON sin z, tiempo, frame ni imagen | Cámara, pose válida y almacenamiento | Definir observación trazable |
| Grabación imagen+pose | `.../telemetry_publisher.py`, `tools/receptordron.py` | Cámara+última pose → imagen/log de texto | E20; inspección, sin ejecución | E | Falsa sincronización; receptor borra JPG antiguos; orientación incompleta | Flujo independiente del de GCS | Preservar responsabilidad y migrar a sesión segura |
| Inventario persistente integrado | GCS, estados Python y SQLite de misión | Código parcial en memoria y exportación CSV manual | E21; búsqueda de lectores/escritores | N | No hay servicio integrado de observaciones/productos con recuperación y trazabilidad | Esquema, identificadores, imagen+pose, API GCS | Construir mínimo persistente reutilizando detección existente |
| GCS Electron | `gcs/main.js`, `renderer/app.js`, `index.html` | ROSLIB/HTTP → paneles; botones → JSON | E22; revisión estática, sin Electron/Node | P | `goto`/`vel_stop` sin gestor; servicios SLAM Toolbox ajenos a Point-LIO; sin acuses | rosbridge, backend coherente | Verificar contrato UI/backend con dobles |
| Arranque y despliegue | `raspberry/*.sh`, `*.service`, `ros2/*/setup.py` | Configuración → procesos ROS2 | Cinco `bash -n`; 13 entradas válidas E03/E24 | P | Humble/Jazzy mezclados; dependencias incompletas; arranques alternativos | SO, distribución, usuario y servicios reales | Validación de instalación en entorno aislado |
| Simulación y diagnóstico | `sim/`, `tools/`, `.../simulador_dron.py`, `.../simulacion_montecarlo.py` | Entradas sintéticas → poses/gráficos | E23/E25; sin ejecutar simulaciones | E | Simulador simple sin dt; Monte Carlo escribe al importar; SITL solo declarado | Entorno de simulación separado | Archivar experimento tras confirmar usos; priorizar pruebas reproducibles |
| Material retirado y documentación previa | Historial Git; `docs/estado/`, `gcs/docs/` | Diseños, manuales y resultados anteriores | Diferencias Git E02/E26/E27 | H | Rutas antiguas y afirmaciones de integración no acreditadas | Revisión humana | Mantener como histórico, sin reutilizar afirmaciones como pruebas |

## Bloqueos y próximos hitos

1. **Contrastar el equipo declarado.** EDISA debe confirmar X500 V2/Pixhawk 6X/Pi 5/L2/Camera Module 3, qué está montado y operativo, firmware, SO y variante de cámara. El contenido de los kits no sustituye una inspección física. E28/E33–E35.
2. **Estabilizar instalación y contratos.** Elegir provisionalmente un entorno reproducible, resolver dependencias declaradas y acordar topics, frames, unidades y tiempos. La incompatibilidad anterior `/Odometry` → `/slam/odom` ya está corregida en código (E36); siguen pendientes frames, validez temporal y ejecución integrada.
3. **Primera demostración sin vuelo.** Reproducir una imagen con código conocido y pose conocida, guardar una observación persistente y verla en la GCS tras reiniciar. Usar una sesión nueva y comprobar hashes de entradas.
4. **Navegación en simulación.** Un solo coordinador y una sola salida de control; estados, límites, pérdida de pose/enlace y cancelación verificables.
5. **Banco y entorno controlado.** Solo tras validar transformaciones, continuidad de consignas, autoridad del operador y comportamiento de fallos. Esta revisión no habilita vuelo real.

La arquitectura detallada y el alcance de cada conexión están en [02](02_Arquitectura_y_Decisiones.md); el plan priorizado, en [03](03_Limpieza_y_Verificacion.md).
