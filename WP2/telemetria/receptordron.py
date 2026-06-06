import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage
from geometry_msgs.msg import PoseStamped
import cv2
from cv_bridge import CvBridge
import os
from datetime import datetime

class ReceptorTelemetria(Node):
    def __init__(self):
        super().__init__('receptor_telemetria_server')
        
        # 1. Crear carpeta para la demo
        self.output_dir = os.path.expanduser('~/PAE/demo_output')
        os.makedirs(self.output_dir, exist_ok=True)
        self.log_file = os.path.join(self.output_dir, 'log_posiciones.txt')

        # 2. Suscriptores (Sincronizados con el Publisher)
        self.img_sub = self.create_subscription(
            CompressedImage, 'camera/image/compressed', self.image_callback, 10)
        
        self.pose_sub = self.create_subscription(
            PoseStamped, 'telemetry/pose_sync', self.pose_callback, 10)

        self.bridge = CvBridge()
        self.latest_pose = "Sin datos de posición"
        
        self.get_logger().info(f'>>> GUARDANDO DATOS EN: {self.output_dir} <<<')

    def pose_callback(self, msg):
        # Guardamos la posición formateada para el log
        pos = msg.pose.position
        ori = msg.pose.orientation
        self.latest_pose = f"Pos: x={pos.x:.2f}, y={pos.y:.2f}, z={pos.z:.2f} | Ori: w={ori.w:.2f}"

    def image_callback(self, data):
        try:
            # Convertimos la imagen comprimida a OpenCV
            frame = self.bridge.compressed_imgmsg_to_cv2(data, desired_encoding='bgr8')
            
            # Generamos nombre de archivo único por tiempo
            timestamp = datetime.now().strftime("%H%M%S_%f")
            img_name = f"frame_{timestamp}.jpg"
            img_path = os.path.join(self.output_dir, img_name)
            
            # Guardamos la imagen
            cv2.imwrite(img_path, frame)
            
            # Guardamos la posición asociada en el log
            with open(self.log_file, "a") as f:
                f.write(f"[{timestamp}] {img_name} -> {self.latest_pose}\n")
            
            self.get_logger().info(f'Recibido: {img_name} con {self.latest_pose}')
            
            # Mantenemos solo las últimas 20 imágenes para no llenar el disco
            all_imgs = sorted([os.path.join(self.output_dir, f) for f in os.listdir(self.output_dir) if f.endswith('.jpg')])
            if len(all_imgs) > 20:
                os.remove(all_imgs[0])

        except Exception as e:
            self.get_logger().error(f'Error al procesar: {e}')

def main():
    rclpy.init()
    node = ReceptorTelemetria()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()