import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import cv2
import numpy as np
from cv_bridge import CvBridge

class EmisorPrueba(Node):
    def __init__(self):
        super().__init__('streamer_dron')
        self.publisher_ = self.create_publisher(Image, 'video_dron', 10)
        self.timer = self.create_timer(0.1, self.timer_callback)
        self.bridge = CvBridge()
        self.get_logger().info('>>> ENVIANDO SEÑAL DE PRUEBA DE VÍDEO <<<')

    def timer_callback(self):
        # Creamos una imagen de prueba (fondo azul)
        frame = np.zeros((480, 640, 3), dtype=np.uint8)
        frame[:] = [255, 0, 0] # Color azul
        
        # Añadimos un texto que parpadea para ver que el streaming está vivo
        tiempo = self.get_clock().now().to_msg().sec
        cv2.putText(frame, f"TELEMETRIA OK - SEC: {tiempo}", (50, 240), 
                    cv2.FONT_HERSHEY_SIMPLEX, 1, (255, 255, 255), 2)
        
        # Convertimos y publicamos
        msg = self.bridge.cv2_to_imgmsg(frame, encoding="bgr8")
        self.publisher_.publish(msg)

def main():
    rclpy.init()
    node = EmisorPrueba()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()