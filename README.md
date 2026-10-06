# Offline video anonymization proof of concept

This is an early, local Python proof of concept with a small desktop interface. It pixelates selected faces and vehicle license plates and can cover participant-name rectangles in an MP4 video. Audio can be kept, removed, or pitch-shifted locally.

## Desktop interface

After installing the dependencies below, run:

```bash
python desktop_app.py
```

Choose **One video** or **Folder of videos**. For one video, the app analyzes a few frames locally and suggests a starting preset. **Online meeting** initially selects faces and participant names; **Dashcam footage** initially selects faces and vehicle plates; **Phone or camera video** initially selects faces. You can change any checkbox before selecting **Create anonymized video**.

Scroll over the settings on the left to reach all four steps and the main action button. Drag the divider between settings and result preview to give either side more room.

For a folder, select the source folder and a separate output folder. The app processes MP4, MOV, MKV, and AVI files directly inside the source folder, one at a time; it does not scan subfolders. With **Let the app suggest** and **Use recommended masks for each video in the folder** selected, every video gets its own type suggestion and matching masks. The visible checkboxes are the fallback when a type is uncertain. Turn off that option, or choose a specific source type, to apply the displayed checkboxes to every video. Each output is an MP4 named after its source with `_anonymized`; an existing result gets a numbered suffix rather than being overwritten. Individual failures are reported in the processing details while the remaining videos continue.

Finished videos appear in the preview on the right. Use **‹ Previous** and **Next ›** to switch results, **Play** to review a result in the app, or **Open full video** to use your usual player. On macOS, the in-app preview also plays sound when the output has an audio track. The preview prepares a temporary local MP3 for sound and deletes it when the app closes. On other systems, use **Open full video** to check sound.

**Processing details** shows an overall progress bar, percentage, and approximate remaining time for single videos and folders. The estimate is based on completed frames and observed processing speed; it becomes more useful after processing starts. Audio finishing can take additional time, so that stage is shown separately before the bar reaches 100%.

Automatic face masking now uses a coarse mosaic even for very large faces. Dashcam footage also gets a closer detection pass over overlapping parts of each frame to catch more distant pedestrians; this can make dashcam processing slower. Small, obscured, or heavily compressed faces can still be missed, so review the result and draw cover areas where needed. MP4/MKV frame counts are treated as estimates: trimmed or no-duration videos continue until decoding reaches the real end of the file.

Click **Cancel processing** to stop a single video, a folder job, or a manual reprocessing job. In a folder job, videos already completed stay available in the result preview; the current video stops and the remaining videos are skipped. The app removes temporary files from the interrupted video. You can start another job after cancellation finishes.

Automatic name rectangles currently cover only the recognized two-by-two meeting layout. For other layouts, use **Draw cover / blur / keep-clear areas…** to cover the visible names. The interface runs locally; it does not upload video.

### Correct missed areas by hand

Select a video and click **Draw cover / blur / keep-clear areas…**. In the source-video window, set **From** and **To** in seconds, or use the slider and **Start at this frame** / **End after this frame**, then draw a box. You can also select an existing box and click **Apply From/To to selected box**. Choose **Solid dark cover** for an opaque mask, **Strong blur** for a softened mask, or **Keep faces clear here** to disable automatic face masking inside the box. **Change selected effect** switches an existing box between these choices. A solid cover takes priority where it overlaps a blur. For names or other readable text, a solid cover is safer because blurred text may remain readable. Each box applies only during its selected time range, but its **screen position stays fixed**. Add more boxes for an object that moves. Move the slider to inspect other frames; only boxes active at that time are outlined. Keep-clear affects automatic face masking only. Plate masks, name masks, and manually covered areas still apply. If another person enters a keep-clear box during its time range, their face can be left clear. Review the whole result before sharing it.

For a folder, process it first, select a finished video with **‹ Previous** or **Next ›**, then draw areas for that video's source. Click **Reprocess selected video with drawn areas** to create a new result without changing the other videos. The earlier output remains on disk so you can compare it; share only the corrected version after reviewing it. From the command line, use repeatable `--hide-region x,y,width,height,start,end`, `--blur-region x,y,width,height,start,end`, and `--keep-face-region x,y,width,height,start,end` options; omit start and end to apply a box to the whole clip.

The interface uses Python's Tkinter. If Homebrew Python reports `No module named '_tkinter'`, install the matching Tk package, for example `brew install python-tk@3.14` for Python 3.14. Then rerun `python desktop_app.py` from the same Python environment.

### Build the desktop app

Build on each operating system separately. With Python 3.14 and Tkinter available, run:

```bash
python -m pip install -r requirements-build.txt
python build_desktop.py
python smoke_desktop_bundle.py
```

**Windows, from PowerShell:** Install 64-bit Python 3.14, download or clone this repository, and open PowerShell in the project folder. Run these commands; they use the virtual environment directly, so activation is not needed:

```powershell
py -3.14 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe build_desktop.py
.\.venv\Scripts\python.exe smoke_desktop_bundle.py
```

If `py -3.14` is unavailable but `python` points to Python 3.14, use `python -m venv .venv` for the first command. After the smoke check passes, double-click `dist\OfflineVideoAnonymizer\OfflineVideoAnonymizer.exe`. Keep the whole `OfflineVideoAnonymizer` folder together when moving it to another Windows PC.

On macOS, open `dist/OfflineVideoAnonymizer.app`. The `build/` folder contains intermediate files, not the app to launch. A macOS build does not create a Windows `.exe`; build it on Windows or download the Windows artifact from the manually triggered GitHub Actions workflow. The app uses its bundled Python, models, and FFmpeg binary; users do not need to install Python. A single-video default output goes into `~/Videos/Offline Video Anonymizer` on Windows or `~/Movies/Offline Video Anonymizer` on macOS. Folder jobs continue to default to an `anonymized` subfolder beside the input videos.

The GitHub Actions **Build desktop apps** workflow can be started manually to produce review ZIP files for Windows x64, Intel Macs, and Apple Silicon Macs. It runs the synthetic-video smoke check on each platform. These are unsigned review builds, not a public release. Downloaded macOS apps need Developer ID signing and notarization for a smooth first launch; Windows downloads may show a SmartScreen warning until signed and trusted. Review [third-party redistribution requirements](THIRD_PARTY.md), especially the bundled FFmpeg binary and its corresponding source, before publishing downloads.

The app icon is generated from `assets/app-icon.svg`; the checked-in `.icns` and `.ico` files are used by the Mac and Windows builds. To change it, install `requirements-icons.txt` and run `python make_app_icons.py` before rebuilding.

## Run locally

1. Install Python and create a virtual environment.
2. Install dependencies with `pip install -r requirements.txt`.
3. Put a video you are authorized to process at `test_video.mp4` in this directory, or pass its path with `--input`.
4. Run `python main.py`.

The result is written to `output/blurred_faces_and_plates.mp4` unless you pass `--output`. The default audio mode is `keep`, which copies the original audio. An audio-processing failure stops with an error; it does not silently substitute another audio mode.

## Video type suggestion

`main.py` now samples up to seven frames before processing and suggests `meeting`, `dashcam`, or `normal`. It prints a confidence **evidence score**, not a calibrated probability. If the result is `unknown`, processing stops until you choose a type. The suggestion can be wrong, so review it and the final video.

```bash
python main.py --input my_video.mp4 --analyze-only
python main.py --input my_video.mp4 --video-type meeting --output output/meeting.mp4
```

You can also run `python video_type.py my_video.mp4` to get the analysis as JSON. The `meeting` profile detects faces but skips license plates, preventing the plate detector from pixelating captions. The `dashcam` profile detects faces and plates; `normal` detects faces. These are current defaults, not final privacy decisions.

Override the visual masks independently with `--faces`/`--no-faces`, `--plates`/`--no-plates`, and `--names`/`--no-names`. For example, `--video-type meeting --no-plates --faces --names` keeps the plate detector away from subtitles. When automatic type detection is uncertain, either choose `--video-type` or set all three mask switches explicitly. Masking names needs matching rectangles; the automatic name rectangles are limited to the recognized two-by-two meeting layout.

For a recognized two-by-two meeting grid, the meeting profile also covers four expected participant-name areas with solid dark bars. This works for the tested Meet layout, but label positions vary among apps and window sizes. You can add a name mask using pixel coordinates from the original video; repeat the option for more labels:

```bash
python main.py --input my_video.mp4 --video-type meeting --name-region 160,320,240,25 --output output/review.mp4
```

Use `--no-auto-names` to disable the four inferred masks when they are misplaced. Review every frame for visible names and captions before sharing the result. The name masks are opaque because softened text can remain readable.

## Audio choices

```bash
python main.py --input my_video.mp4 --audio-mode mute --output output/muted.mp4
python main.py --input my_video.mp4 --audio-mode alter --pitch-semitones -4 --output output/altered.mp4
python main.py --input my_video.mp4 --audio-mode keep --output output/original_audio.mp4
```

`mute` removes the audio stream. `alter` processes the first audio stream with local FFmpeg filters, shifting pitch and formants while keeping roughly the original speaking speed. The allowed shift is -6 to -1 or 1 to 6 semitones; the default is -4. If the source has no audio stream, `alter` stops with an error. Pitch shifting does **not** guarantee that a speaker cannot be recognized, and it does not remove personal information spoken aloud. Listen to and review the result before sharing it.

## Current limitations

- Type detection uses conservative visual rules. Different meeting layouts, static dashcam footage, or mixed-content recordings may be classified as `unknown` or incorrectly; use `--video-type` after reviewing the video.
- Automatic participant-name masking only covers the recognized two-by-two grid. Other meeting layouts and labels outside those four zones need drawn solid cover areas in the desktop app or `--name-region` from the command line.
- Detection can miss faces or plates; review the entire output before sharing it.
- The default `keep` mode leaves the source audio unchanged. `alter` may still leave speakers recognizable and does not censor spoken names or other content.
- The script does not automatically redact names outside the four recognized label zones, chat messages, browser tabs, location clues, or other identifiers.

This repository contains no sample or processed recordings. Local video files and `output/` are excluded by `.gitignore` because they may contain personal data or material that cannot be redistributed.

## Third-party components

The face detector model in `models/` is from [OpenCV Zoo's YuNet model](https://github.com/opencv/opencv_zoo/tree/main/models/face_detection_yunet) and is distributed with its [MIT license notice](models/LICENSE-YUNET.txt). Python dependencies are listed in `requirements.txt`; see [THIRD_PARTY.md](THIRD_PARTY.md) for licensing notes. The project license, if added, applies only to original project content, not to third-party components or recordings.
