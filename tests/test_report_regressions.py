"""Acceptance checks for timing, codecs, cleanup, and desktop behavior."""

from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
import queue
import subprocess
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import imageio_ffmpeg
import numpy as np

from audio_processing import source_audio_codec
from desktop_app import AnonymizerApp, unique_file_destination
from frame_timing import scan_frame_times
import main


FFMPEG = imageio_ffmpeg.get_ffmpeg_exe()
OPTIONS = ["--video-type", "normal", "--no-faces", "--no-plates", "--no-names",
           "--hide-region", "0,0,12,12"]


def make_source(path, *, frames=24, fps=12):
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (64, 64))
    if not writer.isOpened():
        raise RuntimeError("Could not create test video")
    for _ in range(frames):
        writer.write(np.full((64, 64, 3), 180, dtype=np.uint8))
    writer.release()


def ffmpeg(*args):
    subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-y", *map(str, args)],
                   check=True, capture_output=True)


def frame_times(path):
    capture = cv2.VideoCapture(str(path))
    try:
        times, variable = scan_frame_times(capture, capture.get(cv2.CAP_PROP_FPS))
        return times, variable
    finally:
        capture.release()


def audio_bytes(path):
    return subprocess.run([FFMPEG, "-hide_banner", "-loglevel", "error", "-i", str(path),
                           "-map", "0:a:0", "-c", "copy", "-f", "data", "-"],
                          check=True, capture_output=True).stdout


class ReportRegressions(unittest.TestCase):
    def test_vfr_timestamps_and_timed_cover_use_source_clock(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            base = folder / "base.mp4"
            source = folder / "vfr.mp4"
            output = folder / "result.mp4"
            make_source(base)
            ffmpeg("-i", base, "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                   "-vf", "select=not(between(n\\,4\\,7))", "-fps_mode", "vfr",
                   "-c:v", "libx264", "-c:a", "aac", "-shortest", source)
            expected, variable = frame_times(source)
            self.assertTrue(variable)
            with redirect_stdout(StringIO()):
                main.main(["--input", str(source), "--output", str(output), *OPTIONS[:-2],
                           "--hide-region", "0,0,12,12,1,1.5", "--audio-mode", "keep"])
            actual, _ = frame_times(output)
            self.assertEqual(len(expected), len(actual))
            self.assertLessEqual(max(abs(a - b) for a, b in zip(expected, actual)), 0.05)
            capture = cv2.VideoCapture(str(output))
            try:
                for seconds in expected:
                    ok, frame = capture.read()
                    self.assertTrue(ok)
                    self.assertEqual(frame[4, 4].mean() < 40, 1 <= seconds < 1.5)
                    self.assertEqual(frame[30, 30].mean() < 40, False)
            finally:
                capture.release()

    def test_keep_reencodes_incompatible_audio_and_copies_aac(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            base = folder / "base.mp4"
            make_source(base)
            aac = folder / "aac.mp4"
            ffmpeg("-i", base, "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                   "-c:v", "copy", "-c:a", "aac", "-shortest", aac)
            for codec, extension, video_codec in (("pcm_s16le", "mov", "libx264"),
                                                   ("pcm_s16le", "avi", "mpeg4"),
                                                   ("libvorbis", "mkv", "libx264"),
                                                   ("libopus", "mkv", "libx264")):
                with self.subTest(codec=codec, extension=extension):
                    source = folder / f"{codec}.{extension}"
                    output = folder / f"{codec}_out.mp4"
                    ffmpeg("-i", aac, "-c:v", video_codec, "-c:a", codec, source)
                    with redirect_stdout(StringIO()):
                        main.main(["--input", str(source), "--output", str(output),
                                   *OPTIONS, "--audio-mode", "keep"])
                    self.assertEqual(source_audio_codec(output), "aac")
            copied = folder / "aac_out.mp4"
            with redirect_stdout(StringIO()):
                main.main(["--input", str(aac), "--output", str(copied),
                           *OPTIONS, "--audio-mode", "keep"])
            self.assertEqual(audio_bytes(aac), audio_bytes(copied))

    def test_failure_removes_video_and_audio_temporary_files(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            source = folder / "source.mp4"
            output = folder / "result.mp4"
            make_source(source, frames=8)
            calls = 0

            def fail_on_fifth(_frame, _detector, _type):
                nonlocal calls
                calls += 1
                if calls == 5:
                    raise RuntimeError("injected detector failure")
                return []

            with patch.object(main, "detect_faces", side_effect=fail_on_fifth):
                with self.assertRaisesRegex(RuntimeError, "injected detector failure"):
                    with redirect_stdout(StringIO()):
                        main.main(["--input", str(source), "--output", str(output),
                                   "--video-type", "normal", "--faces", "--audio-mode", "mute"])
            self.assertEqual(list(folder.glob(".*_video_only.mp4")), [])
            self.assertEqual(list(folder.glob(".*.audio_tmp.mp4")), [])

    def test_all_audio_modes_encode_h264_yuv420p(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            base = folder / "base.mp4"
            source = folder / "source.mp4"
            make_source(base)
            ffmpeg("-i", base, "-f", "lavfi", "-i", "sine=frequency=440:duration=2",
                   "-c:v", "copy", "-c:a", "aac", "-shortest", source)
            for mode in ("keep", "mute", "alter"):
                with self.subTest(mode=mode):
                    output = folder / f"{mode}.mp4"
                    with redirect_stdout(StringIO()):
                        main.main(["--input", str(source), "--output", str(output),
                                   *OPTIONS, "--audio-mode", mode])
                    info = subprocess.run([FFMPEG, "-hide_banner", "-i", str(output)],
                                          capture_output=True, text=True).stderr
                    self.assertIn("Video: h264", info)
                    self.assertIn("yuv420p", info)
                    ffmpeg("-i", output, "-f", "null", "-")

    def test_default_output_gets_numbered_suffix_on_second_run(self):
        with tempfile.TemporaryDirectory() as folder:
            preferred = Path(folder) / "x_anonymized.mp4"
            reserved = set()
            first = unique_file_destination(preferred, reserved)
            first.touch()
            second = unique_file_destination(preferred, reserved)
            self.assertEqual(first, preferred)
            self.assertEqual(second.name, "x_anonymized_2.mp4")

    def test_processing_error_keeps_analysis_suggestion(self):
        app = AnonymizerApp.__new__(AnonymizerApp)
        app.events = queue.Queue()
        app.events.put(("processing_error", "injected failure"))
        app.suggestion = Mock()
        app.root = Mock()
        with patch("desktop_app.messagebox.showerror") as show_error:
            app._drain_events()
        show_error.assert_called_once_with("Processing failed", "injected failure")
        app.suggestion.set.assert_not_called()


if __name__ == "__main__":
    unittest.main()
