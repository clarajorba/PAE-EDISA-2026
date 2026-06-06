import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from geometry_msgs.msg import PoseStamped

class MonitorNode(Node):
    def __init__(self):
        super().__init__('monitor_node')
        self.create_subscription(CompressedImage, 'camera/image/compressed', self.img_cb, 10)
        self.create_subscription(PoseStamped, 'telemetry/pose_sync', self.pose_cb, 10)

    def img_cb(self, msg):
        self.get_logger().info(f'Recibida Imagen: {msg.header.stamp.sec}.{msg.header.stamp.nanosec}')

    def pose_cb(self, msg):
        self.get_logger().info(f'Recibida Pose: X={msg.pose.position.x:.2f}, Y={msg.pose.position.y:.2f}')

def main():
    rclpy.init()
    rclpy.spin(MonitorNode())