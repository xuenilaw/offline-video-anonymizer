# Offline video anonymization proof of concept

This is an early, local Python proof of concept that pixelates detected faces and vehicle license plates in an MP4 video. It is **not yet a desktop application** and does not process voices or participant names separately.

## Run locally

1. Install Python and create a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Put a video you are authorized to process at `test_video.mp4` in this directory.
4. Run `python main.py`.

The result is written to `output/blurred_faces_and_plates.mp4`. The current script uses fixed paths in `main.py` and copies the source audio into the output. If audio remuxing fails, it produces a video without audio and prints a warning.

## Current limitations

- The plate detector runs on every frame. In screen recordings, it can mistake captions and other interface text for license plates and pixelate them.
- Detection can miss faces or plates; review the entire output before sharing it.
- The source audio is unchanged and may identify speakers or contain personal information.
- The script does not redact names, chat messages, browser tabs, location clues, or other identifiers.

This repository contains no sample or processed recordings. Local video files and `output/` are excluded by `.gitignore` because they may contain personal data or material that cannot be redistributed.

## Third-party components

The face detector model in `models/` is from [OpenCV Zoo's YuNet model](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) and is distributed with its [MIT license notice](models/LICENSE-YUNET.txt). Python dependencies are listed in `requirements.txt`; see [THIRD_PARTY.md](THIRD_PARTY.md) for licensing notes. The project license, if added, applies only to original project content, not to third-party components or recordings.
