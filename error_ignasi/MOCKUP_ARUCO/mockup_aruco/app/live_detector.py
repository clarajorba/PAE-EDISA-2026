from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import numpy as np

from ..camera.calibration import load_calibration
from ..camera.discovery import open_video_source
from ..camera.profiles import list_camera_profiles, load_camera_profile
from ..core.aruco import ArucoDetector
from ..core.config_io import load_marker_layout
from ..core.models import CameraProfile
from ..core.pose import estimate_best_pose
from ..viz.dashboard import compose_dashboard, render_status_panel, render_topdown_panel


BASE_DIR = Path(__file__).resolve().parents[2]
DEFAULT_LAYOUT_PATH = BASE_DIR / "config" / "markers_3d.json"
PROFILE_DIR = BASE_DIR / "config" / "camera_profiles"
DEFAULT_CALIBRATION_PATH = BASE_DIR / "config" / "camera_calibration.json"


def _align_profile_resolution_with_calibration(profile: CameraProfile) -> CameraProfile:
    if profile.calibration is None or profile.calibration.image_size is None:
        return profile
    if profile.width is None or profile.height is None:
        profile.width, profile.height = profile.calibration.image_size
        return profile

    calib_width, calib_height = profile.calibration.image_size
    if profile.width != calib_width or profile.height != calib_height:
        profile.width = calib_width
        profile.height = calib_height
    return profile


def _load_runtime_profile(args: argparse.Namespace) -> CameraProfile:
    if args.profile:
        profile_path = Path(args.profile)
        if not profile_path.exists():
            profile_path = PROFILE_DIR / f"{args.profile}.json"
        if not profile_path.exists():
            raise FileNotFoundError(f"No existe el perfil de camara: {args.profile}")
        profile = load_camera_profile(profile_path)
    else:
        profiles = list_camera_profiles(PROFILE_DIR)
        if profiles:
            profile = load_camera_profile(profiles[0])
        else:
            if args.source is None:
                raise RuntimeError(
                    "No hay perfiles guardados. Ejecuta camera_setup.py o indica --source y --calibration."
                )
            calibration_path = Path(args.calibration) if args.calibration else DEFAULT_CALIBRATION_PATH
            profile = CameraProfile(
                name="runtime",
                source=int(args.source) if str(args.source).isdigit() else args.source,
                width=args.width,
                height=args.height,
                fps=args.fps,
                calibration=load_calibration(calibration_path),
            )

    if args.source is not None:
        profile.source = int(args.source) if str(args.source).isdigit() else args.source
    if args.calibration:
        profile.calibration = load_calibration(args.calibration)
    if profile.calibration is None:
        raise RuntimeError("El detector en vivo necesita una calibracion de camara.")
    if args.width is not None:
        profile.width = args.width
    if args.height is not None:
        profile.height = args.height
    if args.fps is not None:
        profile.fps = args.fps
    return _align_profile_resolution_with_calibration(profile)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Detector ArUco 3D limpio y extensible")
    parser.add_argument("--layout", default=str(DEFAULT_LAYOUT_PATH), help="JSON con el layout de marcadores")
    parser.add_argument("--profile", default=None, help="Perfil de camara guardado o ruta directa al JSON")
    parser.add_argument("--source", default=None, help="Indice o ruta de video")
    parser.add_argument("--calibration", default=None, help="JSON de calibracion si no se usa perfil")
    parser.add_argument("--width", type=int, default=None, help="Resolucion objetivo en ancho")
    parser.add_argument("--height", type=int, default=None, help="Resolucion objetivo en alto")
    parser.add_argument("--fps", type=float, default=None, help="FPS objetivo")
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)

    layout = load_marker_layout(args.layout)
    profile = _load_runtime_profile(args)
    detector = ArucoDetector(
        calibration=profile.calibration,
        dictionary_name=layout.aruco_dict,
        marker_size_m=layout.marker_size_m,
    )

    cap = open_video_source(
        profile.source,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
    )
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir la fuente de video: {profile.source}")

    window_name = "Detector ArUco 3D"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1650, 940)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break

            detections = detector.detect(frame)
            pose = estimate_best_pose(
                layout=layout,
                detections=detections,
                calibration=profile.calibration,
                selected_marker_ids=layout.ids,
                required_markers=1,
            )
            annotated = detector.draw_on_frame(frame, detections)

            current_position = pose.position_world if pose is not None else None
            highlighted_ids = [detection.marker_id for detection in detections if detection.marker_id in layout.ids]
            topdown = render_topdown_panel(
                layout=layout,
                expected_position=None,
                current_position=current_position,
                highlighted_ids=highlighted_ids,
                title="Mapa de referencias",
            )

            if pose is not None:
                roll, pitch, yaw = pose.euler_deg
                lines = [
                    f"Fuente: {profile.source}",
                    f"Marcadores visibles: {len(highlighted_ids)} -> {highlighted_ids}",
                    f"Metodo activo: {pose.method}",
                    f"Reproyeccion: {pose.reprojection_error_px:.3f} px",
                    f"Posicion [m]: x={pose.position_world[0]:+.3f}  y={pose.position_world[1]:+.3f}  z={pose.position_world[2]:+.3f}",
                    f"Orientacion [deg]: roll={roll:+.1f}  pitch={pitch:+.1f}  yaw={yaw:+.1f}",
                    "Tecla q para salir",
                ]
                alerts = ["El layout esta desacoplado del algoritmo y se puede cambiar por JSON."]
            else:
                lines = [
                    f"Fuente: {profile.source}",
                    f"Marcadores visibles: {len(highlighted_ids)} -> {highlighted_ids}",
                    "No se ha podido estimar la pose de la camara.",
                    "Revisa calibracion, iluminacion o visibilidad de los marcadores.",
                    "Tecla q para salir",
                ]
                alerts = ["La aplicacion necesita al menos un marcador conocido para localizar la camara."]

            status = render_status_panel("Estado del detector", lines, alerts=alerts)
            dashboard = compose_dashboard(
                annotated,
                topdown,
                status,
                title="Detector ArUco 3D",
                subtitle=f"{layout.name} | {layout.aruco_dict} | {profile.name}",
            )
            cv2.imshow(window_name, dashboard)

            key = cv2.waitKey(1) & 0xFF
            if key == ord("q"):
                break
    finally:
        cap.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
