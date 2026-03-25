"""Compatibilidad con la ruta historica de calibracion de camara."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mockup_aruco.camera.calibration import ChessboardSettings, run_chessboard_calibration


def main() -> None:
    calibration_path = ROOT / "config" / "camera_calibration.json"
    settings = ChessboardSettings(board_size=(7, 7), square_size_m=0.01, min_captures=15)
    run_chessboard_calibration(
        source=0,
        settings=settings,
        output_path=calibration_path,
    )


if __name__ == "__main__":
    main()
