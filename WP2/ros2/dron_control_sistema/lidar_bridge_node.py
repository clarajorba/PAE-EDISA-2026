"""Bridge between Point-LIO TF pose and cerebro_node, with live status display."""

import csv
import math
import os
import time
from datetime import datetime

import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray
import tf2_ros


class LidarBridgeNode(Node):
    """Reads Point-LIO pose via TF (camera_init→aft_mapped), publishes /drone/pose."""

    _TF_PARENT = 'camera_init'
    _TF_CHILD = 'aft_mapped'
    _POLL_HZ = 10.0   # TF lookup rate
    _LOG_HZ = 1.0     # status log rate

    def __init__(self):
        super().__init__('lidar_bridge_node')

        self._tf_buffer = tf2_ros.Buffer()
        self._tf_listener = tf2_ros.TransformListener(self._tf_buffer, self)

        self.sub_target = self.create_subscription(
            Float32MultiArray, '/cerebro/target', self._target_cb, 10)

        self.pub_pose = self.create_publisher(
            Float32MultiArray, '/drone/pose', 10)

        self._target = [0.0, 0.0, 0.0]
        self._last_log = 0.0

        self.create_timer(1.0 / self._POLL_HZ, self._poll_tf)

        # CSV session log in demo_real/logs/
        pkg_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'demo_real')
        logs_dir = os.path.join(pkg_root, 'logs')
        os.makedirs(logs_dir, exist_ok=True)
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        csv_path = os.path.join(logs_dir, f'sesion_{stamp}.csv')
        self._csv = open(csv_path, 'w', newline='')
        self._writer = csv.writer(self._csv)
        self._writer.writerow(
            ['timestamp', 'x', 'y', 'z', 'yaw_deg',
             'wp_x', 'wp_y', 'wp_z', 'dist_xy_m'])

        self.get_logger().info(f"LiDAR bridge activo | sesion → {csv_path}")
        self.get_logger().info(
            f"Esperando TF {self._TF_PARENT} → {self._TF_CHILD} de Point-LIO...")

    # ------------------------------------------------------------------
    def _target_cb(self, msg: Float32MultiArray):
        self._target = list(msg.data[:3])

    def _poll_tf(self):
        try:
            t = self._tf_buffer.lookup_transform(
                self._TF_PARENT, self._TF_CHILD, rclpy.time.Time())
        except (tf2_ros.LookupException,
                tf2_ros.ConnectivityException,
                tf2_ros.ExtrapolationException):
            return  # Point-LIO not ready yet

        tr = t.transform.translation
        q = t.transform.rotation

        # Quaternion → yaw (rotation around Z)
        yaw = math.atan2(2.0 * (q.w * q.z + q.x * q.y),
                         1.0 - 2.0 * (q.y * q.y + q.z * q.z))

        # Publish for cerebro_node and mavros_node
        out = Float32MultiArray()
        out.data = [float(tr.x), float(tr.y), float(tr.z), float(yaw)]
        self.pub_pose.publish(out)

        # Live status at ~1 Hz
        now = time.monotonic()
        if now - self._last_log >= 1.0 / self._LOG_HZ:
            self._last_log = now
            tx, ty, tz = self._target
            dist_xy = math.sqrt((tr.x - tx) ** 2 + (tr.y - ty) ** 2)
            yaw_deg = math.degrees(yaw)

            self.get_logger().info(
                f"LiDAR pos: ({tr.x:+.2f}, {tr.y:+.2f}, {tr.z:+.2f})  "
                f"Yaw: {yaw_deg:+.1f}°  |  "
                f"Next WP: ({tx:.2f}, {ty:.2f}, {tz:.2f})  "
                f"dist_xy: {dist_xy:.3f} m"
            )

            self._writer.writerow([
                datetime.now().isoformat(),
                f'{tr.x:.4f}', f'{tr.y:.4f}', f'{tr.z:.4f}', f'{yaw_deg:.2f}',
                f'{tx:.4f}', f'{ty:.4f}', f'{tz:.4f}', f'{dist_xy:.4f}',
            ])
            self._csv.flush()

    # ------------------------------------------------------------------
    def destroy_node(self):
        self._csv.close()
        super().destroy_node()


def main(args=None):
    """Entry point."""
    rclpy.init(args=args)
    node = LidarBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()
