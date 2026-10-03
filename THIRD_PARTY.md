# Third-party licensing notes

This file records the upstream components used by the current proof of concept. Check the exact packages and bundled binaries again before distributing a desktop application.

| Component | Use | Upstream license information |
| --- | --- | --- |
| YuNet face model | Bundled `models/face_detection_yunet_2023mar.onnx` | MIT; the original copyright and license text are preserved in `models/LICENSE-YUNET.txt`. |
| `opencv-python-headless` | Video frames, face detection, plate cascade, pixelation | Python packaging scripts: MIT; OpenCV: Apache-2.0; wheel includes additional third-party components and notices. |
| `imageio-ffmpeg` | Provides the FFmpeg executable for audio remuxing | Python wrapper: BSD-2-Clause. FFmpeg has separate LGPL/GPL terms depending on the binary build. |

Installing dependencies from package indexes is different from redistributing their binaries. A future desktop installer must include the relevant license texts and notices and verify the license of the exact FFmpeg build it ships.
