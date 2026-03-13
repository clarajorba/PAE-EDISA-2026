"""
warehouse_map.py
----------------
Modelo del almacén: dimensiones y posiciones conocidas de los marcadores ArUco.

Cada marcador tiene una posición y orientación fija en el sistema de
coordenadas del mundo (origen = esquina inferior-izquierda del almacén).
"""

import json
import math
import numpy as np
import cv2
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Estructuras de datos
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class WarehouseMarker:
    """
    Marcador ArUco instalado en el almacén con posición y orientación conocidas.

    Sistema de coordenadas del mundo (ENU):
        X → Este  (ancho del almacén)
        Y → Norte (largo del almacén)
        Z → Arriba (altura)
    """
    marker_id: int
    position: np.ndarray        # [x, y, z] en metros (mundo)
    rotation_deg: np.ndarray    # [rx, ry, rz] en grados (Euler ZYX)
    location: str               # Descripción legible

    @property
    def rotation_matrix(self) -> np.ndarray:
        """Matriz de rotación 3×3 del marcador en el mundo."""
        rx = math.radians(self.rotation_deg[0])
        ry = math.radians(self.rotation_deg[1])
        rz = math.radians(self.rotation_deg[2])

        Rx = np.array([[1, 0, 0],
                        [0, math.cos(rx), -math.sin(rx)],
                        [0, math.sin(rx),  math.cos(rx)]])
        Ry = np.array([[ math.cos(ry), 0, math.sin(ry)],
                        [0, 1, 0],
                        [-math.sin(ry), 0, math.cos(ry)]])
        Rz = np.array([[math.cos(rz), -math.sin(rz), 0],
                        [math.sin(rz),  math.cos(rz), 0],
                        [0, 0, 1]])
        return Rz @ Ry @ Rx

    @property
    def transform_world_to_marker(self) -> np.ndarray:
        """Matriz homogénea 4×4: T_{world→marker}."""
        T = np.eye(4)
        T[:3, :3] = self.rotation_matrix
        T[:3,  3] = self.position
        return T

    def world_corners_3d(self, marker_size_m: float) -> np.ndarray:
        """
        Devuelve las 4 esquinas del marcador en coordenadas del mundo (4×3).
        Orden: TL, TR, BR, BL (igual que ArUco).
        """
        half = marker_size_m / 2.0
        local = np.array([
            [-half,  half, 0.0],
            [ half,  half, 0.0],
            [ half, -half, 0.0],
            [-half, -half, 0.0],
        ])
        R = self.rotation_matrix
        return (R @ local.T).T + self.position


# ─────────────────────────────────────────────────────────────────────────────
# Mapa del almacén
# ─────────────────────────────────────────────────────────────────────────────

class WarehouseMap:
    """
    Carga y gestiona el mapa del almacén con la posición de todos los marcadores.

    Uso rápido
    ----------
    wmap = WarehouseMap.from_config("config/warehouse_config.json")
    marker = wmap.get_marker(0)          # por ID
    corners = wmap.get_world_corners(5)  # esquinas en coords mundo
    """

    def __init__(self, config: dict):
        self.name: str          = config["warehouse"]["name"]
        self.width_m: float     = config["warehouse"]["dimensions"]["width_m"]
        self.height_m: float    = config["warehouse"]["dimensions"]["height_m"]
        self.ceiling_m: float   = config["warehouse"]["dimensions"]["ceiling_m"]
        self.marker_size_m: float = config["aruco"]["marker_size_m"]
        self.aruco_dict: str    = config["aruco"]["dictionary"]
        self.min_markers: int   = config["aruco"]["min_markers_for_localization"]

        self._markers: Dict[int, WarehouseMarker] = {}
        for m in config["markers"]:
            pos = np.array([m["position"]["x"],
                            m["position"]["y"],
                            m["position"]["z"]], dtype=np.float64)
            rot = np.array([m["rotation_deg"]["rx"],
                            m["rotation_deg"]["ry"],
                            m["rotation_deg"]["rz"]], dtype=np.float64)
            wm = WarehouseMarker(
                marker_id=m["id"],
                position=pos,
                rotation_deg=rot,
                location=m.get("location", ""),
            )
            self._markers[m["id"]] = wm

        logger.info(
            f"WarehouseMap '{self.name}' │ "
            f"{self.width_m}×{self.height_m}m │ "
            f"{len(self._markers)} marcadores"
        )

    # ── Carga ──────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, config_path: str) -> "WarehouseMap":
        path = Path(config_path)
        if not path.exists():
            raise FileNotFoundError(f"Config no encontrado: {config_path}")
        with open(path, "r", encoding="utf-8") as f:
            config = json.load(f)
        return cls(config)

    # ── Acceso a marcadores ────────────────────────────────────────────────

    def get_marker(self, marker_id: int) -> Optional[WarehouseMarker]:
        return self._markers.get(marker_id)

    def all_markers(self) -> List[WarehouseMarker]:
        return list(self._markers.values())

    def known_ids(self) -> List[int]:
        return sorted(self._markers.keys())

    def is_known(self, marker_id: int) -> bool:
        return marker_id in self._markers

    def get_world_corners(
        self, marker_id: int
    ) -> Optional[np.ndarray]:
        """Esquinas del marcador en el mundo (4×3). None si no existe."""
        wm = self.get_marker(marker_id)
        if wm is None:
            return None
        return wm.world_corners_3d(self.marker_size_m)

    # ── Descripción ────────────────────────────────────────────────────────

    def print_summary(self):
        print(f"\n{'═'*60}")
        print(f"  Almacén: {self.name}")
        print(f"  Dimensiones : {self.width_m} × {self.height_m} × {self.ceiling_m} m")
        print(f"  Marcadores  : {len(self._markers)}")
        print(f"  Diccionario : {self.aruco_dict}")
        print(f"  Tamaño marca: {self.marker_size_m*100:.1f} cm")
        print(f"{'─'*60}")
        for m in sorted(self._markers.values(), key=lambda x: x.marker_id):
            p = m.position
            print(f"  ID {m.marker_id:>3d} │ ({p[0]:5.1f}, {p[1]:5.1f}, {p[2]:5.1f}) m │ {m.location}")
        print(f"{'═'*60}\n")

    # ── Validación ─────────────────────────────────────────────────────────

    def validate_position(self, pos: np.ndarray) -> bool:
        """Comprueba si una posición está dentro de los límites del almacén."""
        return (0 <= pos[0] <= self.width_m and
                0 <= pos[1] <= self.height_m and
                0 <= pos[2] <= self.ceiling_m)

    def nearest_marker(self, position: np.ndarray) -> Optional[WarehouseMarker]:
        """Devuelve el marcador más cercano a una posición dada."""
        if not self._markers:
            return None
        return min(
            self._markers.values(),
            key=lambda m: np.linalg.norm(m.position - position),
        )
