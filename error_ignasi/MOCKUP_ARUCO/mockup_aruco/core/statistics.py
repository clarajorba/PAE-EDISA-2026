from __future__ import annotations

from collections import Counter

import numpy as np

from .models import SampleRecord, TestDefinition


def _safe_summary(values: np.ndarray) -> dict[str, float]:
    if values.size == 0:
        return {"mean": 0.0, "std": 0.0, "p95": 0.0}
    std = float(np.std(values, ddof=1)) if values.size > 1 else 0.0
    return {
        "mean": float(np.mean(values)),
        "std": std,
        "p95": float(np.percentile(values, 95)),
    }


def compute_test_summary(
    test: TestDefinition,
    samples: list[SampleRecord],
    attempted_frames: int,
) -> dict:
    """Calcula metricas de repetibilidad y sesgo para un test estatico."""
    valid_samples = len(samples)
    availability = valid_samples / attempted_frames if attempted_frames else 0.0

    summary = {
        "test_name": test.name,
        "selected_marker_ids": test.selected_marker_ids,
        "duration_s": test.duration_s,
        "attempted_frames": attempted_frames,
        "valid_samples": valid_samples,
        "availability": availability,
        "required_visible_markers": test.required_visible_markers,
        "expected_position_m": test.expected_camera_position.tolist(),
        "status": "ok" if valid_samples else "no_valid_samples",
    }

    if not samples:
        summary.update(
            {
                "mean_position_m": [0.0, 0.0, 0.0],
                "median_position_m": [0.0, 0.0, 0.0],
                "std_position_m": [0.0, 0.0, 0.0],
                "var_position_m": [0.0, 0.0, 0.0],
                "range_position_m": [0.0, 0.0, 0.0],
                "bias_m": [0.0, 0.0, 0.0],
                "bias_norm_m": 0.0,
                "rmse_axes_m": [0.0, 0.0, 0.0],
                "rmse_norm_m": 0.0,
                "mae_axes_m": [0.0, 0.0, 0.0],
                "error_norm_mean_m": 0.0,
                "error_norm_std_m": 0.0,
                "error_norm_p95_m": 0.0,
                "jitter_norm_mean_m": 0.0,
                "jitter_norm_std_m": 0.0,
                "reprojection_px": {"mean": 0.0, "std": 0.0, "p95": 0.0},
                "visible_markers": {
                    "mean": 0.0,
                    "min": 0,
                    "max": 0,
                    "distribution": {},
                },
                "covariance_m2": np.zeros((3, 3), dtype=np.float64).tolist(),
                "mean_rotation_deg": [0.0, 0.0, 0.0],
                "std_rotation_deg": [0.0, 0.0, 0.0],
                "method_counts": {},
            }
        )
        return summary

    positions = np.vstack([sample.position_world for sample in samples])
    expected = test.expected_camera_position.reshape(3)
    errors = positions - expected
    error_norm = np.linalg.norm(errors, axis=1)

    mean_position = np.mean(positions, axis=0)
    std_position = np.std(positions, axis=0, ddof=1) if valid_samples > 1 else np.zeros(3)
    covariance = (
        np.cov(positions.T, ddof=1)
        if valid_samples > 1
        else np.zeros((3, 3), dtype=np.float64)
    )
    centered = positions - mean_position
    jitter_norm = np.linalg.norm(centered, axis=1)
    reprojection = np.asarray([sample.reprojection_error_px for sample in samples], dtype=np.float64)
    visible_counts = np.asarray([sample.visible_marker_count for sample in samples], dtype=np.int32)
    rotations = np.vstack([sample.euler_deg for sample in samples])

    method_counts = Counter(sample.method for sample in samples)
    bias = mean_position - expected
    rmse_axes = np.sqrt(np.mean(np.square(errors), axis=0))
    mae_axes = np.mean(np.abs(errors), axis=0)

    summary.update(
        {
            "mean_position_m": mean_position.tolist(),
            "median_position_m": np.median(positions, axis=0).tolist(),
            "std_position_m": std_position.tolist(),
            "var_position_m": np.var(positions, axis=0, ddof=1).tolist()
            if valid_samples > 1
            else [0.0, 0.0, 0.0],
            "range_position_m": (np.max(positions, axis=0) - np.min(positions, axis=0)).tolist(),
            "bias_m": bias.tolist(),
            "bias_norm_m": float(np.linalg.norm(bias)),
            "rmse_axes_m": rmse_axes.tolist(),
            "rmse_norm_m": float(np.sqrt(np.mean(np.square(error_norm)))),
            "mae_axes_m": mae_axes.tolist(),
            "error_norm_mean_m": float(np.mean(error_norm)),
            "error_norm_std_m": float(np.std(error_norm, ddof=1)) if valid_samples > 1 else 0.0,
            "error_norm_p95_m": float(np.percentile(error_norm, 95)),
            "jitter_norm_mean_m": float(np.mean(jitter_norm)),
            "jitter_norm_std_m": float(np.std(jitter_norm, ddof=1)) if valid_samples > 1 else 0.0,
            "reprojection_px": _safe_summary(reprojection),
            "visible_markers": {
                "mean": float(np.mean(visible_counts)),
                "min": int(np.min(visible_counts)),
                "max": int(np.max(visible_counts)),
                "distribution": {str(k): int(v) for k, v in sorted(Counter(visible_counts).items())},
            },
            "covariance_m2": covariance.tolist(),
            "mean_rotation_deg": np.mean(rotations, axis=0).tolist(),
            "std_rotation_deg": (
                np.std(rotations, axis=0, ddof=1).tolist()
                if valid_samples > 1
                else [0.0, 0.0, 0.0]
            ),
            "method_counts": dict(method_counts),
            "mean_confidence_interval_95_m": (
                (1.96 * std_position / np.sqrt(valid_samples)).tolist()
                if valid_samples > 1
                else [0.0, 0.0, 0.0]
            ),
        }
    )
    return summary


def compare_summaries(single_summary: dict, multi_summary: dict) -> dict:
    """Genera un bloque corto de comparacion entre ambos tests."""
    comparison = {
        "single_test": single_summary.get("test_name"),
        "multi_test": multi_summary.get("test_name"),
        "availability_delta": multi_summary.get("availability", 0.0) - single_summary.get("availability", 0.0),
        "bias_norm_delta_m": multi_summary.get("bias_norm_m", 0.0) - single_summary.get("bias_norm_m", 0.0),
        "error_norm_mean_delta_m": multi_summary.get("error_norm_mean_m", 0.0)
        - single_summary.get("error_norm_mean_m", 0.0),
        "error_norm_p95_delta_m": multi_summary.get("error_norm_p95_m", 0.0)
        - single_summary.get("error_norm_p95_m", 0.0),
        "std_norm_delta_m": float(
            np.linalg.norm(np.asarray(multi_summary.get("std_position_m", [0.0, 0.0, 0.0])))
            - np.linalg.norm(np.asarray(single_summary.get("std_position_m", [0.0, 0.0, 0.0])))
        ),
    }
    return comparison
