import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
import random

class LidarNode(Node):
    def __init__(self):
        super().__init__('lidar_node')
        self.publisher_ = self.create_publisher(Float32MultiArray, '/drone/pose', 10)
        
        # Publicar cada 3 segundos para que te dé tiempo a ver los logs
        self.timer = self.create_timer(3.0, self.timer_callback)
        self.get_logger().info("Nodo LIDAR Aleatorio iniciado")

    def timer_callback(self):
        msg = Float32MultiArray()
        
        # Generar valores aleatorios entre 0.0 y 10.0
        x = round(random.uniform(0.0, 10.0), 1)
        y = round(random.uniform(0.0, 10.0), 1)
        z = round(random.uniform(0.0, 5.0), 1)
        yaw = round(random.uniform(0.0, 360.0), 1)
        
        msg.data = [x, y, z, yaw]
        self.publisher_.publish(msg)
        self.get_logger().info(f"Lidar detecta ubicación: {msg.data}")

def main(args=None):
    rclpy.init(args=args)
    node = LidarNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

if __name__ == '__main__':
    main()
    