"""Bridge entre cerebro_node y MAVROS/Pixhawk.

Suscribe a /cerebro/target, calcula velocidad proporcional y publica en
/mavros/setpoint_velocity/cmd_vel_unstamped para que MAVROS la envíe al Pixhawk.
Usa /mavros/local_position/pose como retroalimentación de posición real.
"""

from geometry_msgs.msg import PoseStamped, Twist
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Float32MultiArray

try:
    from mavros_msgs.msg import State
    _MAVROS_MSGS_OK = True
except ImportError:
    _MAVROS_MSGS_OK = False


class MavrosNode(Node):
    """Convierte targets de cerebro_node en comandos de velocidad para MAVROS."""

    def __init__(self):
        """Inicializar suscriptores, publicadores y estado de conexión."""
        super().__init__('mavros_node')

        self._pos = [0.0, 0.0, 0.0]
        self._mavros_connected = False
        self._mavros_armed = False
        self._mavros_mode = 'DESCONOCIDO'
        self._pos_source = 'ninguna'

        _qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        # Posición: acepta tanto el simulador como el Pixhawk real
        self.create_subscription(
            Float32MultiArray, '/drone/pose', self._cb_pose_sim, 10)
        self.create_subscription(
            PoseStamped, '/mavros/local_position/pose', self._cb_pose_mavros, _qos)

        self.create_subscription(
            Float32MultiArray, '/cerebro/target', self._cb_target, 10)

        self._pub_mavros = self.create_publisher(
            Twist, '/mavros/setpoint_velocity/cmd_vel_unstamped', 10)
        # Mantener /drone/cmd_vel para compatibilidad con el simulador
        self._pub_sim = self.create_publisher(Twist, '/drone/cmd_vel', 10)

        if _MAVROS_MSGS_OK:
            self.create_subscription(State, '/mavros/state', self._cb_state, _qos)
        else:
            self.get_logger().warn(
                'mavros_msgs no encontrado — sin monitoreo de estado Pixhawk. '
                'Instalar: sudo apt install ros-humble-mavros ros-humble-mavros-extras')

        self.get_logger().info('mavros_node iniciado. Esperando conexión MAVROS...')

    # ------------------------------------------------------------------
    # Callbacks de posición
    # ------------------------------------------------------------------

    def _cb_pose_sim(self, msg):
        """Posición desde el simulador (Float32MultiArray [x,y,z,yaw])."""
        if self._pos_source != 'mavros':
            self._pos = list(msg.data[:3])
            self._pos_source = 'simulador'

    def _cb_pose_mavros(self, msg):
        """Posición real desde MAVROS/Pixhawk (tiene prioridad sobre el simulador)."""
        p = msg.pose.position
        self._pos = [p.x, p.y, p.z]
        self._pos_source = 'mavros'

    # ------------------------------------------------------------------
    # Callback de estado MAVROS
    # ------------------------------------------------------------------

    def _cb_state(self, msg):
        """Monitorear conexión, armado y modo de vuelo del Pixhawk."""
        prev_connected = self._mavros_connected
        self._mavros_connected = msg.connected
        self._mavros_armed = msg.armed
        self._mavros_mode = msg.mode

        if msg.connected and not prev_connected:
            self.get_logger().info(
                'MAVROS conectado al Pixhawk — '
                f'modo={msg.mode}  armado={msg.armed}')
        elif not msg.connected and prev_connected:
            self.get_logger().warn('MAVROS desconectado del Pixhawk')

    # ------------------------------------------------------------------
    # Callback principal: target → velocidad → MAVROS
    # ------------------------------------------------------------------

    def _cb_target(self, msg):
        """Calcular velocidad proporcional y publicar en MAVROS y simulador."""
        dest = msg.data
        vel = Twist()
        vel.linear.x = float(dest[0] - self._pos[0])
        vel.linear.y = float(dest[1] - self._pos[1])
        vel.linear.z = float(dest[2] - self._pos[2])

        self._pub_mavros.publish(vel)
        self._pub_sim.publish(vel)

        if _MAVROS_MSGS_OK and not self._mavros_connected:
            self.get_logger().warn(
                'MAVROS no conectado — comando enviado al topic pero '
                'puede no llegar al Pixhawk. Comprobar fcu_url y puerto USB.')
            return

        self.get_logger().info(
            f'[{self._pos_source}] '
            f'target=({dest[0]:.2f},{dest[1]:.2f},{dest[2]:.2f})  '
            f'pos=({self._pos[0]:.2f},{self._pos[1]:.2f},{self._pos[2]:.2f})  '
            f'vel=({vel.linear.x:+.2f},{vel.linear.y:+.2f},{vel.linear.z:+.2f})  '
            f'modo={self._mavros_mode}  armado={self._mavros_armed}')


def main(args=None):
    """Punto de entrada del nodo mavros_node."""
    rclpy.init(args=args)
    node = MavrosNode()
    try:
        rclpy.spin(node)
    finally:
        node.destroy_node()
        rclpy.shutdown()
