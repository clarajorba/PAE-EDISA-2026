from __future__ import annotations

import sys
from typing import Iterable

import cv2

from ..core.models import CameraDescriptor


def _open_capture(source: int | str) -> cv2.VideoCapture:
    if isinstance(source, int) and sys.platform.startswith("win"):
        return cv2.VideoCapture(source, cv2.CAP_DSHOW)
    return cv2.VideoCapture(source)


def discover_cameras(max_index: int = 8) -> list[CameraDescriptor]:
    """Busca camaras intentando abrir indices consecutivos."""
    discovered: list[CameraDescriptor] = []

    for index in range(max_index):
        cap = _open_capture(index)
        try:
            if not cap.isOpened():
                continue

            ok, frame = cap.read()
            if not ok or frame is None:
                continue

            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or int(frame.shape[1])
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or int(frame.shape[0])
            fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            backend_name = ""
            try:
                backend_name = cap.getBackendName()
            except cv2.error:
                backend_name = ""

            discovered.append(
                CameraDescriptor(
                    source=index,
                    width=width,
                    height=height,
                    fps=fps,
                    backend_name=backend_name,
                    name=f"Camera {index}",
                )
            )
        finally:
            cap.release()

    return discovered


def open_video_source(
    source: int | str,
    width: int | None = None,
    height: int | None = None,
    fps: float | None = None,
) -> cv2.VideoCapture:
    """Abre una fuente de video y aplica resolucion objetivo cuando procede."""
    cap = _open_capture(source)
    if width:
        cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
    if height:
        cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
    if fps:
        cap.set(cv2.CAP_PROP_FPS, fps)
    return cap
