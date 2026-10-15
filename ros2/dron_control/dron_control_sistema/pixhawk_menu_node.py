"""Nodo interactivo con menú terminal para probar el Pixhawk F550 (PX4) vía MAVROS."""

import math
import threading
import time

from geometry_msgs.msg import PoseStamped, Twist
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

try:
    from mavros_msgs.msg import PositionTarget, State
    from mavros_msgs.srv import CommandBool, SetMode
    MAVROS_OK = True
except ImportError:
    MAVROS_OK = False

# Parámetros de seguridad para pruebas
VEL = 0.3        # m/s
DURACION = 1.0   # s por comando de movimiento
TASA_HZ = 10     # Hz de publicación (PX4 OFFBOARD requiere > 2 Hz)
VEL_DESPEGUE = 0.5      # m/s de subida continua durante el despegue en OFFBOARD
TIMEOUT_DESPEGUE = 15.0  # s máximos para alcanzar la altura antes de cancelar


class PixhawkMenuNode(Node):
    """Nodo ROS2 con menú terminal para pruebas del Pixhawk F550 vía MAVROS (PX4)."""

    def __init__(self):
        """Inicializar suscriptores, publicadores, servicios y hilo de menú."""
        super().__init__('pixhawk_menu_node')

        self._armado = False
        self._modo = 'DESCONOCIDO'
        self._pos = (0.0, 0.0, 0.0)
        self._cmd_vel = Twist()
        self._lock = threading.Lock()
        self._activo_hasta = 0.0
        self._ejecutando = True
        self._ultimo_ack_t = 0.0
        self._z_objetivo = None   # altura local (m) a alcanzar en el despegue; None = sin despegue
        self._despegue_t0 = 0.0

        self._vel_pub = self.create_publisher(
            Twist, '/mavros/setpoint_velocity/cmd_vel_unstamped', 10)

        _qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        if MAVROS_OK:
            self.create_subscription(State, '/mavros/state', self._estado_cb, _qos)
            self.create_subscription(
                PositionTarget,
                '/mavros/setpoint_raw/target_local',
                self._cb_ack_pixhawk,
                _qos,
            )
        self.create_subscription(
            PoseStamped, '/mavros/local_position/pose', self._pose_cb, _qos)

        if MAVROS_OK:
            self._cli_armar = self.create_client(CommandBool, '/mavros/cmd/arming')
            self._cli_modo = self.create_client(SetMode, '/mavros/set_mode')

        self.create_timer(1.0 / TASA_HZ, self._timer_vel)

        hilo = threading.Thread(target=self._bucle_menu, daemon=True)
        hilo.start()

        self.get_logger().info('pixhawk_menu_node iniciado.')

    # ------------------------------------------------------------------
    # Callbacks de suscripción
    # ------------------------------------------------------------------

    def _estado_cb(self, msg):
        """Actualizar estado armed/mode desde /mavros/state."""
        self._armado = msg.armed
        self._modo = msg.mode

    def _pose_cb(self, msg):
        """Actualizar posición local desde /mavros/local_position/pose."""
        p = msg.pose.position
        self._pos = (p.x, p.y, p.z)

    def _cb_ack_pixhawk(self, msg: 'PositionTarget') -> None:
        """Confirmar que el Pixhawk recibió el setpoint (eco MAVLink ID 85)."""
        vx, vy, vz = msg.velocity.x, msg.velocity.y, msg.velocity.z
        if not all(math.isfinite(v) for v in (vx, vy, vz)):
            return  # PX4 responde NaN cuando no controla por velocidad: no es un ACK real
        if abs(vx) < 0.01 and abs(vy) < 0.01 and abs(vz) < 0.01:
            return
        now = time.time()
        if now - self._ultimo_ack_t < 0.4:
            return
        self._ultimo_ack_t = now
        print(f'  [PX4 ACK] Pixhawk confirma setpoint recibido: '
              f'vx={vx:+.3f}  vy={vy:+.3f}  vz={vz:+.3f} m/s  [ENU] ✓')

    # ------------------------------------------------------------------
    # Timer de velocidad
    # ------------------------------------------------------------------

    def _timer_vel(self):
        """Publicar cmd_vel a TASA_HZ Hz; gestiona el despegue y pone a cero al vencer DURACION."""
        with self._lock:
            if self._z_objetivo is not None:
                if not (self._armado and self._modo == 'OFFBOARD'):
                    self._z_objetivo = None
                    self.get_logger().warn('Despegue cancelado (no armado o no OFFBOARD)')
                elif self._pos[2] >= self._z_objetivo - 0.05:
                    self._z_objetivo = None
                    self.get_logger().info(f'Despegue completado: Alt={self._pos[2]:.2f} m')
                elif time.time() - self._despegue_t0 > TIMEOUT_DESPEGUE:
                    self._z_objetivo = None
                    self.get_logger().warn(
                        f'Despegue cancelado: no alcanza la altura en {TIMEOUT_DESPEGUE:.0f} s')

            if self._z_objetivo is not None:
                cmd = Twist()
                cmd.linear.z = VEL_DESPEGUE  # subida continua (Arriba, ENU)
            else:
                if time.time() > self._activo_hasta:
                    self._cmd_vel = Twist()
                cmd = self._cmd_vel
        self._vel_pub.publish(cmd)

    # ------------------------------------------------------------------
    # Comandos internos
    # ------------------------------------------------------------------

    def _enviar_vel(self, vx: float, vy: float, vz: float):
        """Enviar velocidad en marco ENU durante DURACION segundos."""
        with self._lock:
            cmd = Twist()
            cmd.linear.x = vx   # Este  (m/s ENU)
            cmd.linear.y = vy   # Norte (m/s ENU)
            cmd.linear.z = vz   # Arriba(m/s ENU)
            self._cmd_vel = cmd
            self._z_objetivo = None  # una orden manual cancela el despegue
            self._activo_hasta = time.time() + DURACION

    def _parada_emergencia(self):
        """Poner velocidad a cero de inmediato."""
        with self._lock:
            self._cmd_vel = Twist()
            self._activo_hasta = 0.0
            self._z_objetivo = None
        self.get_logger().warn('PARADA DE EMERGENCIA ACTIVADA')

    def _armar(self, valor: bool):
        """Enviar solicitud de armar o desarmar vía /mavros/cmd/arming."""
        if not MAVROS_OK:
            print('[ERROR] mavros_msgs no disponible')
            return
        if not self._cli_armar.wait_for_service(timeout_sec=2.0):
            print('[ERROR] Servicio /mavros/cmd/arming no disponible (MAVROS activo?)')
            return
        req = CommandBool.Request()
        req.value = valor
        accion = 'ARMAR' if valor else 'DESARMAR'
        fut = self._cli_armar.call_async(req)
        fut.add_done_callback(
            lambda f: self.get_logger().info(
                f"{accion}: {'OK' if f.result().success else 'FALLO'}"))

    def _set_modo(self, modo: str):
        """Cambiar modo de vuelo vía /mavros/set_mode."""
        if not MAVROS_OK:
            print('[ERROR] mavros_msgs no disponible')
            return
        if not self._cli_modo.wait_for_service(timeout_sec=2.0):
            print('[ERROR] Servicio /mavros/set_mode no disponible (MAVROS activo?)')
            return
        req = SetMode.Request()
        req.custom_mode = modo
        fut = self._cli_modo.call_async(req)
        fut.add_done_callback(
            lambda f: self.get_logger().info(
                f"SetMode {modo}: {'OK' if f.result().mode_sent else 'FALLO'}"))

    def _despegar(self, altitud: float):
        """Despegar en OFFBOARD subiendo sin parar hasta `altitud` m sobre el punto actual."""
        if not (self._armado and self._modo == 'OFFBOARD'):
            print('[!] Para despegar: [3] OFFBOARD -> [1] Armar -> [4] (antes de 10 s)')
            return
        with self._lock:
            self._z_objetivo = self._pos[2] + altitud  # relativa al suelo actual, sin GPS
            self._despegue_t0 = time.time()
            self._activo_hasta = 0.0
        print(f'[*] Subiendo a {VEL_DESPEGUE} m/s hasta Alt={self._z_objetivo:.2f} m')

    # ------------------------------------------------------------------
    # Menú de terminal
    # ------------------------------------------------------------------

    def _imprimir_menu(self):
        """Mostrar menú con estado actual del dron."""
        est = 'ARMADO  ' if self._armado else 'DESARMADO'
        x, y, z = self._pos
        sep = '-' * 46
        print(f'\n{sep}')
        print('  PIXHAWK F550 (PX4) -- MENU DE PRUEBA')
        print(sep)
        print(f'  Estado : {est}  Modo : {self._modo}')
        print(f'  Pos    : N={y:+.2f}  E={x:+.2f}  Alt={z:.2f} m')
        print(sep)
        print('  PREPARACION (orden recomendado para PX4):')
        print('    [3] OFFBOARD -> [1] Armar -> [4] Despegar (1.5 m)')
        print('    [2] Desarmar (solo en suelo)  |  [5] Aterrizar')
        print(sep)
        print(f'  MOVIMIENTO ({VEL} m/s por {DURACION:.0f} s, frame ENU):')
        print('    [w] Norte    [s] Sur    [r] Subir')
        print('    [a] Oeste    [d] Este   [f] Bajar')
        print(sep)
        print('  [0] PARADA EMERGENCIA    [q] Salir')
        print(sep)

    def _bucle_menu(self):
        """Hilo de entrada: leer teclado y despachar comandos."""
        time.sleep(1.0)
        while self._ejecutando:
            self._imprimir_menu()
            try:
                opcion = input('> ').strip().lower()
            except (EOFError, KeyboardInterrupt):
                break

            if opcion == '1':
                print('[*] Enviando ARMAR...')
                self._armar(True)
            elif opcion == '2':
                print('[*] Enviando DESARMAR...')
                self._armar(False)
            elif opcion == '3':
                print('[*] Cambiando a OFFBOARD...')
                self._set_modo('OFFBOARD')
            elif opcion == '4':
                self._despegar(1.5)
            elif opcion == '5':
                print('[*] Aterrizando (AUTO.LAND)...')
                self._set_modo('AUTO.LAND')
            elif opcion == 'w':
                print(f'[*] NORTE  {VEL} m/s · {DURACION:.0f} s')
                self._enviar_vel(0.0, VEL, 0.0)
            elif opcion == 's':
                print(f'[*] SUR    {VEL} m/s · {DURACION:.0f} s')
                self._enviar_vel(0.0, -VEL, 0.0)
            elif opcion == 'a':
                print(f'[*] OESTE  {VEL} m/s · {DURACION:.0f} s')
                self._enviar_vel(-VEL, 0.0, 0.0)
            elif opcion == 'd':
                print(f'[*] ESTE   {VEL} m/s · {DURACION:.0f} s')
                self._enviar_vel(VEL, 0.0, 0.0)
            elif opcion == 'r':
                print(f'[*] SUBIR  {VEL} m/s · {DURACION:.0f} s')
                self._enviar_vel(0.0, 0.0, VEL)
            elif opcion == 'f':
                print(f'[*] BAJAR  {VEL} m/s · {DURACION:.0f} s')
                self._enviar_vel(0.0, 0.0, -VEL)
            elif opcion == '0':
                self._parada_emergencia()
            elif opcion == 'q':
                self._ejecutando = False
                break
            elif opcion == '':
                pass  # solo refresca el menú
            else:
                print(f'[!] Opcion desconocida: "{opcion}"')

            time.sleep(0.1)

        self.get_logger().info('Menu cerrado.')

    def destroy_node(self):
        """Detener hilo de menú antes de destruir el nodo."""
        self._ejecutando = False
        super().destroy_node()


def main(args=None):
    """Punto de entrada del nodo pixhawk_menu_node."""
    if not MAVROS_OK:
        print('\n[AVISO] mavros_msgs no encontrado. Instalar MAVROS primero:')
        print('  sudo apt install ros-humble-mavros ros-humble-mavros-extras')
        print('  sudo /opt/ros/humble/lib/mavros/install_geographiclib_datasets.sh')
        print()

    rclpy.init(args=args)
    node = PixhawkMenuNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
