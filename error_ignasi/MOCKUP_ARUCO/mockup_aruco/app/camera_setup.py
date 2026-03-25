from __future__ import annotations

from pathlib import Path

import cv2

from ..camera.calibration import ChessboardSettings, load_calibration, run_chessboard_calibration
from ..camera.discovery import discover_cameras, open_video_source
from ..camera.profiles import save_camera_profile
from ..core.models import CameraProfile
from .cli import (
    print_header,
    prompt_choice,
    prompt_float,
    prompt_int,
    prompt_text,
    prompt_yes_no,
)


BASE_DIR = Path(__file__).resolve().parents[2]
PROFILE_DIR = BASE_DIR / "config" / "camera_profiles"
DEFAULT_CALIBRATION_PATH = BASE_DIR / "config" / "camera_calibration.json"


def _align_profile_resolution_with_calibration(profile: CameraProfile) -> CameraProfile:
    if profile.calibration is None or profile.calibration.image_size is None:
        return profile

    calib_width, calib_height = profile.calibration.image_size
    if profile.width != calib_width or profile.height != calib_height:
        print(
            "\nAviso: ajusto el perfil a la resolucion de la calibracion "
            f"({calib_width}x{calib_height}) para evitar sesgos geometricos."
        )
        profile.width = calib_width
        profile.height = calib_height
    return profile


def _parse_source(raw_value: str) -> int | str:
    try:
        return int(raw_value)
    except ValueError:
        return raw_value


def preview_camera(source: int | str, width: int | None = None, height: int | None = None, fps: float | None = None) -> tuple[int, int, float] | None:
    """Abre una vista previa para confirmar la camara seleccionada."""
    cap = open_video_source(source, width=width, height=height, fps=fps)
    if not cap.isOpened():
        print("No se pudo abrir la camara seleccionada.")
        return None

    window_name = "Vista previa de camara"
    cv2.namedWindow(window_name, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window_name, 1100, 760)

    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                print("No se pudo leer imagen de la camara.")
                return None

            display = frame.copy()
            cv2.putText(
                display,
                "Pulsa s para confirmar esta camara o q para cancelar",
                (20, 38),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.72,
                (90, 255, 170),
                2,
                cv2.LINE_AA,
            )
            cv2.imshow(window_name, display)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)) or frame.shape[1]
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)) or frame.shape[0]
                fps = float(cap.get(cv2.CAP_PROP_FPS) or 30.0)
                return width, height, fps
            if key == ord("q"):
                return None
    finally:
        cap.release()
        cv2.destroyAllWindows()


def run_camera_setup_interactive() -> CameraProfile | None:
    """Asistente interactivo para descubrir, probar y calibrar la camara."""
    print_header(
        "CONFIGURACION DE CAMARA",
        "Identificacion, conexion, vista previa y calibracion para el proyecto.",
    )

    cameras = discover_cameras()
    if cameras:
        print("Camaras detectadas:")
        for descriptor in cameras:
            fps_text = f"{descriptor.fps:.1f}" if descriptor.fps > 0 else "n/d"
            backend_text = descriptor.backend_name or "backend por defecto"
            print(
                f"  - fuente={descriptor.source} | {descriptor.width}x{descriptor.height} | "
                f"fps={fps_text} | {backend_text}"
            )
        default_source = str(cameras[0].source)
    else:
        print("No se detectaron camaras automaticamente. Puedes introducir un indice o una ruta manual.")
        default_source = "0"

    source = _parse_source(prompt_text("Fuente de camara (indice o ruta)", default=default_source))
    preview = preview_camera(source)
    if preview is None:
        print("Configuracion cancelada por el usuario.")
        return None

    width, height, fps = preview
    profile_name = prompt_text(
        "Nombre del perfil de camara",
        default=f"camera_{source}",
    )
    notes = prompt_text("Notas del perfil", default="", allow_empty=True)

    calibration = None
    calibration_option = prompt_choice(
        "Que quieres hacer con la calibracion de la camara?",
        [
            "Usar calibracion existente",
            "Calibrar ahora con tablero de ajedrez",
            "Guardar sin calibracion",
        ],
        default=0 if DEFAULT_CALIBRATION_PATH.exists() else 1,
    )

    if calibration_option == "Usar calibracion existente":
        calibration_path = Path(
            prompt_text(
                "Ruta al JSON de calibracion",
                default=str(DEFAULT_CALIBRATION_PATH),
            )
        )
        calibration = load_calibration(calibration_path)
    elif calibration_option == "Calibrar ahora con tablero de ajedrez":
        board_width = prompt_int("Esquinas interiores horizontales", default=7, minimum=2)
        board_height = prompt_int("Esquinas interiores verticales", default=7, minimum=2)
        square_size = prompt_float("Tamano real del cuadrado [m]", default=0.01, minimum=0.001)
        min_captures = prompt_int("Capturas minimas recomendadas", default=15, minimum=4)
        settings = ChessboardSettings(
            board_size=(board_width, board_height),
            square_size_m=square_size,
            min_captures=min_captures,
        )
        calibration = run_chessboard_calibration(
            source=source,
            settings=settings,
            output_path=DEFAULT_CALIBRATION_PATH,
        )

    profile = CameraProfile(
        name=profile_name,
        source=source,
        width=width,
        height=height,
        fps=fps if fps > 0 else 30.0,
        calibration=calibration,
        notes=notes,
    )
    profile = _align_profile_resolution_with_calibration(profile)

    profile_path = PROFILE_DIR / f"{profile_name}.json"
    save_camera_profile(profile, profile_path)

    print("\nPerfil guardado correctamente:")
    print(f"  {profile_path}")
    if calibration is None:
        print("  Aviso: el perfil se ha guardado sin calibracion. El benchmark de error funcionara mejor con calibracion.")
    return profile


def main() -> None:
    run_camera_setup_interactive()


if __name__ == "__main__":
    main()
