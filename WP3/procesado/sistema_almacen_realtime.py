from __future__ import annotations

import argparse
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import torch

from codigos_qr import (
    actualizar_inventario,
    detectar_codigos_frame,
    dibujar_estado_inventario,
    inicializar_estado_inventario,
    tipus_prioritaris_per_estat,
)
from detector_cajas import (
    DetectorConfig,
    cargar_modelo_detector,
    procesar_frame_detector,
    resegmentar_detecciones_cacheadas,
)
from segmentador_contornos import cargar_segmentador
from volumetria_BLOC0_1 import (
    VolumetriaRuntimeConfig,
    inicializar_estado_volumetria,
    procesar_frame_volumetria,
)
from volumetria_BLOC3_1 import LidarConfig


class CameraStream:
    def __init__(self, source: str):
        self.source = source
        self.cap = None
        self.frame = None
        self.lock = threading.Lock()
        self.running = False
        self.connected = False
        self.thread = None

    def start(self, timeout_s: float = 10.0) -> bool:
        self.running = True
        self.thread = threading.Thread(target=self._capture_loop, daemon=True)
        self.thread.start()

        start = time.time()
        while not self.connected and (time.time() - start) < timeout_s:
            time.sleep(0.1)

        return self.connected

    def _open_capture(self):
        source = self.source
        if source.isdigit():
            source = int(source)
        self.cap = cv2.VideoCapture(source)
        self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)

    def _capture_loop(self) -> None:
        while self.running:
            if self.cap is None or not self.cap.isOpened():
                self._open_capture()
                self.connected = self.cap.isOpened()
                if not self.connected:
                    time.sleep(1.0)
                    continue

            ret, frame = self.cap.read()
            if ret:
                with self.lock:
                    self.frame = frame
                self.connected = True
                continue

            self.connected = False
            if self.cap is not None:
                self.cap.release()
            self.cap = None
            time.sleep(0.5)

    def get_frame(self):
        with self.lock:
            if self.frame is None:
                return None
            return self.frame.copy()

    def stop(self) -> None:
        self.running = False
        if self.thread is not None:
            self.thread.join(timeout=1.0)
        if self.cap is not None:
            self.cap.release()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Pipeline unificat de magatzem en temps real")
    parser.add_argument("--source", default="tcp://127.0.0.1:8888", help="Font de video, per exemple tcp://IP:8888")
    parser.add_argument("--frame-skip-detection", type=int, default=5, help="Executa el detector pesat cada N frames")
    parser.add_argument("--barcode-skip", type=int, default=3, help="Executa el detector de codis cada N frames")
    parser.add_argument("--process-width", type=int, default=960, help="Amplada de processament per al detector")
    parser.add_argument("--display-scale", type=float, default=1.0, help="Escala del visor")
    parser.add_argument("--torch-threads", type=int, default=4, help="Threads CPU de Torch")
    parser.add_argument("--disable-sam", action="store_true", help="Desactiva MobileSAM")
    parser.add_argument("--manifest-path", default="detecció_qr_codi/etiquetes_magatzem_simulades_manifest.csv")
    parser.add_argument("--min-frames-volume", type=int, default=3, help="Frames necessaris per calcular volum")
    parser.add_argument("--headless", action="store_true", help="No obri finestra OpenCV")
    return parser


def _point_inside_detection(point: tuple[int, int], detection: dict) -> bool:
    contour = detection.get("vertices") or detection.get("contorno")
    if contour is not None and len(contour) >= 3:
        contour_np = np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2)
        return cv2.pointPolygonTest(contour_np, point, False) >= 0

    x1, y1, x2, y2 = map(int, detection["bbox_px"])
    return x1 <= point[0] <= x2 and y1 <= point[1] <= y2


def associar_codigos_a_cajas(
    caixas_trakeadas: list[dict],
    codigos: list[dict],
    estado_asociaciones: dict,
    estado_inventario: dict,
    now: float | None = None,
) -> None:
    now = time.time() if now is None else now
    por_id = estado_asociaciones.setdefault("por_id", {})
    ttl_s = estado_asociaciones.get("ttl_s", 10.0)

    expired_ids = [
        box_id
        for box_id, data in por_id.items()
        if (now - data["updated_at"]) > ttl_s
    ]
    for box_id in expired_ids:
        del por_id[box_id]

    for codigo in codigos:
        valor = codigo["valor"]
        if codigo["tipo"] == "CODE39" and valor in estado_inventario["estanteries_valides"]:
            continue

        point = tuple(map(int, codigo["centro"]))
        best_detection = None
        best_distance = float("inf")

        for detection in caixas_trakeadas:
            if not _point_inside_detection(point, detection):
                continue
            distance = np.hypot(point[0] - detection["cx"], point[1] - detection["cy"])
            if distance < best_distance:
                best_distance = distance
                best_detection = detection

        if best_detection is None:
            continue

        product_name = estado_inventario["codigo_a_producto"].get(valor, valor)
        por_id[best_detection["id"]] = {
            "codigo": valor,
            "tipo": codigo["tipo"],
            "producto": product_name,
            "updated_at": now,
        }


def _draw_codes(frame_bgr: np.ndarray, codigos: list[dict]) -> None:
    for codigo in codigos:
        polygon = np.asarray(codigo["polygon"], dtype=np.int32).reshape(-1, 1, 2)
        x, y, _, _ = codigo["bbox"]
        cx, cy = codigo["centro"]
        label = f"{codigo['tipo']}: {codigo['valor']}"

        cv2.polylines(frame_bgr, [polygon], True, (0, 255, 0), 2)
        cv2.circle(frame_bgr, (cx, cy), 4, (0, 0, 255), -1)
        cv2.putText(
            frame_bgr,
            label,
            (x, max(20, y - 10)),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.5,
            (0, 255, 0),
            2,
        )


def _draw_detections(
    frame_bgr: np.ndarray,
    caixas_trakeadas: list[dict],
    associations: dict,
) -> None:
    por_id = associations.get("por_id", {})

    for detection in caixas_trakeadas:
        x1, y1, x2, y2 = map(int, detection["bbox_px"])
        color = tuple(int(value) for value in detection["color"])
        contour = detection.get("vertices") or detection.get("contorno")

        if contour is not None and len(contour) >= 3:
            contour_np = np.asarray(contour, dtype=np.int32).reshape(-1, 1, 2)
            overlay = frame_bgr.copy()
            cv2.fillPoly(overlay, [contour_np], color)
            cv2.addWeighted(overlay, 0.15, frame_bgr, 0.85, 0, frame_bgr)
            cv2.polylines(frame_bgr, [contour_np], True, color, 2)
        else:
            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), color, 2)

        lines = [f"ID {detection['id']}"]
        volumetria = detection.get("volumetria")
        if volumetria is not None:
            lines.append(f"V {volumetria['volum_cm3']:.0f} cm3")

        associated = por_id.get(detection["id"])
        if associated is not None:
            lines.append(associated["producto"][:32])

        for idx, line in enumerate(lines):
            y_text = max(20, y1 - 10 - idx * 18)
            cv2.putText(
                frame_bgr,
                line,
                (x1, y_text),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (0, 0, 0),
                3,
            )
            cv2.putText(
                frame_bgr,
                line,
                (x1, y_text),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                color,
                1,
            )


def _draw_valid_zones(frame_bgr: np.ndarray, valid_zones: list[tuple[int, int]] | None) -> None:
    if not valid_zones:
        return

    width = frame_bgr.shape[1]
    for y_min, y_max in valid_zones:
        cv2.line(frame_bgr, (0, y_min), (width, y_min), (0, 255, 0), 2)
        cv2.line(frame_bgr, (0, y_max), (width, y_max), (0, 0, 255), 2)


def _draw_panel(
    frame_bgr: np.ndarray,
    fps: float,
    detector_meta: dict,
    detections_count: int,
    codes_count: int,
    stream: CameraStream,
    frame_skip_detection: int,
    barcode_skip: int,
) -> None:
    status = "ONLINE" if stream.connected else "RECONNECTANT"
    backend = detector_meta.get("backend", "desconegut")
    lines = [
        f"FPS {fps:.1f} | Stream {status}",
        f"Detector {backend} | Cajas {detections_count} | Codis {codes_count}",
        f"Skip D {frame_skip_detection} | Skip QR {barcode_skip}",
    ]

    overlay = frame_bgr.copy()
    cv2.rectangle(overlay, (0, 0), (500, 90), (0, 0, 0), -1)
    cv2.addWeighted(overlay, 0.45, frame_bgr, 0.55, 0, frame_bgr)

    for index, line in enumerate(lines):
        cv2.putText(
            frame_bgr,
            line,
            (15, 28 + index * 25),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.7,
            (255, 255, 255),
            2,
        )


def _maybe_scale_for_display(frame_bgr: np.ndarray, scale: float) -> np.ndarray:
    if abs(scale - 1.0) < 1e-6:
        return frame_bgr
    return cv2.resize(frame_bgr, (0, 0), fx=scale, fy=scale, interpolation=cv2.INTER_LINEAR)


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    torch.set_num_threads(max(1, args.torch_threads))

    base_dir = Path(__file__).resolve().parent
    manifest_path = Path(args.manifest_path)
    if not manifest_path.is_absolute():
        manifest_path = base_dir / manifest_path

    detector_config = DetectorConfig(
        frame_skip_detection=max(1, args.frame_skip_detection),
        process_width=max(0, args.process_width) or None,
    )
    lidar_config = LidarConfig()
    runtime_config = VolumetriaRuntimeConfig(
        min_frames_per_box=max(1, args.min_frames_volume),
    )

    print("Inicialitzant inventari...")
    estado_inventario = inicializar_estado_inventario(str(manifest_path))
    estado_asociaciones = {"por_id": {}, "ttl_s": 10.0}
    estado_volumetria = inicializar_estado_volumetria(runtime_config)

    print("Carregant detector de caixes...")
    detector_ctx = cargar_modelo_detector(detector_config)
    if detector_ctx.get("warning"):
        print(detector_ctx["warning"])

    segmentador_sam = None
    if not args.disable_sam:
        try:
            print("Carregant MobileSAM...")
            segmentador_sam = cargar_segmentador(str(base_dir / "mobile_sam.pt"))
        except Exception as exc:
            print(f"MobileSAM no disponible, continuem sense segmentacio: {exc}")

    stream = CameraStream(args.source)
    if not stream.start():
        raise RuntimeError(f"No s'ha pogut obrir el stream: {args.source}")

    print("Sistema actiu. Prem 'q' per sortir.")

    frame_count = 0
    fps = 0.0
    fps_window_start = time.time()
    fps_window_frames = 0
    paused = False

    last_detections: list[dict] = []
    last_detector_meta = {"backend": detector_ctx["backend"], "valid_zones": None, "cached": False}
    last_codigos: list[dict] = []

    try:
        while True:
            frame = stream.get_frame()
            if frame is None:
                time.sleep(0.01)
                continue

            frame_count += 1
            now = time.time()

            if not paused:
                if not last_detections or (frame_count % detector_config.frame_skip_detection == 0):
                    last_detections, last_detector_meta = procesar_frame_detector(
                        frame_bgr=frame,
                        modelo_detector=detector_ctx,
                        segmentador_sam=segmentador_sam,
                        config=detector_config,
                    )
                else:
                    last_detections = resegmentar_detecciones_cacheadas(
                        frame_bgr=frame,
                        detecciones_previas=last_detections,
                        segmentador_sam=segmentador_sam,
                    )
                    last_detector_meta = {
                        **last_detector_meta,
                        "cached": True,
                    }

                volumetria_out = procesar_frame_volumetria(
                    frame=frame,
                    detecciones_bloque1=last_detections,
                    estado_tracking=estado_volumetria,
                    config_lidar=lidar_config,
                )
                caixas_trakeadas = volumetria_out["cajas_trakeadas"]

                if frame_count % max(1, args.barcode_skip) == 0:
                    last_codigos = detectar_codigos_frame(
                        frame_bgr=frame,
                        tipos_prioritarios=tipus_prioritaris_per_estat(estado_inventario),
                    )
                    actualizar_inventario(last_codigos, estado_inventario, now)
                    associar_codigos_a_cajas(
                        caixas_trakeadas,
                        last_codigos,
                        estado_asociaciones,
                        estado_inventario,
                        now,
                    )
            else:
                caixas_trakeadas = []

            frame_vis = frame.copy()
            _draw_valid_zones(frame_vis, last_detector_meta.get("valid_zones"))
            _draw_detections(frame_vis, caixas_trakeadas, estado_asociaciones)
            _draw_codes(frame_vis, last_codigos)
            dibujar_estado_inventario(frame_vis, estado_inventario)
            _draw_panel(
                frame_vis,
                fps=fps,
                detector_meta=last_detector_meta,
                detections_count=len(caixas_trakeadas),
                codes_count=len(last_codigos),
                stream=stream,
                frame_skip_detection=detector_config.frame_skip_detection,
                barcode_skip=max(1, args.barcode_skip),
            )

            fps_window_frames += 1
            elapsed = now - fps_window_start
            if elapsed >= 1.0:
                fps = fps_window_frames / elapsed
                fps_window_frames = 0
                fps_window_start = now

            if not args.headless:
                display = _maybe_scale_for_display(frame_vis, args.display_scale)
                cv2.imshow("Almacen realtime", display)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("p"):
                    paused = not paused
            else:
                time.sleep(0.001)

    finally:
        stream.stop()
        if not args.headless:
            cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
