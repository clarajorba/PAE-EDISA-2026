from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

from ..core.models import SampleRecord


FIG_BG = "#0a1022"
AX_BG = "#111a33"
GRID = "#2a375c"
TEXT = "#eef3ff"
TEXT_SOFT = "#9fb2e5"
COLORS = {
    "x": "#5cc8ff",
    "y": "#69d58a",
    "z": "#ffd166",
    "error": "#ff7f7f",
    "single": "#5cc8ff",
    "multi": "#69d58a",
}


def _apply_style() -> None:
    plt.rcParams.update(
        {
            "figure.facecolor": FIG_BG,
            "axes.facecolor": AX_BG,
            "axes.edgecolor": GRID,
            "axes.labelcolor": TEXT,
            "xtick.color": TEXT_SOFT,
            "ytick.color": TEXT_SOFT,
            "text.color": TEXT,
            "axes.titlecolor": TEXT,
            "grid.color": GRID,
            "grid.alpha": 0.6,
            "font.size": 10,
        }
    )


def _sample_arrays(
    samples: list[SampleRecord],
    expected_position: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    times = np.asarray([sample.timestamp_s for sample in samples], dtype=np.float64)
    positions = np.vstack([sample.position_world for sample in samples])
    visible = np.asarray([sample.visible_marker_count for sample in samples], dtype=np.int32)
    error_norm = np.linalg.norm(positions - expected_position.reshape(3), axis=1)
    return times, positions, visible, error_norm


def create_test_report(
    summary: dict,
    samples: list[SampleRecord],
    output_path: str | Path | None = None,
):
    """Genera una figura profesional para un test individual."""
    _apply_style()
    fig = plt.figure(figsize=(15, 9), facecolor=FIG_BG)
    gs = fig.add_gridspec(2, 2, width_ratios=[1.5, 1.0], height_ratios=[1.2, 1.0])

    ax_series = fig.add_subplot(gs[0, 0])
    ax_xy = fig.add_subplot(gs[0, 1])
    ax_error = fig.add_subplot(gs[1, 0])
    ax_text = fig.add_subplot(gs[1, 1])

    test_name = summary.get("test_name", "Test")
    expected = np.asarray(summary.get("expected_position_m", [0.0, 0.0, 0.0]), dtype=np.float64)

    if samples:
        times, positions, visible, error_norm = _sample_arrays(samples, expected)
        for index, axis_name in enumerate(("x", "y", "z")):
            ax_series.plot(times, positions[:, index], label=f"{axis_name.upper()} estimada", color=COLORS[axis_name], linewidth=1.8)
            ax_series.axhline(expected[index], color=COLORS[axis_name], linestyle="--", linewidth=1.0, alpha=0.7)
        ax_series.set_title("Posicion estimada en el tiempo")
        ax_series.set_xlabel("Tiempo [s]")
        ax_series.set_ylabel("Posicion [m]")
        ax_series.grid(True)
        ax_series.legend(frameon=False, ncol=3, loc="upper right")

        scatter = ax_xy.scatter(
            positions[:, 0],
            positions[:, 1],
            c=visible,
            cmap="viridis",
            s=28,
            alpha=0.85,
        )
        ax_xy.scatter(expected[0], expected[1], color=COLORS["error"], marker="*", s=160, label="Esperado")
        ax_xy.scatter(
            summary["mean_position_m"][0],
            summary["mean_position_m"][1],
            color=TEXT,
            marker="X",
            s=90,
            label="Media",
        )
        ax_xy.set_title("Dispersión XY")
        ax_xy.set_xlabel("X [m]")
        ax_xy.set_ylabel("Y [m]")
        ax_xy.grid(True)
        ax_xy.legend(frameon=False, loc="best")
        cbar = fig.colorbar(scatter, ax=ax_xy, fraction=0.046, pad=0.04)
        cbar.set_label("Marcadores visibles")
        cbar.ax.yaxis.set_tick_params(color=TEXT_SOFT)

        ax_error.plot(times, error_norm, color=COLORS["error"], linewidth=1.8, label="Norma del error")
        ax_error.axhline(summary.get("error_norm_mean_m", 0.0), color=TEXT, linestyle="--", linewidth=1.0, label="Media")
        ax_error.set_title("Error 3D respecto a la posicion esperada")
        ax_error.set_xlabel("Tiempo [s]")
        ax_error.set_ylabel("Error [m]")
        ax_error.grid(True)
        ax_error.legend(frameon=False, loc="upper left")

        ax_visible = ax_error.twinx()
        ax_visible.plot(times, visible, color="#98f5e1", linewidth=1.0, alpha=0.45, label="Marcadores")
        ax_visible.set_ylabel("Marcadores visibles")
        ax_visible.tick_params(colors=TEXT_SOFT)
    else:
        for axis in (ax_series, ax_xy, ax_error):
            axis.text(0.5, 0.5, "Sin muestras válidas", ha="center", va="center", fontsize=14)
            axis.set_axis_off()

    ax_text.set_title("Resumen numerico")
    ax_text.axis("off")
    text_lines = [
        f"Disponibilidad: {summary.get('availability', 0.0) * 100:.1f} %",
        f"Muestras validas: {summary.get('valid_samples', 0)} / {summary.get('attempted_frames', 0)}",
        f"Bias [m]: {np.array2string(np.asarray(summary.get('bias_m', [0.0, 0.0, 0.0])), precision=4)}",
        f"Bias 3D: {summary.get('bias_norm_m', 0.0):.4f} m",
        f"STD XYZ [m]: {np.array2string(np.asarray(summary.get('std_position_m', [0.0, 0.0, 0.0])), precision=4)}",
        f"RMSE XYZ [m]: {np.array2string(np.asarray(summary.get('rmse_axes_m', [0.0, 0.0, 0.0])), precision=4)}",
        f"Error medio 3D: {summary.get('error_norm_mean_m', 0.0):.4f} m",
        f"Error P95 3D: {summary.get('error_norm_p95_m', 0.0):.4f} m",
        f"Reproyeccion media: {summary.get('reprojection_px', {}).get('mean', 0.0):.3f} px",
        f"Marcadores visibles media: {summary.get('visible_markers', {}).get('mean', 0.0):.2f}",
        f"Metodos: {summary.get('method_counts', {})}",
    ]
    ax_text.text(
        0.03,
        0.98,
        "\n".join(text_lines),
        transform=ax_text.transAxes,
        va="top",
        ha="left",
        fontsize=11,
        family="monospace",
    )

    fig.suptitle(f"{test_name} | Analisis de error de pose", fontsize=16, y=0.98)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=170, facecolor=fig.get_facecolor(), bbox_inches="tight")
    return fig


def create_comparison_report(
    single_summary: dict,
    multi_summary: dict,
    output_path: str | Path | None = None,
):
    """Crea una comparativa compacta entre el test simple y el test multi-marcador."""
    _apply_style()
    fig = plt.figure(figsize=(14, 8), facecolor=FIG_BG)
    gs = fig.add_gridspec(2, 2)

    ax_bias = fig.add_subplot(gs[0, 0])
    ax_std = fig.add_subplot(gs[0, 1])
    ax_avail = fig.add_subplot(gs[1, 0])
    ax_text = fig.add_subplot(gs[1, 1])

    labels = ["Un marcador", "Multi marcador"]
    bias_values = [single_summary.get("bias_norm_m", 0.0), multi_summary.get("bias_norm_m", 0.0)]
    error_values = [
        single_summary.get("error_norm_mean_m", 0.0),
        multi_summary.get("error_norm_mean_m", 0.0),
    ]

    ax_bias.bar(labels, bias_values, color=[COLORS["single"], COLORS["multi"]], alpha=0.9, label="Bias 3D")
    ax_bias.plot(labels, error_values, color=COLORS["error"], marker="o", linewidth=2.0, label="Error medio 3D")
    ax_bias.set_title("Bias y error medio")
    ax_bias.set_ylabel("Metros")
    ax_bias.grid(True, axis="y")
    ax_bias.legend(frameon=False)

    single_std = np.asarray(single_summary.get("std_position_m", [0.0, 0.0, 0.0]), dtype=np.float64)
    multi_std = np.asarray(multi_summary.get("std_position_m", [0.0, 0.0, 0.0]), dtype=np.float64)
    axes = np.arange(3)
    width = 0.34
    ax_std.bar(axes - width / 2, single_std, width=width, color=COLORS["single"], label="Un marcador")
    ax_std.bar(axes + width / 2, multi_std, width=width, color=COLORS["multi"], label="Multi marcador")
    ax_std.set_xticks(axes)
    ax_std.set_xticklabels(["X", "Y", "Z"])
    ax_std.set_title("Desviacion estandar por eje")
    ax_std.set_ylabel("Metros")
    ax_std.grid(True, axis="y")
    ax_std.legend(frameon=False)

    availability_values = [
        single_summary.get("availability", 0.0) * 100.0,
        multi_summary.get("availability", 0.0) * 100.0,
    ]
    visible_values = [
        single_summary.get("visible_markers", {}).get("mean", 0.0),
        multi_summary.get("visible_markers", {}).get("mean", 0.0),
    ]
    ax_avail.bar(labels, availability_values, color=[COLORS["single"], COLORS["multi"]], alpha=0.9, label="Disponibilidad [%]")
    ax_avail.plot(labels, visible_values, color="#98f5e1", marker="D", linewidth=2.0, label="Marcadores visibles medios")
    ax_avail.set_title("Disponibilidad del sistema")
    ax_avail.set_ylabel("% / recuento medio")
    ax_avail.grid(True, axis="y")
    ax_avail.legend(frameon=False)

    ax_text.axis("off")
    better_bias = "multi marcador" if bias_values[1] <= bias_values[0] else "un marcador"
    better_error = "multi marcador" if error_values[1] <= error_values[0] else "un marcador"
    lines = [
        "Lectura rapida",
        "",
        f"Menor bias global: {better_bias}",
        f"Menor error medio: {better_error}",
        f"Bias 3D simple: {bias_values[0]:.4f} m",
        f"Bias 3D multi:  {bias_values[1]:.4f} m",
        f"Error medio simple: {error_values[0]:.4f} m",
        f"Error medio multi:  {error_values[1]:.4f} m",
        f"Disponibilidad simple: {availability_values[0]:.1f} %",
        f"Disponibilidad multi:  {availability_values[1]:.1f} %",
    ]
    ax_text.text(
        0.04,
        0.96,
        "\n".join(lines),
        va="top",
        ha="left",
        fontsize=12,
        family="monospace",
    )

    fig.suptitle("Comparativa: un marcador vs varios marcadores", fontsize=16, y=0.98)
    fig.tight_layout(rect=(0.0, 0.0, 1.0, 0.96))

    if output_path is not None:
        path = Path(output_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        fig.savefig(path, dpi=170, facecolor=fig.get_facecolor(), bbox_inches="tight")
    return fig
