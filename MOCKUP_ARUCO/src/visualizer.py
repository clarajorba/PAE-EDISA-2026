"""
visualizer.py
-------------
Visualización en tiempo real del almacén y la posición del dron.

Panel izquierdo  : frame de la cámara con marcadores anotados.
Panel derecho    : planta 2-D del almacén con la posición estimada del dron,
                   historial de trayectoria y HUD de telemetría.
"""

import cv2
import numpy as np
from typing import Optional, List, Tuple
import time

from .localization import DronePose
from .warehouse_map import WarehouseMap


# ─────────────────────────────────────────────────────────────────────────────
# Paleta de colores (BGR)
# ─────────────────────────────────────────────────────────────────────────────
COLOR_BG         = (20,  20,  20)
COLOR_WALL       = (160, 160, 160)
COLOR_GRID       = (45,  45,  45)
COLOR_MARKER_OK  = (0,   220, 80)
COLOR_MARKER_UNK = (0,   100, 220)
COLOR_DRONE      = (0,   210, 255)
COLOR_DRONE_DIR  = (255, 200, 0)
COLOR_TRAIL      = (80,  130, 255)
COLOR_HUD_OK     = (50,  230, 80)
COLOR_HUD_WARN   = (0,   160, 255)
COLOR_HUD_ERR    = (60,  60,  255)
COLOR_TEXT       = (220, 220, 220)
COLOR_TITLE      = (255, 215, 0)


class WarehouseVisualizer:
    """
    Genera el frame de visualización combinando la vista de cámara (izquierda)
    con el mapa cenital del almacén (derecha).

    Parameters
    ----------
    warehouse_map : mapa del almacén
    map_px        : tamaño del canvas del mapa en píxeles (lado largo)
    cam_width     : ancho del frame de cámara esperado
    cam_height    : alto  del frame de cámara esperado
    trail_length  : número máximo de puntos de trayectoria a mostrar
    """

    def __init__(
        self,
        warehouse_map: WarehouseMap,
        map_px: int = 600,
        cam_width: int = 1280,
        cam_height: int = 720,
        trail_length: int = 120,
    ):
        self.wmap         = warehouse_map
        self.trail_length = trail_length

        # ── Escala píxel/metro ───────────────────────────────────────────
        pad = 40
        scale_x = (map_px - 2 * pad) / warehouse_map.width_m
        scale_y = (map_px - 2 * pad) / warehouse_map.height_m
        self.scale      = min(scale_x, scale_y)
        self.map_width  = int(warehouse_map.width_m  * self.scale + 2 * pad)
        self.map_height = int(warehouse_map.height_m * self.scale + 2 * pad)
        self.pad        = pad

        # ── Altura del canvas de cámara ─────────────────────────────────
        self.cam_w = cam_width
        self.cam_h = cam_height

        # ── Trayectoria y estado ────────────────────────────────────────
        self._trail: List[Tuple[int, int]] = []
        self._fps_buffer: List[float] = []
        self._t_prev = time.time()

        # Pre-renderizar mapa estático
        self._base_map = self._render_base_map()

    # ── Coordinadas mundo → píxeles ────────────────────────────────────────

    def world_to_px(self, x: float, y: float) -> Tuple[int, int]:
        px = int(x * self.scale + self.pad)
        py = int(y * self.scale + self.pad)
        return px, py

    # ── Render principal ───────────────────────────────────────────────────

    def render(
        self,
        camera_frame: np.ndarray,
        pose: Optional[DronePose],
        detected_ids: List[int],
    ) -> np.ndarray:
        """
        Genera el frame compuesto.

        Parameters
        ----------
        camera_frame  : imagen BGR de la cámara (ya anotada con marcadores)
        pose          : pose estimada del dron (puede ser None)
        detected_ids  : IDs de marcadores visibles en este frame

        Returns
        -------
        frame combinado listo para cv2.imshow
        """
        # ── FPS ─────────────────────────────────────────────────────────
        now = time.time()
        dt  = now - self._t_prev
        self._t_prev = now
        self._fps_buffer.append(1.0 / max(dt, 0.001))
        if len(self._fps_buffer) > 30:
            self._fps_buffer.pop(0)
        fps = np.mean(self._fps_buffer)

        # ── Mapa dinámico ───────────────────────────────────────────────
        map_canvas = self._render_dynamic_map(pose, detected_ids)

        # ── Escalar frame de cámara al alto del mapa ────────────────────
        target_h = self.map_height
        cam_scaled_w = int(camera_frame.shape[1] * target_h / camera_frame.shape[0])
        cam_scaled   = cv2.resize(camera_frame, (cam_scaled_w, target_h))

        # ── HUD en el frame de cámara ───────────────────────────────────
        cam_scaled = self._draw_camera_hud(cam_scaled, pose, fps, detected_ids)

        # ── Combinar horizontalmente ────────────────────────────────────
        combined = np.hstack([cam_scaled, map_canvas])
        return combined

    # ── Mapa base (estático) ───────────────────────────────────────────────

    def _render_base_map(self) -> np.ndarray:
        """Dibuja las paredes, rejilla y marcadores del almacén."""
        canvas = np.full((self.map_height, self.map_width, 3), COLOR_BG, dtype=np.uint8)

        # Grid cada 5 m
        step_m = 5.0
        x = step_m
        while x < self.wmap.width_m:
            px, _ = self.world_to_px(x, 0)
            cv2.line(canvas, (px, self.pad), (px, self.map_height - self.pad), COLOR_GRID, 1)
            cv2.putText(canvas, f"{x:.0f}m", (px - 10, self.map_height - 5),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_GRID, 1)
            x += step_m
        y = step_m
        while y < self.wmap.height_m:
            _, py = self.world_to_px(0, y)
            cv2.line(canvas, (self.pad, py), (self.map_width - self.pad, py), COLOR_GRID, 1)
            cv2.putText(canvas, f"{y:.0f}m", (2, py + 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, COLOR_GRID, 1)
            y += step_m

        # Paredes
        tl = self.world_to_px(0, 0)
        br = self.world_to_px(self.wmap.width_m, self.wmap.height_m)
        cv2.rectangle(canvas, tl, br, COLOR_WALL, 2)

        # Título
        cv2.putText(canvas, self.wmap.name, (self.pad, 22),
                    cv2.FONT_HERSHEY_DUPLEX, 0.6, COLOR_TITLE, 1, cv2.LINE_AA)

        # Marcadores conocidos
        for wm in self.wmap.all_markers():
            px, py = self.world_to_px(wm.position[0], wm.position[1])
            cv2.circle(canvas, (px, py), 6, COLOR_MARKER_OK, -1)
            cv2.putText(canvas, str(wm.marker_id), (px + 7, py - 4),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_MARKER_OK, 1, cv2.LINE_AA)

        # Ejes N/S/E/O
        cv2.putText(canvas, "N", (self.map_width // 2 - 5, 14),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT, 1)
        cv2.putText(canvas, "S", (self.map_width // 2 - 5, self.map_height - 4),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT, 1)
        cv2.putText(canvas, "E", (self.map_width - 10, self.map_height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT, 1)
        cv2.putText(canvas, "O", (2, self.map_height // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.4, COLOR_TEXT, 1)
        return canvas

    # ── Mapa dinámico (por frame) ──────────────────────────────────────────

    def _render_dynamic_map(
        self,
        pose: Optional[DronePose],
        detected_ids: List[int],
    ) -> np.ndarray:
        canvas = self._base_map.copy()

        # Resaltar marcadores detectados
        for mid in detected_ids:
            wm = self.wmap.get_marker(mid)
            if wm:
                px, py = self.world_to_px(wm.position[0], wm.position[1])
                cv2.circle(canvas, (px, py), 10, COLOR_DRONE, 2)

        if pose is None:
            self._draw_no_signal(canvas)
            return canvas

        # Trayectoria
        drone_px = self.world_to_px(pose.x, pose.y)
        self._trail.append(drone_px)
        if len(self._trail) > self.trail_length:
            self._trail.pop(0)

        for i in range(1, len(self._trail)):
            alpha = i / len(self._trail)
            color = tuple(int(c * alpha) for c in COLOR_TRAIL)
            cv2.line(canvas, self._trail[i - 1], self._trail[i], color, 2)

        # Dron: círculo + flecha de orientación (yaw)
        cx, cy = drone_px
        cv2.circle(canvas, (cx, cy), 12, COLOR_DRONE, -1)
        cv2.circle(canvas, (cx, cy), 12, (255, 255, 255), 1)

        # Flecha de yaw
        yaw_rad = np.radians(pose.yaw_deg)
        arrow_len = 22
        ex = int(cx + arrow_len * np.sin(yaw_rad))
        ey = int(cy - arrow_len * np.cos(yaw_rad))
        cv2.arrowedLine(canvas, (cx, cy), (ex, ey), COLOR_DRONE_DIR, 2, tipLength=0.4)

        # Etiqueta de posición
        label = f"({pose.x:.1f},{pose.y:.1f},{pose.z:.1f})m"
        cv2.putText(canvas, label, (cx + 15, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.42, COLOR_TEXT, 1, cv2.LINE_AA)

        # Barra de confianza
        self._draw_confidence_bar(canvas, pose.confidence)

        return canvas

    # ── HUD en la imagen de cámara ─────────────────────────────────────────

    def _draw_camera_hud(
        self,
        frame: np.ndarray,
        pose: Optional[DronePose],
        fps: float,
        detected_ids: List[int],
    ) -> np.ndarray:
        h, w = frame.shape[:2]
        overlay = frame.copy()

        # Fondo semitransparente superior
        cv2.rectangle(overlay, (0, 0), (w, 85), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.55, frame, 0.45, 0, frame)

        # FPS
        fps_color = COLOR_HUD_OK if fps >= 20 else COLOR_HUD_WARN
        cv2.putText(frame, f"FPS: {fps:.0f}", (10, 22),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.65, fps_color, 2, cv2.LINE_AA)

        # Marcadores detectados
        ids_str = f"Marcadores: {detected_ids}" if detected_ids else "Marcadores: ninguno"
        cv2.putText(frame, ids_str, (10, 48),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, COLOR_TEXT, 1, cv2.LINE_AA)

        if pose is None:
            cv2.putText(frame, "⚠ SIN LOCALIZACION", (10, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.65, COLOR_HUD_ERR, 2, cv2.LINE_AA)
        else:
            roll, pitch, yaw = pose.euler_deg
            pos_str = (f"Pos: X={pose.x:.2f}m  Y={pose.y:.2f}m  Z={pose.z:.2f}m  "
                       f"Yaw={yaw:.1f}°  Conf:{pose.confidence:.2f}")
            col = COLOR_HUD_OK if pose.confidence > 0.5 else COLOR_HUD_WARN
            cv2.putText(frame, pos_str, (10, 75),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, col, 1, cv2.LINE_AA)

        return frame

    # ── Auxiliares ────────────────────────────────────────────────────────

    def _draw_no_signal(self, canvas: np.ndarray):
        h, w = canvas.shape[:2]
        cv2.putText(canvas, "BUSCANDO MARCADORES...", (w // 2 - 110, h // 2),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, COLOR_HUD_ERR, 2, cv2.LINE_AA)

    def _draw_confidence_bar(self, canvas: np.ndarray, confidence: float):
        h, w = canvas.shape[:2]
        bar_x, bar_y = self.pad, h - 18
        bar_w = self.map_width - 2 * self.pad
        cv2.rectangle(canvas, (bar_x, bar_y), (bar_x + bar_w, bar_y + 8), (50, 50, 50), -1)
        filled = int(bar_w * confidence)
        color  = COLOR_HUD_OK if confidence > 0.6 else COLOR_HUD_WARN if confidence > 0.3 else COLOR_HUD_ERR
        cv2.rectangle(canvas, (bar_x, bar_y), (bar_x + filled, bar_y + 8), color, -1)
        cv2.putText(canvas, f"Confianza: {confidence*100:.0f}%",
                    (bar_x, bar_y - 3), cv2.FONT_HERSHEY_SIMPLEX, 0.38, COLOR_TEXT, 1)

    def reset_trail(self):
        """Borra la trayectoria histórica."""
        self._trail.clear()
