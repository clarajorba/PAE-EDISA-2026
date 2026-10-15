# Guion de presentación técnica

**Borrador para EDISA — 15/10/2026 — base `feature/AiM` / `2c90052`.**

Duración propuesta: **18 minutos**, 12 diapositivas. Los identificadores E remiten a [07_Matriz_Evidencias.md](07_Matriz_Evidencias.md). No utilizar imágenes de resultados históricos como prueba de una ejecución integrada actual. Todos los diagramas propuestos deben llevar la etiqueta «Propuesta».

## Diapositiva 1 — Objetivo y conclusión de la revisión

**Duración: 1 minuto.**

- Inspeccionar el almacén e identificar productos/cajas con ubicación trazable.
- Hay componentes reutilizables de localización, control, visión y GCS.
- La integración completa y el inventario persistente siguen pendientes.

**Visual sugerido:** misión → observación → inventario, con las conexiones pendientes marcadas.

**Notas:** «El objetivo de esta revisión es distinguir lo que existe de lo que podemos demostrar. La base actual permite avanzar sin comenzar desde cero, pero todavía no acredita el proceso completo».

**Evidencia:** E01, E07–E08, E16–E22; resumen [01](01_Estado_Actual_Proyecto.md).

## Diapositiva 2 — Qué ha cambiado en el repositorio

**Duración: 1 minuto.**

- Estructura por responsabilidades: `ros2`, `raspberry`, `gcs`, `vision`, `sim`, `tools`, `docs`.
- Nuevos paquetes ROS2 para percepción y servicios GCS.
- Captura y dos orquestadores conservados; `dron_bringup` aún vacío.

**Visual sugerido:** mapa simplificado de carpetas, con paquete ROS separado de nombre de carpeta.

**Notas:** «Se ha mejorado la organización y se han cambiado rutas de ejecución. Esto reduce dispersión, pero obliga a comprobar instalación, dependencias y enlaces; no equivale a una nueva validación funcional».

**Evidencia:** E01–E03/E24; comparación `c2ae251..2c90052`, tabla Git de [03](03_Limpieza_y_Verificacion.md).

## Diapositiva 3 — Hardware: referencias frente a realidad

**Duración: 1,5 minutos.**

- Software/documentos mencionan Raspberry Pi, Unitree, cámara y Pixhawk.
- Modelo real, firmware, cantidad y estado requieren inspección.
- PX4 en la guía SITL y ArduCopter en el puente son supuestos distintos.

**Visual sugerido:** cuatro componentes con etiqueta «Pendiente de verificación física» y extracto vacío de la ficha de inventario.

**Notas:** «No vamos a completar el inventario por inferencia a partir del código. Confirmar el equipo evita elegir una interfaz de vuelo que luego no corresponda al firmware instalado».

**Evidencia:** E04/E11/E25/E28/E29; ficha [04](04_Inventario_Componentes_Dron.md).

## Diapositiva 4 — Localización y mapa

**Duración: 1,5 minutos.**

- Unitree aporta nube e IMU; Point-LIO produce pose, odometría y TF.
- La salida es `/slam/odom`; parte del software espera `/Odometry`.
- Hay que definir transformación al cuerpo, calidad y antigüedad de pose.

**Visual sugerido:** driver → Point-LIO → pose normalizada; marcar el desacuerdo de topic y el frame pendiente.

**Notas:** «Point-LIO estima el movimiento de su referencia sensorial. Antes de usarlo para guiar el dron o localizar una lectura, deben quedar claros el origen, los ejes y la validez temporal».

**Evidencia:** E04–E06/E12/E19; conexiones C01–C04/C09/C14 de [02](02_Arquitectura_y_Decisiones.md).

## Diapositiva 5 — Navegación y comunicación con la controladora

**Duración: 2 minutos.**

- Dos coordinadores: misión JSON y misión SQLite.
- MAVROS recibe consignas ROS; el puente propio solo gestiona cinco órdenes JSON y telemetría.
- Faltan autoridad única, estados de misión y supervisión completa.

**Visual sugerido:** dos caminos paralelos; señalar que el setpoint de `brain_node` no entra en `mavlink_bridge`.

**Notas:** «La recomendación es elegir un coordinador y un adaptador de vuelo, reutilizando lectura de misión, progreso y telemetría. La elección de hardware se mantiene abierta; la guía de SITL orienta una prueba PX4/MAVROS, no certifica la controladora física».

**Evidencia:** E07–E12/E25; C05–C11 y alternativas de [02](02_Arquitectura_y_Decisiones.md).

## Diapositiva 6 — Cámara y protección de datos

**Duración: 1,5 minutos.**

- Las dos pipelines de volumetría usan sesiones independientes.
- 46 pruebas cubren captura y encaminamiento con fuentes simuladas.
- Siguen existiendo adquisiciones duplicadas y scripts con borrado fuera de esa protección.

**Visual sugerido:** entrada inmutable → sesión de captura → sesión de resultados; advertencia localizada sobre los scripts pendientes.

**Notas:** «La mejora de conservación está probada en temporales con dobles. No se ha probado un códec o stream real aquí. La garantía tampoco debe extenderse al receptor antiguo ni al detector de códigos independiente».

**Evidencia:** E13–E16/E20/E30; T01 y riesgos de [03](03_Limpieza_y_Verificacion.md).

## Diapositiva 7 — Visión, códigos y volumetría

**Duración: 1,5 minutos.**

- YOLO-World/SAM y GroundingDINO/SAM conservan detección, contornos y tracking.
- Hay lectura de códigos y lógica de estanterías reutilizable.
- Faltan evaluación comparable, checkpoint GroundingDINO y validación de medidas.

**Visual sugerido:** imagen → caja/código → contorno → medida; separar código identificado de volumen estimado.

**Notas:** «Para la primera cadena funcional basta una lectura identificada y trazable. La volumetría utiliza constantes y debe validarse con calibración y medidas conocidas antes de ofrecer precisión dimensional».

**Evidencia:** E16–E19/E27/E29/E31; las imágenes históricas no se han revalidado como resultado actual.

## Diapositiva 8 — Qué falta para tener inventario persistente

**Duración: 2 minutos.**

- La GCS acumula códigos en memoria y permite CSV manual.
- SQLite existente almacena misiones y waypoints.
- Falta una observación durable con imagen, tiempo, pose válida e identificadores.

**Visual sugerido:** ficha de observación propuesta con imagen/hash, código, timestamp, frame y pose.

**Notas:** «Ver una fila en la interfaz no significa que se haya guardado. La prueba decisiva será reiniciar y recuperar el registro. También debemos acordar si la ubicación requerida es la estantería, la pose de observación o una coordenada del producto».

**Evidencia:** E08/E19–E21; C15/C18–C20 de [02](02_Arquitectura_y_Decisiones.md).

## Diapositiva 9 — GCS y arquitectura integrada propuesta

**Duración: 2 minutos.**

- Reutilizar Electron y sus paneles, corrigiendo contratos con backend.
- `goto` y `vel_stop` no tienen gestor en el puente propio; falta acuse.
- Propuesta: localización tipada, misión única, captura única e inventario consultable.

**Visual sugerido:** diagrama propuesto de [02](02_Arquitectura_y_Decisiones.md), simplificado a seis bloques.

**Notas:** «Mantendremos la interfaz, pero un estado de envío debe distinguirse de una orden aceptada y completada. Los servicios de mapa actuales pertenecen a SLAM Toolbox y no constituyen una API de Point-LIO».

**Evidencia:** E11/E22/E24; C10/C12/C21; decisiones propuestas, no implementadas.

## Diapositiva 10 — Qué se ha comprobado realmente

**Duración: 1,5 minutos.**

- 46 pruebas con dobles, 108 archivos Python, cinco scripts shell.
- 13 entradas ROS2 contrastadas estáticamente, JSON/XML y cuatro ayudas CLI.
- ROS/SITL, Electron, ML real y hardware no ejecutados en esta revisión.

**Visual sugerido:** matriz por niveles: estático y unitario con dobles, realizados; offline real, ROS/SITL reproducido y hardware, pendientes.

**Notas:** «La guía SITL describe resultados de otro equipo; los distinguimos de nuestras comprobaciones. Los tests actuales protegen archivos y rutas, no acreditan navegación ni precisión de visión».

**Evidencia:** T01–T08/E25/E32; [03](03_Limpieza_y_Verificacion.md).

## Diapositiva 11 — Primer hito verificable y límites de seguridad

**Duración: 1,5 minutos.**

- Reproducir imagen y pose conocidas, guardar observación y mostrarla en GCS.
- Repetir sin sobrescribir y recuperar datos tras reiniciar.
- Después: un waypoint en SITL, pérdida de pose/enlace, cancelación y emisor único.

**Visual sugerido:** tres hitos: inventario offline → navegación SITL → banco/entorno controlado con autorización específica.

**Notas:** «La primera demostración elimina dependencias de vuelo para comprobar utilidad y trazabilidad. Antes del movimiento real hay que demostrar límites, marcos, frescura y parada global; publicar ceros o matar un proceso no resuelve por sí solo la seguridad».

**Evidencia:** Carencias E06–E12/E19–E22; propuesta y aceptación en [02](02_Arquitectura_y_Decisiones.md); N02/N05/N06/N11 de [03](03_Limpieza_y_Verificacion.md).

## Diapositiva 12 — Decisiones y próximos pasos

**Duración: 1 minuto.**

- Confirmar hardware, firmware, SO y responsable de pruebas.
- Acordar registro de inventario, ubicación y criterio de primera demo.
- Validar empaquetado aislado y cerrar responsables/fechas.

**Visual sugerido:** tabla de decisiones pendientes con responsable y fecha por completar en la reunión.

**Notas:** «La revisión permite una reunión técnica útil con preguntas abiertas explícitas. No necesitamos presentar el sistema como terminado: necesitamos acordar el siguiente resultado que podamos verificar».

**Evidencia:** [05_Reunion_Tecnica_EDISA.md](05_Reunion_Tecnica_EDISA.md), D01–D10; plan N01–N14; inventario HW01–HW16.
