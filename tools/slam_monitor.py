import rclpy
from rclpy.node import Node
from geometry_msgs.msg import PoseStamped
import math


def quaternion_to_euler(x, y, z, w):
    """Convierte cuaternión a ángulos de Euler (roll, pitch, yaw) en grados."""
    # Roll (eje X)
    sinr_cosp = 2.0 * (w * x + y * z)
    cosr_cosp = 1.0 - 2.0 * (x * x + y * y)
    roll = math.atan2(sinr_cosp, cosr_cosp)

    # Pitch (eje Y)
    sinp = 2.0 * (w * y - z * x)
    sinp = max(-1.0, min(1.0, sinp))
    pitch = math.asin(sinp)

    # Yaw (eje Z)
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    yaw = math.atan2(siny_cosp, cosy_cosp)

    return math.degrees(roll), math.degrees(pitch), math.degrees(yaw)


class SlamMonitor(Node):
    def __init__(self):
        super().__init__('slam_monitor_node')
        self.subscription = self.create_subscription(
            PoseStamped,
            '/slam/pose',
            self.pose_callback,
            10
        )
        self.msg_count = 0
        print("\033[2J\033[H", end="")  # Limpia la terminal al arrancar
        print("=" * 55)
        print("       MONITOR SLAM — /slam/pose")
        print("=" * 55)
        print("Esperando datos del SLAM...\n")

    def pose_callback(self, msg: PoseStamped):
        self.msg_count += 1

        pos = msg.pose.position
        ori = msg.pose.orientation
        roll, pitch, yaw = quaternion_to_euler(ori.x, ori.y, ori.z, ori.w)

        stamp = msg.header.stamp
        ts = stamp.sec + stamp.nanosec * 1e-9

        # Mover cursor al inicio para sobreescribir en el mismo sitio
        print("\033[H", end="")
        print("=" * 55)
        print("       MONITOR SLAM — /slam/pose")
        print("=" * 55)
        print(f"  Mensajes recibidos : {self.msg_count}")
        print(f"  Timestamp ROS      : {ts:.3f} s")
        print(f"  Frame              : {msg.header.frame_id}")
        print("-" * 55)
        print("  POSICIÓN (m)")
        print(f"    X : {pos.x:+10.4f}")
        print(f"    Y : {pos.y:+10.4f}")
        print(f"    Z : {pos.z:+10.4f}")
        print("-" * 55)
        print("  ORIENTACIÓN — cuaternión")
        print(f"    x : {ori.x:+10.4f}")
        print(f"    y : {ori.y:+10.4f}")
        print(f"    z : {ori.z:+10.4f}")
        print(f"    w : {ori.w:+10.4f}")
        print("-" * 55)
        print("  ORIENTACIÓN — Euler (grados)")
        print(f"    Roll  : {roll:+10.2f}°")
        print(f"    Pitch : {pitch:+10.2f}°")
        print(f"    Yaw   : {yaw:+10.2f}°")
        print("=" * 55)
        print("  Ctrl+C para salir")


def main(args=None):
    rclpy.init(args=args)
    node = SlamMonitor()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        print("\n\nMonitor detenido.")
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
