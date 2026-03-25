from __future__ import annotations

from pathlib import Path

import cv2
import matplotlib.pyplot as plt
import numpy as np

from ..camera.calibration import ChessboardSettings, load_calibration, run_chessboard_calibration
from ..camera.discovery import open_video_source
from ..camera.profiles import list_camera_profiles, load_camera_profile
from ..core.aruco import ArucoDetector, aruco_dictionary_names
from ..core.config_io import save_marker_layout
from ..core.models import CameraProfile, MarkerDefinition, MarkerLayout, SampleRecord, TestDefinition, as_vector
from ..core.pose import estimate_multi_marker_pose, estimate_weighted_pose
from ..core.session_io import create_session_directory, save_samples_csv, save_summary_json
from ..core.statistics import compare_summaries, compute_test_summary
from ..viz.dashboard import compose_dashboard, render_status_panel, render_topdown_panel
from ..viz.plots import create_comparison_report, create_test_report
from .camera_setup import DEFAULT_CALIBRATION_PATH, PROFILE_DIR, run_camera_setup_interactive
from .cli import (
    print_header,
    prompt_choice,
    prompt_float,
    prompt_int,
    prompt_int_list,
    prompt_text,
    prompt_yes_no,
)


BASE_DIR = Path(__file__).resolve().parents[2]
RESULTS_DIR = BASE_DIR / "results"
WINDOW_NAME = "Benchmark de error de pose"


def _align_profile_resolution_with_calibration(profile: CameraProfile) -> CameraProfile:
    if profile.calibration is None or profile.calibration.image_size is None:
        return profile

    calib_width, calib_height = profile.calibration.image_size
    if profile.width != calib_width or profile.height != calib_height:
        print(
            "\nAviso: el perfil estaba en "
            f"{profile.width}x{profile.height}, pero la calibracion es de "
            f"{calib_width}x{calib_height}. Se usara la resolucion de calibracion."
        )
        profile.width = calib_width
        profile.height = calib_height
    return profile


def _select_camera_profile() -> CameraProfile:
    profiles = list_camera_profiles(PROFILE_DIR)
    if not profiles:
        print("No hay perfiles de camara guardados.")
        if not prompt_yes_no("Quieres crear uno ahora con el asistente de camara?", default=True):
            raise RuntimeError("El benchmark necesita un perfil de camara calibrado.")
        profile = run_camera_setup_interactive()
        if profile is None:
            raise RuntimeError("No se pudo crear el perfil de camara.")
        return profile

    print("\nPerfiles de camara disponibles:")
    for index, profile_path in enumerate(profiles, start=1):
        print(f"  {index}. {profile_path.stem}")
    print(f"  {len(profiles) + 1}. Crear perfil nuevo")

    choice = prompt_int("Selecciona un perfil", default=1, minimum=1)
    if choice == len(profiles) + 1:
        profile = run_camera_setup_interactive()
        if profile is None:
            raise RuntimeError("No se pudo crear el perfil de camara.")
        return profile
    if choice < 1 or choice > len(profiles):
        raise RuntimeError("Seleccion de perfil no valida.")

    return load_camera_profile(profiles[choice - 1])


def _ensure_calibration(profile: CameraProfile) -> CameraProfile:
    if profile.calibration is not None:
        return _align_profile_resolution_with_calibration(profile)

    print("\nEl perfil seleccionado no tiene calibracion.")
    if DEFAULT_CALIBRATION_PATH.exists() and prompt_yes_no(
        "Quieres cargar la calibracion por defecto del proyecto?",
        default=True,
    ):
        profile.calibration = load_calibration(DEFAULT_CALIBRATION_PATH)
        return profile

    if not prompt_yes_no("Quieres calibrar la camara ahora?", default=True):
        raise RuntimeError("No se puede medir el error de pose sin calibracion.")

    board_width = prompt_int("Esquinas interiores horizontales", default=7, minimum=2)
    board_height = prompt_int("Esquinas interiores verticales", default=7, minimum=2)
    square_size = prompt_float("Tamano real del cuadrado [m]", default=0.01, minimum=0.001)
    min_captures = prompt_int("Capturas minimas recomendadas", default=15, minimum=4)
    profile.calibration = run_chessboard_calibration(
        source=profile.source,
        settings=ChessboardSettings(
            board_size=(board_width, board_height),
            square_size_m=square_size,
            min_captures=min_captures,
        ),
        output_path=DEFAULT_CALIBRATION_PATH,
    )
    if profile.calibration is None:
        raise RuntimeError("La calibracion no se pudo completar.")
    return _align_profile_resolution_with_calibration(profile)


def _prompt_camera_position(default: np.ndarray | list[float]) -> np.ndarray:
    default = np.asarray(default, dtype=np.float64).reshape(3)
    print("\nPosicion esperada de la camara en el sistema de referencia del test:")
    x = prompt_float("  X [m]", default=float(default[0]))
    y = prompt_float("  Y [m]", default=float(default[1]))
    z = prompt_float("  Z [m]", default=float(default[2]), minimum=0.0)
    return np.array([x, y, z], dtype=np.float64)


def _configure_single_marker_test() -> TestDefinition:
    print_header("TEST 1", "Benchmark estatico con un solo marcador ArUco.")
    dictionaries = aruco_dictionary_names()
    default_dict_index = dictionaries.index("DICT_4X4_1000") if "DICT_4X4_1000" in dictionaries else 0
    dictionary_name = prompt_choice("Selecciona el diccionario ArUco", dictionaries, default=default_dict_index)
    marker_size_m = prompt_float("Lado real del marcador [m]", default=0.12, minimum=0.001)
    marker_id = prompt_int("ID del marcador", default=0, minimum=0)
    duration_s = prompt_float("Duracion del test [s]", default=10.0, minimum=1.0)
    expected_position = _prompt_camera_position([0.0, 0.0, 1.0])

    layout = MarkerLayout(
        name="Single Marker Test",
        aruco_dict=dictionary_name,
        marker_size_m=marker_size_m,
        markers={
            marker_id: MarkerDefinition(
                marker_id=marker_id,
                position=np.array([0.0, 0.0, 0.0], dtype=np.float64),
                label=f"ID{marker_id}",
            )
        },
        spacing_m=None,
        description="Test estatico con un unico marcador en el origen.",
    )
    return TestDefinition(
        name="test_01_single_marker",
        layout=layout,
        expected_camera_position=expected_position,
        duration_s=duration_s,
        required_visible_markers=1,
        selected_marker_ids=[marker_id],
        description="Comparativa base usando un unico ArUco.",
    )


def _create_grid_layout(marker_ids: list[int], rows: int, cols: int, spacing_x: float, spacing_y: float) -> dict[int, MarkerDefinition]:
    markers: dict[int, MarkerDefinition] = {}
    for index, marker_id in enumerate(marker_ids):
        row = index // cols
        col = index % cols
        markers[marker_id] = MarkerDefinition(
            marker_id=marker_id,
            position=np.array([col * spacing_x, row * spacing_y, 0.0], dtype=np.float64),
            label=f"ID{marker_id}",
        )
    return markers


def _configure_multi_marker_test(single_test: TestDefinition) -> TestDefinition:
    print_header("TEST 2", "Benchmark estatico con varios marcadores visibles a la vez.")

    reuse_geometry = prompt_yes_no(
        "Quieres reutilizar diccionario y tamano del test 1?",
        default=True,
    )
    if reuse_geometry:
        dictionary_name = single_test.layout.aruco_dict
        marker_size_m = single_test.layout.marker_size_m
    else:
        dictionaries = aruco_dictionary_names()
        default_dict_index = dictionaries.index("DICT_4X4_1000") if "DICT_4X4_1000" in dictionaries else 0
        dictionary_name = prompt_choice("Selecciona el diccionario ArUco", dictionaries, default=default_dict_index)
        marker_size_m = prompt_float("Lado real del marcador [m]", default=single_test.layout.marker_size_m, minimum=0.001)

    marker_count = prompt_int("Numero de marcadores del test 2", default=4, minimum=2)
    layout_mode = prompt_choice(
        "Como quieres definir la distribucion de los marcadores?",
        ["Rejilla XY", "Manual"],
        default=0,
    )

    default_ids = [single_test.selected_marker_ids[0] + index for index in range(marker_count)]
    marker_ids = prompt_int_list(
        "IDs de los marcadores separados por comas",
        default=default_ids,
    )
    if len(marker_ids) != marker_count:
        raise RuntimeError("Debes indicar exactamente el mismo numero de IDs que marcadores.")

    if layout_mode == "Rejilla XY":
        rows = prompt_int("Numero de filas", default=2, minimum=1)
        cols = prompt_int("Numero de columnas", default=max(2, marker_count // max(rows, 1)), minimum=1)
        if rows * cols < marker_count:
            raise RuntimeError("La rejilla definida no tiene huecos suficientes para todos los marcadores.")
        spacing_x = prompt_float("Separacion horizontal [m]", default=0.4, minimum=0.01)
        spacing_y = prompt_float("Separacion vertical [m]", default=0.4, minimum=0.01)
        markers = _create_grid_layout(marker_ids, rows=rows, cols=cols, spacing_x=spacing_x, spacing_y=spacing_y)
        spacing_m = float((spacing_x + spacing_y) / 2.0)
        description = "Distribucion generada automaticamente en rejilla."
    else:
        markers = {}
        for marker_id in marker_ids:
            print(f"\nMarcador {marker_id}")
            x = prompt_float("  X [m]", default=0.0)
            y = prompt_float("  Y [m]", default=0.0)
            z = prompt_float("  Z [m]", default=0.0)
            markers[marker_id] = MarkerDefinition(
                marker_id=marker_id,
                position=np.array([x, y, z], dtype=np.float64),
                label=f"ID{marker_id}",
            )
        spacing_m = None
        description = "Distribucion manual definida por el usuario."

    if prompt_yes_no("Quieres reutilizar la posicion esperada de la camara del test 1?", default=True):
        expected_position = single_test.expected_camera_position.copy()
    else:
        expected_position = _prompt_camera_position(single_test.expected_camera_position)

    if prompt_yes_no("Quieres reutilizar la duracion del test 1?", default=True):
        duration_s = single_test.duration_s
    else:
        duration_s = prompt_float("Duracion del test [s]", default=10.0, minimum=1.0)

    required_visible = prompt_int(
        "Minimo de marcadores visibles para aceptar una muestra",
        default=min(2, marker_count) if marker_count > 1 else 1,
        minimum=2,
    )

    layout = MarkerLayout(
        name="Multi Marker Test",
        aruco_dict=dictionary_name,
        marker_size_m=marker_size_m,
        markers=markers,
        spacing_m=spacing_m,
        description=description,
    )

    return TestDefinition(
        name="test_02_multi_marker",
        layout=layout,
        expected_camera_position=expected_position,
        duration_s=duration_s,
        required_visible_markers=required_visible,
        selected_marker_ids=marker_ids,
        description="Comparativa usando varios ArUco simultaneos.",
    )


def _estimate_for_test(
    test: TestDefinition,
    detections,
    calibration,
):
    if len(test.selected_marker_ids) > 1 or test.required_visible_markers > 1:
        return estimate_multi_marker_pose(
            layout=test.layout,
            detections=detections,
            calibration=calibration,
            selected_marker_ids=test.selected_marker_ids,
            required_markers=test.required_visible_markers,
        )
    return estimate_weighted_pose(
        layout=test.layout,
        detections=detections,
        selected_marker_ids=test.selected_marker_ids,
        required_markers=1,
    )


def _render_dashboard_for_test(
    frame,
    test: TestDefinition,
    detections,
    estimate,
    title: str,
    subtitle: str,
    status_lines: list[str],
    alerts: list[str] | None = None,
):
    highlighted_ids = [
        detection.marker_id
        for detection in detections
        if detection.marker_id in test.selected_marker_ids
    ]
    current_position = estimate.position_world if estimate is not None else None
    topdown = render_topdown_panel(
        layout=test.layout,
        expected_position=test.expected_camera_position,
        current_position=current_position,
        highlighted_ids=highlighted_ids,
        title="Plano cenital",
    )
    status = render_status_panel("Estado del benchmark", status_lines, alerts=alerts)
    return compose_dashboard(frame, topdown, status, title=title, subtitle=subtitle)


def _preview_test(cap, profile: CameraProfile, test: TestDefinition) -> bool:
    detector = ArucoDetector(
        calibration=profile.calibration,
        dictionary_name=test.layout.aruco_dict,
        marker_size_m=test.layout.marker_size_m,
    )

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1680, 940)

    while True:
        ok, frame = cap.read()
        if not ok:
            return False

        detections = detector.detect(frame)
        estimate = _estimate_for_test(test, detections, profile.calibration)
        annotated = detector.draw_on_frame(frame, detections)
        visible_ids = [detection.marker_id for detection in detections]
        status_lines = [
            f"Perfil: {profile.name} | Fuente: {profile.source}",
            f"Test: {test.name}",
            f"IDs esperados: {test.selected_marker_ids}",
            f"Marcadores visibles ahora: {visible_ids}",
            f"Muestras validas exigen >= {test.required_visible_markers} marcador(es)",
            "Alinea el sistema y pulsa ESPACIO para empezar",
            "Pulsa q para cancelar",
        ]
        alerts = [
            "Este preview sirve para confirmar que la geometria del test es correcta.",
        ]
        dashboard = _render_dashboard_for_test(
            annotated,
            test,
            detections,
            estimate,
            title="Preview del benchmark",
            subtitle=test.description or "Configuracion previa",
            status_lines=status_lines,
            alerts=alerts,
        )
        cv2.imshow(WINDOW_NAME, dashboard)

        key = cv2.waitKey(1) & 0xFF
        if key == ord(" "):
            return True
        if key == ord("q"):
            return False


def _show_countdown(cap, profile: CameraProfile, test: TestDefinition, seconds: int = 3) -> None:
    detector = ArucoDetector(
        calibration=profile.calibration,
        dictionary_name=test.layout.aruco_dict,
        marker_size_m=test.layout.marker_size_m,
    )
    for remaining in range(seconds, 0, -1):
        start_ticks = cv2.getTickCount()
        while (cv2.getTickCount() - start_ticks) / cv2.getTickFrequency() < 1.0:
            ok, frame = cap.read()
            if not ok:
                return
            detections = detector.detect(frame)
            estimate = _estimate_for_test(test, detections, profile.calibration)
            annotated = detector.draw_on_frame(frame, detections)
            cv2.putText(
                annotated,
                str(remaining),
                (annotated.shape[1] // 2 - 40, annotated.shape[0] // 2),
                cv2.FONT_HERSHEY_DUPLEX,
                4.0,
                (0, 230, 255),
                6,
                cv2.LINE_AA,
            )
            status_lines = [
                f"Comenzando en {remaining}",
                f"IDs del test: {test.selected_marker_ids}",
                f"Posicion esperada: {np.array2string(test.expected_camera_position, precision=3)}",
            ]
            dashboard = _render_dashboard_for_test(
                annotated,
                test,
                detections,
                estimate,
                title="Cuenta atras",
                subtitle="Preparando captura de muestras",
                status_lines=status_lines,
            )
            cv2.imshow(WINDOW_NAME, dashboard)
            cv2.waitKey(1)


def _execute_test(cap, profile: CameraProfile, test: TestDefinition) -> tuple[list[SampleRecord], int, bool]:
    detector = ArucoDetector(
        calibration=profile.calibration,
        dictionary_name=test.layout.aruco_dict,
        marker_size_m=test.layout.marker_size_m,
    )

    samples: list[SampleRecord] = []
    attempted_frames = 0
    aborted = False
    start_ticks = cv2.getTickCount()

    while True:
        elapsed = (cv2.getTickCount() - start_ticks) / cv2.getTickFrequency()
        if elapsed >= test.duration_s:
            break

        ok, frame = cap.read()
        if not ok:
            break

        attempted_frames += 1
        detections = detector.detect(frame)
        estimate = _estimate_for_test(test, detections, profile.calibration)
        annotated = detector.draw_on_frame(frame, detections)

        if estimate is not None:
            samples.append(
                SampleRecord(
                    timestamp_s=float(elapsed),
                    frame_index=attempted_frames,
                    position_world=estimate.position_world.copy(),
                    rotation_world=estimate.rotation_world.copy(),
                    visible_marker_ids=list(estimate.visible_marker_ids),
                    reprojection_error_px=float(estimate.reprojection_error_px),
                    method=estimate.method,
                )
            )

        if samples:
            positions = np.vstack([sample.position_world for sample in samples])
            running_mean = np.mean(positions, axis=0)
            running_std = np.std(positions, axis=0, ddof=1) if len(samples) > 1 else np.zeros(3)
        else:
            running_mean = np.zeros(3, dtype=np.float64)
            running_std = np.zeros(3, dtype=np.float64)

        if estimate is not None:
            current_error = np.linalg.norm(estimate.position_world - test.expected_camera_position)
            estimate_line = (
                f"Actual [m]: x={estimate.position_world[0]:+.3f}  "
                f"y={estimate.position_world[1]:+.3f}  z={estimate.position_world[2]:+.3f}"
            )
            error_line = f"Error instantaneo 3D: {current_error:.4f} m | reproj={estimate.reprojection_error_px:.3f} px"
        else:
            estimate_line = "Actual [m]: sin estimacion valida"
            error_line = "Error instantaneo 3D: n/d"

        status_lines = [
            f"Tiempo: {elapsed:5.2f} / {test.duration_s:.2f} s",
            f"Muestras validas: {len(samples)} / {attempted_frames}",
            f"IDs visibles: {[detection.marker_id for detection in detections]}",
            estimate_line,
            error_line,
            f"Media [m]: x={running_mean[0]:+.3f}  y={running_mean[1]:+.3f}  z={running_mean[2]:+.3f}",
            f"STD [m]:   x={running_std[0]:.4f}  y={running_std[1]:.4f}  z={running_std[2]:.4f}",
            "Pulsa q para abortar el test",
        ]
        alerts = None
        if estimate is None:
            alerts = ["No se ha registrado muestra valida en este frame."]

        dashboard = _render_dashboard_for_test(
            annotated,
            test,
            detections,
            estimate,
            title="Captura de benchmark",
            subtitle=test.description,
            status_lines=status_lines,
            alerts=alerts,
        )
        cv2.imshow(WINDOW_NAME, dashboard)

        key = cv2.waitKey(1) & 0xFF
        if key == ord("q"):
            aborted = True
            break

    return samples, attempted_frames, aborted


def _save_test_artifacts(session_dir: Path, test: TestDefinition, samples: list[SampleRecord], summary: dict) -> Path:
    test_dir = session_dir / test.name
    test_dir.mkdir(parents=True, exist_ok=True)
    save_marker_layout(test.layout, test_dir / "layout.json")
    save_samples_csv(samples, test_dir / "samples.csv", expected_position=test.expected_camera_position)
    save_summary_json(summary, test_dir / "summary.json")
    create_test_report(summary, samples, output_path=test_dir / "report.png")
    return test_dir


def run_benchmark_interactive() -> None:
    print_header(
        "BENCHMARK DE ERROR DE POSICION DE CAMARA",
        "Comparativa profesional entre un marcador ArUco y varios marcadores simultaneos.",
    )
    print(
        "Objetivo: medir sesgo, dispersion y estabilidad de la posicion estimada de la camara\n"
        "durante dos tests estaticos de 10 segundos, guardando CSV, JSON y graficas.\n"
    )

    profile = _ensure_calibration(_select_camera_profile())
    single_test = _configure_single_marker_test()
    multi_test = _configure_multi_marker_test(single_test)

    session_dir = create_session_directory(RESULTS_DIR, "pose_error_benchmark")
    print(f"\nLos resultados se guardaran en: {session_dir}")

    cap = open_video_source(
        profile.source,
        width=profile.width,
        height=profile.height,
        fps=profile.fps,
    )
    if not cap.isOpened():
        raise RuntimeError(f"No se pudo abrir la camara/fuente: {profile.source}")

    cv2.namedWindow(WINDOW_NAME, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(WINDOW_NAME, 1680, 940)

    try:
        test_summaries: list[dict] = []
        test_samples: list[list[SampleRecord]] = []

        for index, test in enumerate([single_test, multi_test], start=1):
            if index == 2:
                input("\nPrepara fisicamente el segundo test y pulsa Enter para lanzar la vista previa...")

            print_header(
                f"EJECUTANDO {test.name}",
                f"IDs: {test.selected_marker_ids} | minimo visibles: {test.required_visible_markers}",
            )
            if not _preview_test(cap, profile, test):
                print("Benchmark cancelado antes de iniciar el test.")
                return

            _show_countdown(cap, profile, test, seconds=3)
            samples, attempted_frames, aborted = _execute_test(cap, profile, test)
            summary = compute_test_summary(test, samples, attempted_frames)
            test_dir = _save_test_artifacts(session_dir, test, samples, summary)
            print(f"\nTest guardado en: {test_dir}")

            fig = create_test_report(summary, samples)
            plt.show(block=True)
            plt.close(fig)

            test_summaries.append(summary)
            test_samples.append(samples)

            if aborted:
                print("Benchmark interrumpido por el usuario.")
                return

        comparison = compare_summaries(test_summaries[0], test_summaries[1])
        save_summary_json(comparison, session_dir / "comparison.json")
        comparison_fig = create_comparison_report(
            test_summaries[0],
            test_summaries[1],
            output_path=session_dir / "comparison.png",
        )
        plt.show(block=True)
        plt.close(comparison_fig)

        print_header("BENCHMARK COMPLETADO")
        print(f"Resultados guardados en: {session_dir}")
        print("Archivos principales:")
        print(f"  - {session_dir / single_test.name / 'summary.json'}")
        print(f"  - {session_dir / multi_test.name / 'summary.json'}")
        print(f"  - {session_dir / 'comparison.json'}")
    finally:
        cap.release()
        cv2.destroyAllWindows()


def main() -> None:
    run_benchmark_interactive()


if __name__ == "__main__":
    main()
