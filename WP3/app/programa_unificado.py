"""
Programa unificado para WP3.

Este lanzador centraliza los programas existentes sin duplicar su logica:

  python programa_unificado.py volumetria
  python programa_unificado.py detectar-imagenes
  python programa_unificado.py detectar-video

Cada modo ejecuta el modulo original desde su carpeta para respetar las rutas
relativas actuales de modelos, imagenes y resultados.
"""

from __future__ import annotations

import argparse
import contextlib
import importlib
import os
import sys
from pathlib import Path


WP3_DIR = Path(__file__).resolve().parents[1]
DETECCION_DIR = WP3_DIR / "deteccion_cajas"
VOLUMETRIA_DIR = WP3_DIR / "volumetria"


@contextlib.contextmanager
def working_directory(path: Path):
    previous = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(previous)


def add_import_path(path: Path) -> None:
    path_str = str(path)
    if path_str not in sys.path:
        sys.path.insert(0, path_str)


def require_file(path: Path, description: str) -> None:
    if not path.exists():
        raise FileNotFoundError(
            f"No se encontro {description}: {path}\n"
            "Revisa que el archivo exista o ajusta la ruta con los argumentos del comando."
        )


def require_dir(path: Path, description: str) -> None:
    if not path.exists() or not path.is_dir():
        raise FileNotFoundError(
            f"No se encontro {description}: {path}\n"
            "Revisa que la carpeta exista o ajusta la ruta con los argumentos del comando."
        )


def configure_volumetria(module, args: argparse.Namespace) -> None:
    module.GRAVAR_NOU_VIDEO = args.grabar_video
    module.FONT_VIDEO = args.fuente_video
    module.INTERVAL_CAPTURA_SEG = args.intervalo
    module.DISTANCIA_LIDAR_CM = args.distancia_lidar
    module.CARPETA_FOTOS = str(args.fotos)
    module.CARPETA_RESULTATS = str(args.resultados)
    module.MANIFEST_CSV = str(args.manifest)
    module.GDINO_CONFIG = str(args.gdino_config)
    module.GDINO_WEIGHTS = str(args.gdino_weights)


def run_volumetria(args: argparse.Namespace) -> None:
    add_import_path(VOLUMETRIA_DIR)

    manifest = Path(args.manifest)
    if not manifest.is_absolute():
        manifest = VOLUMETRIA_DIR / manifest
    args.manifest = manifest

    gdino_config = DETECCION_DIR / args.gdino_config
    gdino_weights = DETECCION_DIR / args.gdino_weights
    require_file(gdino_config, "configuracion GroundingDINO para volumetria")
    require_file(gdino_weights, "pesos GroundingDINO para volumetria")
    require_file(VOLUMETRIA_DIR / "models" / "mobile_sam.pt", "modelo MobileSAM de volumetria")
    require_file(manifest, "manifest CSV")
    args.gdino_config = gdino_config
    args.gdino_weights = gdino_weights
    if not args.grabar_video:
        fotos = Path(args.fotos)
        if not fotos.is_absolute():
            fotos = VOLUMETRIA_DIR / fotos
        require_dir(fotos, "carpeta de fotos de volumetria")

    with working_directory(VOLUMETRIA_DIR):
        module = importlib.import_module("volumetria_BLOC0_1")
        configure_volumetria(module, args)
        module.executar_pipeline_orquestrat()


def configure_detector_images(module, args: argparse.Namespace) -> None:
    module.CONFIG_PATH = str(args.config)
    module.WEIGHTS_PATH = str(args.weights)
    module.FOTOS_DIR = str(args.fotos)
    module.IMAGE_NAME = args.imagen
    module.OUTPUT_BASE = str(args.resultados)
    module.TEXT_PROMPT = args.prompt
    module.BOX_THRESHOLD = args.box_threshold
    module.TEXT_THRESHOLD = args.text_threshold
    module.MIN_BOX_SIZE = args.min_box_size
    module.MAX_BOX_ASPECT_RATIO = args.max_aspect_ratio


def run_detectar_imagenes(args: argparse.Namespace) -> None:
    add_import_path(DETECCION_DIR)

    config = DETECCION_DIR / args.config
    weights = DETECCION_DIR / args.weights
    fotos = DETECCION_DIR / args.fotos

    require_file(config, "configuracion GroundingDINO")
    require_file(weights, "pesos GroundingDINO")
    require_file(DETECCION_DIR / "models" / "mobile_sam.pt", "modelo MobileSAM de deteccion")
    require_dir(fotos, "carpeta de imagenes de deteccion")

    args.config = config
    args.weights = weights

    with working_directory(DETECCION_DIR):
        module = importlib.import_module("prueba_detector_almacen2")
        configure_detector_images(module, args)
        module.main()


def configure_detector_video(module, args: argparse.Namespace) -> None:
    module.CONFIG_PATH = str(args.config)
    module.WEIGHTS_PATH = str(args.weights)
    module.STREAM_URL = args.fuente_video
    module.OUTPUT_BASE = str(args.resultados)
    module.SAVE_ON_DETECTION = args.guardar_detecciones
    module.PROCESS_WIDTH = args.ancho_proceso
    module.FRAME_SKIP = args.frame_skip
    module.DISPLAY_SCALE = args.escala_visualizacion
    module.ENABLE_SAM_REALTIME = args.sam
    module.TEXT_PROMPT = args.prompt
    module.BOX_THRESHOLD = args.box_threshold
    module.TEXT_THRESHOLD = args.text_threshold
    module.MIN_BOX_SIZE = args.min_box_size
    module.MAX_BOX_ASPECT_RATIO = args.max_aspect_ratio


def run_detectar_video(args: argparse.Namespace) -> None:
    add_import_path(DETECCION_DIR)

    config = DETECCION_DIR / args.config
    weights = DETECCION_DIR / args.weights
    require_file(config, "configuracion GroundingDINO")
    require_file(weights, "pesos GroundingDINO")
    if args.sam:
        require_file(DETECCION_DIR / "models" / "mobile_sam.pt", "modelo MobileSAM de deteccion")

    args.config = config
    args.weights = weights

    with working_directory(DETECCION_DIR):
        module = importlib.import_module("detector_video_almacen")
        configure_detector_video(module, args)
        module.main()


def add_common_detector_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", default="groundingdino/config/GroundingDINO_SwinT_OGC.py")
    parser.add_argument("--weights", default="weights/groundingdino_swint_ogc.pth")
    parser.add_argument(
        "--prompt",
        default="cardboard box . box . carton . stacked cardboard box . warehouse package . pallet .",
    )
    parser.add_argument("--box-threshold", type=float, default=0.19)
    parser.add_argument("--text-threshold", type=float, default=0.3)
    parser.add_argument("--min-box-size", type=float, default=0.06)
    parser.add_argument("--max-aspect-ratio", type=float, default=2.2)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Programa unificado de WP3: volumetria, deteccion en imagenes y deteccion en video."
    )
    subparsers = parser.add_subparsers(dest="modo", required=True)

    volumetria = subparsers.add_parser("volumetria", help="Ejecuta el pipeline completo de volumetria.")
    volumetria.add_argument("--grabar-video", action=argparse.BooleanOptionalAction, default=True)
    volumetria.add_argument("--fuente-video", default="tcp://172.20.10.2:8888")
    volumetria.add_argument("--intervalo", type=float, default=1.0)
    volumetria.add_argument("--distancia-lidar", type=float, default=120.0)
    volumetria.add_argument("--fotos", default="data/fotos_capturades")
    volumetria.add_argument("--resultados", default="outputs/Resultats_BLOC0")
    volumetria.add_argument("--manifest", default="data/etiquetes_magatzem_simulades_manifest.csv")
    volumetria.add_argument("--gdino-config", default="groundingdino/config/GroundingDINO_SwinT_OGC.py")
    volumetria.add_argument("--gdino-weights", default="weights/groundingdino_swint_ogc.pth")
    volumetria.set_defaults(func=run_volumetria)

    detectar_imagenes = subparsers.add_parser(
        "detectar-imagenes",
        help="Ejecuta GroundingDINO + SAM sobre imagenes de deteccion_cajas.",
    )
    add_common_detector_args(detectar_imagenes)
    detectar_imagenes.add_argument("--fotos", default="data/mis_imagenes")
    detectar_imagenes.add_argument("--imagen", default=None, help="Nombre de una imagen concreta. Si se omite, procesa todas.")
    detectar_imagenes.add_argument("--resultados", default="outputs/comparacion_resultados")
    detectar_imagenes.set_defaults(func=run_detectar_imagenes)

    detectar_video = subparsers.add_parser(
        "detectar-video",
        help="Ejecuta deteccion de cajas en tiempo real desde un stream.",
    )
    add_common_detector_args(detectar_video)
    detectar_video.add_argument("--fuente-video", default="http://192.168.1.100:8080/video")
    detectar_video.add_argument("--resultados", default="capturas_realtime")
    detectar_video.add_argument("--guardar-detecciones", action=argparse.BooleanOptionalAction, default=True)
    detectar_video.add_argument("--ancho-proceso", type=int, default=800)
    detectar_video.add_argument("--frame-skip", type=int, default=3)
    detectar_video.add_argument("--escala-visualizacion", type=float, default=1.0)
    detectar_video.add_argument("--sam", action=argparse.BooleanOptionalAction, default=False)
    detectar_video.set_defaults(func=run_detectar_video)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except KeyboardInterrupt:
        print("\nEjecucion interrumpida por el usuario.")
        return 130
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
