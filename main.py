"""Pixelate selected visual identifiers in one local MP4 video."""

import argparse
from dataclasses import asdict
import json
from pathlib import Path

import cv2
from audio_processing import finish_video
from meeting_names import (
    is_standard_two_by_two,
    parse_region,
    redact_regions,
    standard_two_by_two_regions,
)
from video_type import analyze_video, looks_like_road_plate


PROJECT_DIR = Path(__file__).resolve().parent
INPUT_PATH = PROJECT_DIR / "test_video.mp4"
OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_PATH = OUTPUT_DIR / "blurred_faces_and_plates.mp4"
FACE_MODEL_PATH = PROJECT_DIR / "models" / "face_detection_yunet_2023mar.onnx"

# Keep a detected box briefly when the cascade misses it for a few frames.
MAX_MISSED_FRAMES = 4
SMOOTHING = 0.55


def overlap_score(a, b):
    """Intersection over union (IoU) for two (x, y, width, height) boxes."""
    ax1, ay1, aw, ah = a
    bx1, by1, bw, bh = b
    ax2, ay2 = ax1 + aw, ay1 + ah
    bx2, by2 = bx1 + bw, by1 + bh
    intersection = max(0, min(ax2, bx2) - max(ax1, bx1)) * max(
        0, min(ay2, by2) - max(ay1, by1)
    )
    union = aw * ah + bw * bh - intersection
    return intersection / union if union else 0.0


def update_tracks(tracks, detections):
    """Match detections to recent boxes and smooth their movement."""
    unmatched = set(range(len(detections)))

    for track in tracks:
        best_index = None
        best_score = 0.0
        for index in unmatched:
            score = overlap_score(track["box"], detections[index])
            if score > best_score:
                best_index, best_score = index, score

        if best_index is not None and best_score >= 0.15:
            old = track["box"]
            new = detections[best_index]
            track["box"] = tuple(
                int((1.0 - SMOOTHING) * old[i] + SMOOTHING * new[i])
                for i in range(4)
            )
            track["missed"] = 0
            unmatched.remove(best_index)
        else:
            track["missed"] += 1

    tracks[:] = [track for track in tracks if track["missed"] <= MAX_MISSED_FRAMES]
    tracks.extend({"box": detections[index], "missed": 0} for index in unmatched)


def expanded_box(
    box, frame_width, frame_height, pad_x_ratio=0.15, pad_y_ratio=0.30
):
    """Add padding around a detection while staying inside the frame."""
    x, y, width, height = box
    pad_x = int(width * pad_x_ratio)
    pad_y = int(height * pad_y_ratio)
    x1 = max(0, x - pad_x)
    y1 = max(0, y - pad_y)
    x2 = min(frame_width, x + width + pad_x)
    y2 = min(frame_height, y + height + pad_y)
    return x1, y1, x2, y2


def pixelate(frame, box, pad_x_ratio=0.15, pad_y_ratio=0.30):
    """Apply strong pixelation to one expanded detection region."""
    frame_height, frame_width = frame.shape[:2]
    x1, y1, x2, y2 = expanded_box(
        box, frame_width, frame_height, pad_x_ratio, pad_y_ratio
    )
    region = frame[y1:y2, x1:x2]
    if region.size == 0:
        return

    tiny_width = max(4, (x2 - x1) // 14)
    tiny_height = max(3, (y2 - y1) // 14)
    tiny = cv2.resize(region, (tiny_width, tiny_height), interpolation=cv2.INTER_AREA)
    frame[y1:y2, x1:x2] = cv2.resize(
        tiny, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--video-type", choices=("auto", "meeting", "dashcam", "normal"), default="auto")
    parser.add_argument("--analyze-only", action="store_true", help="Print the type suggestion without processing")
    parser.add_argument("--name-region", type=parse_region, action="append", default=[],
                        metavar="X,Y,WIDTH,HEIGHT", help="Cover an additional name region in pixel coordinates; repeat as needed")
    parser.add_argument("--no-auto-names", action="store_true",
                        help="Disable standard two-by-two meeting label masks")
    parser.add_argument("--audio-mode", choices=("keep", "mute", "alter"), default="keep",
                        help="Keep original audio, remove audio, or shift voice pitch locally")
    parser.add_argument("--pitch-semitones", type=int, default=-4,
                        help="Pitch shift for --audio-mode alter (-6..-1 or 1..6; default: -4)")
    args = parser.parse_args(argv)

    if args.audio_mode == "alter" and (args.pitch_semitones == 0 or not -6 <= args.pitch_semitones <= 6):
        parser.error("--pitch-semitones must be -6..-1 or 1..6 when altering audio")

    if not args.input.exists():
        raise FileNotFoundError(f"Input video not found: {args.input}")

    analysis = None
    if args.video_type == "auto" or args.analyze_only:
        analysis = analyze_video(args.input)
        print(json.dumps(asdict(analysis), indent=2))
    if args.analyze_only:
        return

    video_type = analysis.video_type if args.video_type == "auto" else args.video_type
    if video_type == "unknown":
        parser.error("Video type is uncertain. Review the video and choose --video-type meeting, dashcam, or normal.")
    if args.input.resolve() == args.output.resolve():
        raise ValueError("Input and output paths must differ")

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temp_video_path = args.output.with_name(f".{args.output.stem}_video_only.mp4")
    detector = None
    if video_type == "dashcam":
        detector_path = Path(cv2.data.haarcascades) / "haarcascade_russian_plate_number.xml"
        detector = cv2.CascadeClassifier(str(detector_path))
        if detector.empty():
            raise RuntimeError(f"Could not load plate detector: {detector_path}")
    if not FACE_MODEL_PATH.exists():
        raise FileNotFoundError(f"Face detector model not found: {FACE_MODEL_PATH}")

    capture = cv2.VideoCapture(str(args.input))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open input video: {args.input}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    for x, y, _, _ in args.name_region:
        if x >= width or y >= height:
            capture.release()
            parser.error(f"Name region origin ({x},{y}) is outside the {width}x{height} video")

    name_regions = list(args.name_region)
    if video_type == "meeting" and not args.no_auto_names:
        if analysis is None:
            analysis = analyze_video(args.input)
        if is_standard_two_by_two(analysis):
            name_regions.extend(standard_two_by_two_regions(width, height))
            print("Using four standard meeting label masks; review all names and captions in the output.")
        else:
            print("Standard meeting layout not recognized; add --name-region for each visible label.")
    if video_type == "meeting" and not name_regions:
        print("Warning: no participant name regions are masked.")

    face_detector = cv2.FaceDetectorYN.create(
        str(FACE_MODEL_PATH),
        "",
        (width, height),
        score_threshold=0.45,
        nms_threshold=0.3,
        top_k=5000,
    )
    writer = cv2.VideoWriter(
        str(temp_video_path), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not create temporary video: {temp_video_path}")

    print(f"Profile: {video_type}; input: {width}x{height}, {fps:.3f} FPS, {frame_count} frames")
    print(f"Audio mode: {args.audio_mode}")
    if args.audio_mode == "alter":
        print("Warning: a pitch shift changes the sound but may not conceal speaker identity or spoken personal information.")
    elif args.audio_mode == "keep":
        print("Warning: original audio is retained and may contain identifying information.")
    plate_tracks = []
    face_tracks = []
    processed = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            # Detect on the unmodified frame so one mask cannot hide another.
            _, raw_faces = face_detector.detect(frame)
            face_detections = []
            if raw_faces is not None:
                face_detections = [
                    tuple(map(int, face[:4])) for face in raw_faces
                ]
            update_tracks(face_tracks, face_detections)

            if detector is not None:
                gray = cv2.equalizeHist(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                raw_boxes = detector.detectMultiScale(
                    gray, scaleFactor=1.05, minNeighbors=3,
                    minSize=(24, 6), maxSize=(400, 150),
                )
                detections = [
                    tuple(map(int, box)) for box in raw_boxes
                    if looks_like_road_plate(frame, box)
                ]
                update_tracks(plate_tracks, detections)
                for track in plate_tracks:
                    pixelate(frame, track["box"])

            for track in face_tracks:
                pad_x, pad_y = (0.15, 0.10) if video_type == "meeting" else (0.35, 0.40)
                pixelate(
                    frame,
                    track["box"],
                    pad_x_ratio=pad_x,
                    pad_y_ratio=pad_y,
                )

            redact_regions(frame, name_regions)

            writer.write(frame)
            processed += 1
            if processed % 24 == 0 or processed == frame_count:
                print(f"Processed {processed}/{frame_count} frames")
    finally:
        capture.release()
        writer.release()

    if processed != frame_count:
        raise RuntimeError(f"Decoded {processed} frames, expected {frame_count}")

    finish_video(
        temp_video_path, args.input, args.output,
        mode=args.audio_mode, semitones=args.pitch_semitones,
    )

    print(f"Created: {args.output}")


if __name__ == "__main__":
    main()
