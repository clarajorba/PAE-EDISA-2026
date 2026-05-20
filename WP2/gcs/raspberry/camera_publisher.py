#!/usr/bin/env python3
"""
Camera publisher for drone GCS — uses picamera2 (Raspberry Pi Camera Module).
Publishes sensor_msgs/CompressedImage to /camera/forward/image_raw/compressed

Usage:
  source /opt/ros/jazzy/setup.bash
  python3 camera_publisher.py
  python3 camera_publisher.py --ros-args -p fps:=15 -p jpeg_quality:=70
"""

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy, DurabilityPolicy
from sensor_msgs.msg import CompressedImage
from picamera2 import Picamera2
import cv2


class CameraPublisher(Node):
    def __init__(self):
        super().__init__('camera_publisher')

        self.declare_parameter('device',       0)
        self.declare_parameter('topic',        '/camera/forward/image_raw/compressed')
        self.declare_parameter('fps',          30)
        self.declare_parameter('width',        640)
        self.declare_parameter('height',       480)
        self.declare_parameter('jpeg_quality', 80)
        self.declare_parameter('frame_id',     'camera_forward')

        device  = self.get_parameter('device').value
        topic   = self.get_parameter('topic').value
        fps     = self.get_parameter('fps').value
        width   = self.get_parameter('width').value
        height  = self.get_parameter('height').value
        self.quality = self.get_parameter('jpeg_quality').value
        self.fid     = self.get_parameter('frame_id').value

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            durability=DurabilityPolicy.VOLATILE,
            history=HistoryPolicy.KEEP_LAST,
            depth=1,
        )
        self.pub = self.create_publisher(CompressedImage, topic, qos)

        self.cam = Picamera2(device)
        cfg = self.cam.create_video_configuration(
            main={'size': (width, height), 'format': 'BGR888'}
        )
        self.cam.configure(cfg)
        self.cam.start()

        self._encode_params = [cv2.IMWRITE_JPEG_QUALITY, self.quality]
        self.create_timer(1.0 / fps, self._publish)
        self.get_logger().info(f'Camera publisher ready → {topic} @ {fps} fps')

    def _publish(self):
        frame = self.cam.capture_array()
        ret, buf = cv2.imencode('.jpg', frame, self._encode_params)
        if not ret:
            return
        msg = CompressedImage()
        msg.header.stamp    = self.get_clock().now().to_msg()
        msg.header.frame_id = self.fid
        msg.format          = 'jpeg'
        msg.data            = buf.tobytes()
        self.pub.publish(msg)

    def destroy_node(self):
        self.cam.stop()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = CameraPublisher()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
