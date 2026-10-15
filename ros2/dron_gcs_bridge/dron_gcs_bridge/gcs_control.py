#!/usr/bin/env python3
"""
GCS Control node — lets the dashboard start/stop services on the Pi.

Always running (started by systemd alongside rosbridge).

Subscribes:  /gcs/cmd    std_msgs/String  {"action":"start"|"stop","service":"slam"|"camera"|"mjpeg"|"mavros"|"brain"}
Publishes:   /gcs/status std_msgs/String  {"slam":"stopped","camera":"stopped",...}  @ 1 Hz

Logs per-service to ~/gcs_logs/<service>.log
"""

import os, json, subprocess, signal, threading
import rclpy
from rclpy.node import Node
from std_msgs.msg import String

# Scripts no-ROS (slam_launch.sh, mjpeg_server.py): carpeta raspberry/ del repo.
# rosbridge_boot.sh exporta PAE_RASPBERRY_DIR; si no, se asume que se copiaron a ~.
SCRIPTS     = os.environ.get('PAE_RASPBERRY_DIR', os.path.expanduser('~'))
LOG_DIR     = os.path.expanduser('~/gcs_logs')
ROS_DISTRO  = os.environ.get('ROS_DISTRO', 'jazzy')

# ── command for each service ──────────────────────────────────────────────────
SERVICE_CMDS = {
    'slam': [
        'bash', f'{SCRIPTS}/slam_launch.sh',
    ],
    'camera': [
        'ros2', 'run', 'dron_percepcion', 'camera_publisher',
        '--ros-args',
        '-p', 'device:=0',
        '-p', 'topic:=/camera/forward/image_raw/compressed',
        '-p', 'width:=640', '-p', 'height:=480',
        '-p', 'fps:=30', '-p', 'jpeg_quality:=80',
    ],
    'camera2': [
        'ros2', 'run', 'dron_percepcion', 'camera_publisher',
        '--ros-args',
        '-p', 'device:=1',
        '-p', 'topic:=/camera/down/image_raw/compressed',
        '-p', 'width:=640', '-p', 'height:=480',
        '-p', 'fps:=30', '-p', 'jpeg_quality:=80',
    ],
    'mjpeg': [
        'python3', f'{SCRIPTS}/mjpeg_server.py',
        '0', '8080', '640', '480', '80',
    ],
    'mavros': [
        'ros2', 'run', 'dron_gcs_bridge', 'mavlink_bridge',
    ],
    'brain': [
        'ros2', 'run', 'dron_gcs_bridge', 'brain_node',
    ],
    'barcode': [
        'ros2', 'run', 'dron_percepcion', 'barcode_detector',
    ],
}


class GCSControlNode(Node):
    def __init__(self):
        super().__init__('gcs_control')
        os.makedirs(LOG_DIR, exist_ok=True)

        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

        self._sub = self.create_subscription(String, '/gcs/cmd',    self._on_cmd, 10)
        self._pub = self.create_publisher(  String, '/gcs/status',  10)
        self.create_timer(1.0, self._publish_status)

        self.get_logger().info(f'GCS control ready — scripts: {SCRIPTS}')

    # ── command handler ───────────────────────────────────────────────────────
    def _on_cmd(self, msg: String):
        try:
            d       = json.loads(msg.data)
            action  = d.get('action', '')   # 'start' | 'stop'
            service = d.get('service', '')  # key in SERVICE_CMDS
        except Exception:
            return
        if action == 'start':
            self._start(service)
        elif action == 'stop':
            self._stop(service)

    # ── start ─────────────────────────────────────────────────────────────────
    def _start(self, svc: str):
        if svc not in SERVICE_CMDS:
            self.get_logger().warn(f'Unknown service: {svc}')
            return
        with self._lock:
            if svc in self._procs and self._procs[svc].poll() is None:
                self.get_logger().info(f'{svc} already running')
                return
            log_path = os.path.join(LOG_DIR, f'{svc}.log')
            with open(log_path, 'a') as lf:
                proc = subprocess.Popen(
                    SERVICE_CMDS[svc],
                    env=os.environ.copy(),
                    stdout=lf,
                    stderr=lf,
                    preexec_fn=os.setsid,   # own process group → clean kill
                )
            self._procs[svc] = proc
            self.get_logger().info(f'Started {svc}  PID={proc.pid}')

    # ── stop ──────────────────────────────────────────────────────────────────
    def _stop(self, svc: str):
        with self._lock:
            proc = self._procs.get(svc)
            if not proc or proc.poll() is not None:
                self._procs.pop(svc, None)
                return
            try:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                except ProcessLookupError:
                    pass
            self._procs.pop(svc, None)
            self.get_logger().info(f'Stopped {svc}')

    # ── status publisher (1 Hz) ───────────────────────────────────────────────
    def _publish_status(self):
        with self._lock:
            status = {
                svc: ('running' if svc in self._procs and self._procs[svc].poll() is None else 'stopped')
                for svc in SERVICE_CMDS
            }
        self._pub.publish(String(data=json.dumps(status)))

    # ── cleanup on shutdown ───────────────────────────────────────────────────
    def destroy_node(self):
        for svc in list(self._procs.keys()):
            self._stop(svc)
        super().destroy_node()


def main():
    rclpy.init()
    node = GCSControlNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
