# Preparación de la reunión técnica con EDISA

**Borrador — 15/10/2026.** Base: `feature/AiM` / `2c90052`. Documentación preparada mediante revisión del repositorio, pruebas con dobles y comprobaciones estáticas. No acredita una demostración autónoma ni una inspección física.

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
| Hardware | El ordenador embarcado coordinaría sensores y controladora. El repositorio solo permite identificar referencias de diseño. | Inventario físico por completar; ningún componente confirmado por inspección. [04](04_Inventario_Componentes_Dron.md), E28. |
| LiDAR y Point-LIO | El driver publica nube/IMU; Point-LIO estima pose y genera mapa. | Interfaces implementadas por código; ejecución actual y calidad sin reproducir. E04–E06. |
| Misión | Hay un coordinador con JSON y otro con SQLite. | No hay una misión operativa única ni gestión completa de estados. E07–E08. |
| Vuelo y comunicación | MAVROS y el puente propio son alternativas distintas, no intercambiables por tener topics con nombres parecidos. | El puente propio cubre telemetría y cinco órdenes; no consume setpoints de navegación. Firmware real pendiente. E09–E12. |
| Cámara | Hay adquisición ROS2, HTTP/MJPEG y otra vía imagen+pose. | Es necesario consolidar adquisición y verificar tiempos/orientación. E13–E14/E20. |
| Visión | Se conservan YOLO-World/SAM, GroundingDINO/SAM, códigos y volumetría. | Pruebas de encaminamiento aprobadas; precisión ML y medidas físicas sin validar aquí. E16–E18. |
| Inventario | Existen estructuras de inventario en memoria y visualización/exportación de códigos. | Falta almacenamiento durable de observaciones con imagen y ubicación trazables. SQLite actual almacena misiones. E19–E21. |
| GCS | Electron presenta telemetría, mapa, cámaras y detecciones mediante rosbridge/HTTP. | UI parcial; hay órdenes sin gestor y servicios de mapa incompatibles. No ejecutada en esta auditoría. E22. |
| Pruebas y despliegue | El código ha sido reorganizado en paquetes y conserva tests de captura. | 46 tests aprobados con dobles; 13 entradas ROS2 válidas estáticamente; entorno de despliegue por homogeneizar. E03/E24–E25. |

## Puntos que deben explicarse con precisión

- La reorganización facilita mantenimiento, pero no ha resuelto automáticamente las conexiones. `/slam/odom` y `/Odometry` siguen sin coincidir en varios componentes.
- No debe afirmarse que existe inventario SQLite integrado ni que las órdenes de misión alcanzan siempre la controladora. La GCS muestra envíos, no acuses de ejecución.
- La captura segura protege las dos pipelines principales de volumetría. Siguen existiendo scripts independientes que borran imágenes o sustituyen resultados/configuración.
- La guía SITL aporta experiencia declarada en otro equipo; esta revisión no reproduce vuelo simulado ni certifica hardware.
- La ubicación del dron puede acompañar a una observación. Para hablar de ubicación exacta de la caja hace falta definir geometría, estantería y precisión exigida.

## Decisiones y preguntas para EDISA

| ID | Pregunta / decisión | Quién debe aportar información | Cierre esperado |
|---|---|---|---|
| D01 | ¿Qué controladora y firmware están disponibles? ¿Se conservarán? | Responsable de hardware | Modelo/versión contrastados; selección del adaptador de vuelo después de esa confirmación. |
| D02 | ¿Qué ordenador, SO, LiDAR y cámaras forman el equipo real? | Responsable del equipo | Inventario con fotos, conexiones, disponibilidad y responsable. |
| D03 | ¿Qué significa un registro de inventario: producto, caja, unidad logística o lectura? | Responsable del proceso de almacén | Identificadores, duplicados, relación con estantería, precisión y campos obligatorios. |
| D04 | ¿Cómo se representará la ubicación: estantería o coordenadas de mapa? | Responsable técnico y de almacén | Convenio de referencia, unidades y tolerancia; posición del dron separada de posición del producto. |
| D05 | ¿Dónde se ejecutará la inferencia y qué latencia es aceptable? | Responsable técnico | Recursos disponibles y criterio de selección entre pipelines. |
| D06 | ¿Podemos usar imágenes/poses de prueba y conservarlas con su procedencia? | Responsable de datos | Conjunto de prueba autorizado, códigos esperados y retención de evidencias. |
| D07 | ¿Qué scripts siguen ejecutándose manualmente o desde equipos externos? | Desarrolladores y operadores | Usuarios de Monte Carlo, receptor, `detect_CB.py`, scripts y servicios antes de archivar. |
| D08 | ¿Quién valida seguridad y autoriza banco/entorno controlado? | Responsable de operación | Responsable, procedimiento y criterios previos; la limpieza no autoriza vuelo. |
| D09 | ¿Se acepta como primer hito una observación durable visible en GCS sin vuelo? | Responsable del proyecto | Alcance y criterios de aceptación de [02](02_Arquitectura_y_Decisiones.md). |
| D10 | ¿Dónde se revisan y aprueban documentos e inventario en SharePoint? | Responsable documental | Carpeta, permisos y responsables de revisión; carga manual posterior. |

Si D01/D02 quedan pendientes, se puede continuar con reproducción offline e instalación aislada. No es necesario decidir hoy una arquitectura de vuelo para probar persistencia y trazabilidad.

## Acciones recomendadas para acordar

1. Completar inspección y versión de hardware con la ficha preliminar.
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
