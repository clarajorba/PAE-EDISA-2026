import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
from std_msgs.msg import Float32MultiArray # Importante añadir este
import matplotlib.pyplot as plt
import numpy as np

class SimuladorDron(Node):
    def __init__(self):
        super().__init__('simulador_dron')
        
        # Suscripción a comandos de velocidad
        self.sub_commands = self.create_subscription(
            Twist, 
            '/drone/cmd_vel', 
            self.command_callback, 
            10)
        
        # Publicación de posición actual
        self.publisher_pose = self.create_publisher(
            Float32MultiArray, 
            '/drone/pose', 
            10)
        
        # Estado inicial
        self.pos = np.array([1.0, 1.0, 0.0]) 
        self.yaw = 0.0 # Definido para evitar error en el timer
        
        # Timer para feedback al Cerebro
        self.timer = self.create_timer(0.5, self.publish_current_pose)
        
        # Configuración Visual
        plt.ion()
        self.fig = plt.figure()
        self.ax = self.fig.add_subplot(111, projection='3d')
        self.point, = self.ax.plot([self.pos[0]], [self.pos[1]], [self.pos[2]], 'ro')
        self.ax.set_xlim([0, 10]); self.ax.set_ylim([0, 10]); self.ax.set_zlim([0, 12])
        
        self.get_logger().info("Simulador listo y retroalimentando a /drone/pose")

    def command_callback(self, msg):
        # Actualización de posición
        self.pos[0] += msg.linear.x
        self.pos[1] += msg.linear.y
        self.pos[2] += msg.linear.z
        
        self.get_logger().info(f"Moviendo a: {self.pos}")
        
        # Actualización gráfica
        self.point.set_data(np.array([self.pos[0]]), np.array([self.pos[1]]))
        self.point.set_3d_properties(np.array([self.pos[2]]))
        plt.draw()
        plt.pause(0.01)
        
    def publish_current_pose(self):
        msg = Float32MultiArray()
        # Enviamos [x, y, z, yaw]
        msg.data = [float(self.pos[0]), float(self.pos[1]), float(self.pos[2]), float(self.yaw)]
        self.publisher_pose.publish(msg)

def main(args=None):
    rclpy.init(args=args)
    node = SimuladorDron()
    try:
        while rclpy.ok():
            rclpy.spin_once(node, timeout_sec=0.1)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()