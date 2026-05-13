"""Nodo espía: verifica en tiempo real el pipeline cerebro → ENU → NED → MAVLink."""

import struct
import threading

from geometry_msgs.msg import PoseStamped, Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

# ---------------------------------------------------------------------------
# Constantes MAVLink v2  –  SET_POSITION_TARGET_LOCAL_NED (ID 84)
# ---------------------------------------------------------------------------
MSG_ID = 84
MAV_FRAME_LOCAL_NED = 1
# type_mask: ignorar posición (bits 0-2) y aceleración (bits 6-8) y yaw (9-10)
# → solo se usan vx, vy, vz
TYPE_MASK_VEL_ONLY = 0b11111000111  # 0x7C7

VEL = 0.3  # m/s usado en las teclas de entrada directa

# Colores ANSI
_R = '\033[91m'
_G = '\033[92m'
_Y = '\033[93m'
_B = '\033[94m'
_M = '\033[95m'
_C = '\033[96m'
_DIM = '\033[2m'
_RST = '\033[0m'
_BOLD = '\033[1m'

_TECLAS = {
    'w': (0.0,  VEL,  0.0, 'NORTE ↑'),
    's': (0.0, -VEL,  0.0, 'SUR   ↓'),
    'a': (-VEL, 0.0,  0.0, 'OESTE ←'),
    'd': (VEL,  0.0,  0.0, 'ESTE  →'),
    'r': (0.0,  0.0,  VEL, 'SUBIR ▲'),
    'f': (0.0,  0.0, -VEL, 'BAJAR ▼'),
}


def _payload_bytes(vx_ned: float, vy_ned: float, vz_ned: float) -> bytes:
    """Construir el payload completo de SET_POSITION_TARGET_LOCAL_NED."""
    return struct.pack(
        '<IfffffffffffHBBB',
        0,                   # time_boot_ms
        0.0, 0.0, 0.0,       # x, y, z  (posición, ignorada)
        vx_ned, vy_ned, vz_ned,
        0.0, 0.0, 0.0,       # afx, afy, afz (aceleración, ignorada)
        0.0, 0.0,            # yaw, yaw_rate (ignorados)
        TYPE_MASK_VEL_ONLY,
        1,                   # target_system
        1,                   # target_component
        MAV_FRAME_LOCAL_NED,
    )


def _frame_header(payload: bytes) -> bytes:
    """Construir cabecera MAVLink v2 (sin CRC, solo para visualización)."""
    return bytes([
        0xFD,            # STX
        len(payload),    # LEN
        0x00,            # incompat_flags
        0x00,            # compat_flags
        0x00,            # seq
        0xFF,            # sysid  (GCS = 255)
        0xBE,            # compid (190)
        MSG_ID & 0xFF,          # msg_id byte 0
        (MSG_ID >> 8) & 0xFF,   # msg_id byte 1
        (MSG_ID >> 16) & 0xFF,  # msg_id byte 2
    ])


def _hex(data: bytes, highlight_start: int = -1,
         highlight_len: int = 0) -> str:
    """Hexdump coloreado. Los bytes resaltados se muestran en amarillo."""
    parts = []
    for i, b in enumerate(data):
        if highlight_start <= i < highlight_start + highlight_len:
            parts.append(f'{_Y}{b:02X}{_RST}')
        else:
            parts.append(f'{_DIM}{b:02X}{_RST}')
    return ' '.join(parts)


def _arrow(val: float) -> str:
    if val > 0.01:
        return f'{_G}▲ +{val:.3f}{_RST}'
    if val < -0.01:
        return f'{_R}▼ {val:.3f}{_RST}'
    return f'{_DIM}  {val:.3f}{_RST}'


def _mostrar_transformacion(ex: float, ey: float, ez: float,
                            fuente: str, n: int,
                            target=None, pose=None) -> None:
    """Imprimir contexto del pipeline, tabla ENU→NED y trama MAVLink."""
    nx = ey    # Norte (NED-X) = ENU-Y
    ny = ex    # Este  (NED-Y) = ENU-X
    nz = -ez   # Abajo (NED-Z) = –ENU-Z

    sep = '─' * 66
    print(f'\n{sep}')
    print(f'  {_Y}[{fuente} #{n}]{_RST}')

    # --- Pipeline context (cerebro target + pose verification) ---
    if target is not None or pose is not None:
        print(f'  {_B}── Pipeline: cerebro → mavros_node → MAVROS → Pixhawk ──{_RST}')
        if target is not None:
            tx, ty, tz = target[0], target[1], target[2]
            print(f'  Cerebro target : x={tx:+.3f}  y={ty:+.3f}  z={tz:+.3f}'
                  f'  {_DIM}[frame ENU, misión]{_RST}')
        if pose is not None:
            px, py, pz = pose[0], pose[1], pose[2]
            print(f'  Pose actual    : x={px:+.3f}  y={py:+.3f}  z={pz:+.3f}'
                  f'  {_DIM}[frame ENU]{_RST}')
        if target is not None and pose is not None:
            ex_c = target[0] - pose[0]
            ey_c = target[1] - pose[1]
            ez_c = target[2] - pose[2]
            print(f'  Error esperado : Δx={ex_c:+.3f}  Δy={ey_c:+.3f}  Δz={ez_c:+.3f}')
            ok = abs(ex_c - ex) < 0.005 and abs(ey_c - ey) < 0.005 and abs(ez_c - ez) < 0.005
            tag = f'{_G}✓ OK{_RST}' if ok else f'{_R}✗ DIFIERE{_RST}'
            print(f'  cmd_vel recibido: Δx={ex:+.3f}  Δy={ey:+.3f}  Δz={ez:+.3f}  → {tag}')

    print(sep)

    # --- ENU → NED table ---
    print(f'  {"Eje":<10} {"ROS2 / ENU (Twist)":>22}   {"MAVLink / NED":>18}  Significado')
    print(f'  {"─"*10} {"─"*22}   {"─"*18}  {"─"*20}')

    rows = [
        ('X (Este)',   ex, ny, 'ENU-X -> NED-Y'),
        ('Y (Norte)',  ey, nx, 'ENU-Y -> NED-X'),
        ('Z (Arr/Ab)', ez, nz, 'ENU-Z -> NED-Z  (signo invertido)'),
    ]
    for i, (label, e_val, n_val, note) in enumerate(rows):
        e_str = f'linear.{"xyz"[i]} = {e_val:+.3f}'
        print(f'  {label:<12} {e_str:>22}  →  {_arrow(n_val):>18}  {_DIM}{note}{_RST}')

    # --- MAVLink frame ---
    header = _frame_header(b'')
    payload = _payload_bytes(nx, ny, nz)
    vel_offset = 4 + 12   # time_boot_ms(4B) + pos_xyz(12B)
    vel_len = 12

    print(f'\n  {_BOLD}Trama MAVLink v2 que envía MAVROS al Pixhawk:{_RST}')
    print(f'  {_DIM}STX  LEN  iflg cflg seq  sys  cmp  ── MSG_ID=84 ──{_RST}')
    print(f'  {_hex(header)}')
    print(f'\n  {_DIM}Payload ({len(payload)} bytes) — '
          f'bytes {vel_offset}–{vel_offset+vel_len-1} = velocidades NED (amarillo):{_RST}')
    print(f'  {_hex(payload, vel_offset, vel_len)}')

    vx_b, vy_b, vz_b = struct.unpack_from('<fff', payload, vel_offset)
    print(f'\n  {_DIM}Decodificado:{_RST}  '
          f'vx={_Y}{vx_b:+.3f}{_RST} m/s  '
          f'vy={_Y}{vy_b:+.3f}{_RST} m/s  '
          f'vz={_Y}{vz_b:+.3f}{_RST} m/s  {_DIM}(frame NED){_RST}')
    print(f'\n  {_DIM}type_mask = 0x{TYPE_MASK_VEL_ONLY:03X}  → '
          f'PX4 solo lee velocidad, ignora posición/aceleración{_RST}')


class EspiaMavros(Node):
    """Suscribe a cmd_vel y verifica el pipeline cerebro → MAVLink en cada mensaje."""

    def __init__(self):
        """Inicializar suscriptores, contador y hilo de entrada directa."""
        super().__init__('spy_mavros')
        self._n_topic = 0
        self._n_teclado = 0
        self._lock = threading.Lock()
        self._activo = True
        self._ultimo_target = None
        self._ultima_pose = None

        self.create_subscription(
            Twist,
            '/mavros/setpoint_velocity/cmd_vel_unstamped',
            self._cb_topic,
            10,
        )
        self.create_subscription(
            Float32MultiArray, '/cerebro/target', self._cb_target, 10)
        self.create_subscription(
            Float32MultiArray, '/drone/pose', self._cb_pose_sim, 10)
        self.create_subscription(
            PoseStamped, '/mavros/local_position/pose', self._cb_pose_mavros, 10)

        print(f'\n{_BOLD}{_C}=== SPY MAVROS – pipeline cerebro → MAVLink ==={_RST}')
        print(f'{_DIM}Escuchando: /mavros/setpoint_velocity/cmd_vel_unstamped{_RST}')
        print(f'{_DIM}Contexto  : /cerebro/target  /drone/pose  /mavros/local_position/pose{_RST}')
        print(f'{_DIM}Teclado   : {" ".join(_TECLAS)}  |  q = salir{_RST}\n')

        hilo = threading.Thread(target=self._bucle_teclado, daemon=True)
        hilo.start()

    def _cb_target(self, msg: Float32MultiArray) -> None:
        """Almacenar y mostrar el último target enviado por cerebro_node."""
        with self._lock:
            self._ultimo_target = list(msg.data)
            t = self._ultimo_target
        print(f'  {_C}[CEREBRO] target → x={t[0]:+.3f}  y={t[1]:+.3f}  z={t[2]:+.3f}{_RST}')

    def _cb_pose_sim(self, msg: Float32MultiArray) -> None:
        """Actualizar pose desde el simulador (Float32MultiArray [x,y,z,yaw])."""
        with self._lock:
            self._ultima_pose = list(msg.data[:3])

    def _cb_pose_mavros(self, msg: PoseStamped) -> None:
        """Actualizar pose desde MAVROS / Pixhawk real (PoseStamped)."""
        p = msg.pose.position
        with self._lock:
            self._ultima_pose = [p.x, p.y, p.z]

    def _cb_topic(self, msg: Twist) -> None:
        """Procesar Twist recibido del topic y mostrar la transformación."""
        ex, ey, ez = msg.linear.x, msg.linear.y, msg.linear.z
        es_movimiento = abs(ex) > 0.01 or abs(ey) > 0.01 or abs(ez) > 0.01

        with self._lock:
            self._n_topic += 1
            n = self._n_topic
            target = list(self._ultimo_target) if self._ultimo_target is not None else None
            pose = list(self._ultima_pose) if self._ultima_pose is not None else None

        if not es_movimiento:
            if n % 5 == 0:
                print(f'  {_DIM}[topic #{n:4d}] idle  ENU(0,0,0) → NED(0,0,0){_RST}')
            return

        _mostrar_transformacion(ex, ey, ez, 'TOPIC', n, target=target, pose=pose)

    def _bucle_teclado(self) -> None:
        """Leer teclas y mostrar la transformación directamente sin pasar por el topic."""
        while self._activo:
            try:
                key = input().strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if key == 'q':
                self._activo = False
                break

            if key not in _TECLAS:
                if key:
                    print(f'  {_DIM}Teclas válidas: {" ".join(_TECLAS)}  |  q = salir{_RST}')
                continue

            ex, ey, ez, nombre = _TECLAS[key]
            with self._lock:
                self._n_teclado += 1
                n = self._n_teclado
            print(f'  {_M}[teclado] {nombre}{_RST}')
            _mostrar_transformacion(ex, ey, ez, 'TECLADO', n)

    def destroy_node(self):
        """Detener hilo de teclado antes de destruir el nodo."""
        self._activo = False
        super().destroy_node()


def main(args=None):
    """Punto de entrada del nodo spy_mavros."""
    rclpy.init(args=args)
    node = EspiaMavros()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass
