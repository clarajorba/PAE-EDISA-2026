import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from cv_bridge import CvBridge
import cv2
import numpy as np

class ArtificialCamera(Node):
    def __init__(self):
        super().__init__('artificial_camera')
        self.publisher_ = self.create_publisher(CompressedImage, 'camera/image/compressed', 10)
        self.timer = self.create_timer(1/15.0, self.timer_callback)
        self.bridge = CvBridge()
        self.frame_count = 0

    def timer_callback(self):
        # Crear imagen negra 1080p
        img = np.zeros((1080, 1920, 3), dtype=np.uint8)
        # Dibujar algo dinámico (un contador)
        cv2.putText(img, f'FRAME: {self.frame_count}', (500, 500), 
                    cv2.FONT_HERSHEY_SIMPLEX, 5, (255, 255, 255), 10)
        
        msg = self.bridge.cv2_to_compressed_imgmsg(img, dst_format='jpeg')
        msg.header.stamp = self.get_clock().now().to_msg()
        self.publisher_.publish(msg)
        self.frame_count += 1

def main():
    rclpy.init()
    rclpy.spin(ArtificialCamera())