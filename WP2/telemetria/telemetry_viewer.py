import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, PoseStamped

class TelemetryViewer(Node):
    def __init__(self):
        super().__init__('telemetry_viewer_node')
        self.create_subscription(Twist, '/mavros/setpoint_velocity/cmd_vel_unstamped', self.view_vel, 10)
        self.create_subscription(PoseStamped, '/mavros/vision_pose/pose', self.view_pose, 10)

    def view_pose(self, msg):
        # Visualizamos la posición que la Pixhawk está "creyendo"
        print(f"\033[94m[POSICIÓN EN PIXHAWK]\033[0m X: {msg.pose.position.x:.2f} | Z (Alt): {msg.pose.position.z:.2f}")

    def view_vel(self, msg):
        # Visualizamos la orden de movimiento
        estado = "GIRANDO" if msg.angular.z != 0 else "AVANZANDO"
        print(f"\033[92m[ORDEN DE VUELO]\033[0m Modo: {estado} | Vel Lineal: {msg.linear.x} m/s")
        print("-" * 50)

def main():
    rclpy.init()
    node = TelemetryViewer()
    rclpy.spin(node)