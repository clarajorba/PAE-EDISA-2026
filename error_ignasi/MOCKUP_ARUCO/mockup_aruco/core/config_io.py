from __future__ import annotations

import json
from pathlib import Path

from .models import MarkerDefinition, MarkerLayout, as_vector


def load_marker_layout(path: str | Path) -> MarkerLayout:
    """Carga una distribucion de marcadores desde JSON."""
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))

    markers: dict[int, MarkerDefinition] = {}
    raw_markers = data.get("markers", {})
    for marker_id, marker_data in raw_markers.items():
        marker_int = int(marker_id)
        markers[marker_int] = MarkerDefinition(
            marker_id=marker_int,
            position=as_vector(
                [
                    marker_data.get("x", 0.0),
                    marker_data.get("y", 0.0),
                    marker_data.get("z", 0.0),
                ]
            ),
            label=marker_data.get("label", f"ID{marker_int}"),
            yaw_deg=float(marker_data.get("yaw_deg", 0.0)),
        )

    return MarkerLayout(
        name=data.get("space_name", file_path.stem),
        aruco_dict=data.get("aruco_dict", "DICT_4X4_1000"),
        marker_size_m=float(data.get("marker_size", data.get("marker_size_m", 0.12))),
        markers=markers,
        spacing_m=data.get("spacing_m"),
        description=data.get("description", data.get("_info", "")),
    )


def save_marker_layout(layout: MarkerLayout, path: str | Path) -> Path:
    """Guarda una distribucion de marcadores en JSON."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(layout.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return file_path
