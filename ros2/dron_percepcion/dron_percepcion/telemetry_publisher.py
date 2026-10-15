import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from geometry_msgs.msg import PoseStamped # Asumiendo que tu SLAM publica PoseStamped
from cv_bridge import CvBridge
import cv2

class TelemetryPublisher(Node):
    def __init__(self):
        super().__init__('telemetry_publisher_node')
        
        # 1. Publicadores
        self.img_pub = self.create_publisher(CompressedImage, 'camera/image/compressed', 10)
        self.pose_pub = self.create_publisher(PoseStamped, 'telemetry/pose_sync', 10)
        
        # 2. Suscriptor al SLAM (Aquí recibimos la pose real)
        # Cambia '/slam/pose' por el nombre real de tu topic de SLAM
        self.subscription = self.create_subscription(
            PoseStamped, '/slam/pose', self.slam_callback, 10)
            
        self.latest_pose = None
        self.bridge = CvBridge()
        
        # 3. Timer para la cámara (15 FPS)
        self.timer = self.create_timer(1.0 / 15.0, self.timer_callback)
        self.cap = cv2.VideoCapture(0)

    def slam_callback(self, msg):
        # Guardamos la última pose recibida del SLAM
        self.latest_pose = msg

    def timer_callback(self):
        ret, frame = self.cap.read()
        if ret and self.latest_pose is not None:
            # A. Comprimir y publicar imagen
            img_msg = self.bridge.cv2_to_compressed_imgmsg(frame, dst_format='jpeg')
            
            # Usamos el timestamp de la pose para sincronizar
            timestamp = self.latest_pose.header.stamp
            img_msg.header.stamp = timestamp
            
            self.img_pub.publish(img_msg)
            
            # B. Publicar la pose asociada a esa imagen
            # Ajustamos el header para que coincida con la imagen
            self.latest_pose.header.stamp = timestamp
            self.pose_pub.publish(self.latest_pose)
            
            self.get_logger().info('Publicando imagen y pose sincronizadas')

def main(args=None):
    rclpy.init(args=args)
    node = TelemetryPublisher()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()