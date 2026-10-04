"""Build the double-clickable desktop app on the current operating system."""

from importlib.metadata import distribution
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import imageio_ffmpeg


ROOT = Path(__file__).resolve().parent
APP_NAME = "OfflineVideoAnonymizer"
LICENSE_FILES = {
    "opencv-python-headless": ("LICENSE.txt", "LICENSE-3RD-PARTY.txt"),
    "imageio-ffmpeg": ("LICENSE",),
    "numpy": ("LICENSE.txt",),
}


def copy_notices(destination):
    """Keep wheel license texts with the bundled third-party binaries."""
    destination.mkdir()
    for package, names in LICENSE_FILES.items():
        installed = distribution(package)
        for name in names:
            matches = [item for item in installed.files or ()
                       if item.name == name and ".dist-info" in str(item)]
            if not matches:
                raise FileNotFoundError(f"Missing {name} from installed {package}")
            target = destination / package
            target.mkdir(exist_ok=True)
            shutil.copy2(installed.locate_file(matches[0]), target / name)
    ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
    for option, name in (("-version", "FFmpeg-build.txt"), ("-L", "FFmpeg-license.txt")):
        result = subprocess.run([ffmpeg, option], capture_output=True, text=True, check=True)
        (destination / name).write_text(result.stdout, encoding="utf-8")


def main():
    if sys.platform not in {"darwin", "win32"}:
        raise SystemExit("Desktop bundles are currently built on macOS and Windows only.")
    with tempfile.TemporaryDirectory(prefix="anonymizer-build-") as temporary:
        notices = Path(temporary) / "licenses"
        copy_notices(notices)
        command = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean", "--onedir",
            "--windowed", "--name", APP_NAME,
            "--icon", str(ROOT / "assets" / ("app-icon.icns" if sys.platform == "darwin"
                                               else "app-icon.ico")),
            "--add-data", f"{ROOT / 'assets' / 'app-icon.png'}{os.pathsep}assets",
            "--add-data", f"{ROOT / 'models'}{os.pathsep}models",
            "--add-data", f"{ROOT / 'THIRD_PARTY.md'}{os.pathsep}.",
            "--add-data", f"{notices}{os.pathsep}licenses",
            "--collect-all", "imageio_ffmpeg", "--collect-data", "cv2",
            str(ROOT / "desktop_app.py"),
        ]
        environment = os.environ.copy()
        environment["PYINSTALLER_CONFIG_DIR"] = str(ROOT / "build" / "pyinstaller-cache")
        subprocess.run(command, cwd=ROOT, env=environment, check=True)
    if sys.platform == "darwin":
        print(f"Built {ROOT / 'dist' / (APP_NAME + '.app')}")
    else:
        print(f"Built {ROOT / 'dist' / APP_NAME / (APP_NAME + '.exe')}")


if __name__ == "__main__":
    main()
