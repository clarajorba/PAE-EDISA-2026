import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
import random
import math

class SimSlam(Node):
    def __init__(self):
        super().__init__('sim_slam_node')
        self.publisher_ = self.create_publisher(PoseStamped, '/slam/pose', 10)
        self.timer = self.create_timer(0.1, self.publish_pose) # 10Hz
        self.x = 0.0
        self.y = 0.0
        self.angle = 0.0 # En radianes

    def publish_pose(self):
        msg = PoseStamped()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.header.frame_id = 'map'

        # Simulamos movimiento hacia adelante con un poco de ruido aleatorio
        self.x += 0.05 * math.cos(self.angle) + (random.uniform(-0.01, 0.01))
        self.y += 0.05 * math.sin(self.angle) + (random.uniform(-0.01, 0.01))

        msg.pose.position.x = self.x
        msg.pose.position.y = self.y
        msg.pose.position.z = 1.2 # Altura fija de vuelo
        
        # Orientación simple (convertida a cuaternión básico en Z)
        msg.pose.orientation.z = math.sin(self.angle / 2)
        msg.pose.orientation.w = math.cos(self.angle / 2)

        self.publisher_.publish(msg)

def main():
    rclpy.init()
    node = SimSlam()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()