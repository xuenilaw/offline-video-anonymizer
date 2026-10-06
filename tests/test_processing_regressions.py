"""Regressions for coarse face masks and unreliable container metadata."""

from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cv2
import imageio_ffmpeg
import numpy as np

import main
from video_type import analyze_video


class ProcessingRegressions(unittest.TestCase):
    def test_large_face_has_at_most_eight_blocks_across(self):
        frame = np.random.default_rng(7).integers(0, 256, (700, 700, 3), dtype=np.uint8)
        main.pixelate(frame, (50, 50, 600, 600), pad_x_ratio=0, pad_y_ratio=0)
        row = frame[350, 50:650]
        changes = np.any(row[1:] != row[:-1], axis=1)
        self.assertLessEqual(1 + int(np.count_nonzero(changes)), 8)

    def test_missing_and_inaccurate_frame_counts_do_not_fail_processing(self):
        with tempfile.TemporaryDirectory(prefix="anonymizer-regression-") as directory:
            directory = Path(directory)
            source = directory / "source.mp4"
            writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"),
                                     12, (96, 96))
            self.assertTrue(writer.isOpened())
            try:
                for _ in range(12):
                    writer.write(np.full((96, 96, 3), 180, dtype=np.uint8))
            finally:
                writer.release()

            no_duration = directory / "no_duration.mkv"
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-hide_banner", "-loglevel",
                            "error", "-y", "-i", str(source), "-c", "copy", "-f",
                            "matroska", "-live", "1", str(no_duration)], check=True)
            self.assertGreater(analyze_video(no_duration).sampled_frames, 0)

            options = ["--video-type", "normal", "--no-faces", "--no-plates",
                       "--no-names", "--hide-region", "0,0,20,20", "--audio-mode", "mute"]
            main.main(["--input", str(no_duration), "--output",
                       str(directory / "unknown_count_result.mp4"), *options])

            original_capture = cv2.VideoCapture

            class WrongCountCapture:
                def __init__(self, path):
                    self.capture = original_capture(path)

                def get(self, property_id):
                    if property_id == cv2.CAP_PROP_FRAME_COUNT:
                        return 1000
                    return self.capture.get(property_id)

                def __getattr__(self, name):
                    return getattr(self.capture, name)

            with patch.object(main.cv2, "VideoCapture", WrongCountCapture):
                main.main(["--input", str(source), "--output",
                           str(directory / "wrong_count_result.mp4"), *options])

            for name in ("unknown_count_result.mp4", "wrong_count_result.mp4"):
                capture = original_capture(str(directory / name))
                try:
                    count = 0
                    while capture.read()[0]:
                        count += 1
                    self.assertEqual(count, 12)
                finally:
                    capture.release()


if __name__ == "__main__":
    unittest.main()
