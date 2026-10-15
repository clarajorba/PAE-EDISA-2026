import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped, Twist
import math

class LogicBridge(Node):
    def __init__(self):
        super().__init__('logic_bridge_node')
        
        # Suscribirse al SLAM
        self.create_subscription(PoseStamped, '/slam/pose', self.analyze_logic, 10)
        
        # Publicar a MAVROS (Posición para que la Pixhawk sepa dónde está)
        self.vision_pub = self.create_publisher(PoseStamped, '/mavros/vision_pose/pose', 10)
        
        # Publicar comandos de movimiento (Velocidad)
        self.vel_pub = self.create_publisher(Twist, '/mavros/setpoint_velocity/cmd_vel_unstamped', 10)

        self.limite_traza = 5.0 # Metros antes de girar
        self.giros_realizados = 0

    def analyze_logic(self, msg):
        # 1. PASAR DATOS A PIXHAWK (Localización)
        # Aquí MAVROS se encarga de la conversión de ejes si está bien configurado
        self.vision_pub.publish(msg)

        # 2. LÓGICA DE MOVIMIENTO
        x = msg.pose.position.x
        cmd = Twist()

        # Si no hemos llegado al límite, seguimos recto
        if x < self.limite_traza:
            cmd.linear.x = 0.5 # Velocidad adelante
            self.get_logger().info('Estado: Siguiendo traza recta...')
        
        # Si llegamos al límite y tenemos giros pendientes (Simulamos 2 giros)
        elif self.giros_realizados < 2:
            cmd.linear.x = 0.1 # Frenamos un poco
            cmd.angular.z = 1.57 # Orden de giro (90 grados/seg)
            self.get_logger().warn('¡LÍMITE ALCANZADO! Ordenando giro a la Pixhawk...')
            # En una situación real, aquí esperaríamos a que el Yaw del SLAM cambie
            self.giros_realizados += 1 
            self.limite_traza += 5.0 # Extendemos la traza para el siguiente tramo
        
        else:
            self.get_logger().error('Misión finalizada. Manteniendo posición.')
            cmd.linear.x = 0.0
            cmd.angular.z = 0.0

        self.vel_pub.publish(cmd)

def main():
    rclpy.init()
    node = LogicBridge()
    rclpy.spin(node)