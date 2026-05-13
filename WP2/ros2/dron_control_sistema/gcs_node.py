"""Ground Control Station GUI — telemetry, video streams and SLAM map."""

import math
import sys
import threading
import tkinter as tk
from tkinter import ttk

from geometry_msgs.msg import Twist
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray

# Future imports — uncomment when topics are available:
# from sensor_msgs.msg import Image
# from nav_msgs.msg import Odometry
# from geometry_msgs.msg import PoseStamped
# from std_msgs.msg import Float32

# ── Colour palette (matches gui_node.py) ─────────────────────────────────────
_BG = '#1a1d23'
_PANEL = '#252830'
_BORDER = '#333740'
_ACCENT = '#4fc3f7'
_GREEN = '#4caf50'
_RED = '#e53935'
_ORANGE = '#ff9800'
_TEXT = '#e0e0e0'
_DIM = '#616161'

# Broadcast test-pattern bar colours (SMPTE-style)
_TEST_BARS = [
    '#c0c0c0', '#c0c000', '#00c0c0', '#00c000',
    '#c000c0', '#c00000', '#0000c0', '#181818',
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _labeled_group(parent: tk.Widget, title: str) -> tuple:
    """Return (outer_frame, inner_frame) forming a dark bordered group box."""
    outer = tk.Frame(parent, bg=_BORDER, padx=1, pady=1)
    inner = tk.Frame(outer, bg=_PANEL)
    inner.pack(fill='both', expand=True)
    if title:
        tk.Label(
            inner, text=title.upper(), bg=_PANEL, fg=_ACCENT,
            font=('Monospace', 8, 'bold'),
        ).pack(anchor='w', padx=6, pady=(4, 0))
    return outer, inner


# ── Video panel ───────────────────────────────────────────────────────────────

class VideoPanel(tk.Canvas):
    """Canvas showing a broadcast test pattern with a NO SIGNAL overlay.

    Wired to a sensor_msgs/Image subscription once the camera node is ready.
    """

    def __init__(self, parent: tk.Widget, label: str = 'CAMERA', **kw):
        """Create the canvas; redraws on every resize."""
        super().__init__(parent, bg='#000000', highlightthickness=0, **kw)
        self._label = label
        self.bind('<Configure>', lambda _: self._redraw())

    def _redraw(self) -> None:
        """Paint the test-pattern bars and NO SIGNAL text."""
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10 or h < 10:
            return

        bar_w = w / len(_TEST_BARS)
        bar_h = int(h * 0.62)
        for i, colour in enumerate(_TEST_BARS):
            self.create_rectangle(
                int(i * bar_w), 0, int((i + 1) * bar_w), bar_h,
                fill=colour, outline='',
            )
        self.create_rectangle(0, bar_h, w, h, fill='#0a0a0a', outline='')

        self.create_text(
            w // 2, h // 2 + 14,
            text='NO  SIGNAL',
            fill='#ffffff', font=('Monospace', 13, 'bold'),
        )
        self.create_text(
            w // 2, h // 2 + 34,
            text=f'[ {self._label} ]',
            fill=_ACCENT, font=('Monospace', 8),
        )
        self.create_text(
            6, 6, text=self._label, anchor='nw',
            fill=_DIM, font=('Monospace', 7),
        )

    def update_frame(self, rgb_array) -> None:
        """Display a numpy HxWx3 uint8 RGB frame from a sensor_msgs/Image callback.

        Not implemented — placeholder for the camera node integration.
        """
        pass  # implement: convert array → PhotoImage, self.create_image(...)


# ── Navigation map ────────────────────────────────────────────────────────────

class NavMapPanel(tk.Canvas):
    """Scrolling grid map with a live drone dot and heading arrow.

    Intended to receive nav_msgs/Odometry or geometry_msgs/PoseStamped.
    Falls back to /drone/pose data until the SLAM topic is available.
    """

    _TRAIL_MAX = 300
    _SCALE = 28.0  # pixels per metre

    def __init__(self, parent: tk.Widget, **kw):
        """Initialise map with empty trail and zero pose."""
        super().__init__(parent, bg=_BG, highlightthickness=0, **kw)
        self._x = 0.0
        self._y = 0.0
        self._yaw = 0.0
        self._trail: list = []
        self.bind('<Configure>', lambda _: self._redraw())

    def _to_px(self, x: float, y: float) -> tuple:
        """Convert world metres to canvas pixel coordinates."""
        cx = self.winfo_width() / 2
        cy = self.winfo_height() / 2
        return cx + x * self._SCALE, cy - y * self._SCALE

    def _redraw(self) -> None:
        """Repaint grid, trail and drone marker."""
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 10:
            return

        # Grid lines
        cx, cy = w / 2, h / 2
        step = self._SCALE
        cols = int(w / step) + 2
        rows = int(h / step) + 2
        for i in range(-cols, cols + 1):
            gx = cx + i * step
            clr = _DIM if i == 0 else _BORDER
            self.create_line(gx, 0, gx, h, fill=clr, width=1 if i == 0 else 1)
        for j in range(-rows, rows + 1):
            gy = cy + j * step
            clr = _DIM if j == 0 else _BORDER
            self.create_line(0, gy, w, gy, fill=clr, width=1)

        # Compass label
        self.create_text(
            cx + 4, 8, text='N ↑', anchor='nw',
            fill=_ACCENT, font=('Monospace', 8, 'bold'),
        )

        # Trail
        if len(self._trail) >= 2:
            pts = []
            for tx, ty in self._trail:
                px, py = self._to_px(tx, ty)
                pts += [px, py]
            self.create_line(*pts, fill='#546e7a', width=1, smooth=True)

        # Drone circle + heading arrow
        px, py = self._to_px(self._x, self._y)
        r = 7
        self.create_oval(
            px - r, py - r, px + r, py + r,
            fill=_GREEN, outline='#ffffff', width=1,
        )
        ax = px + 15 * math.cos(self._yaw - math.pi / 2)
        ay = py + 15 * math.sin(self._yaw - math.pi / 2)
        self.create_line(
            px, py, ax, ay,
            fill=_GREEN, width=2, arrow='last', arrowshape=(8, 10, 3),
        )

        # Placeholder note
        self.create_text(
            6, h - 6,
            text='nav_msgs/Odometry  (pending — using /drone/pose)',
            anchor='sw', fill=_DIM, font=('Monospace', 7),
        )

    def update_pose(self, x: float, y: float, yaw: float) -> None:
        """Move the drone marker and extend the trail."""
        self._x, self._y, self._yaw = x, y, yaw
        self._trail.append((x, y))
        if len(self._trail) > self._TRAIL_MAX:
            self._trail = self._trail[-self._TRAIL_MAX:]
        self._redraw()


# ── Speed gauge ───────────────────────────────────────────────────────────────

class SpeedGauge(tk.Canvas):
    """Semicircular arc gauge for current speed derived from /drone/cmd_vel."""

    MAX_SPD = 10.0

    def __init__(self, parent: tk.Widget, **kw):
        """Create gauge canvas with zero initial value."""
        super().__init__(parent, bg=_PANEL, highlightthickness=0, **kw)
        self._value = 0.0
        self.bind('<Configure>', lambda _: self._redraw())

    def _redraw(self) -> None:
        """Repaint the arc, needle and numeric readout."""
        self.delete('all')
        w, h = self.winfo_width(), self.winfo_height()
        if w < 30:
            return

        cx = w / 2
        cy = h * 0.58
        r = min(cx - 14, cy - 8) * 0.88

        # Background arc
        self.create_arc(
            cx - r, cy - r, cx + r, cy + r,
            start=0, extent=180, style='arc',
            outline=_BORDER, width=9,
        )

        # Value arc
        frac = min(self._value / self.MAX_SPD, 1.0)
        extent = frac * 180.0
        arc_clr = _GREEN if frac < 0.6 else (_ORANGE if frac < 0.85 else _RED)
        if extent > 0.5:
            self.create_arc(
                cx - r, cy - r, cx + r, cy + r,
                start=0, extent=extent, style='arc',
                outline=arc_clr, width=9,
            )

        # Needle
        angle = math.radians(frac * 180.0)
        nx = cx + r * 0.78 * math.cos(math.pi - angle)
        ny = cy - r * 0.78 * math.sin(math.pi - angle)
        self.create_line(cx, cy, nx, ny, fill='#ffffff', width=2)
        self.create_oval(cx - 4, cy - 4, cx + 4, cy + 4,
                         fill=_PANEL, outline='#aaaaaa', width=1)

        # Readout
        self.create_text(cx, cy + 16,
                         text=f'{self._value:.1f}',
                         fill='#ffffff', font=('Monospace', 14, 'bold'))
        self.create_text(cx, cy + 32,
                         text='m/s  SPEED',
                         fill=_DIM, font=('Monospace', 8))

        # Scale end-labels
        self.create_text(cx - r - 2, cy + 5, text='0',
                         fill=_DIM, font=('Monospace', 7), anchor='e')
        self.create_text(cx + r + 2, cy + 5,
                         text=str(int(self.MAX_SPD)),
                         fill=_DIM, font=('Monospace', 7), anchor='w')

    def set_value(self, value: float) -> None:
        """Update gauge reading. Called from the UI refresh loop."""
        self._value = max(0.0, float(value))
        self._redraw()


# ── Altitude bar ──────────────────────────────────────────────────────────────

class AltitudeBar(tk.Frame):
    """Vertical filled bar showing current altitude from /drone/pose[2]."""

    MAX_ALT = 10.0

    def __init__(self, parent: tk.Widget, **kw):
        """Build the canvas bar and numeric label."""
        super().__init__(parent, bg=_PANEL, **kw)
        self._value = 0.0
        self._build()

    def _build(self) -> None:
        tk.Label(self, text='ALTITUDE', bg=_PANEL, fg=_ACCENT,
                 font=('Monospace', 8, 'bold')).pack(pady=(4, 0))
        self._canvas = tk.Canvas(self, bg=_BG, highlightthickness=0, width=44)
        self._canvas.pack(fill='y', expand=True, padx=12, pady=4)
        self._canvas.bind('<Configure>', lambda _: self._redraw())
        self._lbl = tk.Label(self, text='0.0 m', bg=_PANEL, fg='#ffffff',
                             font=('Monospace', 10, 'bold'))
        self._lbl.pack(pady=(0, 6))

    def _redraw(self) -> None:
        """Repaint the vertical bar."""
        self._canvas.delete('all')
        w = self._canvas.winfo_width()
        h = self._canvas.winfo_height()
        if h < 20:
            return
        frac = min(self._value / self.MAX_ALT, 1.0)
        bar_h = int(frac * (h - 6))
        self._canvas.create_rectangle(3, 3, w - 3, h - 3,
                                      fill=_BORDER, outline=_BORDER)
        if bar_h > 0:
            clr = _ACCENT if frac < 0.8 else _RED
            self._canvas.create_rectangle(3, h - 3 - bar_h, w - 3, h - 3,
                                          fill=clr, outline='')
        # Tick marks at 25 % intervals
        for i in range(1, 4):
            ty = h - 3 - int(i / 4 * (h - 6))
            self._canvas.create_line(w - 7, ty, w - 3, ty, fill=_DIM)

    def set_value(self, value: float) -> None:
        """Update bar height and label. Called from the UI refresh loop."""
        self._value = max(0.0, float(value))
        self._lbl.config(text=f'{self._value:.1f} m')
        self._redraw()


# ── Battery bar ───────────────────────────────────────────────────────────────

class BatteryBar(tk.Frame):
    """Horizontal progress bar for battery percentage.

    Awaiting a /sensor/battery (std_msgs/Float32) publisher.
    """

    def __init__(self, parent: tk.Widget, **kw):
        """Build the ttk progress bar and percentage label."""
        super().__init__(parent, bg=_PANEL, **kw)
        self._value = 100.0
        self._style = ttk.Style(self)
        self._build()

    def _build(self) -> None:
        tk.Label(self, text='BATTERY', bg=_PANEL, fg=_ACCENT,
                 font=('Monospace', 8, 'bold')).pack(pady=(4, 0))

        self._style.theme_use('default')
        self._style.configure(
            'Bat.Horizontal.TProgressbar',
            troughcolor=_BORDER, background=_GREEN,
            borderwidth=0, relief='flat',
        )
        self._bar = ttk.Progressbar(
            self, style='Bat.Horizontal.TProgressbar',
            orient='horizontal', length=180, mode='determinate',
            maximum=100, value=100,
        )
        self._bar.pack(padx=10, pady=6)

        self._lbl = tk.Label(
            self, text='100 %  ██████████',
            bg=_PANEL, fg=_GREEN, font=('Monospace', 10, 'bold'),
        )
        self._lbl.pack(pady=(0, 4))

        tk.Label(
            self,
            text='/sensor/battery  (pending)',
            bg=_PANEL, fg=_DIM, font=('Monospace', 7),
        ).pack(pady=(0, 2))

    def set_value(self, value: float) -> None:
        """Update bar fill and colour. Called from the UI refresh loop."""
        self._value = max(0.0, min(100.0, float(value)))
        self._bar['value'] = self._value
        blocks = int(self._value / 10)
        bar_str = '█' * blocks + '░' * (10 - blocks)
        clr = _GREEN if self._value > 30 else (_ORANGE if self._value > 15 else _RED)
        self._lbl.config(text=f'{int(self._value)} %  {bar_str}', fg=clr)
        self._style.configure('Bat.Horizontal.TProgressbar', background=clr)


# ── Barcode database log ──────────────────────────────────────────────────────

class BarcodeLog(tk.Frame):
    """Scrollable table ready to receive barcode detection entries.

    The detection logic (image tracking node) is not yet implemented.
    Call add_entry() from the future barcode callback to populate rows.
    """

    _COLS = ('time', 'barcode', 'shelf', 'row', 'conf')
    _HDRS = ('Time', 'Barcode', 'Shelf', 'Row', 'Conf.')
    _WIDTHS = (68, 140, 55, 45, 55)

    def __init__(self, parent: tk.Widget, **kw):
        """Build the Treeview and its vertical scrollbar."""
        super().__init__(parent, bg=_PANEL, **kw)
        self._build()

    def _build(self) -> None:
        tk.Label(
            self, text='BARCODE DATABASE LOG', bg=_PANEL, fg=_ACCENT,
            font=('Monospace', 8, 'bold'),
        ).pack(anchor='w', padx=6, pady=(4, 0))

        style = ttk.Style(self)
        style.theme_use('default')
        style.configure(
            'GCS.Treeview',
            background=_BG, foreground=_TEXT, rowheight=22,
            fieldbackground=_BG, borderwidth=0, font=('Monospace', 9),
        )
        style.configure(
            'GCS.Treeview.Heading',
            background=_PANEL, foreground=_ACCENT,
            relief='flat', font=('Monospace', 8, 'bold'),
        )
        style.map('GCS.Treeview', background=[('selected', '#2a3a4a')])

        wrap = tk.Frame(self, bg=_PANEL)
        wrap.pack(fill='both', expand=True, padx=6, pady=4)

        self._tree = ttk.Treeview(
            wrap, columns=self._COLS, show='headings', style='GCS.Treeview',
        )
        for col, hdr, w in zip(self._COLS, self._HDRS, self._WIDTHS):
            self._tree.heading(col, text=hdr)
            self._tree.column(col, width=w, anchor='center', stretch=True)

        vsb = ttk.Scrollbar(wrap, orient='vertical', command=self._tree.yview)
        self._tree.configure(yscrollcommand=vsb.set)
        self._tree.pack(side='left', fill='both', expand=True)
        vsb.pack(side='right', fill='y')

        self._note = tk.Label(
            self,
            text='Awaiting barcode detections…\n'
                 '(image tracking node not yet implemented)',
            bg=_PANEL, fg=_DIM, font=('Monospace', 8), justify='center',
        )
        self._note.pack(pady=4)

    def add_entry(self, timestamp: str, barcode: str,
                  shelf: str, row: str, confidence: str) -> None:
        """Insert one detection row and scroll to the bottom.

        Hook this to the future barcode/detection callback.
        """
        self._tree.insert('', 'end',
                          values=(timestamp, barcode, shelf, row, confidence))
        self._tree.yview_moveto(1.0)
        if self._note.winfo_manager():
            self._note.pack_forget()


# ── Thread-safe telemetry state ───────────────────────────────────────────────

class _State:
    """Shared data written by ROS callbacks and read by the UI refresh loop."""

    def __init__(self):
        """Initialise all fields to safe defaults."""
        self.lock = threading.Lock()
        self.pose = [0.0, 0.0, 0.0, 0.0]   # x, y, z, yaw
        self.target = [0.0, 0.0, 0.0]       # tx, ty, tz
        self.speed = 0.0                     # magnitude of cmd_vel
        self.battery = 100.0                 # percent (future topic)
        self.dirty = False


# ── Main window ───────────────────────────────────────────────────────────────

class GCSWindow:
    """Root window of the Ground Control Station.

    Builds all panels on a dark grid layout and runs a 20 Hz refresh loop
    that pulls data from _State and pushes it to each widget.
    """

    def __init__(self, root: tk.Tk, node: 'GCSNode', state: _State):
        """Wire up the root window, build the UI and start the refresh loop."""
        self._root = root
        self._node = node
        self._state = state
        self._build_window()
        self._schedule_refresh()

    # ── Window assembly ───────────────────────────────────────────────────────

    def _build_window(self) -> None:
        self._root.title('Drone GCS — dron_control_sistema')
        self._root.configure(bg=_BG)
        self._root.minsize(1280, 740)

        self._build_header()

        body = tk.Frame(self._root, bg=_BG)
        body.pack(fill='both', expand=True, padx=6, pady=(0, 6))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=1)
        body.columnconfigure(2, weight=1)
        body.rowconfigure(0, weight=3)
        body.rowconfigure(1, weight=2)

        self._build_video_row(body)
        self._build_telemetry_row(body)

    def _build_header(self) -> None:
        bar = tk.Frame(self._root, bg=_PANEL, height=40)
        bar.pack(fill='x', padx=6, pady=6)
        bar.pack_propagate(False)

        tk.Label(
            bar, text='DRONE GCS', bg=_PANEL, fg=_ACCENT,
            font=('Monospace', 12, 'bold'),
        ).pack(side='left', padx=14)

        self._lbl_pose = tk.Label(
            bar, text='Pose  X:—  Y:—  Z:—  Yaw:—',
            bg=_PANEL, fg=_TEXT, font=('Monospace', 10),
        )
        self._lbl_pose.pack(side='left', padx=20)

        tk.Label(
            bar, text='ROS2 / dron_control_sistema',
            bg=_PANEL, fg=_DIM, font=('Monospace', 9),
        ).pack(side='right', padx=14)

        self._lbl_status = tk.Label(
            bar, text='● ONLINE', bg=_PANEL, fg=_GREEN,
            font=('Monospace', 10, 'bold'),
        )
        self._lbl_status.pack(side='right', padx=10)

    def _build_video_row(self, parent: tk.Frame) -> None:
        grp1, inn1 = _labeled_group(parent, 'Camera 1  —  /sensor/camera_front  (pending)')
        grp1.grid(row=0, column=0, sticky='nsew', padx=(0, 3), pady=(0, 3))
        self._cam1 = VideoPanel(inn1, label='CAM FRONT', width=320, height=230)
        self._cam1.pack(fill='both', expand=True, padx=4, pady=4)

        grp2, inn2 = _labeled_group(parent, 'Camera 2  —  /sensor/camera_down  (pending)')
        grp2.grid(row=0, column=1, sticky='nsew', padx=3, pady=(0, 3))
        self._cam2 = VideoPanel(inn2, label='CAM DOWN', width=320, height=230)
        self._cam2.pack(fill='both', expand=True, padx=4, pady=4)

        grp3, inn3 = _labeled_group(parent,
                                    'Nav Map  —  nav_msgs/Odometry  (pending)')
        grp3.grid(row=0, column=2, sticky='nsew', padx=(3, 0), pady=(0, 3))
        self._nav_map = NavMapPanel(inn3, width=320, height=230)
        self._nav_map.pack(fill='both', expand=True, padx=4, pady=4)

    def _build_telemetry_row(self, parent: tk.Frame) -> None:
        tele = tk.Frame(parent, bg=_BG)
        tele.grid(row=1, column=0, columnspan=3, sticky='nsew')
        tele.columnconfigure(0, weight=1)
        tele.columnconfigure(1, weight=1)
        tele.columnconfigure(2, weight=2)
        tele.columnconfigure(3, weight=4)
        tele.rowconfigure(0, weight=1)

        grp_s, inn_s = _labeled_group(tele, 'Speed  —  /drone/cmd_vel')
        grp_s.grid(row=0, column=0, sticky='nsew', padx=(0, 3))
        self._speed_gauge = SpeedGauge(inn_s, width=180, height=130)
        self._speed_gauge.pack(fill='both', expand=True, padx=4, pady=4)

        grp_a, inn_a = _labeled_group(tele, 'Altitude  —  /drone/pose [z]')
        grp_a.grid(row=0, column=1, sticky='nsew', padx=3)
        self._alt_bar = AltitudeBar(inn_a)
        self._alt_bar.pack(fill='both', expand=True)

        grp_b, inn_b = _labeled_group(tele, 'Battery  —  /sensor/battery  (pending)')
        grp_b.grid(row=0, column=2, sticky='nsew', padx=3)
        self._battery_bar = BatteryBar(inn_b)
        self._battery_bar.pack(fill='both', expand=True)

        grp_l, inn_l = _labeled_group(tele, '')
        grp_l.grid(row=0, column=3, sticky='nsew', padx=(3, 0))
        self._barcode_log = BarcodeLog(inn_l)
        self._barcode_log.pack(fill='both', expand=True)

    # ── 20 Hz refresh loop ────────────────────────────────────────────────────

    def _schedule_refresh(self) -> None:
        """Queue the next refresh tick via tkinter's event loop."""
        self._root.after(50, self._refresh)

    def _refresh(self) -> None:
        """Pull latest state from the shared object and push to each widget."""
        with self._state.lock:
            if not self._state.dirty:
                self._schedule_refresh()
                return
            x, y, z, yaw = self._state.pose
            speed = self._state.speed
            battery = self._state.battery
            self._state.dirty = False

        self._speed_gauge.set_value(speed)
        self._alt_bar.set_value(z)
        self._battery_bar.set_value(battery)
        self._nav_map.update_pose(x, y, yaw)
        self._lbl_pose.config(
            text=(
                f'Pose  X:{x:+.2f}  Y:{y:+.2f}  Z:{z:+.2f}'
                f'  Yaw:{math.degrees(yaw):.1f}°'
            )
        )
        self._schedule_refresh()

    # ── Public hooks (called by future topic callbacks) ───────────────────────

    def push_camera_frame(self, panel_id: int, rgb_array) -> None:
        """Forward a decoded Image frame to camera panel 1 or 2.

        panel_id: 1 → front camera, 2 → down camera.
        """
        panel = self._cam1 if panel_id == 1 else self._cam2
        panel.update_frame(rgb_array)

    def push_barcode(self, timestamp: str, barcode: str,
                     shelf: str, row: str, confidence: str) -> None:
        """Add a barcode detection row to the database log."""
        self._barcode_log.add_entry(timestamp, barcode, shelf, row, confidence)


# ── ROS2 node ─────────────────────────────────────────────────────────────────

class GCSNode(Node):
    """Embedded ROS2 node: subscribes to telemetry and feeds _State.

    Active topics
    -------------
    /drone/pose        Float32MultiArray  [x, y, z, yaw]
    /cerebro/target    Float32MultiArray  [tx, ty, tz]
    /drone/cmd_vel     geometry_msgs/Twist

    Stub topics (uncomment when hardware/nodes are ready)
    -----------------------------------------------------
    /sensor/camera_front   sensor_msgs/Image
    /sensor/camera_down    sensor_msgs/Image
    /slam/odom             nav_msgs/Odometry
    /sensor/battery        std_msgs/Float32
    """

    def __init__(self, state: _State):
        """Create subscriptions and attach shared state."""
        super().__init__('gcs_node')
        self._state = state

        # ── Active subscriptions ──────────────────────────────────────────────
        self.sub_pose = self.create_subscription(
            Float32MultiArray, '/drone/pose', self._pose_cb, 10)
        self.sub_target = self.create_subscription(
            Float32MultiArray, '/cerebro/target', self._target_cb, 10)
        self.sub_vel = self.create_subscription(
            Twist, '/drone/cmd_vel', self._vel_cb, 10)

        # ── Stub subscriptions — wire up when topics go live ──────────────────
        # from sensor_msgs.msg import Image
        # from nav_msgs.msg import Odometry
        # from std_msgs.msg import Float32
        #
        # self.sub_cam_front = self.create_subscription(
        #     Image, '/sensor/camera_front', self._cam_front_cb, 10)
        # self.sub_cam_down = self.create_subscription(
        #     Image, '/sensor/camera_down', self._cam_down_cb, 10)
        # self.sub_odom = self.create_subscription(
        #     Odometry, '/slam/odom', self._odom_cb, 10)
        # self.sub_battery = self.create_subscription(
        #     Float32, '/sensor/battery', self._battery_cb, 10)

        self.get_logger().info('GCS node online — subscribed to active topics')

    # ── Active callbacks ──────────────────────────────────────────────────────

    def _pose_cb(self, msg: Float32MultiArray) -> None:
        """Write drone pose into shared state."""
        d = msg.data
        yaw = float(d[3]) if len(d) > 3 else 0.0
        with self._state.lock:
            self._state.pose = [float(d[0]), float(d[1]), float(d[2]), yaw]
            self._state.dirty = True

    def _target_cb(self, msg: Float32MultiArray) -> None:
        """Write current waypoint target into shared state."""
        d = msg.data
        with self._state.lock:
            self._state.target = [float(d[0]), float(d[1]), float(d[2])]

    def _vel_cb(self, msg: Twist) -> None:
        """Compute speed magnitude from cmd_vel and write to shared state."""
        speed = math.sqrt(
            msg.linear.x ** 2 + msg.linear.y ** 2 + msg.linear.z ** 2
        )
        with self._state.lock:
            self._state.speed = speed
            self._state.dirty = True

    # ── Stub callbacks — implement when hardware is connected ─────────────────

    # def _cam_front_cb(self, msg):
    #     """Decode sensor_msgs/Image and forward to push_camera_frame(1, ...)."""
    #     pass
    #
    # def _cam_down_cb(self, msg):
    #     """Decode sensor_msgs/Image and forward to push_camera_frame(2, ...)."""
    #     pass
    #
    # def _odom_cb(self, msg):
    #     """Extract x, y, yaw from Odometry and call _state.pose update."""
    #     pass
    #
    # def _battery_cb(self, msg):
    #     """Forward battery percentage to _state.battery."""
    #     pass


# ── Entry point ───────────────────────────────────────────────────────────────

def main(args=None):
    """Launch the GCS: ROS2 node in a daemon thread, tkinter on the main thread."""
    rclpy.init(args=args)
    state = _State()
    node = GCSNode(state)

    ros_thread = threading.Thread(
        target=rclpy.spin, args=(node,), daemon=True)
    ros_thread.start()

    root = tk.Tk()
    gcs = GCSWindow(root, node, state)  # noqa: F841

    try:
        root.mainloop()
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass

    sys.exit(0)


if __name__ == '__main__':
    main()
