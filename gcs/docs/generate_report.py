#!/usr/bin/env python3
"""
Drone GCS — Professional PDF Manual Generator
White paper · Black ink · Single-colour accent
"""

from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.lib.units import cm, mm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_JUSTIFY, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether
)
from datetime import date

OUT = r"C:\drone-gcs\docs\Drone_GCS_Manual.pdf"

# ── Palette (white paper, black ink, one blue accent) ─────────────────────────
WHITE      = colors.white
BLACK      = colors.HexColor("#111111")
ACCENT     = colors.HexColor("#1B3D6F")   # deep navy blue
ACCENT_LT  = colors.HexColor("#E8EFF8")   # very light blue tint
GRAY_90    = colors.HexColor("#1A1A1A")
GRAY_60    = colors.HexColor("#555555")
GRAY_40    = colors.HexColor("#888888")
GRAY_10    = colors.HexColor("#F4F4F4")   # lightest table row
GRAY_05    = colors.HexColor("#FAFAFA")
RULE       = colors.HexColor("#CCCCCC")
COVER_BG   = colors.HexColor("#1B3D6F")
CODE_BG    = colors.HexColor("#F2F4F6")

# ── Typography ─────────────────────────────────────────────────────────────────
def sty(name, **kw):
    return ParagraphStyle(name, **kw)

# Cover
cover_title = sty("CoverTitle",
    fontName="Helvetica-Bold", fontSize=42, textColor=WHITE,
    alignment=TA_LEFT, leading=50, spaceAfter=6)

cover_sub = sty("CoverSub",
    fontName="Helvetica", fontSize=16, textColor=colors.HexColor("#A8C4E6"),
    alignment=TA_LEFT, spaceAfter=4)

cover_label = sty("CoverLabel",
    fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#7B9DC6"),
    alignment=TA_LEFT, spaceAfter=3, leading=15)

# Headings
h1 = sty("H1",
    fontName="Helvetica-Bold", fontSize=17, textColor=ACCENT,
    spaceBefore=20, spaceAfter=4, leading=21)

h2 = sty("H2",
    fontName="Helvetica-Bold", fontSize=12, textColor=BLACK,
    spaceBefore=14, spaceAfter=4, leading=16)

h3 = sty("H3",
    fontName="Helvetica-Bold", fontSize=10, textColor=GRAY_60,
    spaceBefore=8, spaceAfter=3, leading=14)

# Body
body = sty("Body",
    fontName="Helvetica", fontSize=10, textColor=BLACK,
    leading=16, spaceAfter=5, alignment=TA_JUSTIFY)

bullet = sty("Bullet",
    fontName="Helvetica", fontSize=10, textColor=BLACK,
    leading=15, spaceAfter=2, leftIndent=16, bulletIndent=4)

code = sty("Code",
    fontName="Courier", fontSize=8.5, textColor=colors.HexColor("#2A2A2A"),
    backColor=CODE_BG, leading=13, spaceAfter=1,
    leftIndent=10, rightIndent=10, borderPad=6)

note = sty("Note",
    fontName="Helvetica-Oblique", fontSize=9, textColor=GRAY_60,
    leading=13, spaceAfter=4, leftIndent=12,
    borderPad=0)

toc_entry = sty("TOC",
    fontName="Helvetica-Bold", fontSize=11, textColor=BLACK,
    leading=20, leftIndent=0)

toc_num = sty("TOCNum",
    fontName="Helvetica-Bold", fontSize=11, textColor=ACCENT,
    leading=20, leftIndent=0)

toc_sub = sty("TOCSub",
    fontName="Helvetica", fontSize=9.5, textColor=GRAY_60,
    leading=14, leftIndent=18, spaceAfter=4)

# Header/footer paragraph styles
hdr_left  = sty("HdrL",  fontName="Helvetica-Bold", fontSize=8,
                textColor=ACCENT,   leading=10)
hdr_right = sty("HdrR",  fontName="Helvetica",      fontSize=8,
                textColor=GRAY_40, leading=10)
ftr_left  = sty("FtrL",  fontName="Helvetica",      fontSize=8,
                textColor=GRAY_40, leading=10)
ftr_right = sty("FtrR",  fontName="Helvetica-Bold", fontSize=8,
                textColor=GRAY_60, leading=10, alignment=TA_RIGHT)

# ── Page template ──────────────────────────────────────────────────────────────
_W, _H = A4
_LM = 2.0 * cm
_RM = 2.0 * cm

def on_page(canvas, doc):
    canvas.saveState()
    w, h = A4

    # ── header ──────────────────────────
    # top rule (full width, navy)
    canvas.setStrokeColor(ACCENT)
    canvas.setLineWidth(1.5)
    canvas.line(_LM, h - 1.6*cm, w - _RM, h - 1.6*cm)

    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(ACCENT)
    canvas.drawString(_LM, h - 1.3*cm, "DRONE GCS")

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY_40)
    canvas.drawRightString(w - _RM, h - 1.3*cm, "Ground Control Station — Manual d'Usuari")

    # ── footer ──────────────────────────
    canvas.setStrokeColor(RULE)
    canvas.setLineWidth(0.5)
    canvas.line(_LM, 1.5*cm, w - _RM, 1.5*cm)

    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(GRAY_40)
    canvas.drawString(_LM, 1.0*cm,
                      f"PAE-EDISA-2026   ·   {date.today().strftime('%d %B %Y')}")
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(GRAY_60)
    canvas.drawRightString(w - _RM, 1.0*cm, f"Pàgina  {doc.page}")

    canvas.restoreState()

def on_first_page(canvas, doc):
    """Full navy cover page."""
    canvas.saveState()
    w, h = A4

    # navy background
    canvas.setFillColor(COVER_BG)
    canvas.rect(0, 0, w, h, fill=1, stroke=0)

    # white left sidebar accent strip
    canvas.setFillColor(colors.HexColor("#2A5FA8"))
    canvas.rect(0, 0, 6*mm, h, fill=1, stroke=0)

    # bottom band
    canvas.setFillColor(colors.HexColor("#142D52"))
    canvas.rect(0, 0, w, 3.5*cm, fill=1, stroke=0)

    # bottom text
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#7B9DC6"))
    canvas.drawString(_LM + 6*mm, 2.2*cm,
                      f"PAE-EDISA-2026   ·   Versió 1.0   ·   {date.today().strftime('%B %Y')}")
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#4A6E98"))
    canvas.drawString(_LM + 6*mm, 1.4*cm,
                      "Confidential / Internal Use")

    # top-right small label
    canvas.setFont("Helvetica", 9)
    canvas.setFillColor(colors.HexColor("#4A6E98"))
    canvas.drawRightString(w - _RM, h - 1.8*cm,
                           "TECHNICAL MANUAL  ·  v1.0")

    canvas.restoreState()

# ── Helper flowables ───────────────────────────────────────────────────────────
def HR(thick=0.6, col=RULE, before=2, after=8):
    return HRFlowable(width="100%", thickness=thick,
                      color=col, spaceBefore=before, spaceAfter=after)

def HR_accent():
    """Thin navy rule used under H1."""
    return HRFlowable(width="100%", thickness=1.2,
                      color=ACCENT, spaceBefore=0, spaceAfter=10)

def P(text, style=body):
    return Paragraph(text, style)

def B(text):
    return Paragraph(f"<bullet>–</bullet>  {text}", bullet)

def SP(n=6):
    return Spacer(1, n)

def section_header(num, title):
    """Returns [number+title paragraph, accent rule]."""
    return [
        P(f"{num}.&nbsp;&nbsp;{title}", h1),
        HR_accent(),
    ]

# ── Table helpers ──────────────────────────────────────────────────────────────
_TH_STYLE = sty("TH", fontName="Helvetica-Bold",   fontSize=9,
                textColor=WHITE,    leading=13)
_TD_K     = sty("TDK", fontName="Helvetica-Bold",  fontSize=9,
                textColor=ACCENT,   leading=13)
_TD_V     = sty("TDV", fontName="Helvetica",       fontSize=9,
                textColor=BLACK,    leading=13)
_TD_MONO  = sty("TDM", fontName="Courier",         fontSize=8,
                textColor=GRAY_60, leading=12)
_TD_SM    = sty("TDSM", fontName="Helvetica",      fontSize=8.5,
                textColor=GRAY_60, leading=12)

_BASE_TS = [
    ("BACKGROUND",    (0, 0), (-1,  0), ACCENT),
    ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, GRAY_10]),
    ("GRID",          (0, 0), (-1, -1), 0.4, RULE),
    ("TOPPADDING",    (0, 0), (-1, -1), 5),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ("LEFTPADDING",   (0, 0), (-1, -1), 8),
    ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
    ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ("LINEBELOW",     (0, 0), (-1,  0), 0,   ACCENT),
]

def feature_table(rows, col_w=None):
    if col_w is None:
        col_w = [4.8*cm, 11.7*cm]
    data = [
        [P("<b>Característica</b>", _TH_STYLE),
         P("<b>Descripció</b>",     _TH_STYLE)],
    ] + [
        [P(k, _TD_K), P(v, _TD_V)]
        for k, v in rows
    ]
    return Table(data, colWidths=col_w,
                 style=TableStyle(_BASE_TS))

def service_table(rows):
    data = [
        [P("<b>Servei</b>",     _TH_STYLE),
         P("<b>Descripció</b>", _TH_STYLE),
         P("<b>Script Pi</b>",  _TH_STYLE)],
    ] + [
        [P(a, _TD_K), P(b, _TD_V), P(c, _TD_MONO)]
        for a, b, c in rows
    ]
    return Table(data, colWidths=[2.2*cm, 10.0*cm, 4.3*cm],
                 style=TableStyle(_BASE_TS))

def topic_table(rows):
    data = [
        [P("<b>Tòpic ROS2</b>",  _TH_STYLE),
         P("<b>Tipus</b>",       _TH_STYLE),
         P("<b>Descripció</b>",  _TH_STYLE)],
    ] + [
        [P(a, _TD_MONO), P(b, _TD_MONO), P(c, _TD_SM)]
        for a, b, c in rows
    ]
    return Table(data, colWidths=[5.4*cm, 4.0*cm, 7.1*cm],
                 style=TableStyle(_BASE_TS))

def cmd_table(rows):
    data = [
        [P("<b>Acció</b>",       _TH_STYLE),
         P("<b>JSON d'exemple</b>", _TH_STYLE)],
    ] + [
        [P(a, _TD_K), P(b, _TD_MONO)]
        for a, b in rows
    ]
    return Table(data, colWidths=[3.5*cm, 13.0*cm],
                 style=TableStyle(_BASE_TS))

# ── Note box (light blue tint) ─────────────────────────────────────────────────
def note_box(text):
    inner = P(f"<b>Nota:</b>  {text}", sty("NB",
        fontName="Helvetica", fontSize=9, textColor=BLACK,
        leading=14, spaceAfter=0))
    t = Table([[inner]], colWidths=[16.5*cm],
        style=TableStyle([
            ("BACKGROUND",   (0,0), (-1,-1), ACCENT_LT),
            ("LINEBELOW",    (0,0), (-1,-1), 1.0, ACCENT),
            ("LINEBEFORE",   (0,0), (-1,-1), 3.0, ACCENT),
            ("TOPPADDING",   (0,0), (-1,-1), 7),
            ("BOTTOMPADDING",(0,0), (-1,-1), 7),
            ("LEFTPADDING",  (0,0), (-1,-1), 10),
            ("RIGHTPADDING", (0,0), (-1,-1), 10),
        ]))
    return KeepTogether([SP(4), t, SP(6)])

# ══════════════════════════════════════════════════════════════════════════════
# BUILD
# ══════════════════════════════════════════════════════════════════════════════
doc = SimpleDocTemplate(
    OUT, pagesize=A4,
    leftMargin=_LM,  rightMargin=_RM,
    topMargin=2.2*cm, bottomMargin=2.0*cm,
    title="Drone GCS — Manual d'Usuari v1.0",
    author="PAE-EDISA-2026",
    subject="Ground Control Station",
    creator="generate_report.py",
)

story = []

# ──────────────────────────────────────────────────────────────────────────────
# COVER PAGE
# ──────────────────────────────────────────────────────────────────────────────
cover_body = sty("CoverBody",
    fontName="Helvetica", fontSize=10, textColor=colors.HexColor("#A8C4E6"),
    alignment=TA_LEFT, leading=15)

story += [
    SP(3.5*cm),
    P("DRONE", cover_title),
    P("GCS", sty("CT2", fontName="Helvetica-Bold", fontSize=42, textColor=WHITE,
                 alignment=TA_LEFT, leading=44, spaceAfter=16)),
    SP(0.5*cm),
    HRFlowable(width="70%", thickness=1, color=colors.HexColor("#2A5FA8"),
               spaceAfter=16, spaceBefore=0),
    P("Ground Control Station", cover_sub),
    P("Manual d'Usuari  ·  Guia d'Instal·lació", cover_sub),
    SP(0.5*cm),
    P("Sistema de control en temps real per a drons multirotor basat en", cover_body),
    P("Electron · ROS2 Jazzy · rosbridge WebSocket · pymavlink", cover_body),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# TABLE OF CONTENTS
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("", "Índex"),
    SP(6),
]

toc_rows = [
    ("1", "Visió General i Arquitectura",
          "Electron · ROS2 · rosbridge WebSocket · Components"),
    ("2", "Instal·lació",
          "setup.exe Windows  ·  Configuració Raspberry Pi"),
    ("3", "Connexió i Interfície Principal",
          "Topbar · Indicadors · Detecció de xarxa"),
    ("4", "Dashboard",
          "Comandes · Bateria · Serveis · Mapa · Càmera · Motors"),
    ("5", "Navigation",
          "Horizon · Compass · Telemetria · Gràfiques · Setpoints"),
    ("6", "SLAM",
          "Visor 3D WebGL · Pose · Mapa Point-LIO"),
    ("7", "Image Processing — Detecció de Codis",
          "ROI · Inventari · Export CSV"),
    ("8", "Serveis de la Raspberry Pi",
          "gcs_control · SLAM · Camera · MAVROS · Brain · Barcode"),
    ("9", "Referència Tòpics ROS2",
          "Telemetria · Comandes · Formats JSON"),
]

for num, title, sub in toc_rows:
    row_data = [
        [P(f"<b>{num}</b>",  sty(f"tn{num}", fontName="Helvetica-Bold",
                                  fontSize=11, textColor=ACCENT, leading=18)),
         P(f"<b>{title}</b>", sty(f"tt{num}", fontName="Helvetica-Bold",
                                   fontSize=11, textColor=BLACK, leading=18)),
         P("",  sty(f"td{num}", fontName="Helvetica", fontSize=11,
                    textColor=GRAY_40, leading=18))],
        [P("",  body),
         P(sub, sty(f"ts{num}", fontName="Helvetica", fontSize=9,
                    textColor=GRAY_60, leading=13, spaceAfter=6)),
         P("",  body)],
    ]
    t = Table(row_data, colWidths=[0.9*cm, 12.6*cm, 3*cm],
              style=TableStyle([
                  ("TOPPADDING",    (0,0), (-1,-1), 1),
                  ("BOTTOMPADDING", (0,0), (-1,-1), 1),
                  ("LEFTPADDING",   (0,0), (-1,-1), 0),
                  ("RIGHTPADDING",  (0,0), (-1,-1), 0),
                  ("LINEBELOW",     (0,1), (-1,1), 0.4, RULE),
              ]))
    story.append(t)

story.append(PageBreak())

# ──────────────────────────────────────────────────────────────────────────────
# 1. VISIÓ GENERAL
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("1", "Visió General i Arquitectura"),
    P("""<b>Drone GCS</b> és una aplicació d'escriptori per a Windows construïda amb
       <b>Electron</b> que permet monitoritzar i controlar un drone en temps real.
       La comunicació amb el drone es fa a través d'una <b>Raspberry Pi 5</b> que
       executa <b>ROS2 Jazzy</b> i exposa totes les dades via
       <b>rosbridge WebSocket</b> al port 9090.""", body),
    SP(8),

    P("Arquitectura del sistema", h2),
    feature_table([
        ("PC (Windows)",      "Aplicació Electron. Interfície gràfica, visualització 3D, "
                              "controls de vol, SLAM viewer, detecció de codis."),
        ("Raspberry Pi 5",    "ROS2 Jazzy, rosbridge, serveis de vol: SLAM, càmera, "
                              "pymavlink bridge, brain node, detector de codis."),
        ("Pixhawk / FC",      "Controladora de vol ArduCopter. Connectada a la Pi per "
                              "serial UART (/dev/ttyAMA0, 57600 baud)."),
        ("LiDAR Unitree L2",  "Sensor LiDAR 3D. Connectat a la Pi per Ethernet "
                              "(192.168.1.62). Usat per Point-LIO SLAM."),
        ("Càmera frontal",    "Mòdul càmera CSI (Raspberry Pi Camera). Canal: /dev/video0. "
                              "640×480 px, 30 fps, JPEG 80."),
        ("Comunicació",       "WiFi o hotspot entre PC i Pi. "
                              "WebSocket: ws://raspi5.local:9090."),
    ]),
    SP(10),

    P("Flux de dades", h2),
    P("""El PC es connecta al <b>rosbridge WebSocket</b> de la Pi usant la llibreria
       <b>roslibjs</b>. Tot el que es publica o subscriu passa per aquest canal únic.
       La Pi gestiona tota la lògica ROS2: rep comandes del dashboard (a través de
       /drone/cmd i /gcs/cmd) i publica telemetria que el frontend visualitza
       en temps real.""", body),
    SP(6),

    P("Stack tecnològic", h2),
    feature_table([
        ("Frontend",  "HTML5 · CSS3 · JavaScript vanilla · Canvas API · WebGL · roslibjs"),
        ("Backend PC","Electron (Node.js) · Chromium renderer · IPC main/renderer"),
        ("Pi (ROS2)", "Python 3 · rclpy · pymavlink · OpenCV · pyzbar"),
        ("Comunicació","rosbridge_suite WebSocket JSON bridge"),
        ("SLAM",      "Point-LIO (LiDAR Odometry) + Unitree L2 ROS2 driver"),
        ("Instal·lador","electron-builder NSIS (Windows .exe setup)"),
    ]),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 2. INSTAL·LACIÓ
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("2", "Instal·lació"),

    P("2.1  Windows — Instal·lador setup.exe", h2),
    P("""L'aplicació es distribueix com a instal·lador estàndard generat per
       <b>electron-builder</b>. No requereix cap dependència addicional al PC.""", body),
    SP(4),
    B("<b>Pas 1:</b> Executar <b>Drone GCS Setup.exe</b> (doble clic, acceptar UAC si cal)."),
    B("<b>Pas 2:</b> Seguir l'assistent: Next → Install → Finish."),
    B("<b>Pas 3:</b> L'aplicació s'instal·la a <i>%LOCALAPPDATA%\\Drone GCS\\</i> "
      "i es crea un accés directe a l'escriptori."),
    B("<b>Pas 4:</b> Obrir l'aplicació. Intentarà connectar automàticament a "
      "<b>ws://raspi5.local:9090</b>."),
    SP(6),
    note_box("Si la Raspberry Pi no és accessible per hostname, clicar la URL de connexió "
             "a la topbar i introduir la IP directament (ex: ws://172.20.10.2:9090)."),

    P("2.2  Raspberry Pi — Requisits previs", h2),
    feature_table([
        ("Sistema",     "Raspberry Pi OS Bookworm (64-bit) · Raspberry Pi 5"),
        ("ROS2",        "ROS2 Jazzy Jalisco (instal·lat a /opt/ros/jazzy)"),
        ("rosbridge",   "ros-jazzy-rosbridge-server"),
        ("SLAM",        "Workspace ~/slam_ws/ amb unitree_lidar_ros2 + point_lio compilats"),
        ("Python extra","pymavlink · pyzbar · opencv-python · libzbar0"),
    ]),
    SP(8),

    P("2.3  Raspberry Pi — Instal·lació pas a pas", h2),
    P("<b>Fitxers a copiar a la Pi (directori ~/)</b>:", h3),
    feature_table([
        ("gcs_control.py",     "Node gestor de serveis (sempre actiu)."),
        ("mavlink_bridge.py",  "Bridge pymavlink per al Pixhawk."),
        ("barcode_detector.py","Detector de codis amb OpenCV + pyzbar."),
        ("slam_launch.sh",     "Script seqüencial eth1 → LiDAR → Point-LIO."),
        ("camera_publisher.py","Publicador de càmera comprimida."),
        ("mjpeg_server.py",    "Servidor MJPEG HTTP (port 8080)."),
        ("brain_node.py",      "Node d'autonomia i planificació de ruta."),
        ("rosbridge_boot.sh",  "Script d'arrencada (systemd ExecStart)."),
    ], col_w=[4.0*cm, 12.5*cm]),
    SP(8),

    P("<b>Comandes d'instal·lació (terminal de la Pi):</b>", h3),
    P("# ── Dependències Python ────────────────────────────────────────────────", code),
    P("pip3 install --break-system-packages pymavlink pyzbar opencv-python", code),
    P("sudo apt install -y libzbar0", code),
    SP(4),
    P("# ── Permisos i scripts d'arrencada ────────────────────────────────────", code),
    P("chmod +x ~/slam_launch.sh ~/rosbridge_boot.sh", code),
    SP(4),
    P("# ── Servei systemd (arrencada automàtica en cada boot) ─────────────────", code),
    P("sudo cp ~/drone-gcs/raspberry/rosbridge.service /etc/systemd/system/", code),
    P("sudo systemctl daemon-reload", code),
    P("sudo systemctl enable rosbridge", code),
    P("sudo systemctl start  rosbridge", code),
    SP(4),
    P("# ── Permís sudo per configurar interfície de xarxa (requerit per SLAM) ─", code),
    P("sudo visudo    # afegir al final:", code),
    P("raspi5 ALL=(ALL) NOPASSWD: /sbin/ip", code),
    SP(6),
    note_box("Un cop configurat, el servei rosbridge s'inicia automàticament a cada "
             "arrencada. Comprovació: sudo systemctl status rosbridge"),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 3. CONNEXIÓ
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("3", "Connexió i Interfície Principal"),
    P("""La <b>barra superior (topbar)</b> és visible en totes les pestanyes.
       Conté la navegació, l'indicador de connexió ROS i els indicadors clau del drone.""",
      body),
    SP(8),

    P("Indicadors de la topbar", h2),
    feature_table([
        ("Punt de connexió",
         "Verd = connectat · Groc parpellejant = connectant · Vermell = desconnectat."),
        ("URL rosbridge",
         "Mostra la URL activa. Clicar per obrir el panell de connexió manual."),
        ("ARMED / DISARMED",
         "Estat d'armament. El badge parpelleja en vermell quan el drone és armat."),
        ("Mode de vol",
         "Mode actiu: GUIDED, LOITER, AUTO, STABILIZE, RTL, LAND..."),
        ("GPS",
         "3D FIX (≥6 sats) · 2D FIX (3–5 sats) · NO GPS (<3 sats o no fix)."),
    ]),
    SP(10),

    P("Popover de connexió", h2),
    P("""Accessible clicant la URL a la topbar. Permet canviar la destinació del
       rosbridge sense reiniciar l'aplicació:""", body),
    SP(4),
    B("Introduir manualment una URL (ex: ws://172.20.10.2:9090) i prémer <b>Connect</b>."),
    B("<b>Scan network:</b> escaneig automàtic del /24 buscant ports 9090 oberts. "
      "Primer prova mDNS (raspi5.local), després IPs del subnet."),
    B("Seleccionar qualsevol host trobat amb el botó <b>Use</b> per connectar directament."),
    SP(4),
    note_box("La URL es guarda a localStorage i es recupera automàticament en sessions futures."),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 4. DASHBOARD
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("4", "Dashboard"),
    P("""La pestanya principal. Mostra una visió global del drone: comandes de vol,
       bateria, càmera en directe, diagrama de motors i mapa de navegació.""", body),
    SP(8),

    P("4.1  Panell de Comandes", h2),
    P("""Ubicat a la columna esquerra. Ocupa tot l'espai vertical disponible per
       ser fàcilment accessible en tot moment.""", body),
    SP(4),
    feature_table([
        ("ARM",
         "Armar el drone. Requereix <b>doble clic en menys de 0,8 s</b> com a confirmació."),
        ("DISARM",
         "Desarmar. Un sol clic. Sempre disponible (inclòs en vol)."),
        ("GUIDED / LOITER / AUTO / STAB",
         "Canvi de mode de vol. El botó del mode actiu s'il·lumina en blau."),
        ("TAKEOFF",
         "Decollatge a l'altitud indicada al camp <i>Alt (m)</i> (per defecte 5 m)."),
        ("LAND",
         "Aterratge vertical en la posició horitzontal actual."),
        ("RTL",
         "Return To Launch — retorn autònom al punt de decollatge."),
        ("Log de comandes",
         "Les darreres 25 comandes enviades amb el resultat (SENT / OK / FAIL) "
         "i l'hora."),
    ]),
    SP(10),

    P("4.2  Bateria i Estat", h2),
    feature_table([
        ("Gauge circular",
         "Arc de 270° mostrant el % de bateria. Verd >50% · Taronja 20–50% · Vermell <20%. "
         "El voltatge apareix al centre."),
        ("Badge ARMED",
         "Indicador d'armament a la topbar. Parpelleja en vermell quan armat."),
        ("Badge mode",
         "Mode de vol actual en blau clar."),
    ]),
    SP(10),

    P("4.3  Serveis de la Pi", h2),
    P("""Botons d'inici/aturada per a cada servei de la Raspberry Pi. El punt de color
       indica l'estat: verd = actiu, gris = aturat.""", body),
    SP(4),
    service_table([
        ("SLAM",
         "Inicia el LiDAR Unitree L2 i Point-LIO. Configura eth1 automàticament.",
         "slam_launch.sh"),
        ("Camera",
         "Publicador de càmera (/dev/video0) i servidor MJPEG (port 8080).",
         "camera_publisher.py"),
        ("MAVROS",
         "Bridge pymavlink — connecta el Pixhawk via /dev/ttyAMA0 (57600 baud).",
         "mavlink_bridge.py"),
        ("Brain",
         "Node d'autonomia: planificació de missió i waypoints.",
         "brain_node.py"),
    ]),
    SP(10),

    P("4.4  Càmera (Cam 1 — Forward)", h2),
    P("""Feed de vídeo en directe de la càmera frontal. S'actualitza via compressió
       JPEG per ROS2 (/camera/forward/image_raw/compressed) o per MJPEG HTTP si el
       servei MJPEG està actiu (port 8080). Indicador LIVE / NO SIGNAL a la cantonada
       superior esquerra.""", body),
    SP(10),

    P("4.5  Diagrama de Motors (Hexacòpter)", h2),
    P("""Visualització en temps real del thrust de cada motor (M1–M6) en forma de
       gauge rotatori individual:""", body),
    SP(4),
    B("Arc de progrés del 0% al 100% de thrust."),
    B("Color dinàmic: verd <30% · taronja 30–70% · vermell >70%."),
    B("Anell indicador CW/CCW (blau = sentit antihorari, verd = horari)."),
    B("Valor PWM en microsegons (1000–2000 µs) al peu de cada gauge."),
    SP(10),

    P("4.6  Mapa de Navegació", h2),
    P("""Mapa 2D en temps real (Leaflet + OpenStreetMap) que mostra la posició
       i trajectòria del drone. S'actualitza automàticament amb GPS, SLAM o ambdós.""",
      body),
    SP(4),
    feature_table([
        ("Mode GPS",
         "Trajectòria real en blau, posició centrada. Radi visible ~200 m."),
        ("Mode SLAM",
         "Trajectòria en el marc local (metres), escala de 5 m. Sense GPS."),
        ("Mode híbrid",
         "Fusió GPS + SLAM quan ambdós estan actius i s'ha capturat l'origen GPS."),
        ("Missió",
         "Waypoints de la missió en taronja (actiu) o verd (completat). "
         "Línia discontínua de connexió."),
        ("Punt d'origen",
         "Creu verda al punt on el drone estava en arrencar (home position)."),
        ("Agulla de rumb",
         "Línia taronja des del centre indicant el heading actual."),
    ]),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 5. NAVIGATION
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("5", "Navigation"),
    P("""Pestanya dedicada a la telemetria de vol detallada. Dividida en instruments
       de vol i gràfiques d'historial en temps real.""", body),
    SP(8),

    P("5.1  Instruments de Vol", h2),
    feature_table([
        ("Artificial Horizon",
         "Indicador d'actitud amb roll i pitch en temps real. "
         "Cel blau, terra marró, escala de graus."),
        ("Compass",
         "Rosa dels vents amb agulla de heading. Nord en vermell. "
         "Angle numèric al centre."),
        ("Flight Data",
         "Taula completa: airspeed (m/s), velocitat vertical (m/s), altitud (m), "
         "heading (°), roll/pitch/yaw (°), velocitats Vx/Vy/Vz, satèl·lits GPS, "
         "fix type, lat/lon, armat, mode, cronometre de vol."),
    ]),
    SP(10),

    P("5.2  Gràfiques d'Historial", h2),
    P("""Cada gràfica acumula els darrers <b>120 punts</b> (últims ~2 min a 1 Hz).
       El valor actual s'imprimeix a la cantonada superior dreta.""", body),
    SP(4),
    feature_table([
        ("Altitude (m)",          "Historial d'altitud relativa. Línia blava."),
        ("Airspeed (m/s)",        "Historial de velocitat aèria. Línia verda."),
        ("Vertical Speed (m/s)",  "Historial de velocitat vertical. Línia taronja. "
                                  "Negatiu = baixada."),
    ]),
    SP(10),

    P("5.3  Go To / Setpoint", h2),
    P("""Secció al peu del panell Flight Data per enviar comandes de posició
       o velocitat en el marc local del drone:""", body),
    SP(4),
    feature_table([
        ("Camps X, Y, Z (m)", "Posició objectiu en el marc de referència local."),
        ("Send Setpoint",     "Envia la posició via /drone/cmd {action: goto, x, y, z}."),
        ("Stop (vel=0)",      "Publica velocitat zero per aturar el moviment."),
        ("Hold Pos",          "Canvia a mode LOITER per mantenir la posició actual."),
    ]),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 6. SLAM
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("6", "SLAM"),
    P("""Visualitzador 3D del núvol de punts generat per <b>Point-LIO</b> amb el
       LiDAR <b>Unitree L2</b>. Renderitzat per WebGL directament al navegador
       Chromium d'Electron, sense cap dependència externa ni servidor de visualització.""",
      body),
    SP(8),

    P("6.1  Visor 3D WebGL", h2),
    P("""El visor acumula fins a <b>800.000 punts</b> en un ring buffer i els
       renderitza amb coloració en arc de Sant Martí per coordenada Z
       (blau = baix, verd = mig, vermell = alt).""", body),
    SP(4),
    feature_table([
        ("Rotació de càmera",  "Arrossegar amb el botó esquerre del ratolí."),
        ("Desplaçament",       "Arrossegar amb el botó dret del ratolí."),
        ("Zoom",               "Roda del ratolí."),
        ("Actualització",      "Punts nous s'afegeixen en temps real des de "
                               "/cloud_registered (sensor_msgs/PointCloud2)."),
        ("Ring buffer",        "800k punts (~11 min a 1.200 pts/s). "
                               "Els punts més antics s'eliminen automàticament."),
    ]),
    SP(10),

    P("6.2  Panell d'Estat SLAM", h2),
    feature_table([
        ("Status",        "Active (verd) quan arriben dades de /cloud_registered."),
        ("Pose X / Y",    "Posició actual del drone en el marc local SLAM (metres), "
                          "extreta de /Odometry o del TF camera_init → aft_mapped."),
        ("Orientation",   "Angle de guinyada (yaw) en graus."),
        ("Points/scan",   "Nombre total de punts acumulats al visor."),
        ("TF frames",     "camera_init (origen fix) · aft_mapped (pose actual)."),
    ]),
    SP(10),

    P("6.3  Controls SLAM", h2),
    feature_table([
        ("Start / Pause", "Activa o pausa el SLAM Toolbox (si instal·lat al sistema)."),
        ("Save Map",      "Desa el mapa actual (/slam_toolbox/save_map service call)."),
        ("Reset Pose",    "Reinicia la pose estimada al valor zero."),
        ("Clear Map",     "Esborra el núvol de punts del visor 3D (memòria local del client, "
                          "no afecta la Pi)."),
    ]),
    SP(6),
    note_box("El LiDAR ha d'estar connectat per Ethernet a la Pi. El servei SLAM configura "
             "automàticament la IP 192.168.1.2/24 a eth1 i espera confirmació ping al LiDAR "
             "(192.168.1.62) abans de llançar Point-LIO."),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 7. IMAGE PROCESSING
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("7", "Image Processing  —  Detecció de Codis"),
    P("""Pestanya per a la detecció automàtica de codis de barres i QR en temps real,
       construcció d'un inventari georeferit amb posició SLAM i exportació a CSV / Excel.""",
      body),
    SP(8),

    P("7.1  Feed de Càmera amb ROI", h2),
    P("""La part central mostra el feed de la càmera frontal <b>anotat en temps real</b>
       pel node barcode_detector.py de la Pi. El node publica les imatges processades
       al tòpic /barcode/roi/image/compressed. Quan es detecta un codi:""", body),
    SP(4),
    B("Es dibuixa un <b>polígon verd</b> al voltant del codi detectat."),
    B("El text del codi apareix en un label sobre el polígon."),
    B("A la cantonada superior esquerra es mostra la <b>posició SLAM actual</b> "
      "(x, y, θ en temps real)."),
    SP(4),
    note_box("Requereix que el servei Codis estigui actiu. El botó Start/Stop es troba "
             "al panell lateral dret d'aquesta mateixa pestanya."),
    SP(6),

    P("7.2  Inventari — Taula de Deteccions", h2),
    P("""La taula s'actualitza automàticament amb cada detecció nova. "
       Emmagatzema fins a les darreres 100 entrades:""", body),
    SP(4),
    feature_table([
        ("Hora",      "Hora de la detecció (format HH:MM:SS)."),
        ("Codi",      "Contingut del codi de barres o QR llegit per pyzbar."),
        ("Producte",  "Identificador del producte (igual al Codi per defecte)."),
        ("Posició",   "Coordenades SLAM en el moment de la detecció (x, y en metres). "
                      "Mostra '—' si el SLAM no està actiu."),
    ]),
    SP(6),
    note_box("La deduplicació evita registrar el mateix codi més d'una vegada en una "
             "finestra de 3 segons, evitant entrades duplicades per frames consecutius."),
    SP(8),

    P("7.3  Log de Base de Dades", h2),
    P("""El panell inferior dret mostra un log en viu de totes les deteccions
       (fins a 60 entrades) amb format <b>[hora]  DB INSERT → [codi]  [OK]</b>.
       Útil per verificar que les deteccions s'estan processant correctament.""", body),
    SP(8),

    P("7.4  Exportació CSV / Excel", h2),
    P("""El botó <b>Exportar CSV / Excel</b> al panell lateral genera i descarrega
       automàticament un arxiu .csv amb totes les deteccions acumulades durant la sessió.""",
      body),
    SP(4),
    feature_table([
        ("Format",    "CSV amb separador coma, codificació UTF-8 BOM "
                      "(compatible amb Microsoft Excel per doble clic directe)."),
        ("Columnes",  "Hora  ·  Codi  ·  Producte  ·  Posicio X (m)  ·  Posicio Y (m)  ·  Estat"),
        ("Nom arxiu", "inventari_YYYY-MM-DD_HH-MM-SS.csv"),
        ("Obertura",  "Doble clic al fitxer l'obre directament a Microsoft Excel."),
    ]),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 8. SERVEIS RASPBERRY PI
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("8", "Serveis de la Raspberry Pi"),
    P("""Tots els serveis es gestionen des del Dashboard (panell Services) o des de
       la pestanya Image Processing (servei Codis). El node <b>gcs_control.py</b>
       s'inicia automàticament amb el sistema i gestiona el cicle de vida dels
       altres serveis.""", body),
    SP(8),

    P("gcs_control.py — Gestor de Serveis (sempre actiu)", h2),
    feature_table([
        ("Subscripció",
         "/gcs/cmd (std_msgs/String) — rep {action: start|stop, service: nom}."),
        ("Publicació",
         "/gcs/status (std_msgs/String) — JSON amb l'estat de cada servei cada segon."),
        ("Logs",
         "~/gcs_logs/[servei].log — stdout + stderr de cada procés fill."),
        ("Process groups",
         "Cada servei s'inicia amb os.setsid() per poder matar tot el grup de "
         "processos (kill -SIGTERM al grup) de forma neta."),
    ], col_w=[3.5*cm, 13.0*cm]),
    SP(10),

    P("Descripció detallada de cada servei", h2),
    service_table([
        ("SLAM",
         "Configura eth1 (IP 192.168.1.2/24), espera ping al LiDAR (192.168.1.62), "
         "inicia unitree_lidar_ros2, espera el topic /unilidar/... i finalment "
         "llança point_lio (mapping_unilidar_l2.launch.py rviz:=false).",
         "slam_launch.sh"),
        ("Camera",
         "Publica el feed de /dev/video0 com a imatge JPEG comprimida a "
         "/camera/forward/image_raw/compressed (640×480, 30fps, JPEG 80). "
         "Inicia també el servidor MJPEG al port 8080.",
         "camera_publisher.py\nmjpeg_server.py"),
        ("MAVROS",
         "Bridge pymavlink. Connecta al Pixhawk per /dev/ttyAMA0 a 57600 baud. "
         "Publica: /drone/vfr, /drone/state, /drone/motors, /drone/gps_status, "
         "/mavros/battery, /mavros/imu/data, /mavros/global_position/global. "
         "Rep comandes de /drone/cmd.",
         "mavlink_bridge.py"),
        ("Brain",
         "Node d'autonomia. Gestiona la planificació de missió, waypoints "
         "i la lògica de vol autònom.",
         "brain_node.py"),
        ("Codis",
         "Detector de codis de barres i QR. Rep imatges de "
         "/camera/forward/image_raw/compressed, aplica pyzbar per detectar codis, "
         "dibuixa ROI en verd, publica la imatge anotada a "
         "/barcode/roi/image/compressed i les deteccions JSON a /barcode/detection.",
         "barcode_detector.py"),
    ]),
    SP(10),

    P("Consulta de logs en directe", h2),
    P("Des de la Pi, per seguir el log de cada servei en temps real:", body),
    P("tail -f ~/gcs_logs/slam.log", code),
    P("tail -f ~/gcs_logs/mavros.log", code),
    P("tail -f ~/gcs_logs/barcode.log", code),
    SP(4),
    P("Per veure els logs del servei systemd principal (rosbridge + gcs_control):", body),
    P("journalctl -u rosbridge -f", code),
    SP(4),
    note_box("Si un servei no arrenca, revisar el log corresponent a ~/gcs_logs/. "
             "Errors comuns: dispositiu /dev/ttyAMA0 no accessible (MAVROS), "
             "eth1 no disponible (SLAM), libzbar0 no instal·lat (Codis)."),
    PageBreak(),
]

# ──────────────────────────────────────────────────────────────────────────────
# 9. TOPICS ROS2
# ──────────────────────────────────────────────────────────────────────────────
story += [
    *section_header("9", "Referència Tòpics ROS2"),
    P("""Tots els tòpics que la GCS subscriu o publica a través del rosbridge WebSocket.
       S'utilitzen exclusivament tipus de missatge estàndard (sense mavros_msgs).""", body),
    SP(8),

    P("9.1  Telemetria — subscripcions des del PC", h2),
    topic_table([
        ("/drone/vfr",
         "std_msgs/String",
         "JSON: airspeed, groundspeed, heading (°), alt (m), climb (m/s)"),
        ("/drone/state",
         "std_msgs/String",
         "JSON: armed (bool), mode (str), connected (bool)"),
        ("/drone/motors",
         "std_msgs/String",
         "JSON: channels [pwm1..pwm8] (1000–2000 µs)"),
        ("/drone/gps_status",
         "std_msgs/String",
         "JSON: fix_type (0–6), satellites_visible"),
        ("/mavros/battery",
         "sensor_msgs/BatteryState",
         "Voltatge (V), corrent (A), percentatge (0–1)"),
        ("/mavros/imu/data",
         "sensor_msgs/Imu",
         "Quaternió orientació, velocitat angular, acceleració lineal"),
        ("/mavros/global_position/global",
         "sensor_msgs/NavSatFix",
         "Latitud, longitud, altitud absoluta (m)"),
        ("/mavros/local_position/velocity_body",
         "geometry_msgs/TwistStamped",
         "Velocitat corporal Vx/Vy/Vz (m/s)"),
        ("/gcs/status",
         "std_msgs/String",
         "JSON: {slam, camera, mavros, brain, barcode} → running|stopped"),
        ("/cloud_registered",
         "sensor_msgs/PointCloud2",
         "Núvol de punts registrat per Point-LIO (SLAM)"),
        ("/Odometry",
         "nav_msgs/Odometry",
         "Pose SLAM: posició + orientació en marc camera_init"),
        ("/tf",
         "tf2_msgs/TFMessage",
         "Transformació camera_init → aft_mapped (fallback pose)"),
        ("/barcode/roi/image/compressed",
         "sensor_msgs/CompressedImage",
         "Feed càmera anotat amb ROI de codis (JPEG, 4 fps)"),
        ("/barcode/detection",
         "std_msgs/String",
         "JSON: {barcode, code, status, slam_x, slam_y, slam_theta}"),
        ("/brain/planned_path",
         "std_msgs/String",
         "JSON: {waypoints:[], wp_index, mission}"),
    ]),
    SP(10),

    P("9.2  Comandes — publicacions des del PC", h2),
    topic_table([
        ("/drone/cmd",
         "std_msgs/String",
         "JSON: acció de vol (arm, disarm, mode, takeoff, land, goto, vel_stop)"),
        ("/gcs/cmd",
         "std_msgs/String",
         "JSON: {action: start|stop, service: slam|camera|mavros|brain|barcode}"),
    ]),
    SP(10),

    P("9.3  Exemples de comandes (/drone/cmd)", h2),
    cmd_table([
        ("arm",        '{"action": "arm"}'),
        ("disarm",     '{"action": "disarm"}'),
        ("mode",       '{"action": "mode", "mode": "GUIDED"}'),
        ("takeoff",    '{"action": "takeoff", "alt": 5.0}'),
        ("land",       '{"action": "land"}'),
        ("goto",       '{"action": "goto", "x": 2.0, "y": 1.0, "z": 5.0}'),
        ("vel_stop",   '{"action": "vel_stop"}'),
    ]),
    SP(10),

    P("9.4  Modes de vol disponibles (ArduCopter)", h2),
    feature_table([
        ("Manual",     "STABILIZE · ACRO · SPORT · DRIFT"),
        ("Assistit",   "ALT_HOLD · LOITER · POSHOLD · BRAKE"),
        ("Autònom",    "AUTO · GUIDED · RTL · CIRCLE · LAND"),
        ("Avançat",    "FLOWHOLD · FOLLOW · ZIGZAG · SYSTEMID · AUTOTUNE"),
    ], col_w=[3.5*cm, 13.0*cm]),
]

# ── Compile ────────────────────────────────────────────────────────────────────
doc.build(story, onFirstPage=on_first_page, onLaterPages=on_page)
print(f"PDF generat: {OUT}")
