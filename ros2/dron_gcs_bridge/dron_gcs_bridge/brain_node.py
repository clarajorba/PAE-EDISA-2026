#!/usr/bin/env python3
"""
Brain node — autonomous mission planner.
Reads waypoints from SQLite, tracks position via LiDAR-SLAM odometry,
streams setpoints to MAVROS, and publishes the planned path for the GCS map.

Launch alongside the GCS stack (start_gcs.sh passes --brain flag).
"""
import rclpy
from rclpy.node import Node
import sqlite3
import json
import math
import os

from nav_msgs.msg    import Odometry
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import NavSatFix
from std_msgs.msg    import String

DB_PATH     = os.path.expanduser('~/brain_data.db')
ARRIVE_DIST = 1.5   # metres — waypoint considered reached


def dist2d(x1, y1, x2, y2):
    return math.hypot(x2 - x1, y2 - y1)


class BrainNode(Node):

    def __init__(self):
        super().__init__('brain_node')

        self._init_db()
        self._load_active_mission()

        self.slam_x  = None
        self.slam_y  = None
        self.gps     = None
        self.wp_idx  = 0
        self.done    = False

        self.create_subscription(Odometry,  '/Odometry',                      self._on_odom, 10)
        self.create_subscription(NavSatFix, '/mavros/global_position/global', self._on_gps,  10)

        self._pub_sp   = self.create_publisher(PoseStamped, '/mavros/setpoint_position/local', 10)
        self._pub_path = self.create_publisher(String,      '/brain/planned_path',             10)

        self.create_timer(0.1,  self._tick)         # 10 Hz control loop
        self.create_timer(1.0,  self._publish_path) # 1 Hz map display
        self.get_logger().info(
            f'Brain node ready — mission "{self.mission_name}" with {len(self.waypoints)} waypoints'
        )

    # ── database ──────────────────────────────────────────────────────────────

    def _init_db(self):
        con = sqlite3.connect(DB_PATH)
        con.executescript('''
            CREATE TABLE IF NOT EXISTS missions (
                id         INTEGER PRIMARY KEY,
                name       TEXT NOT NULL,
                active     INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS waypoints (
                id         INTEGER PRIMARY KEY,
                mission_id INTEGER NOT NULL REFERENCES missions(id),
                seq        INTEGER NOT NULL,
                x          REAL    NOT NULL,
                y          REAL    NOT NULL,
                z          REAL    NOT NULL DEFAULT 5.0,
                label      TEXT             DEFAULT ''
            );
        ''')
        # Seed a default square mission when the DB is brand new
        if con.execute('SELECT COUNT(*) FROM missions').fetchone()[0] == 0:
            con.execute("INSERT INTO missions (name, active) VALUES ('default', 1)")
            mid = con.execute('SELECT last_insert_rowid()').fetchone()[0]
            # 5 m square at 5 m altitude — edit via DB to match the real environment
            con.executemany(
                'INSERT INTO waypoints (mission_id,seq,x,y,z,label) VALUES (?,?,?,?,?,?)',
                [
                    (mid, 0,  0.0,  0.0, 5.0, 'origin'),
                    (mid, 1,  5.0,  0.0, 5.0, 'wp-1'),
                    (mid, 2,  5.0,  5.0, 5.0, 'wp-2'),
                    (mid, 3,  0.0,  5.0, 5.0, 'wp-3'),
                    (mid, 4,  0.0,  0.0, 5.0, 'home'),
                ],
            )
        con.commit()
        con.close()

    def _load_active_mission(self):
        con = sqlite3.connect(DB_PATH)
        row = con.execute(
            'SELECT id, name FROM missions WHERE active=1 ORDER BY id DESC LIMIT 1'
        ).fetchone()
        if not row:
            self.mission_name = 'none'
            self.waypoints    = []
            con.close()
            return
        mid = row[0]
        self.mission_name = row[1]
        self.waypoints = [
            {'seq': r[0], 'x': r[1], 'y': r[2], 'z': r[3], 'label': r[4]}
            for r in con.execute(
                'SELECT seq,x,y,z,label FROM waypoints WHERE mission_id=? ORDER BY seq',
                (mid,),
            )
        ]
        con.close()

    # ── subscribers ───────────────────────────────────────────────────────────

    def _on_odom(self, msg):
        p = msg.pose.pose.position
        self.slam_x = p.x
        self.slam_y = p.y

    def _on_gps(self, msg):
        self.gps = msg

    # ── control loop ──────────────────────────────────────────────────────────

    def _tick(self):
        if self.done or not self.waypoints or self.slam_x is None:
            return

        if self.wp_idx >= len(self.waypoints):
            self.get_logger().info('Mission complete.', once=True)
            self.done = True
            return

        wp = self.waypoints[self.wp_idx]
        if dist2d(self.slam_x, self.slam_y, wp['x'], wp['y']) < ARRIVE_DIST:
            self.get_logger().info(f'Reached "{wp["label"]}" (wp {self.wp_idx})')
            self.wp_idx += 1
            return

        sp = PoseStamped()
        sp.header.stamp    = self.get_clock().now().to_msg()
        sp.header.frame_id = 'map'
        sp.pose.position.x = float(wp['x'])
        sp.pose.position.y = float(wp['y'])
        sp.pose.position.z = float(wp['z'])
        sp.pose.orientation.w = 1.0
        self._pub_sp.publish(sp)

    def _publish_path(self):
        self._pub_path.publish(String(data=json.dumps({
            'mission':    self.mission_name,
            'wp_index':   self.wp_idx,
            'done':       self.done,
            'waypoints':  self.waypoints,
            'slam_pos':   {'x': self.slam_x, 'y': self.slam_y}
                          if self.slam_x is not None else None,
        })))


def main():
    rclpy.init()
    node = BrainNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
