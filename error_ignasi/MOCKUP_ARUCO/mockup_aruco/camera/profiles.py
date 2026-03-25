from __future__ import annotations

import json
from pathlib import Path

from ..core.models import CameraProfile


def list_camera_profiles(profile_dir: str | Path) -> list[Path]:
    """Lista perfiles de camara guardados en disco."""
    directory = Path(profile_dir)
    if not directory.exists():
        return []
    return sorted(directory.glob("*.json"))


def load_camera_profile(path: str | Path) -> CameraProfile:
    """Carga un perfil de camara desde JSON."""
    file_path = Path(path)
    data = json.loads(file_path.read_text(encoding="utf-8"))
    return CameraProfile.from_json_dict(data)


def save_camera_profile(profile: CameraProfile, path: str | Path) -> Path:
    """Guarda un perfil de camara."""
    file_path = Path(path)
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        json.dumps(profile.to_json_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return file_path
