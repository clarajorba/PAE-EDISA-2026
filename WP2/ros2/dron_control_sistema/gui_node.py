"""Panel de operador central: vistas en tiempo real, cámara y base de datos."""

import json
import sys
import threading
from pathlib import Path

import numpy as np
import rclpy
from rclpy.node import Node
from std_msgs.msg import Float32MultiArray, Float32
from geometry_msgs.msg import Twist

try:
    from ament_index_python.packages import get_package_share_directory
    _share = get_package_share_directory('dron_control_sistema')
    _MISION_FILE = Path(_share) / 'mision.json'
except Exception:
    _MISION_FILE = Path(__file__).parent / 'mision.json'

try:
    from PyQt5.QtWidgets import (
        QApplication, QMainWindow, QWidget, QLabel, QPushButton,
        QHBoxLayout, QVBoxLayout, QGroupBox,
        QTableWidget, QTableWidgetItem, QHeaderView, QSplitter, QFrame,
        QSizePolicy,
    )
    from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject
    from PyQt5.QtGui import QFont, QPalette, QColor
    import matplotlib
    matplotlib.use('Qt5Agg')
    from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
    from matplotlib.figure import Figure
    import matplotlib.patches as mpatches
    _GUI_OK = True
except ImportError:
    _GUI_OK = False

# ── Paleta oscura ────────────────────────────────────────────────────────────
_BG = '#1a1d23'
_PANEL = '#252830'
_ACCENT = '#4fc3f7'
_GREEN = '#4caf50'
_RED = '#e53935'
_ORANGE = '#ff9800'
_TEXT = '#e0e0e0'
_DIM = '#616161'
_SHELF_CLR = '#37474f'


# ── Helpers de estilo ────────────────────────────────────────────────────────

def _dark_palette() -> 'QPalette':
    """Devolver QPalette con tema oscuro para toda la aplicación."""
    p = QPalette()
    for role, color in [
        (QPalette.Window,          _BG),
        (QPalette.WindowText,      _TEXT),
        (QPalette.Base,            _PANEL),
        (QPalette.AlternateBase,   _BG),
        (QPalette.Text,            _TEXT),
        (QPalette.Button,          _PANEL),
        (QPalette.ButtonText,      _TEXT),
        (QPalette.Highlight,       _ACCENT),
        (QPalette.HighlightedText, '#000000'),
    ]:
        p.setColor(role, QColor(color))
    return p


def _make_button(label: str, bg: str, fg: str = '#ffffff',
                 min_w: int = 100) -> 'QPushButton':
    """Crear QPushButton con estilo plano coherente con el tema."""
    btn = QPushButton(label)
    btn.setMinimumWidth(min_w)
    btn.setFixedHeight(36)
    btn.setStyleSheet(
        f'QPushButton{{background:{bg};color:{fg};border:none;'
        f'border-radius:4px;font-weight:bold;font-size:13px;}}'
        f'QPushButton:hover{{background:{bg}cc;}}'
        f'QPushButton:pressed{{background:{bg}88;}}'
    )
    return btn


def _group_style() -> str:
    """Devolver hoja de estilo común para QGroupBox."""
    return (
        f'QGroupBox{{color:{_ACCENT};font-weight:bold;font-size:11px;'
        f'border:1px solid #333;border-radius:6px;margin-top:10px;'
        f'padding-top:6px;}}'
        f'QGroupBox::title{{subcontrol-origin:margin;left:10px;}}'
    )


# ── Vistas matplotlib ────────────────────────────────────────────────────────

class _MplCanvas(FigureCanvasQTAgg):
    """Canvas base: fondo oscuro, cuadrícula sutil y tamaño elástico."""

    def __init__(self, w: float = 5.0, h: float = 4.0):
        """Inicializar figura matplotlib con tema oscuro."""
        fig = Figure(figsize=(w, h), facecolor=_PANEL)
        fig.subplots_adjust(left=0.11, right=0.97, top=0.91, bottom=0.13)
        self.ax = fig.add_subplot(111, facecolor=_BG)
        super().__init__(fig)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.ax.tick_params(colors=_DIM, labelsize=8)
        for sp in self.ax.spines.values():
            sp.set_color(_DIM)
        self.ax.grid(True, color='#2e3038', linewidth=0.5, zorder=0)


class TopViewCanvas(_MplCanvas):
    """Vista superior XY: trayectoria de misión, dron y objetivo actual."""

    _TRAIL_MAX = 400

    def __init__(self):
        """Inicializar canvas y cargar la misión del fichero JSON."""
        super().__init__(w=5.5, h=4.0)
        self._trail_x: list = []
        self._trail_y: list = []
        self._setup_axes()
        self._load_mission()
        self._trail_ln, = self.ax.plot(
            [], [], '-', color='#546e7a', lw=0.9, zorder=2)
        self._drone_pt, = self.ax.plot(
            [], [], 'o', color=_GREEN, ms=10, zorder=5)
        self._drone_arrow, = self.ax.plot(
            [], [], '-', color=_GREEN, lw=2.0, zorder=5)
        self._target_pt, = self.ax.plot(
            [], [], 'x', color=_ORANGE, ms=10, mew=2.0, zorder=4)

    def _setup_axes(self) -> None:
        """Configurar límites, etiquetas y estantes."""
        self.ax.set_xlim(-1.5, 14.0)
        self.ax.set_ylim(-1.2, 5.5)
        self.ax.set_xlabel('X  (m)', color=_TEXT, fontsize=9)
        self.ax.set_ylabel('Y  (m)', color=_TEXT, fontsize=9)
        self.ax.set_title('Vista Superior  –  plano XY', color=_ACCENT,
                          fontsize=10, pad=4)
        shelf_w, shelf_h = 3.0, 4.0
        for sx, name in [(0, 'E1'), (5, 'E2'), (10, 'E3')]:
            rect = mpatches.Rectangle(
                (sx - 0.15, -0.1), 0.3, shelf_h + 0.2,
                facecolor=_SHELF_CLR, edgecolor='#546e7a', lw=0.8, zorder=1)
            self.ax.add_patch(rect)
            rect2 = mpatches.Rectangle(
                (sx, -0.1), shelf_w, shelf_h + 0.2,
                facecolor='#1c2a33', edgecolor='#455a64', lw=0.6,
                linestyle='--', zorder=1)
            self.ax.add_patch(rect2)
            self.ax.text(sx + shelf_w / 2, -0.9, name,
                         color=_DIM, ha='center', fontsize=8)

    def _load_mission(self) -> None:
        """Superponer la ruta de misión desde mision.json si existe."""
        if not _MISION_FILE.exists():
            return
        with open(_MISION_FILE) as f:
            data = json.load(f)
        wps = data.get('mapa_mision', [])
        if not wps:
            return
        xs = [w['pos'][0] for w in wps]
        ys = [w['pos'][1] for w in wps]
        self.ax.plot(xs, ys, '-', color='#37474f', lw=1.0,
                     alpha=0.8, zorder=1)
        self.ax.plot(xs[0], ys[0], 's', color=_ACCENT, ms=6, zorder=3)
        self.ax.plot(xs[-1], ys[-1], '*', color=_ACCENT, ms=9, zorder=3)

    def update_state(self, x: float, y: float, yaw: float,
                     tx: float, ty: float) -> None:
        """Actualizar trail del dron, marcador y objetivo; redibujar."""
        self._trail_x.append(x)
        self._trail_y.append(y)
        if len(self._trail_x) > self._TRAIL_MAX:
            self._trail_x = self._trail_x[-self._TRAIL_MAX:]
            self._trail_y = self._trail_y[-self._TRAIL_MAX:]
        self._trail_ln.set_data(self._trail_x, self._trail_y)
        self._drone_pt.set_data([x], [y])
        dx, dy = 0.35 * np.cos(yaw), 0.35 * np.sin(yaw)
        self._drone_arrow.set_data([x, x + dx], [y, y + dy])
        self._target_pt.set_data([tx], [ty])
        self.draw_idle()


class FrontalViewCanvas(_MplCanvas):
    """Vista frontal XZ: posición horizontal vs. altitud del dron."""

    _TRAIL_MAX = 300

    def __init__(self):
        """Inicializar canvas con perfil de altitud de los estantes."""
        super().__init__(w=5.5, h=3.0)
        self._trail_x: list = []
        self._trail_z: list = []
        self._setup_axes()
        self._trail_ln, = self.ax.plot(
            [], [], '-', color='#546e7a', lw=0.9, zorder=2)
        self._drone_pt, = self.ax.plot(
            [], [], 'D', color=_GREEN, ms=8, zorder=5)
        self._target_pt, = self.ax.plot(
            [], [], 'x', color=_ORANGE, ms=10, mew=2.0, zorder=4)

    def _setup_axes(self) -> None:
        """Configurar límites, etiquetas y silueta de estantes."""
        self.ax.set_xlim(-1.5, 14.0)
        self.ax.set_ylim(-0.2, 3.5)
        self.ax.set_xlabel('X  (m  –  pasillo)', color=_TEXT, fontsize=9)
        self.ax.set_ylabel('Z  (m  –  altura)', color=_TEXT, fontsize=9)
        self.ax.set_title('Vista Frontal  –  plano XZ', color=_ACCENT,
                          fontsize=10, pad=4)
        for sx in [0, 5, 10]:
            rect = mpatches.Rectangle(
                (sx, 0), 3.0, 3.0,
                facecolor='#1c2a33', edgecolor='#455a64', lw=0.7,
                linestyle='--', zorder=1)
            self.ax.add_patch(rect)
        for zh in [1.0, 2.0]:
            self.ax.axhline(zh, color='#455a64', lw=0.6,
                            linestyle=':', zorder=1)

    def update_state(self, x: float, z: float,
                     tx: float, tz: float) -> None:
        """Actualizar posición del dron en XZ y redibujar."""
        self._trail_x.append(x)
        self._trail_z.append(z)
        if len(self._trail_x) > self._TRAIL_MAX:
            self._trail_x = self._trail_x[-self._TRAIL_MAX:]
            self._trail_z = self._trail_z[-self._TRAIL_MAX:]
        self._trail_ln.set_data(self._trail_x, self._trail_z)
        self._drone_pt.set_data([x], [z])
        self._target_pt.set_data([tx], [tz])
        self.draw_idle()


# ── Señales Qt (puente entre hilo ROS2 y hilo GUI) ───────────────────────────

class _RosSignals(QObject):
    """Señales Qt para actualizar la UI desde callbacks ROS2."""

    pose_updated = pyqtSignal(float, float, float, float)   # x, y, z, yaw
    target_updated = pyqtSignal(float, float, float)        # tx, ty, tz
    # future: frame_ready   = pyqtSignal(object)            # numpy RGB frame
    # future: barcode_found = pyqtSignal(str, str)          # código, ubicación


# ── Ventana principal ────────────────────────────────────────────────────────

class OperatorWindow(QMainWindow):
    """Ventana principal del panel de operador del dron."""

    def __init__(self, node: 'DroneGuiNode'):
        """Conectar señales ROS2, construir UI y configurar timer de emergencia."""
        super().__init__()
        self._node = node
        self._speed = 1.0
        self._stopped = False
        self._pos = (0.0, 0.0, 1.0, 0.0)
        self._target = (0.0, 0.0, 1.0)

        node.signals.pose_updated.connect(self._on_pose)
        node.signals.target_updated.connect(self._on_target)

        self.setWindowTitle(
            'Drone Operator Console  –  dron_control_sistema')
        self.setMinimumSize(1320, 780)
        self._build_ui()

        # Publica vel=0 a 10 Hz mientras el operador mantiene PARAR activo
        self._stop_timer = QTimer(self)
        self._stop_timer.setInterval(100)
        self._stop_timer.timeout.connect(self._publish_zero_vel)

    # ── Construcción de la interfaz ──────────────────────────────────────────

    def _build_ui(self) -> None:
        """Ensamblar todos los paneles de la ventana."""
        root = QWidget()
        root.setStyleSheet(f'background:{_BG};')
        self.setCentralWidget(root)
        vbox = QVBoxLayout(root)
        vbox.setSpacing(6)
        vbox.setContentsMargins(8, 8, 8, 8)
        vbox.addWidget(self._build_header())
        content = QSplitter(Qt.Horizontal)
        content.setStyleSheet(
            'QSplitter::handle{background:#333;width:2px;}')
        content.addWidget(self._build_camera_panel())
        content.addWidget(self._build_views_panel())
        content.addWidget(self._build_db_panel())
        content.setSizes([260, 740, 320])
        vbox.addWidget(content, stretch=1)
        vbox.addWidget(self._build_controls())

    def _build_header(self) -> QFrame:
        """Construir barra superior con título, coordenadas y estado."""
        frame = QFrame()
        frame.setFixedHeight(40)
        frame.setStyleSheet(
            f'background:{_PANEL};border-radius:4px;')
        hbox = QHBoxLayout(frame)
        hbox.setContentsMargins(14, 0, 14, 0)
        title = QLabel('DRONE OPERATOR CONSOLE')
        title.setFont(QFont('Monospace', 11, QFont.Bold))
        title.setStyleSheet(f'color:{_ACCENT};')
        hbox.addWidget(title)
        hbox.addStretch()
        self._lbl_pos_hdr = QLabel('Pos: –')
        self._lbl_pos_hdr.setStyleSheet(
            f'color:{_TEXT};font-size:12px;')
        hbox.addWidget(self._lbl_pos_hdr)
        hbox.addSpacing(24)
        self._lbl_status = QLabel('● EN MISIÓN')
        self._lbl_status.setStyleSheet(
            f'color:{_GREEN};font-weight:bold;font-size:12px;')
        hbox.addWidget(self._lbl_status)
        return frame

    def _build_camera_panel(self) -> QGroupBox:
        """Construir panel de cámara en vivo (placeholder para implementación futura)."""
        box = QGroupBox('Cámara en vivo')
        box.setStyleSheet(_group_style())
        vbox = QVBoxLayout(box)
        vbox.setSpacing(8)
        self._cam_label = QLabel()
        self._cam_label.setMinimumSize(240, 180)
        self._cam_label.setAlignment(Qt.AlignCenter)
        self._cam_label.setStyleSheet(
            f'background:#0d1117;color:{_DIM};'
            f'border:1px solid {_DIM};border-radius:4px;font-size:11px;')
        self._cam_label.setText(
            '📷  Sin señal\n\nConectar publicador\nde cámara')
        vbox.addWidget(self._cam_label)
        for line in ['Resolución: —', 'FPS: —', 'Estado: offline',
                     '', 'Pendiente: nodo de cámara']:
            lbl = QLabel(line)
            lbl.setStyleSheet(
                f'color:{_DIM if line else _BG};font-size:10px;')
            vbox.addWidget(lbl)
        vbox.addStretch()
        return box

    def _build_views_panel(self) -> QGroupBox:
        """Construir panel central con vistas superior y frontal."""
        box = QGroupBox('Visualización en tiempo real')
        box.setStyleSheet(_group_style())
        vbox = QVBoxLayout(box)
        vbox.setSpacing(4)
        self._top_view = TopViewCanvas()
        self._front_view = FrontalViewCanvas()
        vbox.addWidget(self._top_view, stretch=3)
        vbox.addWidget(self._front_view, stretch=2)
        return box

    def _build_db_panel(self) -> QGroupBox:
        """Construir panel de base de datos de códigos de barras."""
        box = QGroupBox('BD – Códigos de barras detectados')
        box.setStyleSheet(_group_style())
        vbox = QVBoxLayout(box)
        self._table = QTableWidget(0, 4)
        self._table.setHorizontalHeaderLabels(
            ['Código', 'Estante', 'Balda', 'Hora'])
        self._table.horizontalHeader().setSectionResizeMode(
            QHeaderView.Stretch)
        self._table.setStyleSheet(
            f'QTableWidget{{background:{_BG};color:{_TEXT};'
            f'gridline-color:#333;border:none;font-size:11px;}}'
            f'QHeaderView::section{{background:{_PANEL};color:{_ACCENT};'
            f'border:1px solid #333;padding:4px;}}'
        )
        self._table.setAlternatingRowColors(True)
        self._table.setEditTriggers(QTableWidget.NoEditTriggers)
        self._table.setSelectionBehavior(QTableWidget.SelectRows)
        vbox.addWidget(self._table)
        placeholder = QLabel(
            'Esperando detecciones…\n'
            '(nodo de cámara pendiente de implementar)')
        placeholder.setAlignment(Qt.AlignCenter)
        placeholder.setStyleSheet(
            f'color:{_DIM};font-size:10px;margin-top:8px;')
        vbox.addWidget(placeholder)
        return box

    def _build_controls(self) -> QFrame:
        """Construir franja inferior con botones de control y coordenadas."""
        frame = QFrame()
        frame.setFixedHeight(82)
        frame.setStyleSheet(
            f'background:{_PANEL};border-radius:4px;')
        outer = QVBoxLayout(frame)
        outer.setContentsMargins(12, 6, 12, 6)
        outer.setSpacing(5)

        row = QHBoxLayout()
        row.setSpacing(8)

        self._btn_stop = _make_button('■  PARAR', _RED)
        self._btn_stop.setToolTip(
            'Emergencia: publica velocidad cero continuamente')
        self._btn_stop.clicked.connect(self._toggle_stop)

        btn_home = _make_button('⌂  INICIO', '#1565c0')
        btn_home.setToolTip(
            'Enviar dron a posición de origen (0, 0, 1 m)')
        btn_home.clicked.connect(self._cmd_home)

        btn_call = _make_button('↩  LLAMAR', '#6a1b9a')
        btn_call.setToolTip(
            'Congelar dron en su posición actual')
        btn_call.clicked.connect(self._cmd_call)

        btn_spd_m = _make_button('−  VEL', '#424242', min_w=70)
        btn_spd_m.setToolTip('Reducir factor de velocidad (mín 0.2×)')
        btn_spd_m.clicked.connect(self._speed_down)

        self._lbl_speed = QLabel('1.0×')
        self._lbl_speed.setAlignment(Qt.AlignCenter)
        self._lbl_speed.setFixedWidth(52)
        self._lbl_speed.setStyleSheet(
            f'color:{_ORANGE};font-weight:bold;font-size:15px;')

        btn_spd_p = _make_button('+  VEL', '#424242', min_w=70)
        btn_spd_p.setToolTip('Aumentar factor de velocidad (máx 3.0×)')
        btn_spd_p.clicked.connect(self._speed_up)

        for w in [self._btn_stop, btn_home, btn_call,
                  btn_spd_m, self._lbl_speed, btn_spd_p]:
            row.addWidget(w)
        row.addStretch()
        outer.addLayout(row)

        self._lbl_coords = QLabel(
            'X: —    Y: —    Z: —    |    '
            'Objetivo: —    |    Factor velocidad: 1.0×')
        self._lbl_coords.setStyleSheet(
            f'color:{_DIM};font-size:11px;')
        outer.addWidget(self._lbl_coords)
        return frame

    # ── Slots ROS2 → UI (se ejecutan en el hilo Qt) ──────────────────────────

    def _on_pose(self, x: float, y: float,
                 z: float, yaw: float) -> None:
        """Actualizar vistas y etiquetas con la nueva posición del dron."""
        self._pos = (x, y, z, yaw)
        tx, ty, tz = self._target
        self._top_view.update_state(x, y, yaw, tx, ty)
        self._front_view.update_state(x, z, tx, tz)
        self._lbl_pos_hdr.setText(
            f'X:{x:+.2f}  Y:{y:+.2f}  Z:{z:+.2f}')
        self._lbl_coords.setText(
            f'X: {x:+.3f}    Y: {y:+.3f}    Z: {z:+.3f}'
            f'    |    Objetivo: ({tx:.2f}, {ty:.2f}, {tz:.2f})'
            f'    |    Factor velocidad: {self._speed:.1f}×'
        )

    def _on_target(self, tx: float, ty: float, tz: float) -> None:
        """Actualizar coordenadas del objetivo activo."""
        self._target = (tx, ty, tz)

    # ── Acciones de los botones ──────────────────────────────────────────────

    def _toggle_stop(self) -> None:
        """Activar o desactivar la parada de emergencia."""
        self._stopped = not self._stopped
        if self._stopped:
            self._stop_timer.start()
            self._btn_stop.setText('▶  REANUDAR')
            self._btn_stop.setStyleSheet(
                self._btn_stop.styleSheet().replace(_RED, _GREEN))
            self._lbl_status.setText('● DETENIDO')
            self._lbl_status.setStyleSheet(
                f'color:{_RED};font-weight:bold;font-size:12px;')
        else:
            self._stop_timer.stop()
            self._btn_stop.setText('■  PARAR')
            self._btn_stop.setStyleSheet(
                self._btn_stop.styleSheet().replace(_GREEN, _RED))
            self._lbl_status.setText('● EN MISIÓN')
            self._lbl_status.setStyleSheet(
                f'color:{_GREEN};font-weight:bold;font-size:12px;')

    def _publish_zero_vel(self) -> None:
        """Publicar Twist nulo para mantener el dron parado."""
        self._node.pub_vel.publish(Twist())

    def _cmd_home(self) -> None:
        """Enviar al dron a la posición de origen (0, 0, z_fijo)."""
        msg = Float32MultiArray()
        msg.data = [0.0, 0.0, 1.0]
        self._node.pub_target.publish(msg)
        self._lbl_status.setText('● RETORNO A INICIO')
        self._lbl_status.setStyleSheet(
            f'color:{_ORANGE};font-weight:bold;font-size:12px;')

    def _cmd_call(self) -> None:
        """Publicar la posición actual del dron como objetivo (hover)."""
        x, y, z, _ = self._pos
        msg = Float32MultiArray()
        msg.data = [x, y, z]
        self._node.pub_target.publish(msg)
        self._lbl_status.setText('● POSICIÓN FIJA')
        self._lbl_status.setStyleSheet(
            f'color:{_ORANGE};font-weight:bold;font-size:12px;')

    def _speed_down(self) -> None:
        """Reducir el factor de velocidad en 0.1 (mínimo 0.2)."""
        self._speed = max(0.2, round(self._speed - 0.1, 1))
        self._apply_speed()

    def _speed_up(self) -> None:
        """Aumentar el factor de velocidad en 0.1 (máximo 3.0)."""
        self._speed = min(3.0, round(self._speed + 0.1, 1))
        self._apply_speed()

    def _apply_speed(self) -> None:
        """Actualizar etiqueta y publicar el nuevo factor al mavros_node."""
        self._lbl_speed.setText(f'{self._speed:.1f}×')
        msg = Float32()
        msg.data = float(self._speed)
        self._node.pub_speed.publish(msg)

    # ── Método de integración de cámara (futuro) ─────────────────────────────

    def update_camera_frame(self, rgb_array: np.ndarray) -> None:
        """Mostrar un fotograma numpy RGB en el panel de cámara.

        Se llamará desde el slot conectado a signals.frame_ready
        una vez que el nodo de cámara esté implementado.
        """
        from PyQt5.QtGui import QImage, QPixmap
        h, w, ch = rgb_array.shape
        img = QImage(rgb_array.data, w, h, ch * w, QImage.Format_RGB888)
        self._cam_label.setPixmap(
            QPixmap.fromImage(img).scaled(
                self._cam_label.width(), self._cam_label.height(),
                Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ── Método de integración de BD (futuro) ─────────────────────────────────

    def add_barcode_row(self, codigo: str, estante: str,
                        balda: str, hora: str) -> None:
        """Insertar una fila nueva en la tabla de códigos de barras.

        Se llamará desde el slot conectado a signals.barcode_found
        una vez que el nodo de detección esté implementado.
        """
        row = self._table.rowCount()
        self._table.insertRow(row)
        for col, val in enumerate([codigo, estante, balda, hora]):
            item = QTableWidgetItem(val)
            item.setTextAlignment(Qt.AlignCenter)
            self._table.setItem(row, col, item)
        self._table.scrollToBottom()


# ── Nodo ROS2 ────────────────────────────────────────────────────────────────

class DroneGuiNode(Node):
    """Nodo ROS2 embebido en la GUI: suscripciones y publicaciones."""

    def __init__(self):
        """Inicializar suscriptores, publicadores y señales Qt."""
        super().__init__('drone_gui')
        self.signals = _RosSignals()

        self.sub_pose = self.create_subscription(
            Float32MultiArray, '/drone/pose', self._pose_cb, 10)
        self.sub_target = self.create_subscription(
            Float32MultiArray, '/cerebro/target', self._target_cb, 10)

        self.pub_vel = self.create_publisher(
            Twist, '/drone/cmd_vel', 10)
        self.pub_target = self.create_publisher(
            Float32MultiArray, '/cerebro/target', 10)
        self.pub_speed = self.create_publisher(
            Float32, '/gui/speed_factor', 10)

    def _pose_cb(self, msg: Float32MultiArray) -> None:
        """Emitir señal Qt con la posición recibida."""
        d = msg.data
        yaw = float(d[3]) if len(d) > 3 else 0.0
        self.signals.pose_updated.emit(
            float(d[0]), float(d[1]), float(d[2]), yaw)

    def _target_cb(self, msg: Float32MultiArray) -> None:
        """Emitir señal Qt con el objetivo recibido."""
        d = msg.data
        self.signals.target_updated.emit(
            float(d[0]), float(d[1]), float(d[2]))


# ── Punto de entrada ─────────────────────────────────────────────────────────

def main(args=None):
    """Punto de entrada del nodo gui_node."""
    if not _GUI_OK:
        print('[ERROR] PyQt5 no disponible. Instalar con:')
        print('  sudo apt install python3-pyqt5')
        sys.exit(1)

    rclpy.init(args=args)
    node = DroneGuiNode()

    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setPalette(_dark_palette())

    window = OperatorWindow(node)
    window.show()

    ros_thread = threading.Thread(
        target=rclpy.spin, args=(node,), daemon=True)
    ros_thread.start()

    try:
        ret = app.exec_()
    finally:
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass

    sys.exit(ret)
