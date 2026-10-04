# Third-party licensing notes

This file records the upstream components used by the desktop app. The build script includes the installed wheels' license files plus the bundled FFmpeg binary's `-version` and `-L` output in the app's `licenses` folder. Check the exact builds before public distribution.

| Component | Use | Upstream license information |
| --- | --- | --- |
| YuNet face model | Bundled `models/face_detection_yunet_2023mar.onnx` | MIT; the original copyright and license text are preserved in `models/LICENSE-YUNET.txt`. |
| `opencv-python-headless` | Video frames, face detection, plate cascade, pixelation | Python packaging scripts: MIT; OpenCV: Apache-2.0; wheel includes additional third-party components and notices. |
| `imageio-ffmpeg` | Provides the FFmpeg executable for audio remuxing | Python wrapper: BSD-2-Clause. Its bundled FFmpeg executable has separate LGPL/GPL terms depending on the binary build. The macOS ARM binary in the locally tested 0.6.0 wheel reports GPLv2-or-later with `ffmpeg -L`. |
| NumPy | Required by OpenCV and the desktop preview | The installed wheel's license text is included in the app's `licenses` folder. |

Installing dependencies from package indexes is different from redistributing their binaries. Do not publish these unsigned build artifacts as a public release until the exact FFmpeg binaries' corresponding source and redistribution obligations are addressed for each platform. FFmpeg's own [legal guidance](https://ffmpeg.org/legal.html) explains that GPL components can change the binary's license and recommends providing the corresponding source with distributed binaries. macOS Developer ID signing and notarization, and Windows code signing, are also still pending for a smooth first launch after download.
