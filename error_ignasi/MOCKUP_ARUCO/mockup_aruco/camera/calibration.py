from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

from ..core.models import CalibrationData
from .discovery import open_video_source


@dataclass(slots=True)
class ChessboardSettings:
    board_size: tuple[int, int] = (7, 7)
    square_size_m: float = 0.01
    min_captures: int = 15


def load_calibration(path: str | Path) -> CalibrationData:
    """Carga un JSON de calibracion desde disco."""
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    return CalibrationData.from_json_dict(data)


def save_calibration(calibration: CalibrationData, path: str | Path) -> Path:
    """Guarda un JSON de calibracion."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(calibration.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return file_path


def _object_points(settings: ChessboardSettings) -> np.ndarray:
    objp = np.zeros((settings.board_size[0] * settings.board_size[1], 3), np.float32)
    objp[:, :2] = np.mgrid[
        0 : settings.board_size[0],
        0 : settings.board_size[1],
    ].T.reshape(-1, 2)
    objp *= settings.square_size_m
    return objp


def run_chessboard_calibration(
    source: int | str,
    settings: ChessboardSettings,
    output_path: str | Path | None = None,
) -> CalibrationData | None:
    """Calibracion interactiva con capturas manuales usando ESPACIO."""
    cap = open_video_source(source, width=1920, height=1080, fps=30)
    if not cap.isOpened():
        raise RuntimeError(f"No se puede abrir la camara/fuente: {source}")

    pattern_points = _object_points(settings)
    object_points: list[np.ndarray] = []
    image_points: list[np.ndarray] = []
    image_size: tuple[int, int] | None = None

    criteria = (
        cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER,
        30,
        0.001,
    )

    print("\n" + "=" * 62)
    print("CALIBRACION DE CAMARA")
    print("=" * 62)
    print(f"Tablero: {settings.board_size[0]} x {settings.board_size[1]} esquinas interiores")
    print(f"Tamano real del cuadrado: {settings.square_size_m:.4f} m")
    print(f"Capturas minimas recomendadas: {settings.min_captures}")
    print("Controles: ESPACIO = capturar | q = calibrar/salir")
    print("=" * 62 + "\n")

    window_name = "Calibracion de camara"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1100, 800)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            image_size = gray.shape[::-1]
            found, corners = cv2.findChessboardCorners(
                gray,
                settings.board_size,
                cv2.CALIB_CB_ADAPTIVE_THRESH
                + cv2.CALIB_CB_NORMALIZE_IMAGE
                + cv2.CALIB_CB_FAST_CHECK,
            )

            display = frame.copy()
            refined_corners = None
            if found:
                refined_corners = cv2.cornerSubPix(
                    gray,
                    corners,
                    (11, 11),
                    (-1, -1),
                    criteria,
                )
                cv2.drawChessboardCorners(
                    display,
                    settings.board_size,
                    refined_corners,
                    found,
                )
                status_text = "Tablero detectado - pulsa ESPACIO para capturar"
                status_color = (40, 220, 90)
            else:
                status_text = "Buscando tablero..."
                status_color = (0, 170, 255)

            cv2.putText(
                display,
                status_text,
                (18, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                status_color,
                2,
                cv2.LINE_AA,
            )
            cv2.putText(
                display,
                f"Capturas: {len(object_points)}/{settings.min_captures}",
                (18, 72),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.6,
                (255, 220, 120),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord(" ") and found and refined_corners is not None:
                object_points.append(pattern_points.copy())
                image_points.append(refined_corners)
                print(f"Captura #{len(object_points)} guardada")
            elif key == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()

    if image_size is None or len(object_points) < 4:
        print("No hay suficientes capturas para calibrar.")
        return None

    _, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        object_points,
        image_points,
        image_size,
        None,
        None,
        flags=cv2.CALIB_FIX_K4 + cv2.CALIB_FIX_K5,
    )

    total_error = 0.0
    total_points = 0
    for index, object_points_i in enumerate(object_points):
        projected, _ = cv2.projectPoints(
            object_points_i,
            rvecs[index],
            tvecs[index],
            camera_matrix,
            dist_coeffs,
        )
        error = cv2.norm(image_points[index], projected, cv2.NORM_L2)
        total_error += error**2
        total_points += len(object_points_i)

    reprojection_error = float(np.sqrt(total_error / max(total_points, 1)))
    calibration = CalibrationData(
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs.reshape(-1, 1),
        image_size=(int(image_size[0]), int(image_size[1])),
        reprojection_error_px=reprojection_error,
        calibration_date=datetime.now().isoformat(),
    )

    if output_path is not None:
        save_calibration(calibration, output_path)

    print("\n" + "=" * 62)
    print("CALIBRACION COMPLETADA")
    print("=" * 62)
    print(f"Error de reproyeccion: {reprojection_error:.4f} px")
    print(f"Resolucion calibrada: {image_size[0]} x {image_size[1]}")
    print("Matriz intrinseca:")
    print(camera_matrix)
    print("Distorsion:")
    print(dist_coeffs.flatten())
    if output_path is not None:
        print(f"Guardado en: {Path(output_path)}")
    print("=" * 62 + "\n")

    return calibration
