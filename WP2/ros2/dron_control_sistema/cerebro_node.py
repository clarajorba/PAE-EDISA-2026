import json

import numpy as np
import rclpy
from ament_index_python.packages import get_package_share_directory
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

class CerebroNode(Node):
    def __init__(self):
        super().__init__('cerebro_node')
        self.sub_pose   = self.create_subscription(
            Float32MultiArray, '/drone/pose', self.pose_callback, 10)
        self.pub_target = self.create_publisher(
            Float32MultiArray, '/cerebro/target', 10)

        _share = get_package_share_directory('dron_control_sistema')
        with open(f'{_share}/mision.json', 'r') as f:
            data = json.load(f)
            self.mapa   = data['mapa_mision']
            self.margen = data['config']['margen']
            self.z_fijo = data['config'].get('z_fijo', 1.0)

        self.idx   = 0
        self.total = len(self.mapa)

        self.get_logger().info(
            f"Cerebro OK — {self.total} waypoints | "
            f"margen={self.margen} m | Z fijo={self.z_fijo} m\n"
            f"Patrón: serpentín rectangular  → ↑ ← ↑ →  por estantería"
        )

    def pose_callback(self, msg):
        if self.idx >= self.total:
            return

        hito     = self.mapa[self.idx]
        pos      = np.array(msg.data[:3])
        objetivo = np.array(hito['pos'][:3])

        # Evaluamos distancia solo en XY  (Z es constante y no cambia)
        dist_xy = np.linalg.norm(pos[:2] - objetivo[:2])

        if dist_xy <= self.margen:
            self.get_logger().info(
                f"[{self.idx+1}/{self.total}] '{hito['msg']}' "
                f"(d_xy={dist_xy:.3f} m) → next={hito['next']}"
            )
            out      = Float32MultiArray()
            out.data = [float(v) for v in hito['next']]
            self.pub_target.publish(out)
            self.idx += 1
            if self.idx >= self.total:
                self.get_logger().info("✓ MISIÓN COMPLETADA")


def main(args=None):
    rclpy.init(args=args)
    node = CerebroNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()
