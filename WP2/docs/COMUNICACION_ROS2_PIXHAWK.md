# Comunicación ROS 2 ↔ Pixhawk (PX4): de la tecla al motor

Este documento explica, paso a paso, cómo una orden generada en un nodo ROS 2 llega
hasta los motores del DJI Flame Wheel F550 pasando por MAVROS, MAVLink y el firmware
PX4.

---

## 1. Vista general de la pila

```
┌─────────────────────────────────────────────────────────────┐
│  PC / WSL2                                                   │
│                                                              │
│  pixhawk_menu_node  ←──topics──→  mavros_node (MAVROS)      │
│       (Python / ROS 2)                   │                   │
│                                    serializa a              │
│                                    MAVLink                   │
└─────────────────────────────────────────────────┬───────────┘
                                                  │ USB  (serial)
                                         /dev/ttyACM0  921600 baud
                                                  │
┌─────────────────────────────────────────────────▼───────────┐
│  Pixhawk (hardware)                                          │
│                                                              │
│  PX4 firmware                                                │
│    ├─ Commander  (modos, arme)                               │
│    ├─ MPC (controlador de posición/velocidad)                │
│    ├─ Attitude controller                                    │
│    └─ Mixer  →  PWM  →  ESC x6  →  Motores F550             │
└─────────────────────────────────────────────────────────────┘
```

Hay **cuatro capas** diferenciadas:

| Capa | Qué hace | Tecnología |
|------|----------|------------|
| Aplicación | Genera órdenes (menú, misión) | Python / ROS 2 |
| Transporte ROS 2 | Pub/sub y servicios | DDS (rmw_fastrtps) |
| Puente | Convierte msgs ROS 2 ↔ MAVLink | MAVROS |
| Protocolo dron | Telemetría y control serie | MAVLink v2 |

---

## 2. MAVLink: el idioma del dron

MAVLink es un protocolo binario ligero diseñado para vehículos autónomos.
Cada **mensaje** tiene:

```
Byte 0   : STX (marcador de inicio, 0xFD para v2)
Byte 1   : LEN (longitud del payload)
Byte 2-3 : SEQ, flags
Byte 4-5 : System ID, Component ID (quién envía)
Byte 6-8 : Message ID  (qué tipo de mensaje)
Bytes ...: Payload (los datos, little-endian)
Bytes -2: CRC (checksum de 2 bytes)
```

Los mensajes relevantes para este proyecto:

| ID MAVLink | Nombre | Dirección | Contenido |
|------------|--------|-----------|-----------|
| 76 | `COMMAND_LONG` | PC → Pixhawk | Armar, cambiar modo, despegar |
| 84 | `SET_POSITION_TARGET_LOCAL_NED` | PC → Pixhawk | Setpoint velocidad/posición |
| 0  | `HEARTBEAT` | bidireccional | Estado del sistema |
| 32 | `LOCAL_POSITION_NED` | Pixhawk → PC | Posición estimada |
| 65 | `RC_CHANNELS` | Pixhawk → PC | Canales RC |

---

## 3. MAVROS: el puente

MAVROS (`ros-jazzy-mavros`) es un nodo ROS 2 que:

1. Mantiene abierta la conexión serie con el Pixhawk.
2. Escucha topics ROS 2 y los **serializa a MAVLink** para enviarlos.
3. Recibe tramas MAVLink del Pixhawk y las **deserializa a topics ROS 2**.

```
  Topic ROS 2                       Mensaje MAVLink
  ─────────────────────────────────────────────────
  /mavros/setpoint_velocity/        SET_POSITION_TARGET_LOCAL_NED
    cmd_vel_unstamped    ──────►    (ID 84)  [vx, vy, vz en NED]

  /mavros/state          ◄──────    HEARTBEAT (ID 0)
                                    SYS_STATUS (ID 1)

  /mavros/local_position/pose◄────  LOCAL_POSITION_NED (ID 32)

  /mavros/cmd/arming     ──────►    COMMAND_LONG (ID 76)
    (servicio ROS 2)                MAV_CMD_COMPONENT_ARM_DISARM

  /mavros/set_mode       ──────►    COMMAND_LONG (ID 76)
    (servicio ROS 2)                MAV_CMD_DO_SET_MODE

  /mavros/cmd/takeoff    ──────►    COMMAND_LONG (ID 76)
    (servicio ROS 2)                MAV_CMD_NAV_TAKEOFF
```

---

## 4. Transformación de coordenadas: ENU ↔ NED

Este es el punto más importante y más fuente de errores.

ROS 2 y el Pixhawk/PX4 usan **marcos de referencia distintos**:

```
ROS 2 usa ENU                    MAVLink/PX4 usa NED
(East-North-Up)                  (North-East-Down)

        Z (arriba)                       X (Norte)
        │                                │
        │                                │
        └───── Y (Norte)         Z───────┘
       /                        (abajo)   \
      X (Este)                             Y (Este)
```

Equivalencias:

| Componente en el código ROS 2 | Equivalente físico | Después en MAVLink/NED |
|-------------------------------|-------------------|------------------------|
| `twist.linear.x = +0.3` | +Este | `vy = +0.3` |
| `twist.linear.y = +0.3` | +Norte | `vx = +0.3` |
| `twist.linear.z = +0.3` | +Arriba | `vz = -0.3` ← **signo invertido** |

MAVROS aplica esta conversión automáticamente antes de serializar.
El código nunca toca esa transformación; solo escribe valores en ENU y MAVROS
se encarga del resto.

**Ejemplo concreto** — cuando el usuario pulsa `[w]` (mover Norte):

```python
# pixhawk_menu_node.py  línea 208
self._enviar_vel(0.0, VEL, 0.0)
# cmd.linear.x = 0.0   (sin componente Este)
# cmd.linear.y = 0.3   (Norte en ENU)
# cmd.linear.z = 0.0   (sin componente vertical)
```

MAVROS convierte esto al mensaje MAVLink (ID 84):

```
SET_POSITION_TARGET_LOCAL_NED
  coordinate_frame = MAV_FRAME_LOCAL_NED
  type_mask        = ignora posición, usa solo velocidad
  vx = +0.3   (Norte en NED  ← era linear.y en ENU)
  vy =  0.0   (Este  en NED  ← era linear.x en ENU)
  vz =  0.0   (Abajo en NED  ← linear.z=0, sin cambio)
```

---

## 5. Flujo completo: de la tecla al motor

### 5.1 Paso 1 — El nodo publica el Twist

```
pixhawk_menu_node._timer_vel()   [cada 100 ms, timer ROS 2]
  └─► self._vel_pub.publish(cmd)
       topic: /mavros/setpoint_velocity/cmd_vel_unstamped
       tipo:  geometry_msgs/Twist
       dato:  linear.x=0  linear.y=0.3  linear.z=0
```

### 5.2 Paso 2 — MAVROS recibe y convierte

El proceso `mavros_node` (externo, del paquete MAVROS) está suscrito a ese topic.
Al recibir el Twist:

1. Aplica rotación ENU → NED.
2. Rellena el payload del mensaje MAVLink 84.
3. Escribe la trama binaria en el puerto serie `/dev/ttyACM0` a 921 600 baud.

La trama binaria viaja por el cable USB en ~1 ms.

### 5.3 Paso 3 — PX4 recibe el mensaje

El módulo `mavlink` de PX4 escucha el puerto serie.
Al detectar un mensaje ID 84:

1. Valida el CRC.
2. Publica en el bus uORB interno: `vehicle_local_position_setpoint`.

### 5.4 Paso 4 — Controlador de posición/velocidad (MPC)

El módulo `mc_pos_control` de PX4 lee ese setpoint de velocidad y, con la posición
estimada (del EKF2, fusión de IMU + GPS/flujo óptico), calcula el **error de velocidad**
y genera un setpoint de aceleración horizontal → convierte a **ángulo de inclinación**
(roll / pitch) necesario para producir esa aceleración.

```
vx_deseada = +0.3 m/s Norte
vx_actual  = +0.0 m/s   (parado)
─────────────────────────────────
error = 0.3 m/s  →  pitch necesario ≈ -3°  (inclinarse hacia delante)
```

### 5.5 Paso 5 — Controlador de actitud

El módulo `mc_att_control` recibe el setpoint de actitud (roll, pitch, yaw, thrust)
y usa un controlador PID para compararlo con la actitud real (IMU) y producir
**setpoints de velocidad angular**.

### 5.6 Paso 6 — Mixer y PWM

El módulo `mixer` toma las demandas de roll/pitch/yaw/thrust y las distribuye entre
los 6 motores del F550 según su geometría.

```
     Motor 1 (delante-izq)   Motor 2 (delante-der)
     Motor 3 (izq)            Motor 4 (der)
     Motor 5 (atrás-izq)     Motor 6 (atrás-der)

Para inclinar hacia delante (pitch negativo):
  Motores traseros (5,6) ↑   Motores delanteros (1,2) ↓
```

Cada motor recibe una señal **PWM** (típicamente 1000–2000 µs) a ~400 Hz.

### 5.7 Paso 7 — ESC y motor BLDC

Cada ESC interpreta el pulso PWM, controla la corriente en las bobinas del motor
BLDC (sin escobillas) mediante conmutación de MOSFETs, y ajusta las RPM en
milisegundos.

---

## 6. Modo OFFBOARD: por qué hay que publicar a ≥ 10 Hz

PX4 tiene un watchdog sobre los setpoints externos: si no llega ninguno en
**500 ms**, abandona OFFBOARD y vuelve al modo anterior (normalmente HOLD).
Por eso el nodo tiene un timer que publica cada 100 ms (10 Hz), incluso cuando
el dron está quieto (publica `Twist` con todos los campos a cero).

```python
# pixhawk_menu_node.py  línea 51
self.create_timer(1.0 / TASA_HZ, self._timer_vel)   # TASA_HZ = 10

# línea 76-82
def _timer_vel(self):
    with self._lock:
        if time.time() > self._activo_hasta:
            self._cmd_vel = Twist()      # ← setpoint cero si venció la duración
        cmd = self._cmd_vel
    self._vel_pub.publish(cmd)           # ← publica SIEMPRE, aunque sea cero
```

Además, PX4 requiere que ya haya setpoints en cola **antes** de que se cambie al
modo OFFBOARD. Por eso la secuencia correcta es:

```
1. Arrancar el nodo  (empieza a publicar 0,0,0 a 10 Hz)
2. Esperar ~2 s
3. [3] Cambiar a OFFBOARD
4. [1] Armar
5. [4] Despegar
6. Enviar comandos de movimiento
```

---

## 7. Servicios ROS 2: cómo funciona la llamada a un servicio

Los comandos de armar, cambiar modo y despegar no usan topics sino **servicios**
(patrón petición-respuesta, equivalente a una llamada RPC).

```
pixhawk_menu_node                    MAVROS                      Pixhawk
      │                                │                              │
      │  CommandBool.Request           │                              │
      │   value = True                 │                              │
      ├───────────────────────────────►│                              │
      │                                │  COMMAND_LONG (MAVLink 76)   │
      │                                │   cmd = ARM_DISARM           │
      │                                │   param1 = 1.0 (armar)       │
      │                                ├─────────────────────────────►│
      │                                │                              │ valida
      │                                │  COMMAND_ACK (MAVLink 77)    │ prearm
      │                                │   result = MAV_RESULT_ACCEPTED│
      │                                │◄─────────────────────────────┤
      │  CommandBool.Response          │                              │
      │   success = True               │                              │
      │◄───────────────────────────────┤                              │
```

El código usa `call_async` para no bloquear el hilo de ROS 2 mientras espera
la respuesta del Pixhawk (que puede tardar hasta ~500 ms si hay latencia en la
comunicación serie).

---

## 8. Telemetría de vuelta: cómo el nodo sabe dónde está el dron

```
Pixhawk (PX4)
  └─ EKF2 fusiona: IMU + GPS + barómetro + (flujo óptico opcional)
       └─ publica LOCAL_POSITION_NED (MAVLink ID 32) a 30 Hz

MAVROS recibe la trama, convierte NED → ENU, publica:
  /mavros/local_position/pose  (geometry_msgs/PoseStamped)
    pose.position.x = Este (m)
    pose.position.y = Norte (m)
    pose.position.z = Altitud (m, positivo arriba)
    pose.orientation = quaternion de actitud

pixhawk_menu_node._pose_cb() almacena x, y, z y los muestra en el menú:
  Pos : N=+0.00  E=+0.00  Alt=0.00 m
```

El topic `/mavros/state` recibe el HEARTBEAT del Pixhawk (1 Hz) y expone:
- `armed` (bool): si los motores están armados
- `mode` (string): modo de vuelo actual (`MANUAL`, `OFFBOARD`, `AUTO.LAND`, etc.)
- `connected` (bool): si hay comunicación activa con el Pixhawk

---

## 9. Resumen del flujo de datos (diagrama de secuencia)

```
Usuario   pixhawk_menu_node    MAVROS          PX4 (Pixhawk)        ESC+Motor
  │              │                │                  │                   │
  │ pulsa [w]    │                │                  │                   │
  ├─────────────►│                │                  │                   │
  │              │ Twist(y=0.3)   │                  │                   │
  │              ├───────────────►│                  │                   │
  │              │                │ SET_POS_TARGET   │                   │
  │              │                │ _NED (vx=0.3)    │                   │
  │              │                ├─────────────────►│                   │
  │              │                │                  │ MPC calcula       │
  │              │                │                  │ pitch setpoint    │
  │              │                │                  │ att_ctrl → PID    │
  │              │                │                  │ mixer → PWM       │
  │              │                │                  ├──────────────────►│
  │              │                │                  │                   │ RPM↑/↓
  │              │                │                  │                   │
  │  (100 ms después)             │                  │                   │
  │              │ Twist(0,0,0)   │                  │                   │
  │              ├───────────────►│  (watchdog reset)│                   │
  │              │                │ SET_POS_TARGET   │                   │
  │              │                │ (vx=0)           │                   │
  │              │                ├─────────────────►│                   │
  │              │                │                  │ pitch → 0°        │
  │              │                │                  ├──────────────────►│
  │              │                │                  │                   │ RPM=hover
  │              │ LOCAL_POS_NED  │                  │                   │
  │              │◄───────────────┤◄─────────────────┤                   │
  │ menú         │                │                  │                   │
  │ actualizado  │                │                  │                   │
```

---

## 10. Parámetros de la conexión serie

| Parámetro | Valor |
|-----------|-------|
| Puerto | `/dev/ttyACM0` (USB virtual CDC) |
| Baudrate | 921 600 bps |
| Bits de datos | 8 |
| Paridad | Ninguna |
| Bits de stop | 1 |
| Control de flujo | Ninguno |

El Pixhawk expone el puerto USB como un CDC-ACM virtual (la misma clase que un
Arduino). No es necesario ningún adaptador FTDI. A 921 600 bps, un mensaje
MAVLink típico de 20 bytes tarda ~0,2 ms en transmitirse.

---

## 11. Qué pasa si se corta la conexión

| Evento | Reacción PX4 |
|--------|-------------|
| No llegan setpoints OFFBOARD > 500 ms | Sale de OFFBOARD → entra en HOLD (flota en su posición) |
| No llega HEARTBEAT del GCS > 3 s | Puede activar `COM_OBL_ACT` (aterrizaje de emergencia) |
| Pérdida total de MAVLink | Depende de `NAV_DLL_ACT`: aterrizar / RTL / mantener |

Esto explica el doble rol del timer en `pixhawk_menu_node`: mantener el
watchdog vivo aunque el dron no se esté moviendo.
