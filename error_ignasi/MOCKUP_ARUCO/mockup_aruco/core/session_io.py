from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path

import numpy as np

from .models import SampleRecord


def create_session_directory(base_dir: str | Path, prefix: str) -> Path:
    """Crea una carpeta con timestamp para guardar un benchmark."""
    root = Path(base_dir)
    root.mkdir(parents=True, exist_ok=True)
    session_dir = root / f"{prefix}_{datetime.now():%Y%m%d_%H%M%S}"
    session_dir.mkdir(parents=True, exist_ok=True)
    return session_dir


def save_samples_csv(
    samples: list[SampleRecord],
    path: str | Path,
    expected_position: np.ndarray | None = None,
) -> Path:
    """Exporta las muestras crudas a CSV."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)

    with file_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "timestamp_s",
                "frame_index",
                "x_m",
                "y_m",
                "z_m",
                "roll_deg",
                "pitch_deg",
                "yaw_deg",
                "visible_marker_count",
                "visible_marker_ids",
                "reprojection_error_px",
                "method",
                "error_x_m",
                "error_y_m",
                "error_z_m",
                "error_norm_m",
            ]
        )

        for sample in samples:
            roll, pitch, yaw = sample.euler_deg
            error_x = error_y = error_z = error_norm = ""
            if expected_position is not None:
                error_vector = sample.position_world - expected_position
                error_x, error_y, error_z = [f"{value:.6f}" for value in error_vector]
                error_norm = f"{np.linalg.norm(error_vector):.6f}"

            writer.writerow(
                [
                    f"{sample.timestamp_s:.6f}",
                    sample.frame_index,
                    f"{sample.position_world[0]:.6f}",
                    f"{sample.position_world[1]:.6f}",
                    f"{sample.position_world[2]:.6f}",
                    f"{roll:.6f}",
                    f"{pitch:.6f}",
                    f"{yaw:.6f}",
                    sample.visible_marker_count,
                    ",".join(str(marker_id) for marker_id in sample.visible_marker_ids),
                    f"{sample.reprojection_error_px:.6f}",
                    sample.method,
                    error_x,
                    error_y,
                    error_z,
                    error_norm,
                ]
            )

    return file_path


def save_summary_json(summary: dict, path: str | Path) -> Path:
    """Guarda el resumen numerico del test."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return file_path
