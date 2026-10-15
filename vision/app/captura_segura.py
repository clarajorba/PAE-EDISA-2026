"""Captura i directoris de sessió; independent dels models de visió."""

import math
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path


class CaptureError(RuntimeError):
    """La captura no s'ha completat; les sessions anteriors es preserven."""


def crear_directori_sessio(carpeta_base, nom_sessio=None):
    """Reserva un directori nou, també si coincideixen nom o timestamp."""
    base = Path(carpeta_base).resolve()
    nom = (datetime.now(timezone.utc).strftime("sessio_%Y%m%dT%H%M%S_%fZ")
           if nom_sessio is None else nom_sessio)
    if not isinstance(nom, str) or not nom or nom in {".", ".."} or Path(nom).name != nom:
        raise ValueError("El nom de sessió ha de ser un nom de directori simple.")
    base.mkdir(parents=True, exist_ok=True)
    index = 0
    while True:
        desti = base / (nom if index == 0 else f"{nom}_{index:03d}")
        try:
            desti.mkdir(exist_ok=False)
            return desti
        except FileExistsError:
            index += 1


def _validar_font(font_video):
    try:
        font = os.fspath(font_video)
    except TypeError as exc:
        raise CaptureError("La font de vídeo ha de ser un fitxer o una URL.") from exc
    if not isinstance(font, str) or not font.strip():
        raise CaptureError("La font de vídeo és buida o invàlida.")
    if "://" in font:
        return font, False
    path = Path(font).resolve()
    if not path.is_file():
        raise CaptureError(f"El vídeo no existeix o no és un fitxer: {path}")
    try:
        with path.open("rb"):
            pass
    except OSError as exc:
        raise CaptureError(f"El vídeo no és accessible: {path}: {exc}") from exc
    return str(path), True


def _read_video_metadata(cap, cv2_module):
    """Read optional integer metadata; unsupported/invalid values are unknown."""
    def read_integer(property_name, minimum):
        property_id = getattr(cv2_module, property_name, None)
        if property_id is None:
            return None
        try:
            value = float(cap.get(property_id))
        except Exception:
            return None
        if not math.isfinite(value) or value < minimum:
            return None
        integer = round(value)
        if abs(value - integer) > 1e-3:
            return None
        return integer

    return (read_integer("CAP_PROP_FRAME_COUNT", 1),
            read_integer("CAP_PROP_POS_FRAMES", 0))


def _local_completion_status(expected_frames, frames_read, metadata_consistent):
    """Classify EOF conservatively; metadata is evidence, not a guarantee."""
    if not metadata_consistent:
        return "unverified"
    if frames_read == expected_frames:
        return "completed"
    # An off-by-one count can be a backend estimate: do not reject that video.
    if expected_frames - frames_read <= 1:
        return "unverified"
    raise CaptureError(
        "Terminació prematura sospitada: "
        f"llegits {frames_read} de {expected_frames} frames segons les metadades."
    )


def capturar_frames_de_video(
    carpeta_desti, font_video, interval_seg, *, nom_sessio=None,
    cv2_module=None, mostrar_preview=True,
):
    """Valida la font i guarda frames en una sessió nova; retorna el seu Path.

    No modifica fitxers existents. Si falla després de començar, conserva la
    sessió parcial i informa de la seva ubicació. El retorn continua sent Path:
    EOF verificat, final no verificable i aturada amb 'q' es diferencien als
    missatges. KeyboardInterrupt es propaga; la pèrdua del stream és un error.
    """
    try:
        interval = float(interval_seg)
    except (TypeError, ValueError) as exc:
        raise CaptureError("L'interval de captura ha de ser positiu i finit.") from exc
    if not math.isfinite(interval) or interval <= 0:
        raise CaptureError("L'interval de captura ha de ser positiu i finit.")
    font, es_fitxer = _validar_font(font_video)
    if cv2_module is None:
        import cv2 as cv2_module

    cap = None
    sessio = None
    finestra = "Captura en Directe (BLOC 0)"
    try:
        if es_fitxer:
            cap = cv2_module.VideoCapture(font)
        else:
            # OpenCV només admet aquests timeouts en FFmpeg/GStreamer i en obrir.
            try:
                params = [cv2_module.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                          cv2_module.CAP_PROP_READ_TIMEOUT_MSEC, 5000]
                cap = cv2_module.VideoCapture(font, cv2_module.CAP_ANY, params)
            except AttributeError as exc:
                raise CaptureError("OpenCV no suporta els timeouts necessaris per al stream.") from exc
        if not cap.isOpened():
            raise CaptureError(f"OpenCV no pot obrir la font de vídeo: {font}")
        if not es_fitxer and cap.getBackendName() not in {"FFMPEG", "GSTREAMER"}:
            raise CaptureError("El stream necessita un backend FFmpeg o GStreamer amb timeouts.")
        cap.set(cv2_module.CAP_PROP_BUFFERSIZE, 1)
        ok, frame = cap.read()
        if not ok or frame is None or getattr(frame, "size", 1) == 0:
            raise CaptureError(f"No s'ha pogut llegir el primer fotograma: {font}")

        fps = 0.0
        if es_fitxer:
            fps = cap.get(cv2_module.CAP_PROP_FPS)
            if not isinstance(fps, (int, float)) or not math.isfinite(fps) or fps <= 0:
                raise CaptureError("No es pot determinar l'FPS del vídeo per respectar l'interval.")

        frames_read = 1
        expected_frames = None
        metadata_consistent = False
        if es_fitxer:
            expected_frames, position = _read_video_metadata(cap, cv2_module)
            metadata_consistent = expected_frames is not None and position == frames_read

        # La carpeta no es prepara fins que la font retorna una imatge vàlida.
        sessio = crear_directori_sessio(carpeta_desti, nom_sessio)
        print(f"Captures de la nova sessió: {sessio}")
        index_frame = 0
        guardats = 0
        ultim_guardat = None
        completion_status = None

        while True:
            # Per als vídeos locals, mostrejar temps de vídeo, no velocitat de CPU.
            instant = index_frame / fps if es_fitxer else time.monotonic()
            if ultim_guardat is None or instant - ultim_guardat + 1e-9 >= interval:
                ok, jpeg = cv2_module.imencode(".jpg", frame)
                if not ok or jpeg is None:
                    raise CaptureError("OpenCV no ha pogut codificar el fotograma JPEG.")
                dades = jpeg.tobytes()
                if not dades:
                    raise CaptureError("OpenCV ha retornat un fotograma JPEG buit.")
                ruta = sessio / f"frame_{guardats + 1:04d}.jpg"
                # 'xb' rebutja qualsevol fitxer existent, en lloc de substituir-lo.
                with ruta.open("xb") as fitxer:
                    fitxer.write(dades)
                guardats += 1
                ultim_guardat = instant

            if mostrar_preview:
                visual = frame.copy()
                cv2_module.putText(
                    visual, "Gravant... Prem 'q' per aturar", (10, 30),
                    cv2_module.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 255), 2,
                )
                cv2_module.imshow(finestra, visual)
                if cv2_module.waitKey(1) & 0xFF == ord("q"):
                    completion_status = "interrupted"
                    break

            ok, frame = cap.read()
            if not ok or frame is None or getattr(frame, "size", 1) == 0:
                if es_fitxer and not ok:
                    count, position = _read_video_metadata(cap, cv2_module)
                    metadata_consistent = (metadata_consistent
                                           and count == expected_frames
                                           and position == frames_read)
                    completion_status = _local_completion_status(
                        expected_frames, frames_read, metadata_consistent,
                    )
                    break
                raise CaptureError(f"S'ha interromput la lectura del vídeo: {font}")
            index_frame += 1
            frames_read += 1
            if es_fitxer:
                count, position = _read_video_metadata(cap, cv2_module)
                metadata_consistent = (metadata_consistent
                                       and count == expected_frames
                                       and position == frames_read
                                       and count >= frames_read)

        if completion_status == "completed":
            print(f"Captura completada (EOF verificat segons les metadades): "
                  f"{guardats} fotografies a {sessio}")
        elif completion_status == "interrupted":
            print(f"Captura interrompuda per l'usuari ('q'): {guardats} fotografies. "
                  f"Sessió parcial conservada a: {sessio}")
        else:
            print(f"Captura finalitzada amb completitud no verificada: "
                  f"metadades absents, inconsistents o recompte aproximat. "
                  f"{guardats} fotografies conservades a: {sessio}", file=sys.stderr)
        return sessio
    except KeyboardInterrupt:
        if sessio is not None:
            print(f"Captura interrompuda per l'usuari (KeyboardInterrupt). "
                  f"Sessió parcial conservada a: {sessio}", file=sys.stderr)
        else:
            print("Captura interrompuda per l'usuari abans de crear cap sessió.",
                  file=sys.stderr)
        raise
    except Exception as exc:
        parcial = f" Sessió parcial conservada a: {sessio}." if sessio else ""
        raise CaptureError(f"Error de captura: {exc}.{parcial}") from exc
    finally:
        if cap is not None:
            try:
                cap.release()
            except Exception as exc:
                print(f"Avís: no s'ha pogut alliberar la font: {exc}", file=sys.stderr)
        if mostrar_preview:
            try:
                cv2_module.destroyAllWindows()
            except Exception as exc:
                print(f"Avís: no s'ha pogut tancar la previsualització: {exc}", file=sys.stderr)
