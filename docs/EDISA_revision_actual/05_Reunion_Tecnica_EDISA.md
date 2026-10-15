# Preparación de la reunión técnica con EDISA


## Resultado esperado de la reunión

Compartir una imagen precisa del sistema existente y acordar un primer hito verificable, las decisiones de hardware pendientes y los responsables de las siguientes validaciones. La recomendación es reutilizar los componentes actuales y cerrar contratos e integraciones antes de ampliar funcionalidades.

## Agenda propuesta: 40 minutos

| Tiempo | Tema | Resultado buscado |
|---|---|---|
| 0–3 min | Objetivo de inventario y alcance de la revisión | Acordar qué debe demostrar el sistema. |
| 3–21 min | Presentación técnica de 18 minutos: [guion de 12 diapositivas](06_Guion_Presentacion.md) | Entender qué existe, qué se ha verificado y dónde se rompe la cadena. |
| 21–29 min | Hardware, firmware y arquitectura | Resolver o asignar responsable a cada decisión bloqueante. |
| 29–35 min | Primera demostración y plan de validación | Aprobar criterios de aceptación y datos de prueba. |
| 35–40 min | Responsables, evidencias y próximos pasos | Cerrar acciones, fechas propuestas y pendientes. |

## Explicación breve de los componentes

| Componente | Explicación para la reunión | Mensaje de estado y evidencia |
|---|---|---|
| Hardware | El equipo declara X500 V2/Pixhawk 6X, Raspberry Pi 5 (kit DB-TRONIC), Unitree 4D LiDAR L2 y Camera Module 3 — variante pendiente de confirmar. | Identificación comunicada el 14/10/2026; contenido de kit separado de inspección/funcionamiento. [04](04_Inventario_Componentes_Dron.md), E28/E33–E35. |
| LiDAR y Point-LIO | El driver publica nube/IMU; Point-LIO estima pose y genera mapa. | Interfaces implementadas por código; ejecución actual y calidad sin reproducir. E04–E06. |
| Misión | Hay un coordinador con JSON y otro con SQLite. | No hay una misión operativa única ni gestión completa de estados. E07–E08. |
| Vuelo y comunicación | MAVROS y el puente propio son alternativas distintas, no intercambiables por tener topics con nombres parecidos. | El puente propio cubre telemetría y cinco órdenes; no consume setpoints de navegación. Firmware real pendiente. E09–E12. |
| Cámara | Hay adquisición ROS2, HTTP/MJPEG y otra vía imagen+pose. | Es necesario consolidar adquisición y verificar tiempos/orientación. E13–E14/E20. |
| Visión | Se conservan YOLO-World/SAM, GroundingDINO/SAM, códigos y volumetría. | Pruebas de encaminamiento aprobadas; precisión ML y medidas físicas sin validar aquí. E16–E18. |
| Inventario | Existen estructuras de inventario en memoria y visualización/exportación de códigos. | Falta almacenamiento durable de observaciones con imagen y ubicación trazables. SQLite actual almacena misiones. E19–E21. |
| GCS | Electron presenta telemetría, mapa, cámaras y detecciones mediante rosbridge/HTTP. | UI parcial; hay órdenes sin gestor y servicios de mapa incompatibles. No ejecutada en esta auditoría. E22. |
| Pruebas y despliegue | El código ha sido reorganizado en paquetes y conserva tests de captura. | 46 tests aprobados con dobles; 13 entradas ROS2 válidas estáticamente; entorno de despliegue por homogeneizar. E03/E24–E25. |

## Puntos que deben explicarse con precisión

- La reorganización facilita mantenimiento, pero no completa las conexiones. El desacuerdo anterior `/Odometry` → `/slam/odom` ya está corregido en los tres consumidores contrastados (E36); frames, frescura e integración real siguen pendientes.
- No debe afirmarse que existe inventario SQLite integrado ni que las órdenes de misión alcanzan siempre la controladora. La GCS muestra envíos, no acuses de ejecución.
- La captura segura protege las dos pipelines principales de volumetría. Siguen existiendo scripts independientes que borran imágenes o sustituyen resultados/configuración.
- La guía SITL aporta experiencia declarada en otro equipo; esta revisión no reproduce vuelo simulado ni certifica hardware.
- La ubicación del dron puede acompañar a una observación. Para hablar de ubicación exacta de la caja hace falta definir geometría, estantería y precisión exigida.

## Decisiones y preguntas para EDISA

| ID | Pregunta / decisión | Quién debe aportar información | Cierre esperado |
|---|---|---|---|
| D01 | ¿Se confirma Pixhawk 6X, con qué revisión, firmware y versión instalados? ¿Se conservarán? | Responsable de hardware | Etiqueta/modelo y firmware contrastados; no deducir PX4 del nombre del kit. Elegir adaptador después. |
| D02 | ¿EDISA confirma X500 V2, Pi 5 (DB-TRONIC), Unitree L2 y una Camera Module 3? ¿Qué piezas y accesorios están disponibles, montados y operativos? | Responsable del equipo | Inventario contrastado, recuentos reales, fotos, ubicación y responsable; separar declaración y prueba. |
| D03 | ¿Qué significa un registro de inventario: producto, caja, unidad logística o lectura? | Responsable del proceso de almacén | Identificadores, duplicados, relación con estantería, precisión y campos obligatorios. |
| D04 | ¿Cómo se representará la ubicación: estantería o coordenadas de mapa? | Responsable técnico y de almacén | Convenio de referencia, unidades y tolerancia; posición del dron separada de posición del producto. |
| D05 | ¿Qué RAM, SO y distribución/versión ROS2 tiene Pi 5? ¿Dónde se ejecutará la inferencia y con qué latencia objetivo? | Responsable técnico | Configuración real registrada y recursos para seleccionar pipeline; RAM no inferida del catálogo. |
| D06 | ¿Podemos usar imágenes/poses de prueba y conservarlas con su procedencia? | Responsable de datos | Conjunto de prueba autorizado, códigos esperados y retención de evidencias. |
| D07 | ¿Qué scripts siguen ejecutándose manualmente o desde equipos externos? | Desarrolladores y operadores | Usuarios de Monte Carlo, receptor, `detect_CB.py`, scripts y servicios antes de archivar. |
| D08 | ¿Qué comprobaciones de integración y seguridad ya se han realizado, con qué evidencias? ¿Quién autoriza las siguientes pruebas? | Responsable de operación | Registros y responsable; separar inspección, banco, SITL y vuelo. La identificación del kit no autoriza movimiento. |
| D09 | ¿Se acepta como primer hito una observación durable visible en GCS sin vuelo? | Responsable del proyecto | Alcance y criterios de aceptación de [02](02_Arquitectura_y_Decisiones.md). |
| D10 | ¿Dónde se revisan y aprueban documentos e inventario en SharePoint? | Responsable documental | Carpeta, permisos y responsables de revisión; carga manual posterior. |
| D11 | ¿Qué variante y óptica tiene Camera Module 3? ¿Cuáles son la red, alimentación, montaje y calibración efectivos del L2 y la cámara? | Responsable de sensores | Modelo/óptica, CSI, configuración de red, orientación y extrínsecas con evidencia. |
| D12 | ¿Qué batería, cargador, RC, radio/enlaces y reguladores se usan? ¿Se confirma la referencia y el marcado 433 MHz de la SiK? ¿Cómo se alimenta Pi 5 a bordo? | Responsable eléctrico y de comunicaciones | Esquema y equipos identificados; fuente externa de 27 W separada de batería y alimentación de vuelo. |

Si D01/D02 quedan pendientes, se puede continuar con reproducción offline e instalación aislada. No es necesario decidir hoy una arquitectura de vuelo para probar persistencia y trazabilidad.

## Acciones recomendadas para acordar

1. Contrastar los modelos declarados, completar el recuento, firmware/versión, SO/ROS2, variante de cámara y montaje con la ficha preliminar; no repetir la identificación como si no existiera información del equipo.
2. Validar en entorno aislado el empaquetado reciente y sus dependencias, sin iniciar nodos.
3. Definir contrato mínimo de observación y un conjunto de entrada reproducible.
4. Decidir si se protegen o archivan los scripts con borrado, después de confirmar usos externos.
5. Programar la demostración imagen+pose→persistencia→GCS; después, navegación en SITL.

Cada acción debe terminar con un responsable y una fecha acordados en reunión; no se asignan personas ni fechas de entrega sin confirmación.

## Estructura sugerida de SharePoint

```text
Proyecto_Dron_EDISA/
  01_Estado_proyecto/
    01_Estado_Actual_Proyecto.md
  02_Arquitectura_software/
    02_Arquitectura_y_Decisiones.md
  03_Limpieza_y_validacion/
    03_Limpieza_y_Verificacion.md
    07_Matriz_Evidencias.md
    Evidencias_de_pruebas/
  04_Inventario_hardware/
    04_Inventario_Componentes_Dron.md
    Fotos_y_fichas_validadas/
  05_Reuniones_tecnicas/
    05_Reunion_Tecnica_EDISA.md
    06_Guion_Presentacion.md
    Actas_y_decisiones/
  99_Documentacion_historica/
```

Mantener fecha, commit revisado, responsable de revisión y estado de aprobación en cada versión. Los documentos antiguos deben quedar identificados como históricos sin sobrescribirlos. No se ha creado esta estructura en SharePoint ni se ha cargado ningún archivo.

## Plantilla breve para el cierre de reunión

| Decisión o acción | Acuerdo | Responsable | Fecha objetivo | Evidencia necesaria | Pendiente |
|---|---|---|---|---|---|
| Por completar en la reunión | PENDIENTE | PENDIENTE | PENDIENTE | PENDIENTE | PENDIENTE |
