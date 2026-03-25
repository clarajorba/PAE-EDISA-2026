from __future__ import annotations

import cv2
import numpy as np

from ..core.models import MarkerLayout


BACKGROUND = (10, 14, 28)
CARD = (18, 24, 42)
CARD_ALT = (24, 31, 54)
TEXT_PRIMARY = (232, 238, 255)
TEXT_MUTED = (140, 164, 210)
ACCENT = (92, 220, 255)
SUCCESS = (64, 220, 120)
WARNING = (0, 190, 255)
ERROR = (88, 96, 255)


def _fit_image(image: np.ndarray, width: int, height: int) -> np.ndarray:
    h, w = image.shape[:2]
    scale = min(width / max(w, 1), height / max(h, 1))
    new_size = (max(1, int(w * scale)), max(1, int(h * scale)))
    return cv2.resize(image, new_size, interpolation=cv2.INTER_AREA)


def _draw_title(canvas: np.ndarray, text: str, subtitle: str | None = None) -> None:
    cv2.putText(
        canvas,
        text,
        (24, 34),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.9,
        TEXT_PRIMARY,
        2,
        cv2.LINE_AA,
    )
    if subtitle:
        cv2.putText(
            canvas,
            subtitle,
            (26, 58),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            TEXT_MUTED,
            1,
            cv2.LINE_AA,
        )


def render_topdown_panel(
    layout: MarkerLayout,
    expected_position: np.ndarray | None = None,
    current_position: np.ndarray | None = None,
    highlighted_ids: list[int] | None = None,
    title: str = "Plano cenital del test",
    size: tuple[int, int] = (520, 360),
) -> np.ndarray:
    """Dibuja un plano cenital simple con marcadores y posicion esperada."""
    width, height = size
    panel = np.full((height, width, 3), CARD, dtype=np.uint8)
    cv2.rectangle(panel, (0, 0), (width - 1, height - 1), CARD_ALT, 1)
    cv2.putText(
        panel,
        title,
        (18, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        TEXT_PRIMARY,
        2,
        cv2.LINE_AA,
    )

    points = [marker.position[:2] for marker in layout.markers.values()]
    if expected_position is not None:
        points.append(expected_position[:2])
    if current_position is not None:
        points.append(current_position[:2])
    coords = np.vstack(points)

    pad = 48
    min_xy = coords.min(axis=0)
    max_xy = coords.max(axis=0)
    span = np.maximum(max_xy - min_xy, np.array([0.6, 0.6], dtype=np.float64))
    min_xy = min_xy - span * 0.15
    max_xy = max_xy + span * 0.15
    span = max_xy - min_xy

    usable_w = width - pad * 2
    usable_h = height - pad * 2 - 22
    scale = min(usable_w / span[0], usable_h / span[1])

    def world_to_px(x: float, y: float) -> tuple[int, int]:
        px = int(pad + (x - min_xy[0]) * scale)
        py = int(height - pad - (y - min_xy[1]) * scale)
        return px, py

    cv2.line(panel, (pad, height - pad), (width - pad, height - pad), (50, 72, 118), 1)
    cv2.line(panel, (pad, height - pad), (pad, pad + 18), (50, 72, 118), 1)
    cv2.putText(panel, "X", (width - pad - 18, height - pad - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.48, TEXT_MUTED, 1)
    cv2.putText(panel, "Y", (pad + 10, pad + 16), cv2.FONT_HERSHEY_SIMPLEX, 0.48, TEXT_MUTED, 1)

    highlighted = set(highlighted_ids or [])
    marker_size_px = max(18, int(layout.marker_size_m * scale))
    for marker_id, marker in sorted(layout.markers.items()):
        px, py = world_to_px(marker.position[0], marker.position[1])
        color = SUCCESS if marker_id in highlighted else (70, 110, 190)
        cv2.rectangle(
            panel,
            (px - marker_size_px // 2, py - marker_size_px // 2),
            (px + marker_size_px // 2, py + marker_size_px // 2),
            color,
            -1,
        )
        cv2.rectangle(
            panel,
            (px - marker_size_px // 2, py - marker_size_px // 2),
            (px + marker_size_px // 2, py + marker_size_px // 2),
            (255, 255, 255),
            1,
        )
        cv2.putText(
            panel,
            str(marker_id),
            (px - 18, py - marker_size_px // 2 - 8),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.45,
            TEXT_PRIMARY,
            1,
            cv2.LINE_AA,
        )

    if expected_position is not None:
        ex, ey = world_to_px(expected_position[0], expected_position[1])
        cv2.rectangle(panel, (ex - 18, ey - 12), (ex + 18, ey + 12), WARNING, 2)
        cv2.circle(panel, (ex, ey), 4, WARNING, -1)
        cv2.putText(
            panel,
            f"Esperado z={expected_position[2]:.2f} m",
            (ex - 42, ey - 20),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            WARNING,
            1,
            cv2.LINE_AA,
        )

    if current_position is not None:
        cx, cy = world_to_px(current_position[0], current_position[1])
        cv2.circle(panel, (cx, cy), 8, ACCENT, -1)
        cv2.circle(panel, (cx, cy), 12, (255, 255, 255), 1)
        cv2.putText(
            panel,
            f"Actual z={current_position[2]:.2f} m",
            (cx - 34, cy + 30),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.42,
            ACCENT,
            1,
            cv2.LINE_AA,
        )

    footer = (
        f"Marcadores: {len(layout.markers)}  |  "
        f"Diccionario: {layout.aruco_dict}  |  "
        f"Lado: {layout.marker_size_m:.3f} m"
    )
    cv2.putText(
        panel,
        footer,
        (18, height - 16),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.44,
        TEXT_MUTED,
        1,
        cv2.LINE_AA,
    )
    return panel


def render_status_panel(
    title: str,
    lines: list[str],
    alerts: list[str] | None = None,
    size: tuple[int, int] = (520, 360),
) -> np.ndarray:
    """Panel lateral de texto para el estado del test."""
    width, height = size
    panel = np.full((height, width, 3), CARD_ALT, dtype=np.uint8)
    cv2.rectangle(panel, (0, 0), (width - 1, height - 1), (34, 44, 74), 1)
    cv2.putText(
        panel,
        title,
        (18, 28),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.68,
        TEXT_PRIMARY,
        2,
        cv2.LINE_AA,
    )

    y = 64
    for line in lines:
        cv2.putText(
            panel,
            line,
            (18, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.54,
            TEXT_MUTED,
            1,
            cv2.LINE_AA,
        )
        y += 28

    if alerts:
        y += 10
        cv2.putText(
            panel,
            "Alertas / notas",
            (18, y),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.52,
            TEXT_PRIMARY,
            1,
            cv2.LINE_AA,
        )
        y += 28
        for alert in alerts:
            cv2.putText(
                panel,
                f"- {alert}",
                (18, y),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                WARNING,
                1,
                cv2.LINE_AA,
            )
            y += 24

    return panel


def compose_dashboard(
    frame: np.ndarray,
    topdown_panel: np.ndarray,
    status_panel: np.ndarray,
    title: str,
    subtitle: str | None = None,
) -> np.ndarray:
    """Compone un dashboard con camara a la izquierda y paneles a la derecha."""
    side_width = max(topdown_panel.shape[1], status_panel.shape[1])
    side_height = topdown_panel.shape[0] + status_panel.shape[0] + 14
    fitted_frame = _fit_image(frame, width=1020, height=side_height)

    canvas_width = fitted_frame.shape[1] + side_width + 46
    canvas_height = max(fitted_frame.shape[0], side_height) + 80
    canvas = np.full((canvas_height, canvas_width, 3), BACKGROUND, dtype=np.uint8)

    _draw_title(canvas, title, subtitle)

    frame_x = 20
    frame_y = 70
    canvas[
        frame_y : frame_y + fitted_frame.shape[0],
        frame_x : frame_x + fitted_frame.shape[1],
    ] = fitted_frame
    cv2.rectangle(
        canvas,
        (frame_x - 1, frame_y - 1),
        (frame_x + fitted_frame.shape[1], frame_y + fitted_frame.shape[0]),
        CARD_ALT,
        1,
    )

    side_x = frame_x + fitted_frame.shape[1] + 14
    side_y = frame_y
    canvas[
        side_y : side_y + topdown_panel.shape[0],
        side_x : side_x + topdown_panel.shape[1],
    ] = topdown_panel
    bottom_y = side_y + topdown_panel.shape[0] + 14
    canvas[
        bottom_y : bottom_y + status_panel.shape[0],
        side_x : side_x + status_panel.shape[1],
    ] = status_panel

    return canvas
