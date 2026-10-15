#!/usr/bin/env python3
"""
mavlink_bridge.py — lightweight MAVLink↔ROS2 bridge (pymavlink, no MAVROS).

Started on-demand by gcs_control.py when the MAVROS button is pressed.

Topics published (standard types only):
  /drone/vfr          std_msgs/String  JSON {airspeed,groundspeed,heading,throttle,alt,climb}
  /drone/state        std_msgs/String  JSON {armed,mode,connected}
  /drone/motors       std_msgs/String  JSON {channels:[pwm1..pwm8]}
  /drone/gps_status   std_msgs/String  JSON {fix_type,satellites_visible}
  /mavros/battery     sensor_msgs/BatteryState
  /mavros/imu/data    sensor_msgs/Imu
  /mavros/global_position/global        sensor_msgs/NavSatFix
  /mavros/local_position/velocity_body  geometry_msgs/TwistStamped

Topics subscribed:
  /drone/cmd  std_msgs/String  JSON
    {"action":"arm"}
    {"action":"disarm"}
    {"action":"mode","mode":"GUIDED"}
    {"action":"takeoff","alt":5.0}
    {"action":"land"}
"""

import json, math, os, threading, time
import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import BatteryState, Imu, NavSatFix
from geometry_msgs.msg import TwistStamped
from pymavlink import mavutil

BAUD_RATE   = int(os.environ.get('MAV_BAUD', '57600'))

# Auto-detect serial port: env var → /dev/serial0 (symlink) → /dev/ttyAMA10 (RPi5 GPIO) → /dev/ttyAMA0 → /dev/ttyUSB0
# NOTE: ttyAMA10 intentionally precedes ttyAMA0 — on RPi5, ttyAMA0 may be mapped
# to the Bluetooth chip (RP1), not to the GPIO 14/15 UART.
def _find_serial_port():
    if 'MAV_PORT' in os.environ:
        return os.environ['MAV_PORT']
    candidates = ['/dev/serial0', '/dev/ttyAMA10', '/dev/ttyAMA0', '/dev/ttyUSB0', '/dev/ttyACM0']
    for p in candidates:
        if os.path.exists(p):
            return p
    return '/dev/serial0'   # will fail with a clear error if not present

SERIAL_PORT = _find_serial_port()

# ArduCopter custom mode numbers
MODE_MAP = {
    'STABILIZE': 0, 'ACRO': 1, 'ALT_HOLD': 2, 'AUTO': 3,
    'GUIDED': 4,    'LOITER': 5, 'RTL': 6,    'CIRCLE': 7,
    'LAND': 9,      'DRIFT': 11, 'SPORT': 13, 'FLIP': 14,
    'AUTOTUNE': 15, 'POSHOLD': 16, 'BRAKE': 17,
}
MODE_REV = {v: k for k, v in MODE_MAP.items()}


class MavlinkBridge(Node):
    def __init__(self):
        super().__init__('mavlink_bridge')

        # ── publishers ────────────────────────────────────────────────────────
        self._pub_vfr    = self.create_publisher(String,        '/drone/vfr',                            10)
        self._pub_state  = self.create_publisher(String,        '/drone/state',                          10)
        self._pub_motors = self.create_publisher(String,        '/drone/motors',                         10)
        self._pub_gpss   = self.create_publisher(String,        '/drone/gps_status',                     10)
        self._pub_bat    = self.create_publisher(BatteryState,  '/mavros/battery',                       10)
        self._pub_imu    = self.create_publisher(Imu,           '/mavros/imu/data',                      10)
        self._pub_gps    = self.create_publisher(NavSatFix,     '/mavros/global_position/global',        10)
        self._pub_vel    = self.create_publisher(TwistStamped,  '/mavros/local_position/velocity_body',  10)

        # ── subscriber for dashboard commands ────────────────────────────────
        self.create_subscription(String, '/drone/cmd', self._on_cmd, 10)

        self._mav       = None
        self._armed     = False
        self._mode      = '—'
        self._connected = False

        # Lock protecting all MAVLink send operations (recv runs in its own thread)
        self._mav_lock  = threading.Lock()

        # 1 Hz state publisher + 1 Hz GCS heartbeat to Pixhawk
        self.create_timer(1.0, self._publish_state)
        self.create_timer(1.0, self._send_heartbeat)

        # MAVLink reader in background thread
        threading.Thread(target=self._mav_loop, daemon=True).start()
        self.get_logger().info(f'mavlink_bridge starting — {SERIAL_PORT} @ {BAUD_RATE}')

    # ── MAVLink reader loop ───────────────────────────────────────────────────
    def _mav_loop(self):
        while rclpy.ok():
            try:
                # F-12: close previous connection explicitly before opening a new one
                if self._mav is not None:
                    try:
                        self._mav.close()
                    except Exception:
                        pass
                    self._mav = None

                self.get_logger().info(f'Connecting to Pixhawk on {SERIAL_PORT}…')
                self._mav = mavutil.mavlink_connection(
                    SERIAL_PORT, baud=BAUD_RATE, source_system=255)
                hb = self._mav.wait_heartbeat(timeout=15)
                if hb is None:
                    raise Exception('No heartbeat received within 15 s')
                # Explicitly set target from heartbeat (pymavlink doesn't always do this)
                self._mav.target_system    = hb.get_srcSystem()
                self._mav.target_component = hb.get_srcComponent()
                self._connected = True
                self.get_logger().info(
                    f'Pixhawk connected ✓  '
                    f'sysid={self._mav.target_system} '
                    f'compid={self._mav.target_component}')
                self._request_streams()

                while rclpy.ok():
                    msg = self._mav.recv_match(blocking=True, timeout=2.0)
                    if msg is None:
                        continue
                    self._handle(msg)

            except Exception as exc:
                self._connected = False
                self.get_logger().warn(f'MAVLink disconnected: {exc} — retry in 5 s')
                time.sleep(5)

    def _request_streams(self):
        with self._mav_lock:
            m = self._mav
            if m is None:
                return
            for sid, rate in [
                (mavutil.mavlink.MAV_DATA_STREAM_ALL,        4),
                (mavutil.mavlink.MAV_DATA_STREAM_EXTRA1,    10),   # ATTITUDE
                (mavutil.mavlink.MAV_DATA_STREAM_EXTRA2,     4),   # VFR_HUD
                (mavutil.mavlink.MAV_DATA_STREAM_POSITION,   5),   # GPS
                (mavutil.mavlink.MAV_DATA_STREAM_RC_CHANNELS, 4),  # RC/SERVO
            ]:
                m.mav.request_data_stream_send(
                    m.target_system, m.target_component, sid, rate, 1)

    # ── F-08: 1 Hz GCS heartbeat → keeps ArduCopter streaming ────────────────
    def _send_heartbeat(self):
        with self._mav_lock:
            if self._mav is None or not self._connected:
                return
            try:
                self._mav.mav.heartbeat_send(
                    mavutil.mavlink.MAV_TYPE_GCS,
                    mavutil.mavlink.MAV_AUTOPILOT_INVALID,
                    0, 0, 0)
            except Exception as e:
                self.get_logger().debug(f'heartbeat_send error: {e}')

    # ── message dispatcher ────────────────────────────────────────────────────
    def _handle(self, msg):
        t = msg.get_type()

        if t == 'HEARTBEAT':
            self._armed = bool(
                msg.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)
            self._mode = MODE_REV.get(msg.custom_mode, str(msg.custom_mode))
            self.get_logger().debug(f'HB armed={self._armed} mode={self._mode}')

        elif t == 'VFR_HUD':
            self._pub_vfr.publish(String(data=json.dumps({
                'airspeed':    round(float(msg.airspeed),    2),
                'groundspeed': round(float(msg.groundspeed), 2),
                'heading':     int(msg.heading),
                'throttle':    int(msg.throttle),
                'alt':         round(float(msg.alt),   2),
                'climb':       round(float(msg.climb), 2),
            })))

        elif t == 'ATTITUDE':
            imu = Imu()
            r, p, y = msg.roll, msg.pitch, msg.yaw
            cy, sy = math.cos(y * 0.5), math.sin(y * 0.5)
            cp, sp = math.cos(p * 0.5), math.sin(p * 0.5)
            cr, sr = math.cos(r * 0.5), math.sin(r * 0.5)
            imu.orientation.w = cr * cp * cy + sr * sp * sy
            imu.orientation.x = sr * cp * cy - cr * sp * sy
            imu.orientation.y = cr * sp * cy + sr * cp * sy
            imu.orientation.z = cr * cp * sy - sr * sp * cy
            imu.angular_velocity.x = float(msg.rollspeed)
            imu.angular_velocity.y = float(msg.pitchspeed)
            imu.angular_velocity.z = float(msg.yawspeed)
            self._pub_imu.publish(imu)

        elif t == 'SYS_STATUS':
            bat = BatteryState()
            bat.voltage    = float(msg.voltage_battery) / 1000.0
            bat.current    = (float(msg.current_battery) / 100.0
                              if msg.current_battery >= 0 else float('nan'))
            bat.percentage = (float(msg.battery_remaining) / 100.0
                              if msg.battery_remaining >= 0 else float('nan'))
            self._pub_bat.publish(bat)

        elif t == 'GLOBAL_POSITION_INT':
            fix = NavSatFix()
            fix.latitude  = msg.lat / 1e7
            fix.longitude = msg.lon / 1e7
            fix.altitude  = msg.alt / 1000.0
            self._pub_gps.publish(fix)

            tw = TwistStamped()
            tw.twist.linear.x = float(msg.vx) / 100.0
            tw.twist.linear.y = float(msg.vy) / 100.0
            tw.twist.linear.z = float(msg.vz) / 100.0
            self._pub_vel.publish(tw)

        elif t == 'GPS_RAW_INT':
            self._pub_gpss.publish(String(data=json.dumps({
                'fix_type':           int(msg.fix_type),
                'satellites_visible': int(msg.satellites_visible),
            })))

        elif t == 'SERVO_OUTPUT_RAW':
            channels = [int(getattr(msg, f'servo{i}_raw', 1000)) for i in range(1, 9)]
            self._pub_motors.publish(String(data=json.dumps({'channels': channels})))

        elif t == 'RC_CHANNELS':
            channels = [int(getattr(msg, f'chan{i}_raw', 1000)) for i in range(1, 9)]
            self._pub_motors.publish(String(data=json.dumps({'channels': channels})))

    # ── 1 Hz state publisher ─────────────────────────────────────────────────
    def _publish_state(self):
        self._pub_state.publish(String(data=json.dumps({
            'armed':     self._armed,
            'mode':      self._mode,
            'connected': self._connected,
        })))

    # ── command handler ───────────────────────────────────────────────────────
    def _on_cmd(self, msg: String):
        if not self._connected or not self._mav:
            self.get_logger().warn('Cmd received but Pixhawk not connected')
            return
        try:
            d = json.loads(msg.data)
        except Exception:
            return

        action = d.get('action', '')

        with self._mav_lock:
            m = self._mav
            if m is None:
                return

            if action == 'arm':
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, 1, 0, 0, 0, 0, 0, 0)
                self.get_logger().info('ARM sent')

            elif action == 'disarm':
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                    0, 0, 0, 0, 0, 0, 0, 0)
                self.get_logger().info('DISARM sent')

            elif action == 'mode':
                name    = d.get('mode', 'LOITER').upper()
                mode_id = MODE_MAP.get(name, 5)
                m.mav.set_mode_send(
                    m.target_system,
                    mavutil.mavlink.MAV_MODE_FLAG_CUSTOM_MODE_ENABLED,
                    mode_id)
                self.get_logger().info(f'SET_MODE {name} ({mode_id})')

            elif action == 'takeoff':
                alt = float(d.get('alt', 5.0))
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    0, 0, 0, 0, 0, 0, 0, alt)
                self.get_logger().info(f'TAKEOFF {alt} m')

            elif action == 'land':
                m.mav.command_long_send(
                    m.target_system, m.target_component,
                    mavutil.mavlink.MAV_CMD_NAV_LAND,
                    0, 0, 0, 0, 0, 0, 0, 0)
                self.get_logger().info('LAND sent')


def main():
    rclpy.init()
    node = MavlinkBridge()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
