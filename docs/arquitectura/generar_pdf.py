"""
Genera el PDF de documentación técnica: Comunicación ROS2 ↔ Pixhawk F550.

Uso:
    cd demo_real/
    python3 generar_pdf.py

Salida: COMUNICACION_ROS2_PIXHAWK.pdf
"""

import os
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch
import numpy as np

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image, Table,
    TableStyle, HRFlowable, PageBreak, KeepTogether,
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY

# ---------------------------------------------------------------------------
# Rutas
# ---------------------------------------------------------------------------
HERE = os.path.dirname(os.path.abspath(__file__))
PDF_PATH = os.path.join(HERE, 'COMUNICACION_ROS2_PIXHAWK.pdf')
TMP = os.path.join(HERE, '_tmp_diag')
os.makedirs(TMP, exist_ok=True)

# ---------------------------------------------------------------------------
# Paleta de colores
# ---------------------------------------------------------------------------
C_ROS    = '#1565C0'   # azul     – capa ROS2 / Python
C_BRIDGE = '#6A1B9A'   # morado   – MAVROS
C_SERIAL = '#37474F'   # gris     – cable USB / serial
C_PX4    = '#2E7D32'   # verde    – firmware PX4
C_HW     = '#BF360C'   # naranja  – hardware ESC/motor
C_TOPIC  = '#0277BD'   # azul claro – topics
C_SRV    = '#558B2F'   # verde claro – servicios
C_MAV    = '#E65100'   # naranja  – MAVLink
WHITE    = '#FFFFFF'
LGRAY    = '#ECEFF1'
DGRAY    = '#546E7A'

# ---------------------------------------------------------------------------
# Helpers de dibujo
# ---------------------------------------------------------------------------

def box(ax, x, y, w, h, label, color, tc=WHITE, fs=10, bold=True, radius=0.03):
    """Dibuja un rectángulo redondeado con etiqueta centrada."""
    r = FancyBboxPatch((x, y), w, h,
                       boxstyle=f'round,pad={radius}',
                       facecolor=color, edgecolor=WHITE, linewidth=1.5,
                       zorder=2)
    ax.add_patch(r)
    weight = 'bold' if bold else 'normal'
    ax.text(x + w / 2, y + h / 2, label,
            ha='center', va='center', fontsize=fs,
            color=tc, fontweight=weight, zorder=3,
            multialignment='center')


def arrow_v(ax, x, y_top, length, label='', color=DGRAY):
    """Flecha vertical hacia abajo con etiqueta lateral."""
    ax.annotate('', xy=(x, y_top - length), xytext=(x, y_top),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8))
    if label:
        ax.text(x + 0.02, y_top - length / 2, label,
                ha='left', va='center', fontsize=8, color=color,
                style='italic')


def arrow_h(ax, x_left, y, length, label='', color=DGRAY):
    """Flecha horizontal hacia la derecha."""
    ax.annotate('', xy=(x_left + length, y), xytext=(x_left, y),
                arrowprops=dict(arrowstyle='->', color=color, lw=1.8))
    if label:
        ax.text(x_left + length / 2, y + 0.015, label,
                ha='center', va='bottom', fontsize=8, color=color)


def save(fig, name):
    """Guarda la figura y cierra."""
    path = os.path.join(TMP, name)
    fig.savefig(path, dpi=180, bbox_inches='tight', facecolor='white')
    plt.close(fig)
    return path


# ===========================================================================
# DIAGRAMA 1 – Pila de comunicación completa
# ===========================================================================

def diag_pila():
    fig, ax = plt.subplots(figsize=(9, 11))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.975, 'Pila de comunicación completa',
            ha='center', va='top', fontsize=13, fontweight='bold', color=DGRAY)

    # ---- bloques principales ----
    # PC / Python
    box(ax, 0.05, 0.80, 0.58, 0.12,
        'pixhawk_menu_node\n(Python / ROS 2)', C_ROS, fs=10)
    ax.text(0.68, 0.86, 'PC / WSL2', ha='left', va='center',
            fontsize=9, color=C_ROS, fontweight='bold')
    ax.text(0.68, 0.82, 'geometry_msgs/Twist\n(frame ENU)', ha='left',
            va='center', fontsize=8, color=DGRAY)

    # MAVROS
    box(ax, 0.05, 0.63, 0.58, 0.10,
        'MAVROS  (mavros_node)\nPuente ROS2 ↔ MAVLink', C_BRIDGE, fs=10)
    ax.text(0.68, 0.68, 'Convierte ENU→NED\nSerializa a binario', ha='left',
            va='center', fontsize=8, color=DGRAY)

    # Cable USB
    bx, by, bw, bh = 0.22, 0.555, 0.24, 0.055
    r = FancyBboxPatch((bx, by), bw, bh,
                       boxstyle='round,pad=0.01',
                       facecolor=C_SERIAL, edgecolor=WHITE, linewidth=1,
                       zorder=2)
    ax.add_patch(r)
    ax.text(bx + bw / 2, by + bh / 2,
            'USB /dev/ttyACM0  921600 baud\nMAVLink v2 (binario)',
            ha='center', va='center', fontsize=8.5, color=WHITE,
            fontweight='bold', zorder=3)

    # PX4 Commander
    box(ax, 0.05, 0.435, 0.58, 0.10,
        'PX4 – Commander\n(modos, arme, watchdog OFFBOARD)', C_PX4, fs=9.5)
    ax.text(0.68, 0.485, 'Pixhawk (hardware)\nFirmware PX4', ha='left',
            va='center', fontsize=9, color=C_PX4, fontweight='bold')

    # Controladores internos
    box(ax, 0.05, 0.30, 0.58, 0.12,
        'MPC  →  Attitude Ctrl  →  Rate Ctrl', C_PX4, fs=9.5)
    ax.text(0.68, 0.36, 'Err. vel. → pitch/roll\nPID de actitud', ha='left',
            va='center', fontsize=8, color=DGRAY)

    # Mixer
    box(ax, 0.05, 0.195, 0.58, 0.085,
        'Mixer  →  PWM (1000–2000 µs)', C_PX4, fs=9.5)
    ax.text(0.68, 0.237, 'Distribuye thrust\na 6 motores', ha='left',
            va='center', fontsize=8, color=DGRAY)

    # ESC + Motores
    box(ax, 0.05, 0.075, 0.58, 0.10,
        'ESC ×6  →  Motor BLDC ×6\nDJI Flame Wheel F550', C_HW, fs=9.5)
    ax.text(0.68, 0.125, 'PWM → RPM\n~400 Hz', ha='left',
            va='center', fontsize=8, color=DGRAY)

    # ---- flechas verticales ----
    cx = 0.34
    # ROS2 → MAVROS
    arrow_v(ax, cx, 0.80, 0.065, color=C_BRIDGE)
    # MAVROS → Cable
    arrow_v(ax, cx, 0.63, 0.07, color=C_SERIAL)
    # Cable → Commander
    arrow_v(ax, cx, 0.555, 0.115, color=C_PX4)
    # Commander → Ctrl
    arrow_v(ax, cx, 0.435, 0.13, color=C_PX4)
    # Ctrl → Mixer
    arrow_v(ax, cx, 0.30, 0.10, color=C_PX4)
    # Mixer → ESC
    arrow_v(ax, cx, 0.195, 0.115, color=C_HW)

    # ---- flecha de telemetría de vuelta ----
    ax.annotate('', xy=(0.03, 0.74), xytext=(0.03, 0.175),
                arrowprops=dict(arrowstyle='->', color=C_ROS, lw=1.5,
                                connectionstyle='arc3,rad=0'))
    ax.text(0.005, 0.46, 'Telemetría\nMSG 32\nEKF2', ha='center',
            va='center', fontsize=7.5, color=C_ROS, style='italic',
            rotation=90)

    return save(fig, 'pila.png')


# ===========================================================================
# DIAGRAMA 2 – Transformación de coordenadas ENU ↔ NED
# ===========================================================================

def diag_coords():
    fig = plt.figure(figsize=(11, 5))
    fig.patch.set_facecolor(LGRAY)

    fig.text(0.5, 0.96, 'Transformación de marcos de referencia  ENU ↔ NED',
             ha='center', fontsize=12, fontweight='bold', color=DGRAY)

    # ---- ENU (izquierda) ----
    ax1 = fig.add_subplot(1, 2, 1, projection='3d')
    ax1.set_facecolor(LGRAY)
    ax1.set_title('ROS 2 usa ENU\n(East · North · Up)',
                  fontsize=10, fontweight='bold', color=C_ROS, pad=8)

    L = 1.4
    for vec, col, lbl, off in [
        ([L, 0, 0], '#E53935', 'X  Este', (L + 0.1, 0, 0)),
        ([0, L, 0], '#1E88E5', 'Y  Norte', (0, L + 0.1, 0)),
        ([0, 0, L], '#43A047', 'Z  Arriba', (0, 0, L + 0.1)),
    ]:
        ax1.quiver(0, 0, 0, *vec, color=col, arrow_length_ratio=0.18,
                   linewidth=2.5)
        ax1.text(*off, lbl, color=col, fontsize=9, fontweight='bold')

    ax1.set_xlim(-0.2, 1.8)
    ax1.set_ylim(-0.2, 1.8)
    ax1.set_zlim(-0.2, 1.8)
    ax1.set_xlabel('')
    ax1.set_ylabel('')
    ax1.set_zlabel('')
    ax1.set_xticks([])
    ax1.set_yticks([])
    ax1.set_zticks([])
    ax1.xaxis.pane.fill = False
    ax1.yaxis.pane.fill = False
    ax1.zaxis.pane.fill = False

    # ---- NED (derecha) ----
    ax2 = fig.add_subplot(1, 2, 2, projection='3d')
    ax2.set_facecolor(LGRAY)
    ax2.set_title('MAVLink / PX4 usa NED\n(North · East · Down)',
                  fontsize=10, fontweight='bold', color=C_PX4, pad=8)

    for vec, col, lbl, off in [
        ([L, 0, 0], '#1E88E5', 'X  Norte', (L + 0.1, 0, 0)),
        ([0, L, 0], '#E53935', 'Y  Este',  (0, L + 0.1, 0)),
        ([0, 0, -L], '#E53935', 'Z  Abajo', (0, 0, -L - 0.2)),
    ]:
        ax2.quiver(0, 0, 0, *vec, color=col, arrow_length_ratio=0.18,
                   linewidth=2.5)
        ax2.text(*off, lbl, color=col, fontsize=9, fontweight='bold')

    ax2.set_xlim(-0.2, 1.8)
    ax2.set_ylim(-0.2, 1.8)
    ax2.set_zlim(-1.8, 0.2)
    ax2.set_xticks([])
    ax2.set_yticks([])
    ax2.set_zticks([])
    ax2.xaxis.pane.fill = False
    ax2.yaxis.pane.fill = False
    ax2.zaxis.pane.fill = False

    # ---- tabla de conversión ----
    tbl_ax = fig.add_axes([0.2, 0.0, 0.6, 0.17])
    tbl_ax.axis('off')
    table_data = [
        ['Componente ENU (Twist ROS2)', 'Significado físico',
         'Componente NED (MAVLink)'],
        ['linear.x = +0.3', 'Este (+X ENU)', 'vy = +0.3'],
        ['linear.y = +0.3', 'Norte (+Y ENU)', 'vx = +0.3'],
        ['linear.z = +0.3', 'Arriba (+Z ENU)', 'vz = -0.3  ← signo invertido'],
    ]
    t = tbl_ax.table(cellText=table_data[1:], colLabels=table_data[0],
                     loc='center', cellLoc='center')
    t.auto_set_font_size(False)
    t.set_fontsize(8.5)
    t.scale(1, 1.6)
    for (r, c), cell in t.get_celld().items():
        if r == 0:
            cell.set_facecolor(DGRAY)
            cell.set_text_props(color=WHITE, fontweight='bold')
        elif c == 2 and r == 3:
            cell.set_facecolor('#FFCCBC')
        else:
            cell.set_facecolor('#E8EAF6' if r % 2 == 0 else WHITE)

    fig.subplots_adjust(top=0.88, bottom=0.22, wspace=0.1)
    return save(fig, 'coords.png')


# ===========================================================================
# DIAGRAMA 3 – Grafo de nodos ROS2
# ===========================================================================

def diag_nodos():
    fig, ax = plt.subplots(figsize=(12, 5.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.96, 'Grafo de nodos ROS2 y comunicación con MAVROS',
            ha='center', fontsize=12, fontweight='bold', color=DGRAY)

    # Nodo principal
    box(ax, 0.02, 0.35, 0.20, 0.28,
        'pixhawk\n_menu\n_node', C_ROS, fs=10)

    # MAVROS
    box(ax, 0.40, 0.35, 0.20, 0.28,
        'mavros\n_node\n(MAVROS)', C_BRIDGE, fs=10)

    # Pixhawk
    box(ax, 0.78, 0.35, 0.20, 0.28,
        'Pixhawk\n(PX4)', C_PX4, fs=10)

    # ---- Topics (flechas azules, arriba) ----
    # cmd_vel → MAVROS
    ax.annotate('', xy=(0.40, 0.60), xytext=(0.22, 0.60),
                arrowprops=dict(arrowstyle='->', color=C_TOPIC, lw=2))
    ax.text(0.31, 0.635,
            '/mavros/setpoint_velocity/\ncmd_vel_unstamped\n(geometry_msgs/Twist)',
            ha='center', va='bottom', fontsize=7.5, color=C_TOPIC)

    # state ← MAVROS
    ax.annotate('', xy=(0.22, 0.49), xytext=(0.40, 0.49),
                arrowprops=dict(arrowstyle='->', color=C_TOPIC, lw=2))
    ax.text(0.31, 0.50,
            '/mavros/state\n(mavros_msgs/State)',
            ha='center', va='bottom', fontsize=7.5, color=C_TOPIC)

    # local_position ← MAVROS
    ax.annotate('', xy=(0.22, 0.39), xytext=(0.40, 0.39),
                arrowprops=dict(arrowstyle='->', color=C_TOPIC, lw=2))
    ax.text(0.31, 0.40,
            '/mavros/local_position/pose\n(geometry_msgs/PoseStamped)',
            ha='center', va='bottom', fontsize=7.5, color=C_TOPIC)

    # ---- Servicios (flechas verdes, debajo) ----
    for i, (srv, ypos) in enumerate([
        ('/mavros/cmd/arming\n(CommandBool)', 0.28),
        ('/mavros/set_mode\n(SetMode)', 0.20),
        ('/mavros/cmd/takeoff\n(CommandTOL)', 0.12),
    ]):
        ax.annotate('', xy=(0.40, ypos + 0.04), xytext=(0.22, ypos + 0.04),
                    arrowprops=dict(arrowstyle='->', color=C_SRV, lw=1.8,
                                   linestyle='dashed'))
        ax.text(0.31, ypos + 0.055, srv,
                ha='center', va='bottom', fontsize=7.5, color=C_SRV)

    # ---- MAVLink ↔ Pixhawk ----
    ax.annotate('', xy=(0.78, 0.55), xytext=(0.60, 0.55),
                arrowprops=dict(arrowstyle='<->', color=C_MAV, lw=2.2))
    ax.text(0.69, 0.575,
            'MAVLink v2\nUSB serie\n921600 baud',
            ha='center', va='bottom', fontsize=8, color=C_MAV,
            fontweight='bold')

    # ---- Leyenda ----
    ley = [
        mpatches.Patch(color=C_TOPIC, label='Topics (pub/sub)'),
        mpatches.Patch(color=C_SRV,   label='Servicios (req/resp)'),
        mpatches.Patch(color=C_MAV,   label='MAVLink serie'),
    ]
    ax.legend(handles=ley, loc='lower right', fontsize=8.5,
              framealpha=0.8, facecolor=WHITE)

    return save(fig, 'nodos.png')


# ===========================================================================
# DIAGRAMA 4 – Pipeline interno PX4
# ===========================================================================

def diag_px4():
    fig, ax = plt.subplots(figsize=(13, 3.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.95, 'Pipeline interno PX4: de setpoint de velocidad a PWM',
            ha='center', fontsize=11, fontweight='bold', color=DGRAY)

    stages = [
        ('Setpoint\nvelocidad\n(MAVLink)', C_MAV),
        ('MPC\n(pos/vel\ncontrol)', C_PX4),
        ('Setpoint\nactitud\n(roll/pitch)', C_PX4),
        ('Attitude\nController\n(PID)', C_PX4),
        ('Setpoint\nrates\n(ω)', C_PX4),
        ('Mixer\n(F550\n6 motores)', C_PX4),
        ('PWM\n1000–2000 µs\n400 Hz', C_HW),
        ('ESC ×6\n+\nMotor BLDC', C_HW),
    ]

    n = len(stages)
    bw = 0.095
    gap = (1.0 - n * bw) / (n + 1)
    y0, bh = 0.15, 0.60

    for i, (label, color) in enumerate(stages):
        x = gap + i * (bw + gap)
        box(ax, x, y0, bw, bh, label, color, fs=8.5, radius=0.02)
        if i < n - 1:
            arrow_h(ax, x + bw, y0 + bh / 2, gap, color=DGRAY)

    # Nota EKF2
    ax.text(0.5, 0.04,
            'El MPC usa la posición estimada del EKF2 '
            '(fusión IMU + GPS/flujo óptico) para calcular el error de velocidad',
            ha='center', fontsize=8, color=DGRAY, style='italic')

    return save(fig, 'px4.png')


# ===========================================================================
# DIAGRAMA 5 – Formato trama MAVLink v2
# ===========================================================================

def diag_mavlink():
    fig, ax = plt.subplots(figsize=(11, 2.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.93, 'Formato de trama MAVLink v2',
            ha='center', fontsize=11, fontweight='bold', color=DGRAY)

    fields = [
        ('STX\n0xFD\n1 B',  0.06, '#546E7A'),
        ('LEN\npayload\n1 B', 0.06, '#546E7A'),
        ('Flags\n2 B',        0.06, '#546E7A'),
        ('SysID\nCompID\n2 B', 0.07, '#546E7A'),
        ('MSG ID\n3 B',       0.07, '#37474F'),
        ('PAYLOAD\nvx, vy, vz, …\nhasta 255 B', 0.38, C_MAV),
        ('CRC\n2 B',          0.07, '#546E7A'),
        ('Sign.\n13 B\n(opc.)', 0.10, '#78909C'),
    ]

    x = 0.01
    y0, bh = 0.12, 0.62
    for label, width, color in fields:
        box(ax, x, y0, width - 0.005, bh, label, color, fs=8, radius=0.01)
        x += width

    ax.text(0.5, 0.03,
            'Ejemplo: SET_POSITION_TARGET_LOCAL_NED (ID 84)  '
            '→  payload contiene vx=0.3, vy=0, vz=0 en NED + máscara de tipo',
            ha='center', fontsize=8, color=DGRAY)

    return save(fig, 'mavlink.png')


# ===========================================================================
# DIAGRAMA 6 – Diagrama de secuencia simplificado
# ===========================================================================

def diag_secuencia():
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.97,
            'Diagrama de secuencia: Usuario pulsa [w] (mover Norte)',
            ha='center', fontsize=11, fontweight='bold', color=DGRAY)

    # Columnas de actores
    actors = [
        ('Usuario', 0.08, '#5D4037'),
        ('pixhawk_menu_node', 0.28, C_ROS),
        ('MAVROS', 0.52, C_BRIDGE),
        ('PX4 / Pixhawk', 0.75, C_PX4),
        ('ESC + Motor', 0.95, C_HW),
    ]

    # Líneas de vida
    for _, x, color in actors:
        ax.plot([x, x], [0.06, 0.88], color=color, lw=1.2,
                linestyle='--', alpha=0.5, zorder=1)
        box(ax, x - 0.07, 0.88, 0.14, 0.07,
            actors[actors.index((_, x, color))][0],
            color, fs=8, radius=0.01)

    def msg(x1, x2, y, label, color, dashed=False):
        ls = 'dashed' if dashed else 'solid'
        ax.annotate('', xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle='->', color=color,
                                   lw=1.6, linestyle=ls))
        mid = (x1 + x2) / 2
        direction = 1 if x2 > x1 else -1
        ax.text(mid, y + 0.012, label,
                ha='center', va='bottom', fontsize=7.8,
                color=color)

    def note(x, y, text, color=DGRAY):
        ax.text(x, y, text, ha='center', va='center',
                fontsize=7.5, color=color,
                bbox=dict(boxstyle='round,pad=0.2', facecolor=WHITE,
                          edgecolor=color, alpha=0.85))

    # Secuencia de eventos
    steps = [
        # (x1, x2, y, label, color)
        (0.08, 0.28, 0.83, 'Pulsa tecla [w]', '#5D4037'),
        (0.28, 0.52, 0.74, 'Twist(y=+0.3) → /mavros/.../cmd_vel_unstamped', C_ROS),
        (0.28, 0.52, 0.65, 'Twist(0,0,0) cada 100 ms (timer 10 Hz)', C_ROS),
        (0.52, 0.75, 0.56,
         'SET_POSITION_TARGET_LOCAL_NED  vx=+0.3 NED  (USB)', C_BRIDGE),
        (0.75, 0.95, 0.47, 'PWM motors traseros ↑  delanteros ↓', C_PX4),
        (0.75, 0.52, 0.38,
         'LOCAL_POSITION_NED (ID 32, 30 Hz)', C_PX4),
        (0.52, 0.28, 0.29,
         '/mavros/local_position/pose  (ENU)', C_BRIDGE),
        (0.28, 0.08, 0.20, 'Menú actualiza  N=+0.30 m', C_ROS),
    ]
    for x1, x2, y, lbl, col in steps:
        msg(x1, x2, y, lbl, col)

    # Notas
    note(0.40, 0.69,
         'MAVROS convierte ENU→NED\nlinear.y→vx,  linear.x→vy,  linear.z→−vz')
    note(0.75, 0.52,
         'MPC calcula error vel.\n→ setpoint pitch ≈ −3°\n→ Attitude PID → Mixer')

    return save(fig, 'secuencia.png')


# ===========================================================================
# DIAGRAMA 7 – Cadena USB: Pixhawk → Windows → WSL2
# ===========================================================================

def diag_usbipd():
    fig, ax = plt.subplots(figsize=(12, 3.8))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.95, 'Cadena USB: Pixhawk → Windows COM5 → usbipd-win → WSL2',
            ha='center', fontsize=11, fontweight='bold', color=DGRAY)

    C_WIN = '#0078D4'
    C_WSL = '#E65100'

    blocks = [
        ('Pixhawk\n(USB)', 0.01, C_PX4),
        ('Windows\nCOM5', 0.21, C_WIN),
        ('usbipd-win\nkernel bridge', 0.41, C_WIN),
        ('WSL2\nLinux kernel', 0.61, C_WSL),
        ('/dev/\nttyACM0', 0.81, C_SERIAL),
    ]
    bw, bh, y0 = 0.17, 0.44, 0.32

    for label, x, color in blocks:
        box(ax, x, y0, bw, bh, label, color, fs=8.5, radius=0.02)
        if x < 0.81:
            arrow_h(ax, x + bw, y0 + bh / 2, 0.03, color=DGRAY)

    cmds = [
        (0.10, ''),
        (0.295, 'usbipd bind\n--busid 2-2'),
        (0.495, 'usbipd attach\n--wsl --busid 2-2'),
        (0.695, 'sudo chmod 666\n/dev/ttyACM0'),
        (0.895, '→ MAVROS\nfcu_url'),
    ]
    for xc, cmd in cmds:
        ax.text(xc, 0.10, cmd, ha='center', fontsize=7.5, color=DGRAY,
                style='italic', family='monospace')

    return save(fig, 'usbipd.png')


# ===========================================================================
# DIAGRAMA 8 – Ciclo round-trip: [w] → MAVLink ID 84 → ID 85 → [PX4 ACK]
# ===========================================================================

def diag_roundtrip():
    fig, ax = plt.subplots(figsize=(12, 6.5))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.97, 'Ciclo de verificación round-trip: [w] → MAVLink → [PX4 ACK]',
            ha='center', fontsize=11, fontweight='bold', color=DGRAY)

    actors = [
        ('Usuario', 0.08, '#5D4037'),
        ('pixhawk_menu\n_node', 0.30, C_ROS),
        ('MAVROS', 0.56, C_BRIDGE),
        ('PX4 / Pixhawk', 0.82, C_PX4),
    ]
    for name, x, color in actors:
        ax.plot([x, x], [0.05, 0.88], color=color, lw=1.2,
                linestyle='--', alpha=0.5, zorder=1)
        box(ax, x - 0.08, 0.88, 0.16, 0.09, name, color, fs=8, radius=0.01)

    def seq(x1, x2, y, label, color, dashed=False):
        ls = 'dashed' if dashed else 'solid'
        ax.annotate('', xy=(x2, y), xytext=(x1, y),
                    arrowprops=dict(arrowstyle='->', color=color,
                                   lw=1.8, linestyle=ls))
        ax.text((x1 + x2) / 2, y + 0.013, label,
                ha='center', va='bottom', fontsize=7.8, color=color)

    seq(0.08, 0.30, 0.80, 'Pulsa [w]', '#5D4037')
    seq(0.30, 0.56, 0.70,
        'Twist(linear.y=+0.3) ENU → /mavros/.../cmd_vel_unstamped', C_ROS)
    seq(0.56, 0.82, 0.56,
        'ID 84  SET_POSITION_TARGET_LOCAL_NED\nvx_NED=+0.3 m/s  (USB serie)', C_MAV)
    seq(0.82, 0.56, 0.40,
        'ID 85  POSITION_TARGET_LOCAL_NED\n(eco del setpoint recibido)', C_PX4)
    seq(0.56, 0.30, 0.26,
        '/mavros/setpoint_raw/target_local\nmavros_msgs/PositionTarget (ENU)', C_BRIDGE)
    seq(0.30, 0.08, 0.13,
        '[PX4 ACK] vx=+0.300 vy=+0.000 vz=+0.000 m/s  [ENU]  ✓', C_ROS)

    ax.text(0.56, 0.47, 'MAVROS convierte\nNED→ENU antes\nde publicar',
            ha='center', fontsize=7.5, color=DGRAY,
            bbox=dict(boxstyle='round,pad=0.25', facecolor=WHITE,
                      edgecolor=DGRAY, alpha=0.85))

    return save(fig, 'roundtrip.png')


# ===========================================================================
# DIAGRAMA 9 – Problema QoS y solución
# ===========================================================================

def diag_qos():
    fig, ax = plt.subplots(figsize=(11, 4))
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')
    fig.patch.set_facecolor(LGRAY)
    ax.set_facecolor(LGRAY)

    ax.text(0.5, 0.95, 'Incompatibilidad QoS: BEST_EFFORT vs RELIABLE',
            ha='center', fontsize=11, fontweight='bold', color=DGRAY)

    ax.axvline(x=0.50, ymin=0.05, ymax=0.90, color='#B0BEC5',
               lw=1.5, linestyle='--')

    # Antes
    ax.text(0.25, 0.87, 'ANTES  (sin mensajes)', ha='center',
            fontsize=10, fontweight='bold', color='#C62828')
    box(ax, 0.02, 0.52, 0.22, 0.26,
        'MAVROS\npublica\nBEST_EFFORT', C_BRIDGE, fs=8.5)
    box(ax, 0.26, 0.52, 0.22, 0.26,
        'Nuestro nodo\nsuscribe\nRELIABLE', '#C62828', fs=8.5)
    ax.annotate('', xy=(0.26, 0.65), xytext=(0.24, 0.65),
                arrowprops=dict(arrowstyle='->', color='#C62828', lw=2))
    ax.text(0.25, 0.46, '✗  No messages will be received\n'
            'Last incompatible policy: RELIABILITY',
            ha='center', fontsize=8, color='#C62828', fontweight='bold')

    # Después
    ax.text(0.75, 0.87, 'DESPUÉS  (funciona)', ha='center',
            fontsize=10, fontweight='bold', color='#2E7D32')
    box(ax, 0.52, 0.52, 0.22, 0.26,
        'MAVROS\npublica\nBEST_EFFORT', C_BRIDGE, fs=8.5)
    box(ax, 0.76, 0.52, 0.22, 0.26,
        'Nuestro nodo\nsuscribe\nBEST_EFFORT', '#2E7D32', fs=8.5)
    ax.annotate('', xy=(0.76, 0.65), xytext=(0.74, 0.65),
                arrowprops=dict(arrowstyle='->', color='#2E7D32', lw=2))
    ax.text(0.75, 0.46, '✓  Mensajes recibidos',
            ha='center', fontsize=8.5, color='#2E7D32', fontweight='bold')

    ax.text(0.5, 0.20,
            '_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)',
            ha='center', fontsize=8.5, color=DGRAY, family='monospace',
            bbox=dict(boxstyle='round,pad=0.3', facecolor=WHITE,
                      edgecolor=DGRAY, alpha=0.9))
    ax.text(0.5, 0.07,
            'Afecta a: /mavros/state · /mavros/local_position/pose · '
            '/mavros/setpoint_raw/target_local',
            ha='center', fontsize=8, color=DGRAY, style='italic')

    return save(fig, 'qos.png')


# ===========================================================================
# CONSTRUCCIÓN DEL PDF
# ===========================================================================

def build_pdf(img_paths):
    doc = SimpleDocTemplate(
        PDF_PATH,
        pagesize=A4,
        leftMargin=2.2 * cm,
        rightMargin=2.2 * cm,
        topMargin=2.5 * cm,
        bottomMargin=2.5 * cm,
        title='Comunicación ROS2 – Pixhawk F550',
        author='dron_control_sistema',
    )

    # Ancho útil: page - margins - frame padding (6pt cada lado por defecto)
    W = A4[0] - 4.4 * cm - 12

    # ---- Estilos ----
    base = getSampleStyleSheet()

    def style(name, parent='Normal', **kw):
        s = ParagraphStyle(name, parent=base[parent], **kw)
        return s

    s_title  = style('Title2', 'Normal',
                     fontSize=22, leading=28, textColor=colors.HexColor(C_ROS),
                     fontName='Helvetica-Bold', spaceAfter=6,
                     alignment=TA_CENTER)
    s_sub    = style('Subtitle', fontSize=12, leading=16,
                     textColor=colors.HexColor(DGRAY),
                     fontName='Helvetica', spaceAfter=4, alignment=TA_CENTER)
    s_h1     = style('H1', fontSize=13, leading=18,
                     textColor=colors.HexColor(C_ROS),
                     fontName='Helvetica-Bold', spaceBefore=14, spaceAfter=4)
    s_h2     = style('H2', fontSize=10.5, leading=14,
                     textColor=colors.HexColor(C_BRIDGE),
                     fontName='Helvetica-Bold', spaceBefore=8, spaceAfter=3)
    s_body   = style('Body', fontSize=9.5, leading=14,
                     fontName='Helvetica', alignment=TA_JUSTIFY, spaceAfter=4)
    s_code   = style('Code2', 'Code', fontSize=8, leading=11,
                     fontName='Courier', leftIndent=10,
                     backColor=colors.HexColor('#ECEFF1'), spaceAfter=6)
    s_cap    = style('Caption', fontSize=8, leading=10,
                     textColor=colors.HexColor(DGRAY),
                     fontName='Helvetica-Oblique', alignment=TA_CENTER,
                     spaceAfter=10)
    s_note   = style('Note', fontSize=8.5, leading=12,
                     fontName='Helvetica-Oblique',
                     textColor=colors.HexColor('#4A148C'), spaceAfter=4,
                     leftIndent=8)

    def img(path, w=None, caption=None):
        from PIL import Image as PILImg
        w = w or W * 0.98
        pil = PILImg.open(path)
        pw, ph = pil.size
        h = w * (ph / pw)
        # Si la imagen es demasiado alta para una página, escalar a lo alto
        max_h = A4[1] - 4.8 * cm - 12
        if h > max_h:
            h = max_h
            w = h * (pw / ph)
        elems = [Image(path, width=w, height=h)]
        if caption:
            elems.append(Paragraph(caption, s_cap))
        return elems

    def hr():
        return HRFlowable(width='100%', thickness=0.5,
                          color=colors.HexColor('#B0BEC5'),
                          spaceAfter=6, spaceBefore=6)

    def tbl(data, col_widths=None, header_color=DGRAY):
        t = Table(data, colWidths=col_widths, repeatRows=1)
        style_cmds = [
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor(header_color)),
            ('TEXTCOLOR',  (0, 0), (-1, 0), colors.white),
            ('FONTNAME',   (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE',   (0, 0), (-1, -1), 8.5),
            ('LEADING',    (0, 0), (-1, -1), 12),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1),
             [colors.HexColor('#E8EAF6'), colors.white]),
            ('GRID',       (0, 0), (-1, -1), 0.3,
             colors.HexColor('#B0BEC5')),
            ('ALIGN',      (0, 0), (-1, -1), 'LEFT'),
            ('VALIGN',     (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ]
        t.setStyle(TableStyle(style_cmds))
        return t

    # ================================================================
    story = []

    # ---- Portada ----
    story.append(Spacer(1, 3 * cm))
    story.append(Paragraph('Comunicación ROS 2 ↔ Pixhawk', s_title))
    story.append(Paragraph('Flujo de datos desde el nodo Python hasta los motores del F550',
                            s_sub))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'Versión 2 — Mayo 2026 &nbsp;|&nbsp; '
        'Proyecto: dron_control_sistema &nbsp;|&nbsp; '
        'Firmware: PX4 &nbsp;|&nbsp; '
        'Conexión: USB /dev/ttyACM0',
        s_sub))
    story.append(Spacer(1, 1.5 * cm))
    story.append(tbl(
        [['Sección', 'Contenido'],
         ['1', 'Vista general de la pila de comunicación'],
         ['2', 'MAVLink: el protocolo binario del dron'],
         ['3', 'MAVROS: el puente ROS 2 ↔ MAVLink'],
         ['4', 'Transformación de coordenadas ENU ↔ NED'],
         ['5', 'Flujo completo: de la tecla al motor'],
         ['6', 'Pipeline interno PX4'],
         ['7', 'Modo OFFBOARD y watchdog de PX4'],
         ['8', 'Servicios ROS 2: petición-respuesta'],
         ['9', 'Parámetros de la conexión serie'],
         ['10', 'Comportamiento ante pérdida de conexión'],
         ['11', 'Conexión USB real: WSL2 y usbipd-win (nuevo)'],
         ['12', 'Mejoras al nodo mavros_node (nuevo)'],
         ['13', 'Verificación round-trip: [PX4 ACK] (nuevo)'],
         ['14', 'Problema QoS y solución (nuevo)'],
         ['15', 'Estado actual del proyecto (nuevo)']],
        col_widths=[1.5 * cm, 13 * cm],
    ))
    story.append(PageBreak())

    # ---- Sección 1: Vista general ----
    story.append(Paragraph('1.  Vista general de la pila', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'La cadena completa desde que el usuario presiona una tecla hasta que '
        'el motor ajusta sus RPM pasa por cuatro capas diferenciadas:', s_body))

    story.append(tbl(
        [['Capa', 'Qué hace', 'Tecnología'],
         ['Aplicación', 'Genera órdenes (menú, misión)', 'Python / ROS 2'],
         ['Transporte ROS 2', 'Pub/sub y servicios', 'DDS (rmw_fastrtps)'],
         ['Puente', 'Convierte msgs ROS2 ↔ MAVLink', 'MAVROS'],
         ['Protocolo dron', 'Telemetría y control serie', 'MAVLink v2']],
        col_widths=[3.5 * cm, 7 * cm, 5 * cm],
    ))
    story.append(Spacer(1, 0.3 * cm))
    story += img(img_paths['pila'],
                 caption='Figura 1 — Pila de comunicación completa: '
                         'del nodo Python al motor BLDC.')
    story.append(PageBreak())

    # ---- Sección 2: MAVLink ----
    story.append(Paragraph('2.  MAVLink: el idioma del dron', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'MAVLink es un protocolo binario ligero diseñado para vehículos autónomos. '
        'Cada mensaje incluye un identificador de tipo (Message ID), los IDs del '
        'sistema emisor/receptor, el payload con los datos y un CRC de verificación.', s_body))
    story += img(img_paths['mavlink'], w=W * 0.96,
                 caption='Figura 2 — Estructura de una trama MAVLink v2 con payload de velocidad.')
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph('Mensajes clave en este proyecto:', s_h2))
    story.append(tbl(
        [['ID', 'Nombre', 'Dirección', 'Contenido'],
         ['76', 'COMMAND_LONG',   'PC → Pixhawk', 'Armar, cambiar modo, despegar'],
         ['84', 'SET_POSITION_TARGET_LOCAL_NED', 'PC → Pixhawk',
          'Setpoint velocidad (vx, vy, vz)'],
         ['0',  'HEARTBEAT',      'Bidireccional', 'Estado del sistema (1 Hz)'],
         ['32', 'LOCAL_POSITION_NED', 'Pixhawk → PC',
          'Posición estimada por EKF2 (30 Hz)'],
         ['77', 'COMMAND_ACK',    'Pixhawk → PC',
          'Confirmación de COMMAND_LONG']],
        col_widths=[1 * cm, 5.5 * cm, 3 * cm, 6 * cm],
    ))
    story.append(PageBreak())

    # ---- Sección 3: MAVROS ----
    story.append(Paragraph('3.  MAVROS: el puente ROS 2 ↔ MAVLink', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'MAVROS es un nodo ROS 2 externo que mantiene abierta la conexión serie '
        'con el Pixhawk. Actúa como traductor bidireccional:', s_body))
    story += img(img_paths['nodos'], w=W,
                 caption='Figura 3 — Grafo de nodos ROS 2: topics (azul) y servicios (verde).')
    story.append(Spacer(1, 0.2 * cm))
    story.append(tbl(
        [['Topic / Servicio ROS 2', 'Tipo de mensaje', 'Mensaje MAVLink'],
         ['/mavros/setpoint_velocity/cmd_vel_unstamped',
          'geometry_msgs/Twist',
          'SET_POSITION_TARGET_LOCAL_NED (84)'],
         ['/mavros/state',
          'mavros_msgs/State',
          'HEARTBEAT (0) + SYS_STATUS (1)'],
         ['/mavros/local_position/pose',
          'geometry_msgs/PoseStamped',
          'LOCAL_POSITION_NED (32)'],
         ['/mavros/cmd/arming  (srv)',
          'mavros_msgs/CommandBool',
          'COMMAND_LONG → ARM_DISARM'],
         ['/mavros/set_mode  (srv)',
          'mavros_msgs/SetMode',
          'COMMAND_LONG → DO_SET_MODE'],
         ['/mavros/cmd/takeoff  (srv)',
          'mavros_msgs/CommandTOL',
          'COMMAND_LONG → NAV_TAKEOFF'],
         ['/mavros/setpoint_raw/target_local',
          'mavros_msgs/PositionTarget',
          'POSITION_TARGET_LOCAL_NED (85) — eco del setpoint']],
        col_widths=[5.5 * cm, 4.5 * cm, 5.5 * cm],
    ))
    story.append(PageBreak())

    # ---- Sección 4: Coordenadas ----
    story.append(Paragraph('4.  Transformación de coordenadas ENU ↔ NED', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'Este es el punto más importante y la fuente de errores más común. '
        'ROS 2 y MAVLink/PX4 usan marcos de referencia distintos. '
        'MAVROS aplica la conversión automáticamente, '
        'pero el programador debe saber en qué marco está escribiendo.', s_body))
    story += img(img_paths['coords'], w=W,
                 caption='Figura 4 — Comparación de marcos ENU (ROS 2) y NED (MAVLink/PX4). '
                          'El eje Z se invierte.')
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'Regla de conversión que aplica MAVROS internamente:', s_h2))
    story.append(Paragraph(
        'vx<sub>NED</sub> = linear.y<sub>ENU</sub> &nbsp;&nbsp; '
        'vy<sub>NED</sub> = linear.x<sub>ENU</sub> &nbsp;&nbsp; '
        'vz<sub>NED</sub> = −linear.z<sub>ENU</sub>', s_code))
    story.append(Paragraph(
        'Ejemplo: pulsar [w] en el menú llama a '
        '<font face="Courier" size="8">_enviar_vel(0.0, +0.3, 0.0)</font>, '
        'que pone <font face="Courier" size="8">linear.y = +0.3</font> '
        '(Norte en ENU). MAVROS lo convierte a vx=+0.3 m/s en NED, '
        'lo que hace que el dron se mueva hacia el Norte.', s_body))
    story.append(PageBreak())

    # ---- Sección 5: Flujo completo ----
    story.append(Paragraph('5.  Flujo completo: de la tecla al motor', s_h1))
    story.append(hr())
    story += img(img_paths['secuencia'], w=W,
                 caption='Figura 5 — Diagrama de secuencia: ciclo completo desde '
                          'la pulsación de tecla hasta la respuesta del motor y '
                          'la actualización de posición.')
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph('Resumen de pasos numerados:', s_h2))
    for i, step in enumerate([
        'El hilo de menú lee la tecla [w] y llama a '
        '<font face="Courier" size="8">_enviar_vel(0.0, 0.3, 0.0)</font>.',
        'El timer ROS 2 (10 Hz) publica el Twist al topic '
        '<font face="Courier" size="8">/mavros/setpoint_velocity/cmd_vel_unstamped</font>.',
        'MAVROS convierte ENU→NED y serializa el mensaje MAVLink ID 84 '
        'por el puerto serie USB a 921 600 baud.',
        'PX4 recibe el mensaje, valida el CRC y lo publica en el bus interno uORB.',
        'El MPC calcula el error de velocidad y genera un setpoint de pitch (~−3°).',
        'El controlador de actitud usa un PID para alcanzar ese pitch; '
        'el mixer distribuye entre los 6 motores.',
        'Los ESC ajustan las RPM en milisegundos vía PWM.',
        'El EKF2 fusiona IMU+GPS y publica LOCAL_POSITION_NED (ID 32) a 30 Hz.',
        'MAVROS convierte NED→ENU y publica en /mavros/local_position/pose.',
        'El nodo actualiza la posición mostrada en el menú.',
    ], 1):
        story.append(Paragraph(f'<b>{i}.</b> {step}', s_body))
    story.append(PageBreak())

    # ---- Sección 6: PX4 interno ----
    story.append(Paragraph('6.  Pipeline interno PX4', s_h1))
    story.append(hr())
    story += img(img_paths['px4'], w=W,
                 caption='Figura 6 — Cadena de control interna de PX4: '
                          'del setpoint de velocidad a la señal PWM.')
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph(
        'El MPC (Multicopter Position Controller) necesita una estimación de '
        'posición/velocidad precisa. Sin GPS ni flujo óptico, no puede operar '
        'en modo OFFBOARD con comandos de velocidad. Para pruebas en interiores '
        'se suele usar un sistema de captura de movimiento (mocap) o T265.', s_note))

    # ---- Sección 7: Modo OFFBOARD ----
    story.append(Paragraph('7.  Modo OFFBOARD: el watchdog de PX4', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'PX4 tiene un watchdog interno: si no llegan setpoints externos en '
        '<b>500 ms</b>, abandona OFFBOARD y entra en HOLD. '
        'Por eso el nodo publica a 10 Hz incluso cuando el dron está quieto '
        '(Twist con todos los campos a cero):', s_body))
    story.append(Paragraph(
        '# pixhawk_menu_node.py — línea 51\n'
        'self.create_timer(1.0 / TASA_HZ, self._timer_vel)  # 10 Hz\n\n'
        '# línea 79-80\n'
        'if time.time() > self._activo_hasta:\n'
        '    self._cmd_vel = Twist()  # setpoint cero al expirar la duración',
        s_code))
    story.append(Paragraph(
        'Secuencia de arranque obligatoria para PX4:', s_h2))
    story.append(tbl(
        [['Paso', 'Acción', 'Por qué'],
         ['1', 'Arrancar pixhawk_menu_node', 'Inicia la publicación de setpoints a 10 Hz'],
         ['2', 'Esperar ~2 s',
          'PX4 verifica que ya hay setpoints en cola'],
         ['3', '[3] Modo OFFBOARD',
          'PX4 acepta el cambio porque ya ve setpoints'],
         ['4', '[1] Armar',
          'Los motores se activan'],
         ['5', '[4] Despegar',
          'Sube a la altitud indicada'],
         ['6', '[w/s/a/d/r/f]',
          'Envía velocidad durante 1 s, luego vuelve a cero']],
        col_widths=[1.2 * cm, 5 * cm, 9.3 * cm],
    ))
    story.append(PageBreak())

    # ---- Sección 8: Servicios ----
    story.append(Paragraph('8.  Servicios ROS 2: petición-respuesta', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'A diferencia de los topics (one-way), los servicios son síncronos '
        '(req/resp). El nodo usa <font face="Courier" size="8">call_async</font> '
        'para no bloquear el executor de ROS 2 mientras espera la confirmación '
        'del Pixhawk (que puede tardar hasta ~500 ms):', s_body))
    story.append(Paragraph(
        '# _armar() — línea 116\n'
        'fut = self._cli_armar.call_async(req)\n'
        'fut.add_done_callback(\n'
        '    lambda f: self.get_logger().info(\n'
        '        f"ARMAR: {\'OK\' if f.result().success else \'FALLO\'}"))',
        s_code))
    story.append(Paragraph(
        'El flujo interno es:', s_h2))
    story.append(Paragraph(
        '1. El nodo envía <b>CommandBool.Request(value=True)</b> al servicio.<br/>'
        '2. MAVROS empaqueta un <b>COMMAND_LONG (ID 76)</b> con '
        'MAV_CMD_COMPONENT_ARM_DISARM y param1=1.0.<br/>'
        '3. Pixhawk ejecuta los prearm checks (nivel batería, calibración IMU, etc.).<br/>'
        '4. Responde con <b>COMMAND_ACK (ID 77)</b>: result=ACCEPTED o DENIED.<br/>'
        '5. MAVROS traduce la respuesta a <b>CommandBool.Response(success=True/False)</b>.',
        s_body))

    # ---- Sección 9: Parámetros de conexión ----
    story.append(Paragraph('9.  Parámetros de la conexión serie', s_h1))
    story.append(hr())
    story.append(tbl(
        [['Parámetro', 'Valor', 'Observación'],
         ['Puerto', '/dev/ttyACM0', 'USB virtual CDC-ACM (como un Arduino)'],
         ['Baudrate', '921 600 bps', 'Máxima velocidad soportada por el USB virtual'],
         ['Bits datos', '8', 'Estándar'],
         ['Paridad', 'Ninguna', '—'],
         ['Bits de stop', '1', '—'],
         ['Control de flujo', 'Ninguno', '—'],
         ['Tiempo/trama', '~0.2 ms', 'Para un mensaje de 20 bytes a 921 600 bps']],
        col_widths=[4 * cm, 4.5 * cm, 7 * cm],
    ))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(
        'Comando para arrancar MAVROS con PX4 (ejecutar antes del nodo menú):', s_h2))
    story.append(Paragraph(
        'ros2 run mavros mavros_node \\\n'
        '  --ros-args \\\n'
        '  -p fcu_url:=serial:///dev/ttyACM0:921600 \\\n'
        '  -p gcs_url:=\'\'',
        s_code))

    # ---- Sección 10: Pérdida de conexión ----
    story.append(Paragraph('10.  Comportamiento ante pérdida de conexión', s_h1))
    story.append(hr())
    story.append(tbl(
        [['Evento', 'Reacción PX4', 'Parámetro relevante'],
         ['Sin setpoints OFFBOARD > 500 ms',
          'Sale de OFFBOARD → HOLD\n(flota en posición actual)',
          'COM_RC_OVERRIDE'],
         ['Sin HEARTBEAT del GCS > 3 s',
          'Puede activar acción de failsafe',
          'COM_DL_LOSS_T'],
         ['Pérdida total de MAVLink',
          'Aterrizar / RTL / mantener\nsegún configuración',
          'NAV_DLL_ACT']],
        col_widths=[5.5 * cm, 5.5 * cm, 4.5 * cm],
    ))
    story.append(Spacer(1, 0.4 * cm))
    story.append(Paragraph(
        'Nota de seguridad: siempre tener a mano el mando RC '
        'con mayor prioridad que OFFBOARD para recuperar el control manualmente '
        'ante cualquier fallo del software.', s_note))

    # ---- Sección 11: WSL2 + usbipd ----
    story.append(PageBreak())
    story.append(Paragraph('11.  Conexión USB real: WSL2 y usbipd-win', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'El Pixhawk se conecta por USB al PC Windows como <b>COM5</b>. '
        'WSL2 es una máquina virtual Linux que por defecto no puede ver '
        'dispositivos USB del host. Para reenviar el puerto al kernel Linux '
        'se usa <b>usbipd-win</b>, un driver de kernel de Microsoft.', s_body))
    story += img(img_paths['usbipd'], w=W,
                 caption='Figura 7 — Cadena completa de reenvío USB desde el Pixhawk '
                         'hasta MAVROS en WSL2.')
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph('Pasos de configuración (una vez por sesión):', s_h2))
    story.append(tbl(
        [['Dónde', 'Comando', 'Efecto'],
         ['PowerShell (Admin)', 'winget install usbipd',
          'Instala usbipd-win (solo la primera vez)'],
         ['PowerShell (Admin)', 'usbipd list',
          'Muestra BUSID del Pixhawk (VID 3185:0038)'],
         ['PowerShell (Admin)', 'usbipd bind --busid 2-2',
          'Marca el dispositivo para ser compartido'],
         ['PowerShell (Admin)', 'usbipd attach --wsl --busid 2-2',
          'Conecta el dispositivo a WSL2'],
         ['WSL2', 'ls /dev/ttyACM*',
          'Confirma que aparece /dev/ttyACM0'],
         ['WSL2', 'sudo chmod 666 /dev/ttyACM0',
          'Da permisos de lectura/escritura sin sudo'],
         ['WSL2', 'ros2 launch mavros px4.launch fcu_url:=/dev/ttyACM0:57600',
          'Arranca MAVROS conectado al Pixhawk']],
        col_widths=[3.5 * cm, 5.5 * cm, 6.5 * cm],
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'Señal de éxito en MAVROS: '
        '<font face="Courier" size="8">'
        '[mavros.mavros]: CON: Got HEARTBEAT, connected. FCU: PX4 Autopilot'
        '</font>', s_note))

    # ---- Sección 12: Mejoras mavros_node ----
    story.append(PageBreak())
    story.append(Paragraph('12.  Mejoras al nodo mavros_node', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'El <b>mavros_node.py</b> original solo publicaba en <b>/drone/cmd_vel</b> '
        '(el simulador) y leía posición de <b>/drone/pose</b>. '
        'Para conectar con el Pixhawk real se añadieron tres capacidades:', s_body))
    story.append(tbl(
        [['Qué se añadió', 'Por qué'],
         ['Publisher → /mavros/setpoint_velocity/cmd_vel_unstamped',
          'Canal que MAVROS escucha para reenviar al Pixhawk'],
         ['Subscriber ← /mavros/local_position/pose  (PoseStamped)',
          'Posición real del Pixhawk vía EKF2; tiene prioridad sobre el '
          'simulador (pos_source=mavros)'],
         ['Subscriber ← /mavros/state  (mavros_msgs/State)',
          'Monitorea si MAVROS está conectado; avisa si el comando '
          'puede no llegar al Pixhawk'],
         ['Log enriquecido con pos_source, mode, armed',
          'Permite verificar en tiempo real si la fuente de posición '
          'es el simulador o el Pixhawk real']],
        col_widths=[7 * cm, 8.5 * cm],
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'Ejemplo de log cuando MAVROS está conectado y hay target activo:', s_h2))
    story.append(Paragraph(
        '[INFO] [mavros] target=(2.40,1.50,1.00)  '
        'pos=(0.12,0.08,0.00)  vel=(+2.28,+1.42,+1.00)  '
        'modo=OFFBOARD  armado=False',
        s_code))
    story.append(Paragraph(
        'El prefijo <b>[mavros]</b> indica que la posición proviene del Pixhawk real, '
        'no del simulador.', s_note))

    # ---- Sección 13: Round-trip ACK ----
    story.append(PageBreak())
    story.append(Paragraph('13.  Verificación round-trip: [PX4 ACK]', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'Para confirmar que un comando llega físicamente al Pixhawk se añadió '
        'en <b>pixhawk_menu_node.py</b> una suscripción al topic '
        '<font face="Courier" size="9">/mavros/setpoint_raw/target_local</font>. '
        'Este topic es el eco que PX4 emite vía '
        '<b>POSITION_TARGET_LOCAL_NED (MAVLink ID 85)</b> cada vez que recibe '
        'y procesa un setpoint de velocidad.', s_body))
    story += img(img_paths['roundtrip'], w=W,
                 caption='Figura 8 — Ciclo completo de verificación: desde la pulsación '
                         'de [w] hasta el mensaje [PX4 ACK] que confirma el eco del Pixhawk.')
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph('Código clave en pixhawk_menu_node.py:', s_h2))
    story.append(Paragraph(
        'from mavros_msgs.msg import PositionTarget, State\n\n'
        '# en __init__:\n'
        'self.create_subscription(\n'
        '    PositionTarget,\n'
        "    '/mavros/setpoint_raw/target_local',\n"
        '    self._cb_ack_pixhawk, _qos)\n\n'
        '# callback:\n'
        'def _cb_ack_pixhawk(self, msg):\n'
        '    vx, vy, vz = msg.velocity.x, msg.velocity.y, msg.velocity.z\n'
        '    if abs(vx) < 0.01 and abs(vy) < 0.01 and abs(vz) < 0.01:\n'
        '        return\n'
        "    print(f'[PX4 ACK] vx={vx:+.3f}  vy={vy:+.3f}  vz={vz:+.3f} m/s  [ENU] ✓')",
        s_code))

    # ---- Sección 14: QoS ----
    story.append(PageBreak())
    story.append(Paragraph('14.  Problema QoS y solución', s_h1))
    story.append(hr())
    story.append(Paragraph(
        'Al conectar el Pixhawk real se detectó que el menú mostraba '
        '<b>Modo: DESCONOCIDO</b> aunque MAVROS estuviera conectado. '
        'El log mostraba:', s_body))
    story.append(Paragraph(
        '[WARN] New publisher discovered on topic /mavros/local_position/pose, '
        'offering incompatible QoS. No messages will be received from it. '
        'Last incompatible policy: RELIABILITY',
        s_code))
    story.append(Paragraph(
        'La causa es una diferencia en la política de calidad de servicio (QoS) '
        'de ROS 2. MAVROS publica los topics de sensores con '
        '<b>BEST_EFFORT</b> (puede perder mensajes, menor latencia), '
        'pero el suscriptor por defecto de ROS 2 usa <b>RELIABLE</b> '
        '(exige entrega garantizada). DDS los considera incompatibles y '
        'descarta todos los mensajes.', s_body))
    story += img(img_paths['qos'], w=W * 0.92,
                 caption='Figura 9 — Incompatibilidad QoS antes y después de la corrección.')
    story.append(Spacer(1, 0.2 * cm))
    story.append(Paragraph('Topics afectados y solución aplicada:', s_h2))
    story.append(tbl(
        [['Topic MAVROS', 'QoS publicador', 'QoS original nuestro', 'QoS corregido'],
         ['/mavros/state', 'BEST_EFFORT', 'RELIABLE', 'BEST_EFFORT'],
         ['/mavros/local_position/pose', 'BEST_EFFORT', 'RELIABLE', 'BEST_EFFORT'],
         ['/mavros/setpoint_raw/target_local', 'BEST_EFFORT', 'RELIABLE', 'BEST_EFFORT']],
        col_widths=[6 * cm, 3 * cm, 3.5 * cm, 3 * cm],
    ))
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph(
        'La corrección se aplicó en <b>pixhawk_menu_node.py</b> y '
        '<b>mavros_node.py</b> creando un perfil QoS compartido:', s_body))
    story.append(Paragraph(
        'from rclpy.qos import QoSProfile, ReliabilityPolicy\n\n'
        '_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)\n'
        "self.create_subscription(State, '/mavros/state', self._estado_cb, _qos)\n"
        "self.create_subscription(PoseStamped, '/mavros/local_position/pose', "
        "self._pose_cb, _qos)",
        s_code))

    # ---- Sección 15: Estado actual ----
    story.append(PageBreak())
    story.append(Paragraph('15.  Estado actual del proyecto', s_h1))
    story.append(hr())
    story.append(tbl(
        [['Componente', 'Estado', 'Detalle'],
         ['USB Pixhawk → WSL2', '✓ Operativo',
          'usbipd-win, /dev/ttyACM0:57600, VID 3185:0038'],
         ['MAVROS ↔ Pixhawk', '✓ Conectado',
          'Got HEARTBEAT, FCU: PX4 Autopilot'],
         ['mavros_node → MAVROS', '✓ Publicando',
          'Publica en /mavros/setpoint_velocity/cmd_vel_unstamped'],
         ['Posición real Pixhawk', '⚠ Pendiente confirmar',
          'Suscripción a /mavros/local_position/pose con QoS corregido'],
         ['Estado MAVROS (armed/mode)', '⚠ Pendiente confirmar',
          'QoS BEST_EFFORT aplicado, pendiente reiniciar nodo'],
         ['Round-trip [PX4 ACK]', '⚠ Pendiente confirmar',
          'Código en pixhawk_menu_node, necesita QoS fix activo'],
         ['Simulador (simulador_dron)', '✓ Sin cambios',
          'Funciona en paralelo; mavros_node usa /drone/pose si no hay Pixhawk'],
         ['cerebro_node → misión', '✓ Sin cambios',
          'Lee mision.json, secuencia de waypoints triple-Z']],
        col_widths=[4.5 * cm, 3 * cm, 8 * cm],
    ))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph('Próximos pasos para completar la integración:', s_h2))
    for step in [
        'Reiniciar <b>pixhawk_menu_node</b> con el binario nuevo (QoS fix) y '
        'verificar que Modo ya no muestra DESCONOCIDO.',
        'Pulsar <b>[w]</b> y confirmar que aparece la línea '
        '<font face="Courier" size="8">[PX4 ACK] vx=+0.300 ... ✓</font>.',
        'Con OFFBOARD activo, verificar que '
        '<font face="Courier" size="8">/mavros/local_position/pose</font> '
        'actualiza la posición en el menú.',
        'Integrar <b>cerebro_node + mavros_node</b> con Pixhawk real para '
        'ejecutar la misión triple-Z en hardware.',
    ]:
        story.append(Paragraph(f'• {step}', s_body))

    # ---- Construcción ----
    doc.build(story)
    print(f'PDF generado: {PDF_PATH}')


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    """Generar todos los diagramas y construir el PDF."""
    print('Generando diagramas...')
    paths = {
        'pila':       diag_pila(),
        'coords':     diag_coords(),
        'nodos':      diag_nodos(),
        'px4':        diag_px4(),
        'mavlink':    diag_mavlink(),
        'secuencia':  diag_secuencia(),
        'usbipd':     diag_usbipd(),
        'roundtrip':  diag_roundtrip(),
        'qos':        diag_qos(),
    }
    print('Construyendo PDF...')
    build_pdf(paths)

    # Limpiar imágenes temporales
    import shutil
    shutil.rmtree(TMP, ignore_errors=True)


if __name__ == '__main__':
    main()
