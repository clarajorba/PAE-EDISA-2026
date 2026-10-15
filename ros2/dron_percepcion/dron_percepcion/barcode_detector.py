#!/usr/bin/env python3
"""
barcode_detector.py — ROS2 node: detects barcodes / QR codes in the forward
camera, draws ROI boxes + SLAM overlay, and publishes results to the GCS.

Subscribes:
  /camera/forward/image_raw/compressed  sensor_msgs/CompressedImage
  /Odometry                             nav_msgs/Odometry   (SLAM pose)
  /tf                                   tf2_msgs/TFMessage  (fallback)

Publishes:
  /barcode/roi/image/compressed  sensor_msgs/CompressedImage
      → annotated JPEG (green ROI boxes, barcode text, SLAM position overlay)
  /barcode/detection             std_msgs/String
      → JSON {barcode, code, status, slam_x, slam_y, slam_theta}

Install dependencies (run once on Pi):
  sudo apt install -y libzbar0
  pip3 install --break-system-packages pyzbar opencv-python
"""

import json, math, time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from std_msgs.msg import String
from sensor_msgs.msg import CompressedImage

# Must match camera_publisher.py QoS (BEST_EFFORT) — otherwise subscriber gets nothing
CAM_QOS = QoSProfile(
    reliability=ReliabilityPolicy.BEST_EFFORT,
    durability=DurabilityPolicy.VOLATILE,
    history=HistoryPolicy.KEEP_LAST,
    depth=1,
)

# ── optional imports (graceful fallback if not installed) ─────────────────────
try:
    import cv2
    import numpy as np
    CV2 = True
except ImportError:
    CV2 = False

try:
    from pyzbar.pyzbar import decode as zbar_decode
    PYZBAR = True
except ImportError:
    PYZBAR = False


class BarcodeDetector(Node):
    def __init__(self):
        super().__init__('barcode_detector')

        if not CV2:
            self.get_logger().error('opencv-python not installed. Run: pip3 install --break-system-packages opencv-python')
        if not PYZBAR:
            self.get_logger().error('pyzbar not installed. Run: pip3 install --break-system-packages pyzbar')

        self._slam_x     = 0.0
        self._slam_y     = 0.0
        self._slam_z     = 0.0
        self._slam_theta = 0.0

        # ── Publishers ────────────────────────────────────────────────────────
        self._pub_roi = self.create_publisher(
            CompressedImage, '/barcode/roi/image/compressed', 5)
        self._pub_det = self.create_publisher(
            String, '/barcode/detection', 10)

        # ── Subscribers ───────────────────────────────────────────────────────
        self.create_subscription(
            CompressedImage, '/camera/forward/image_raw/compressed',
            self._on_image, CAM_QOS)

        from nav_msgs.msg import Odometry
        self.create_subscription(Odometry, '/Odometry', self._on_odom, 10)

        from tf2_msgs.msg import TFMessage
        self.create_subscription(TFMessage, '/tf', self._on_tf, 10)

        # Throttle: only process 1 frame per N seconds to save CPU
        self._last_proc = 0.0
        self._proc_interval = 0.25   # 4 fps processing

        # Dedup: don't re-publish the same code within X seconds
        self._seen: dict[str, float] = {}
        self._dedup_window = 3.0   # seconds

        self.get_logger().info(
            f'barcode_detector ready  cv2={CV2}  pyzbar={PYZBAR}')

    # ── SLAM pose from /Odometry ──────────────────────────────────────────────
    def _on_odom(self, msg):
        p = msg.pose.pose
        self._slam_x = p.position.x
        self._slam_y = p.position.y
        self._slam_z = p.position.z
        q = p.orientation
        self._slam_theta = math.degrees(math.atan2(
            2 * (q.w * q.z + q.x * q.y),
            1 - 2 * (q.y * q.y + q.z * q.z)))

    # ── SLAM pose fallback from /tf ───────────────────────────────────────────
    def _on_tf(self, msg):
        for tr in (msg.transforms or []):
            if (tr.header.frame_id == 'camera_init' and
                    tr.child_frame_id == 'aft_mapped'):
                p = tr.transform.translation
                q = tr.transform.rotation
                self._slam_x = p.x
                self._slam_y = p.y
                self._slam_theta = math.degrees(math.atan2(
                    2 * (q.w * q.z + q.x * q.y),
                    1 - 2 * (q.y * q.y + q.z * q.z)))

    # ── Main image callback ───────────────────────────────────────────────────
    def _on_image(self, msg: CompressedImage):
        if not CV2:
            return

        now = time.monotonic()
        if now - self._last_proc < self._proc_interval:
            return
        self._last_proc = now

        # Decode JPEG → OpenCV BGR
        buf = np.frombuffer(bytes(msg.data), dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        if img is None:
            return

        # ── Orientation correction (camera mounted upside-down) ───────────────
        img = cv2.rotate(img, cv2.ROTATE_180)


        # ── Barcode / QR detection ────────────────────────────────────────────
        if PYZBAR:
            for barcode in zbar_decode(img):
                try:
                    code = barcode.data.decode('utf-8', errors='replace').strip()
                except Exception:
                    continue

                # Draw green polygon around barcode
                pts = np.array([(p.x, p.y) for p in barcode.polygon], dtype=np.int32)
                cv2.polylines(img, [pts], True, (0, 220, 80), 2)

                # Label background + text
                x, y, w, h = barcode.rect
                label = code[:32]
                (tw, th), _ = cv2.getTextSize(
                    label, cv2.FONT_HERSHEY_SIMPLEX, 0.48, 1)
                cv2.rectangle(img, (x, y - th - 8), (x + tw + 6, y), (0, 180, 60), -1)
                cv2.putText(img, label, (x + 3, y - 4),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.48, (0, 0, 0), 1, cv2.LINE_AA)

                # Dedup check
                if now - self._seen.get(code, 0) < self._dedup_window:
                    continue
                self._seen[code] = now

                # Publish detection
                self._pub_det.publish(String(data=json.dumps({
                    'barcode':    code,
                    'code':       code,
                    'status':     'OK',
                    'slam_x':     round(self._slam_x,     3),
                    'slam_y':     round(self._slam_y,     3),
                    'slam_theta': round(self._slam_theta, 1),
                })))
                self.get_logger().info(
                    f'Barcode: {code}  '
                    f'pos=({self._slam_x:.2f}, {self._slam_y:.2f})  '
                    f'θ={self._slam_theta:.1f}°')

        # ── SLAM overlay (top-left corner, 2 lines) ──────────────────────────
        line1 = f'SLAM  x:{self._slam_x:.2f}  y:{self._slam_y:.2f}  z:{self._slam_z:.2f}'
        line2 = f'      th:{self._slam_theta:.1f}°'
        font, scale, thick = cv2.FONT_HERSHEY_SIMPLEX, 0.40, 1
        (w1, lh), _ = cv2.getTextSize(line1, font, scale, thick)
        (w2,  _), _ = cv2.getTextSize(line2, font, scale, thick)
        box_w = max(w1, w2) + 12
        box_h = lh * 2 + 12
        cv2.rectangle(img, (0, 0), (box_w, box_h), (0, 0, 0), -1)
        cv2.putText(img, line1, (5, lh + 3),        font, scale, (80, 255, 80), thick, cv2.LINE_AA)
        cv2.putText(img, line2, (5, lh * 2 + 8),    font, scale, (80, 255, 80), thick, cv2.LINE_AA)

        # ── Re-encode + publish annotated image ───────────────────────────────
        ok, enc = cv2.imencode('.jpg', img, [cv2.IMWRITE_JPEG_QUALITY, 72])
        if ok:
            out         = CompressedImage()
            out.header  = msg.header
            out.format  = 'jpeg'
            out.data    = enc.tobytes()
            self._pub_roi.publish(out)


def main():
    rclpy.init()
    node = BarcodeDetector()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
