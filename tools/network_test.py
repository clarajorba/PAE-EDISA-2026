import rclpy
from rclpy.node import Node
from std_msgs.msg import String
import time

class NetworkTester(Node):
    def __init__(self):
        super().__init__('network_tester')
        self.publisher_ = self.create_publisher(String, 'test_comms', 10)
        self.timer = self.create_timer(1.0, self.timer_callback)
        self.counter = 0
        self.get_logger().info('Tester iniciado. Enviando datos al servidor...')

    def timer_callback(self):
        msg = String()
        msg.data = f'Test Packet #{self.counter} - Time: {time.time()}'
        self.publisher_.publish(msg)
        self.get_logger().info(f'Enviando: {msg.data}')
        self.counter += 1

def main(args=None):
    rclpy.init(args=args)
    node = NetworkTester()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()