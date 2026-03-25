"""
camera_calibration.py
---------------------
Herramienta de calibración de cámara con tablero de ajedrez.

Uso:
    python -m src.camera_calibration --source 0 --output config/camera_params.json
    python -m src.camera_calibration --source video.mp4 --output config/camera_params.json

Captura automáticamente frames del tablero cuando éste permanece inmóvil
durante 1 segundo. Pulsa 'q' para finalizar y calcular la calibración.
"""

import cv2
import numpy as np
import json
import argparse
import time
from pathlib import Path
from typing import List, Tuple, Optional
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s │ %(message)s")
logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Calibrador
# ─────────────────────────────────────────────────────────────────────────────

class CameraCalibrator:
    """
    Calibra una cámara usando un tablero de ajedrez estándar.

    Parameters
    ----------
    board_w       : número de esquinas interiores horizontales (default 9)
    board_h       : número de esquinas interiores verticales  (default 6)
    square_size_m : tamaño del cuadrado en metros             (default 0.025)
    min_frames    : mínimo de capturas para calibrar          (default 15)
    """

    def __init__(
        self,
        board_w: int = 9,
        board_h: int = 6,
        square_size_m: float = 0.025,
        min_frames: int = 15,
    ):
        self.board_size    = (board_w, board_h)
        self.square_size   = square_size_m
        self.min_frames    = min_frames

        # Puntos 3-D del tablero en su sistema local
        self._obj_template = np.zeros((board_w * board_h, 3), np.float32)
        self._obj_template[:, :2] = (
            np.mgrid[0:board_w, 0:board_h].T.reshape(-1, 2) * square_size_m
        )

        self._obj_points: List[np.ndarray] = []
        self._img_points: List[np.ndarray] = []
        self._image_size: Optional[Tuple[int, int]] = None

        # Para detección de movimiento
        self._prev_corners: Optional[np.ndarray] = None
        self._still_since: Optional[float] = None
        self._captured_hashes: set = set()

    # ── Calibración interactiva ────────────────────────────────────────────

    def run_interactive(self, source: int | str, output_path: str):
        """Abre la fuente de vídeo y captura frames del tablero."""
        cap = cv2.VideoCapture(source)
        if not cap.isOpened():
            raise RuntimeError(f"No se puede abrir la fuente: {source}")

        logger.info(f"Calibración iniciada │ tablero={self.board_size} │ "
                    f"cuadrado={self.square_size*100:.1f}cm")
        logger.info("Mueve el tablero ante la cámara. "
                    "Las capturas se realizan automáticamente. 'q' para terminar.")

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            if self._image_size is None:
                h, w = frame.shape[:2]
                self._image_size = (w, h)

            display = frame.copy()
            found, corners = self._find_corners(frame)

            if found:
                cv2.drawChessboardCorners(display, self.board_size, corners, found)
                captured = self._try_capture(corners)
                n = len(self._obj_points)
                status = f"Capturas: {n}/{self.min_frames}"
                color  = (0, 220, 80) if captured else (0, 200, 255)
                cv2.putText(display, status, (10, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.9, color, 2)
            else:
                cv2.putText(display, "Tablero no detectado", (10, 35),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.7, (60, 60, 255), 2)

            cv2.putText(display,
                        f"[q] Finalizar calibración  │  Captures: {len(self._obj_points)}",
                        (10, display.shape[0] - 10),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
            cv2.imshow("Calibración de Cámara", display)

            key = cv2.waitKey(1) & 0xFF
            if key == ord('q'):
                break

        cap.release()
        cv2.destroyAllWindows()

        if len(self._obj_points) < self.min_frames:
            logger.warning(
                f"Solo {len(self._obj_points)} capturas (mínimo {self.min_frames}). "
                "La calibración puede ser imprecisa."
            )

        if len(self._obj_points) < 4:
            logger.error("Insuficientes capturas para calibrar.")
            return None

        return self.calibrate_and_save(output_path)

    # ── Detección de esquinas ──────────────────────────────────────────────

    def _find_corners(
        self, frame: np.ndarray
    ) -> Tuple[bool, Optional[np.ndarray]]:
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        found, corners = cv2.findChessboardCorners(gray, self.board_size, None)
        if found:
            criteria = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 30, 0.001)
            corners = cv2.cornerSubPix(gray, corners, (11, 11), (-1, -1), criteria)
        return found, corners if found else None

    def _try_capture(self, corners: np.ndarray) -> bool:
        """Captura si el tablero lleva ≥1 s inmóvil y es nuevo."""
        if self._prev_corners is not None:
            movement = np.mean(np.abs(corners - self._prev_corners))
            if movement > 2.0:
                self._still_since = None
                self._prev_corners = corners
                return False

        if self._still_since is None:
            self._still_since = time.time()

        self._prev_corners = corners

        if time.time() - self._still_since >= 1.0:
            h = hash(corners.tobytes())
            if h not in self._captured_hashes:
                self._captured_hashes.add(h)
                self._obj_points.append(self._obj_template.copy())
                self._img_points.append(corners)
                self._still_since = None
                logger.info(f"  ✓ Captura {len(self._obj_points)}")
                return True
        return False

    # ── Calibración y guardado ─────────────────────────────────────────────

    def calibrate_and_save(self, output_path: str) -> dict:
        logger.info(f"Calculando calibración con {len(self._obj_points)} capturas...")

        rms, K, dist, _, _ = cv2.calibrateCamera(
            self._obj_points, self._img_points,
            self._image_size, None, None,
        )

        logger.info(f"  RMS error: {rms:.4f} px")
        logger.info(f"  fx={K[0,0]:.2f}  fy={K[1,1]:.2f}")
        logger.info(f"  cx={K[0,2]:.2f}  cy={K[1,2]:.2f}")

        result = {
            "image_width":       self._image_size[0],
            "image_height":      self._image_size[1],
            "camera_matrix":     K.tolist(),
            "dist_coefficients": dist.flatten().tolist(),
            "calibration_error_rms": round(float(rms), 4),
            "calibration_date":  time.strftime("%Y-%m-%d"),
            "n_frames_used":     len(self._obj_points),
            "board_size":        list(self.board_size),
            "square_size_m":     self.square_size,
        }

        out = Path(output_path)
        out.parent.mkdir(parents=True, exist_ok=True)
        with open(out, "w") as f:
            json.dump(result, f, indent=2)

        logger.info(f"  Parámetros guardados en: {output_path}")
        return result


# ─────────────────────────────────────────────────────────────────────────────
# Carga de parámetros
# ─────────────────────────────────────────────────────────────────────────────

def load_camera_params(config_path: str) -> Tuple[np.ndarray, np.ndarray]:
    """
    Carga la matriz de cámara y los coeficientes de distorsión desde JSON.

    Returns
    -------
    (camera_matrix 3×3, dist_coefficients 1×5)
    """
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"camera_params no encontrado: {config_path}")

    with open(path, "r") as f:
        data = json.load(f)

    K    = np.array(data["camera_matrix"],     dtype=np.float64)
    dist = np.array(data["dist_coefficients"], dtype=np.float64)
    return K, dist


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Calibración de cámara con tablero de ajedrez"
    )
    parser.add_argument("--source",  default=0,
                        help="Fuente de vídeo: 0=webcam, ruta de archivo")
    parser.add_argument("--output",  default="config/camera_params.json",
                        help="Ruta de salida del JSON con parámetros")
    parser.add_argument("--board-w", type=int, default=9,
                        help="Esquinas interiores horizontales (default 9)")
    parser.add_argument("--board-h", type=int, default=6,
                        help="Esquinas interiores verticales  (default 6)")
    parser.add_argument("--square",  type=float, default=0.025,
                        help="Tamaño del cuadrado en metros   (default 0.025)")
    parser.add_argument("--min-frames", type=int, default=15,
                        help="Mínimo de capturas para calibrar (default 15)")
    args = parser.parse_args()

    # Intentar convertir source a int (índice de webcam)
    try:
        source = int(args.source)
    except ValueError:
        source = args.source

    calibrator = CameraCalibrator(
        board_w=args.board_w,
        board_h=args.board_h,
        square_size_m=args.square,
        min_frames=args.min_frames,
    )
    calibrator.run_interactive(source, args.output)
