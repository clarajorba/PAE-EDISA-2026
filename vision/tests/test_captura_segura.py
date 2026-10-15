"""Regression tests for capture isolation, without a camera or ML imports.

Run from the repository root with:
    python3 -B -m unittest discover -s vision/tests -v
"""

import ast
import builtins
import contextlib
import hashlib
import io
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from vision.app import captura_segura


AUTO_METADATA = object()


class FakeFrame:
    """Only the image attributes used by a capture helper are needed."""

    def __init__(self, payload=b"frame", shape=(2, 2, 3)):
        self.payload = payload
        self.size = len(payload)
        self.shape = shape

    def copy(self):
        return FakeFrame(self.payload, self.shape)

    def __getitem__(self, key):
        return self

    def __setitem__(self, key, value):
        pass


class FakeEncoded:
    def __init__(self, payload):
        self.payload = payload

    def tobytes(self):
        return self.payload


class FakeCapture:
    def __init__(self, frames=(), *, opened=True, fps=30, backend="FFMPEG",
                 frame_count=AUTO_METADATA, positions=None, frame_counts=None,
                 metadata_error=None):
        events = list(frames)
        self.frames = iter(events)
        self.opened = opened
        self.read_calls = 0
        self.release_calls = 0
        self.settings = []
        self.fps = fps
        self.backend = backend
        self.successful_reads = 0
        self.frame_count = (
            sum(
                isinstance(event, tuple) and bool(event[0])
                and event[1] is not None and getattr(event[1], "size", 1) > 0
                for event in events
            ) if frame_count is AUTO_METADATA else frame_count
        )
        self.positions = positions
        self.frame_counts = frame_counts
        self.metadata_error = metadata_error
        self.frame_count_calls = 0

    def isOpened(self):
        return self.opened

    def read(self):
        self.read_calls += 1
        result = next(self.frames, (False, None))
        if isinstance(result, BaseException):
            raise result
        if result[0] and result[1] is not None and getattr(result[1], "size", 1) > 0:
            self.successful_reads += 1
        return result

    def set(self, key, value):
        self.settings.append((key, value))
        return True

    def get(self, key):
        if key == 5:  # CAP_PROP_FPS
            return self.fps
        if self.metadata_error is not None:
            raise self.metadata_error
        if key == 7:  # CAP_PROP_FRAME_COUNT
            self.frame_count_calls += 1
            if self.frame_counts:
                index = min(self.frame_count_calls - 1, len(self.frame_counts) - 1)
                return self.frame_counts[index]
            return self.frame_count
        if key == 1:  # CAP_PROP_POS_FRAMES
            if self.positions:
                index = min(max(self.read_calls - 1, 0), len(self.positions) - 1)
                return self.positions[index]
            return self.successful_reads
        return 0

    def getBackendName(self):
        return self.backend

    def release(self):
        self.release_calls += 1


class FakeCV2:
    """A complete fake of the small OpenCV surface used for video capture."""

    CAP_PROP_BUFFERSIZE = 38
    CAP_PROP_FPS = 5
    CAP_PROP_FRAME_COUNT = 7
    CAP_PROP_POS_FRAMES = 1
    CAP_ANY = 0
    CAP_PROP_OPEN_TIMEOUT_MSEC = 53
    CAP_PROP_READ_TIMEOUT_MSEC = 54
    IMWRITE_JPEG_QUALITY = 1
    FONT_HERSHEY_SIMPLEX = 0

    def __init__(self, frames=(), *, opened=True, encode_ok=True, fps=30,
                 backend="FFMPEG", frame_count=AUTO_METADATA, positions=None,
                 frame_counts=None, metadata_error=None):
        self.capture = FakeCapture(
            frames, opened=opened, fps=fps, backend=backend,
            frame_count=frame_count, positions=positions,
            frame_counts=frame_counts, metadata_error=metadata_error,
        )
        self.encode_ok = encode_ok
        self.sources = []
        self.capture_arguments = []
        self.encoded_frames = []
        self.preview_frames = []
        self.destroy_calls = 0

    def VideoCapture(self, source, *args):
        self.sources.append(source)
        self.capture_arguments.append((source, args))
        return self.capture

    def imencode(self, extension, frame, *args, **kwargs):
        self.encoded_frames.append(frame)
        if not self.encode_ok:
            return False, None
        return True, FakeEncoded(b"jpeg:" + frame.payload)

    def imshow(self, name, frame):
        self.preview_frames.append(frame)

    def putText(self, *args, **kwargs):
        pass

    def waitKey(self, delay):
        return -1

    def destroyAllWindows(self):
        self.destroy_calls += 1


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class CaptureSafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tfg-capture-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.source = self.root / "source.mp4"
        self.source.write_bytes(b"fake local video; never opened by OpenCV")
        self.destination = self.root / "photos"

    def capture(self, fake, **kwargs):
        options = {
            "nom_sessio": "demo",
            "cv2_module": fake,
            "mostrar_preview": False,
        }
        options.update(kwargs)
        return captura_segura.capturar_frames_de_video(
            self.destination, str(self.source), 0.1, **options
        )

    def original_files(self):
        self.destination.mkdir()
        nested = self.destination / "originals"
        nested.mkdir()
        originals = [
            self.destination / "frame_00000.jpg",
            self.destination / "frame00000.jpg",
            self.destination / "manifest.csv",
            nested / "photo.jpeg",
        ]
        for index, path in enumerate(originals):
            path.write_bytes(f"original-{index}".encode())
        return {path: file_hash(path) for path in originals}

    def assert_originals_unchanged(self, originals):
        self.assertEqual(
            originals,
            {path: file_hash(path) for path in originals},
            "capture must not remove or overwrite existing source data",
        )

    def test_missing_local_source_fails_without_creating_destination(self):
        fake = FakeCV2([(True, FakeFrame())])
        with self.assertRaises(captura_segura.CaptureError):
            captura_segura.capturar_frames_de_video(
                self.destination,
                str(self.root / "missing.mp4"),
                0.1,
                cv2_module=fake,
                mostrar_preview=False,
            )
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.sources, [])

    def test_directory_is_not_a_local_video_file(self):
        fake = FakeCV2([(True, FakeFrame())])
        with self.assertRaises(captura_segura.CaptureError):
            captura_segura.capturar_frames_de_video(
                self.destination,
                str(self.root),
                0.1,
                cv2_module=fake,
                mostrar_preview=False,
            )
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.sources, [])

    def test_existing_unreadable_source_fails_before_opening_cv2_or_creating_outputs(self):
        fake = FakeCV2([(True, FakeFrame())])
        source_hash = file_hash(self.source)
        real_io_open = io.open

        def inaccessible_source(file, mode="r", *args, **kwargs):
            if mode == "rb" and Path(file).resolve() == self.source:
                raise PermissionError("simulated inaccessible video file")
            return real_io_open(file, mode, *args, **kwargs)

        with mock.patch("io.open", inaccessible_source):
            with self.assertRaises(captura_segura.CaptureError):
                self.capture(fake)
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.sources, [])
        self.assertEqual(file_hash(self.source), source_hash)

    def test_invalid_intervals_fail_before_opening_or_creating_files(self):
        for interval in (0, -1, float("nan"), float("inf"), -float("inf")):
            with self.subTest(interval=interval):
                fake = FakeCV2([(True, FakeFrame())])
                with self.assertRaises(captura_segura.CaptureError):
                    captura_segura.capturar_frames_de_video(
                        self.destination,
                        str(self.source),
                        interval,
                        cv2_module=fake,
                        mostrar_preview=False,
                    )
                self.assertFalse(self.destination.exists())
                self.assertEqual(fake.sources, [])

    def test_open_failure_leaves_existing_photos_untouched(self):
        originals = self.original_files()
        fake = FakeCV2(opened=False)
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake)
        self.assert_originals_unchanged(originals)
        self.assertFalse((self.destination / "demo").exists())
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(fake.capture.read_calls, 0)

    def test_capture_constructor_exception_preserves_originals_and_creates_no_session(self):
        originals = self.original_files()
        fake = FakeCV2([(True, FakeFrame())])
        with mock.patch.object(
            fake, "VideoCapture", side_effect=RuntimeError("decoder unavailable")
        ):
            with self.assertRaises(captura_segura.CaptureError):
                self.capture(fake)
        self.assert_originals_unchanged(originals)
        self.assertFalse((self.destination / "demo").exists())
        self.assertEqual(fake.capture.release_calls, 0)

    def test_no_initial_frame_does_not_create_destination(self):
        fake = FakeCV2([(False, None)])
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake)
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.capture.release_calls, 1)

    def test_null_initial_frame_is_not_a_valid_capture(self):
        fake = FakeCV2([(True, None)])
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake)
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.capture.release_calls, 1)

    def test_empty_initial_frame_does_not_create_destination(self):
        fake = FakeCV2([(True, FakeFrame(b""))])
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake)
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.capture.release_calls, 1)

    def test_invalid_local_fps_fails_before_creating_destination(self):
        for fps in (0, -1, float("nan"), float("inf")):
            with self.subTest(fps=fps):
                fake = FakeCV2([(True, FakeFrame())], fps=fps)
                with self.assertRaises(captura_segura.CaptureError):
                    self.capture(fake)
                self.assertFalse(self.destination.exists())
                self.assertEqual(fake.capture.release_calls, 1)

    def test_success_uses_session_directory_and_preserves_original_hashes(self):
        originals = self.original_files()
        frame = FakeFrame(b"first-image")
        fake = FakeCV2([(True, frame)])
        session = self.capture(fake)
        self.assertIsInstance(session, Path)
        self.assertEqual(session, self.destination / "demo")
        self.assert_originals_unchanged(originals)
        images = list(session.glob("*.jpg"))
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].read_bytes(), b"jpeg:first-image")
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(file_hash(self.source), hashlib.sha256(
            b"fake local video; never opened by OpenCV"
        ).hexdigest())

    def test_first_frame_is_saved_even_with_long_sampling_interval(self):
        fake = FakeCV2([(True, FakeFrame(b"first"))])
        session = captura_segura.capturar_frames_de_video(
            self.destination,
            str(self.source),
            3600,
            nom_sessio="demo",
            cv2_module=fake,
            mostrar_preview=False,
        )
        images = list(session.glob("*.jpg"))
        self.assertEqual(len(images), 1)
        self.assertEqual(images[0].read_bytes(), b"jpeg:first")

    def test_local_video_samples_media_time_instead_of_cpu_speed(self):
        fake = FakeCV2(
            [(True, FakeFrame(f"frame-{index}".encode())) for index in range(5)],
            fps=2,
        )
        session = captura_segura.capturar_frames_de_video(
            self.destination,
            str(self.source),
            1,
            nom_sessio="demo",
            cv2_module=fake,
            mostrar_preview=False,
        )
        self.assertEqual(
            [path.read_bytes() for path in sorted(session.glob("*.jpg"))],
            [b"jpeg:frame-0", b"jpeg:frame-2", b"jpeg:frame-4"],
        )
        self.assertEqual(fake.capture.release_calls, 1)

    def test_fractional_sampling_interval_does_not_drop_boundary_frames(self):
        fake = FakeCV2(
            [(True, FakeFrame(str(index).encode())) for index in range(13)],
            fps=10,
        )
        session = captura_segura.capturar_frames_de_video(
            self.destination,
            str(self.source),
            0.3,
            nom_sessio="demo",
            cv2_module=fake,
            mostrar_preview=False,
        )
        self.assertEqual(
            [path.read_bytes() for path in sorted(session.glob("*.jpg"))],
            [b"jpeg:0", b"jpeg:3", b"jpeg:6", b"jpeg:9", b"jpeg:12"],
        )

    def test_duplicate_session_name_never_reuses_or_overwrites_previous_run(self):
        first = self.capture(FakeCV2([(True, FakeFrame(b"first"))]))
        previous = {path: file_hash(path) for path in first.iterdir()}
        second = self.capture(FakeCV2([(True, FakeFrame(b"second"))]))
        self.assertEqual(first.name, "demo")
        self.assertEqual(second.name, "demo_001")
        self.assertNotEqual(first, second)
        self.assert_originals_unchanged(previous)
        self.assertEqual(next(second.glob("*.jpg")).read_bytes(), b"jpeg:second")

    def test_session_creator_avoids_existing_directories_and_files(self):
        first = captura_segura.crear_directori_sessio(self.destination, "demo")
        occupied = self.destination / "demo_001"
        occupied.write_bytes(b"existing file, not a directory")
        second = captura_segura.crear_directori_sessio(self.destination, "demo")
        self.assertEqual(first, self.destination / "demo")
        self.assertEqual(second, self.destination / "demo_002")
        self.assertEqual(occupied.read_bytes(), b"existing file, not a directory")

    def test_default_session_names_are_unique(self):
        first = captura_segura.crear_directori_sessio(self.destination)
        second = captura_segura.crear_directori_sessio(self.destination)
        self.assertNotEqual(first, second)
        self.assertTrue(first.is_dir())
        self.assertTrue(second.is_dir())
        self.assertEqual(first.parent, self.destination)
        self.assertEqual(second.parent, self.destination)

    def test_encoder_failure_is_reported_and_releases_capture(self):
        originals = self.original_files()
        fake = FakeCV2([(True, FakeFrame())], encode_ok=False)
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake)
        self.assert_originals_unchanged(originals)
        self.assertEqual(list(self.destination.rglob("demo/*.jpg")), [])
        self.assertEqual(fake.capture.release_calls, 1)

    def test_success_flag_with_null_or_empty_jpeg_still_fails(self):
        for encoded in (None, FakeEncoded(b"")):
            with self.subTest(encoded=encoded):
                fake = FakeCV2([(True, FakeFrame())])
                with mock.patch.object(fake, "imencode", return_value=(True, encoded)):
                    with self.assertRaises(captura_segura.CaptureError):
                        self.capture(fake)
                self.assertEqual(list(self.destination.rglob("*.jpg")), [])
                self.assertEqual(fake.capture.release_calls, 1)

    def test_unexpected_existing_frame_in_reserved_session_is_never_overwritten(self):
        originals = self.original_files()
        session = self.destination / "demo"
        session.mkdir()
        occupied = session / "frame_0001.jpg"
        occupied.write_bytes(b"existing frame must survive an exclusive-create collision")
        previous_hash = file_hash(occupied)
        fake = FakeCV2([(True, FakeFrame(b"replacement must not be written"))])
        with mock.patch.object(
            captura_segura, "crear_directori_sessio", return_value=session
        ):
            with self.assertRaises(captura_segura.CaptureError):
                self.capture(fake)
        self.assertEqual(file_hash(occupied), previous_hash)
        self.assert_originals_unchanged(originals)
        self.assertEqual(list(session.iterdir()), [occupied])
        self.assertEqual(fake.capture.release_calls, 1)

    def test_mid_capture_read_exception_keeps_first_frame_and_originals(self):
        originals = self.original_files()
        fake = FakeCV2([
            (True, FakeFrame(b"first")),
            RuntimeError("decoder failed after the first frame"),
        ])
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake)
        self.assert_originals_unchanged(originals)
        saved = list((self.destination / "demo").glob("*.jpg"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), b"jpeg:first")
        self.assertEqual(fake.capture.release_calls, 1)

    def test_local_eof_is_success(self):
        fake = FakeCV2([(True, FakeFrame()), (False, None)])
        session = self.capture(fake)
        self.assertTrue(session.is_dir())
        self.assertEqual(len(list(session.glob("*.jpg"))), 1)
        self.assertEqual(fake.capture.release_calls, 1)

    def test_stream_loss_is_error_and_retains_partial_session(self):
        fake = FakeCV2([(True, FakeFrame(b"stream-first")), (False, None)])
        with self.assertRaises(captura_segura.CaptureError):
            captura_segura.capturar_frames_de_video(
                self.destination,
                "tcp://example.invalid:8888",
                0.1,
                nom_sessio="demo",
                cv2_module=fake,
                mostrar_preview=False,
            )
        saved = list((self.destination / "demo").glob("*.jpg"))
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].read_bytes(), b"jpeg:stream-first")
        self.assertEqual(fake.capture.release_calls, 1)

    def test_stream_open_and_read_have_explicit_timeouts(self):
        fake = FakeCV2([(True, FakeFrame()), (False, None)])
        source = "tcp://example.invalid:8888"
        with self.assertRaises(captura_segura.CaptureError):
            captura_segura.capturar_frames_de_video(
                self.destination, source, 0.1,
                cv2_module=fake, mostrar_preview=False,
            )
        self.assertEqual(fake.capture_arguments, [(
            source,
            (fake.CAP_ANY, [
                fake.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                fake.CAP_PROP_READ_TIMEOUT_MSEC, 5000,
            ]),
        )])

    def test_stream_backend_without_timeout_support_is_rejected(self):
        fake = FakeCV2([(True, FakeFrame())], backend="V4L2")
        with self.assertRaises(captura_segura.CaptureError):
            captura_segura.capturar_frames_de_video(
                self.destination, "tcp://example.invalid:8888", 0.1,
                cv2_module=fake, mostrar_preview=False,
            )
        self.assertFalse(self.destination.exists())
        self.assertEqual(fake.capture.release_calls, 1)

    def test_write_permission_error_does_not_damage_existing_data(self):
        originals = self.original_files()
        fake = FakeCV2([(True, FakeFrame())])
        real_builtin_open = builtins.open
        real_io_open = io.open

        def reject_new_file(real_open):
            def open_checked(file, mode="r", *args, **kwargs):
                if "x" in mode:
                    raise PermissionError("simulated read-only session directory")
                return real_open(file, mode, *args, **kwargs)
            return open_checked

        with mock.patch("builtins.open", reject_new_file(real_builtin_open)), \
                mock.patch("io.open", reject_new_file(real_io_open)):
            with self.assertRaises(captura_segura.CaptureError):
                self.capture(fake)
        self.assert_originals_unchanged(originals)
        self.assertEqual(fake.capture.release_calls, 1)

    def test_preview_is_cleaned_up_on_success(self):
        fake = FakeCV2([(True, FakeFrame())])
        self.capture(fake, mostrar_preview=True)
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(fake.destroy_calls, 1)

    def test_preview_is_cleaned_up_when_first_read_fails(self):
        fake = FakeCV2([(False, None)])
        with self.assertRaises(captura_segura.CaptureError):
            self.capture(fake, mostrar_preview=True)
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(fake.destroy_calls, 1)

    def test_no_preview_does_not_touch_window_functions(self):
        fake = FakeCV2([(True, FakeFrame())])
        self.capture(fake)
        self.assertEqual(fake.preview_frames, [])
        self.assertEqual(fake.destroy_calls, 0)

    def test_verified_local_eof_is_the_only_case_reported_as_complete(self):
        fake = FakeCV2([
            (True, FakeFrame(b"first")),
            (True, FakeFrame(b"second")),
            (False, None),
        ])
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            session = self.capture(fake)
        self.assertTrue(session.is_dir())
        self.assertIn("Captura completada", output.getvalue())
        self.assertNotIn("completitud no verificada", diagnostics.getvalue().lower())
        self.assertEqual(fake.capture.successful_reads, 2)
        self.assertEqual(fake.capture.release_calls, 1)

    def test_known_large_frame_gap_reports_premature_termination_and_partial_path(self):
        originals = self.original_files()
        previous = self.destination / "previous-session"
        previous.mkdir()
        old_frame = previous / "frame_0001.jpg"
        old_frame.write_bytes(b"previous capture")
        originals[old_frame] = file_hash(old_frame)
        fake = FakeCV2([(True, FakeFrame(b"first")), (False, None)], frame_count=8)
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            with self.assertRaisesRegex(captura_segura.CaptureError, "Terminació prematura") as error:
                self.capture(fake, mostrar_preview=True)
        session = self.destination / "demo"
        self.assertIn(str(session), str(error.exception))
        self.assertEqual(next(session.glob("*.jpg")).read_bytes(), b"jpeg:first")
        self.assert_originals_unchanged(originals)
        self.assertNotIn("Captura completada", output.getvalue())
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(fake.destroy_calls, 1)

    def test_missing_invalid_or_unavailable_metadata_returns_unverified_session(self):
        metadata_cases = (
            {"frame_count": None}, {"frame_count": 0}, {"frame_count": -1},
            {"frame_count": float("nan")}, {"frame_count": float("inf")},
            {"frame_count": 1.5},
            {"metadata_error": RuntimeError("metadata not available")},
        )
        for metadata in metadata_cases:
            with self.subTest(metadata=metadata):
                fake = FakeCV2([(True, FakeFrame()), (False, None)], **metadata)
                output, diagnostics = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    session = self.capture(fake)
                self.assertTrue(session.is_dir())
                self.assertIn("completitud no verificada", diagnostics.getvalue().lower())
                self.assertNotIn("Captura completada", output.getvalue())
                self.assertEqual(fake.capture.release_calls, 1)

    def test_unstable_declared_frame_count_returns_unverified_session(self):
        fake = FakeCV2(
            [(True, FakeFrame()), (True, FakeFrame()), (False, None)],
            frame_counts=[2, 3, 2],
        )
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            session = self.capture(fake)
        self.assertTrue(session.is_dir())
        self.assertIn("completitud no verificada", diagnostics.getvalue().lower())
        self.assertNotIn("Captura completada", output.getvalue())

    def test_zero_regressive_jumpy_or_reset_cursor_is_not_trusted_as_eof(self):
        for positions in ([0, 0, 0], [1, 0, 0], [1, 4, 4], [1, 2, 0]):
            with self.subTest(positions=positions):
                fake = FakeCV2(
                    [(True, FakeFrame()), (True, FakeFrame()), (False, None)],
                    positions=positions,
                )
                output, diagnostics = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    session = self.capture(fake)
                self.assertTrue(session.is_dir())
                self.assertIn("completitud no verificada", diagnostics.getvalue().lower())
                self.assertNotIn("Captura completada", output.getvalue())

    def test_single_overreported_frame_is_unverified_instead_of_a_hard_error(self):
        fake = FakeCV2(
            [(True, FakeFrame()), (True, FakeFrame()), (False, None)],
            frame_count=3,
        )
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            session = self.capture(fake)
        self.assertTrue(session.is_dir())
        self.assertIn("completitud no verificada", diagnostics.getvalue().lower())
        self.assertNotIn("Captura completada", output.getvalue())

    def test_underreported_count_is_inconsistent_metadata_not_a_verified_end(self):
        fake = FakeCV2(
            [(True, FakeFrame()), (True, FakeFrame()), (False, None)],
            frame_count=1,
        )
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            session = self.capture(fake)
        self.assertTrue(session.is_dir())
        self.assertIn("completitud no verificada", diagnostics.getvalue().lower())
        self.assertNotIn("Captura completada", output.getvalue())

    def test_q_on_file_or_stream_returns_partial_path_and_interrupt_status(self):
        for source in (str(self.source), "tcp://example.invalid:8888"):
            with self.subTest(source=source):
                fake = FakeCV2([
                    (True, FakeFrame(b"first")), (True, FakeFrame(b"not reached")),
                ])
                output, diagnostics = io.StringIO(), io.StringIO()
                with mock.patch.object(fake, "waitKey", return_value=ord("q")), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    session = captura_segura.capturar_frames_de_video(
                        self.destination, source, 0.1, nom_sessio="demo",
                        cv2_module=fake, mostrar_preview=True,
                    )
                self.assertIsInstance(session, Path)
                self.assertEqual(len(list(session.glob("*.jpg"))), 1)
                self.assertIn("Captura interrompuda", output.getvalue())
                self.assertIn("parcial", output.getvalue().lower())
                self.assertIn(str(session), output.getvalue())
                self.assertNotIn("Captura completada", output.getvalue())
                self.assertEqual(fake.capture.read_calls, 1)
                self.assertEqual(fake.capture.release_calls, 1)
                self.assertEqual(fake.destroy_calls, 1)

    def test_keyboard_interrupt_before_first_frame_creates_no_session(self):
        fake = FakeCV2([KeyboardInterrupt()])
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            with self.assertRaises(KeyboardInterrupt):
                self.capture(fake, mostrar_preview=True)
        self.assertFalse(self.destination.exists())
        self.assertNotIn("Captura completada", output.getvalue())
        self.assertTrue(diagnostics.getvalue())
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(fake.destroy_calls, 1)

    def test_keyboard_interrupt_after_first_frame_preserves_originals_and_previous_run(self):
        originals = self.original_files()
        previous = self.destination / "previous-session"
        previous.mkdir()
        old_frame = previous / "frame_0001.jpg"
        old_frame.write_bytes(b"previous capture")
        originals[old_frame] = file_hash(old_frame)
        fake = FakeCV2([(True, FakeFrame(b"first")), KeyboardInterrupt()])
        output, diagnostics = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
            with self.assertRaises(KeyboardInterrupt):
                self.capture(fake, mostrar_preview=True)
        session = self.destination / "demo"
        self.assertIn(str(session), diagnostics.getvalue())
        self.assertIn("parcial", diagnostics.getvalue().lower())
        self.assertNotIn("Captura completada", output.getvalue())
        self.assertEqual(next(session.glob("*.jpg")).read_bytes(), b"jpeg:first")
        self.assert_originals_unchanged(originals)
        self.assertEqual(fake.capture.release_calls, 1)
        self.assertEqual(fake.destroy_calls, 1)

    def test_file_decoder_error_or_stream_loss_preserves_previous_run_hashes(self):
        originals = self.original_files()
        previous = self.destination / "previous-session"
        previous.mkdir()
        old_frame = previous / "frame_0001.jpg"
        old_frame.write_bytes(b"previous capture")
        originals[old_frame] = file_hash(old_frame)
        scenarios = (
            (str(self.source), RuntimeError("decoder failed"), "decode-error"),
            ("tcp://example.invalid:8888", (False, None), "stream-loss"),
        )
        for source, failure, name in scenarios:
            with self.subTest(source=source):
                fake = FakeCV2([(True, FakeFrame(b"first")), failure])
                output, diagnostics = io.StringIO(), io.StringIO()
                with contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    with self.assertRaises(captura_segura.CaptureError) as error:
                        captura_segura.capturar_frames_de_video(
                            self.destination, source, 0.1, nom_sessio=name,
                            cv2_module=fake, mostrar_preview=True,
                        )
                session = self.destination / name
                self.assertIn(str(session), str(error.exception))
                self.assertEqual(next(session.glob("*.jpg")).read_bytes(), b"jpeg:first")
                self.assert_originals_unchanged(originals)
                self.assertNotIn("Captura completada", output.getvalue())
                self.assertEqual(fake.capture.release_calls, 1)
                self.assertEqual(fake.destroy_calls, 1)

    def test_preview_callback_errors_preserve_partial_frames_and_clean_resources(self):
        for callback in ("putText", "imshow", "waitKey"):
            with self.subTest(callback=callback):
                fake = FakeCV2([(True, FakeFrame(b"first"))])
                output, diagnostics = io.StringIO(), io.StringIO()
                with mock.patch.object(fake, callback, side_effect=RuntimeError("preview failed")), \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    with self.assertRaises(captura_segura.CaptureError) as error:
                        self.capture(fake, nom_sessio=callback, mostrar_preview=True)
                session = self.destination / callback
                self.assertIn(str(session), str(error.exception))
                self.assertEqual(next(session.glob("*.jpg")).read_bytes(), b"jpeg:first")
                self.assertNotIn("Captura completada", output.getvalue())
                self.assertEqual(fake.capture.release_calls, 1)
                self.assertEqual(fake.destroy_calls, 1)

    def test_cleanup_failures_do_not_mask_decoder_errors_or_keyboard_interrupt(self):
        for failure in (RuntimeError("decoder failed"), KeyboardInterrupt()):
            with self.subTest(failure=type(failure).__name__):
                fake = FakeCV2([(True, FakeFrame(b"first")), failure])
                expected_error = KeyboardInterrupt if isinstance(failure, KeyboardInterrupt) else captura_segura.CaptureError
                output, diagnostics = io.StringIO(), io.StringIO()
                with mock.patch.object(fake.capture, "release", side_effect=RuntimeError("release failed")) as release, \
                        mock.patch.object(fake, "destroyAllWindows", side_effect=RuntimeError("window cleanup failed")) as destroy, \
                        contextlib.redirect_stdout(output), contextlib.redirect_stderr(diagnostics):
                    with self.assertRaises(expected_error):
                        self.capture(fake, mostrar_preview=True)
                release.assert_called_once()
                destroy.assert_called_once()
                self.assertIn("release failed", diagnostics.getvalue())
                self.assertIn("window cleanup failed", diagnostics.getvalue())
                self.assertNotIn("Captura completada", output.getvalue())


class PipelineCV2(FakeCV2):
    """Read/write fixture bytes, replacing image operations with harmless fakes."""

    ROTATE_180 = 1

    def __init__(self):
        super().__init__()
        self.read_paths = []
        self.write_paths = []

    def imread(self, path):
        path = Path(path).resolve()
        self.read_paths.append(path)
        return FakeFrame(path.read_bytes(), shape=(100, 120, 3))

    def imwrite(self, path, frame):
        path = Path(path).resolve()
        self.write_paths.append(path)
        path.write_bytes(b"annotated:" + frame.payload)
        return True

    def rotate(self, frame, rotation):
        return frame.copy()

    def addWeighted(self, image, *args):
        return image.copy()

    def fillPoly(self, *args):
        pass

    def drawContours(self, *args):
        pass

    def rectangle(self, *args):
        pass

    def circle(self, *args):
        pass


def pipeline_function(path, namespace):
    """Compile the real orchestrator, excluding all heavyweight module imports.

    This is an orchestration test, not a test of model inference. Parsing the
    source lets it exercise the actual routing statements with controlled
    detector/segmenter results and no ultralytics, torch, numpy or pyzbar.
    """
    tree = ast.parse(path.read_text())
    function = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "executar_pipeline_orquestrat"
    )
    selected = ast.Module(body=[function], type_ignores=[])
    exec(compile(selected, str(path), "exec"), namespace)
    return namespace["executar_pipeline_orquestrat"]


class PipelineRoutingTests(unittest.TestCase):
    PIPELINES = (
        "volumetria/volumetria_BLOC0_1.py",
        "UNIFICACIO_FINAL/BLOC0.py",
    )

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="tfg-routing-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.photos = self.root / "photos"
        self.photos.mkdir()
        self.originals = [
            self.photos / "original_a.jpg",
            self.photos / "original_b.JPG",
            self.photos / "notes.txt",
        ]
        for index, path in enumerate(self.originals):
            path.write_bytes(f"original-{index}".encode())
        self.original_hashes = {path: file_hash(path) for path in self.originals}
        self.wp3 = Path(__file__).resolve().parents[1]

    def make_pipeline(self, relative_path, *, record=False, results=None):
        cv2 = PipelineCV2()
        vertices = [(20, 20), (80, 20), (80, 80), (20, 80)]
        box = {
            "id": 7,
            "bbox": (20, 20, 80, 80),
            "color": (0, 200, 0),
            "contorn": vertices,
            "cx": 50,
            "cy": 50,
        }
        state = {
            "frames_processats": 0,
            "frames_amb_deteccions": 0,
            "ultim_index_frame": 0,
            "ultim_temps_simulat": 0,
        }
        volume = {
            "n_frontals": 1,
            "n_perspectiva": 1,
            "amplada_cm": 20,
            "profunditat_cm": 10,
            "alcada_cm": 15,
            "volum_cm3": 3000,
        }
        namespace = {
            "Path": Path,
            "os": os,
            "cv2": cv2,
            "np": mock.MagicMock(name="numpy_fake"),
            "CARPETA_FOTOS": str(self.photos),
            "CARPETA_RESULTATS": str(results or self.root / "results"),
            "GRAVAR_NOU_VIDEO": record,
            "FONT_VIDEO": "tcp://example.invalid:8888",
            "INTERVAL_CAPTURA_SEG": 1,
            "MANIFEST_CSV": "unused-manifest.csv",
            "DISTANCIA_LIDAR_CM": 120,
            "MARGE_BORDE_VALIDACIO": 10,
            "carregar_manifest": mock.Mock(return_value=({"shelf"}, {})),
            "capturar_frames_de_video": mock.Mock(),
            "crear_directori_sessio": mock.Mock(
                wraps=captura_segura.crear_directori_sessio
            ),
            "YOLO": mock.Mock(name="YOLO"),
            "SAM": mock.Mock(name="SAM"),
            "load_model": mock.Mock(name="load_model"),
            "GD_CONFIG_PATH": "fake-config.py",
            "GD_WEIGHTS_PATH": "fake-weights.pth",
            "DEVICE": "cpu",
            "VOLUMETRIA_DIR": str(self.wp3 / "volumetria"),
            "ZBAR_IMPORT_ERROR": None,
            "FRAME_INTERVAL_SECONDS": 0.5,
            "extreure_ids_i_posicions": mock.Mock(return_value=[box]),
            "extreure_codis_imatge": mock.Mock(return_value=[]),
            "detectar_qualsevol_caixa": mock.Mock(return_value=vertices),
            "calcular_volumetria": mock.Mock(return_value=volume),
            "crear_estat_inventari": mock.Mock(return_value=state),
            "registrar_codis_globals": mock.Mock(),
            "processar_codis_inventari": mock.Mock(),
            "anotar_codis_frame": mock.Mock(),
            "finalizar_inventario_si_hace_falta": mock.Mock(),
            "imprimir_resum_general_inventari": mock.Mock(),
        }
        function = pipeline_function(self.wp3 / relative_path, namespace)
        return function, namespace, cv2

    def assert_originals_unchanged(self):
        self.assertEqual(
            self.original_hashes,
            {path: file_hash(path) for path in self.originals},
        )

    def assert_volume_reads(self, namespace, photos, names):
        namespace["calcular_volumetria"].assert_called()
        for call in namespace["calcular_volumetria"].call_args_list:
            self.assertEqual(Path(call.args[0]), photos)
            self.assertEqual(set(call.args[1]), set(names))

    def test_repeated_offline_runs_get_distinct_outputs_and_preserve_originals(self):
        for relative_path in self.PIPELINES:
            with self.subTest(pipeline=relative_path):
                run, namespace, cv2 = self.make_pipeline(relative_path)
                configured = {
                    key: namespace[key]
                    for key in ("CARPETA_FOTOS", "CARPETA_RESULTATS")
                }
                with contextlib.redirect_stdout(io.StringIO()):
                    run()
                    first_paths = list(cv2.write_paths)
                    first_hashes = {path: file_hash(path) for path in first_paths}
                    run()
                second_paths = cv2.write_paths[len(first_paths):]
                self.assertEqual(len(first_paths), 2)
                self.assertEqual(len(second_paths), 2)
                self.assertNotEqual(first_paths[0].parent, second_paths[0].parent)
                self.assertEqual(first_hashes, {
                    path: file_hash(path) for path in first_paths
                })
                self.assert_originals_unchanged()
                self.assertEqual(configured, {
                    key: namespace[key] for key in configured
                })
                namespace["capturar_frames_de_video"].assert_not_called()
                self.assert_volume_reads(
                    namespace, self.photos, {"original_a.jpg", "original_b.JPG"}
                )
                if "UNIFICACIO_FINAL" in relative_path:
                    summary = namespace["imprimir_resum_general_inventari"]
                    self.assertEqual(len(summary.call_args_list), 2)
                    self.assertEqual(
                        Path(summary.call_args_list[0].args[1]), first_paths[0].parent
                    )
                    self.assertEqual(
                        Path(summary.call_args_list[1].args[1]), second_paths[0].parent
                    )

    def test_output_base_equal_to_input_does_not_overwrite_or_reprocess_outputs(self):
        for relative_path in self.PIPELINES:
            with self.subTest(pipeline=relative_path):
                run, namespace, cv2 = self.make_pipeline(
                    relative_path, results=self.photos
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    run()
                    run()
                self.assert_originals_unchanged()
                self.assertEqual(len(cv2.read_paths), 4)
                self.assertTrue(all(path.parent == self.photos for path in cv2.read_paths))
                self.assertEqual({path.name for path in cv2.read_paths}, {
                    "original_a.jpg", "original_b.JPG"
                })
                self.assertEqual(len({path.parent for path in cv2.write_paths}), 2)
                self.assertTrue(all(path.parent != self.photos for path in cv2.write_paths))
                self.assert_volume_reads(
                    namespace, self.photos, {"original_a.jpg", "original_b.JPG"}
                )

    def test_new_capture_is_the_only_photo_directory_processed(self):
        captured = self.root / "captured-session"
        captured.mkdir()
        for name in ("capture_a.jpg", "capture_b.jpg"):
            (captured / name).write_bytes(name.encode())
        for relative_path in self.PIPELINES:
            with self.subTest(pipeline=relative_path):
                run, namespace, cv2 = self.make_pipeline(relative_path, record=True)
                namespace["capturar_frames_de_video"].return_value = captured
                configured = namespace["CARPETA_FOTOS"]
                with contextlib.redirect_stdout(io.StringIO()):
                    run()
                namespace["capturar_frames_de_video"].assert_called_once_with(
                    self.photos, "tcp://example.invalid:8888", 1
                )
                self.assertEqual({path.parent for path in cv2.read_paths}, {captured})
                self.assertEqual(namespace["CARPETA_FOTOS"], configured)
                self.assert_originals_unchanged()
                self.assert_volume_reads(
                    namespace, captured, {"capture_a.jpg", "capture_b.jpg"}
                )
                if "UNIFICACIO_FINAL" in relative_path:
                    summary = namespace["imprimir_resum_general_inventari"]
                    summary.assert_called_once()
                    self.assertEqual(Path(summary.call_args.args[1]), cv2.write_paths[0].parent)

    def test_capture_failure_aborts_before_loading_models_or_making_outputs(self):
        for relative_path in self.PIPELINES:
            with self.subTest(pipeline=relative_path):
                run, namespace, cv2 = self.make_pipeline(relative_path, record=True)
                namespace["capturar_frames_de_video"].side_effect = (
                    captura_segura.CaptureError("source returned no image")
                )
                with contextlib.redirect_stdout(io.StringIO()):
                    with self.assertRaises(captura_segura.CaptureError):
                        run()
                for name in ("YOLO", "SAM", "load_model", "crear_directori_sessio"):
                    namespace[name].assert_not_called()
                self.assertEqual(cv2.read_paths, [])
                self.assertEqual(cv2.write_paths, [])
                self.assert_originals_unchanged()


if __name__ == "__main__":
    unittest.main()
