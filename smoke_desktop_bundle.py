"""Check a bundled desktop executable without using private recordings."""

from pathlib import Path
import subprocess
import sys
import tempfile

import cv2
import numpy as np


ROOT = Path(__file__).resolve().parent
APP_NAME = "OfflineVideoAnonymizer"


def bundled_executable():
    if sys.platform == "darwin":
        return ROOT / "dist" / f"{APP_NAME}.app" / "Contents" / "MacOS" / APP_NAME
    if sys.platform == "win32":
        return ROOT / "dist" / APP_NAME / f"{APP_NAME}.exe"
    raise SystemExit("Only macOS and Windows desktop bundles are supported.")


def main():
    executable = bundled_executable()
    if not executable.is_file():
        raise FileNotFoundError(executable)
    with tempfile.TemporaryDirectory(prefix="anonymizer-smoke-") as temporary:
        directory = Path(temporary)
        source = directory / "source.mp4"
        output = directory / "result.mp4"
        log = directory / "worker.log"
        writer = cv2.VideoWriter(str(source), cv2.VideoWriter_fourcc(*"mp4v"), 12, (96, 96))
        if not writer.isOpened():
            raise RuntimeError("Could not create a synthetic test video")
        try:
            for _ in range(12):
                writer.write(np.full((96, 96, 3), 180, dtype=np.uint8))
        finally:
            writer.release()
        command = [
            str(executable), "--worker", "process", str(log),
            "--input", str(source), "--output", str(output),
            "--video-type", "normal", "--faces", "--no-plates", "--no-names",
            "--audio-mode", "keep",
        ]
        result = subprocess.run(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                timeout=120)
        details = log.read_text(encoding="utf-8") if log.exists() else "No worker log was created"
        if result.returncode or not output.is_file() or "Finished decoding 12 frames" not in details:
            raise RuntimeError(f"Bundled processing failed ({result.returncode}):\n{details}")
        capture = cv2.VideoCapture(str(output))
        try:
            if not capture.isOpened() or not capture.read()[0]:
                raise RuntimeError("The bundled app created an unreadable video")
        finally:
            capture.release()
    print(f"Bundled video processing passed: {executable}")


if __name__ == "__main__":
    main()
