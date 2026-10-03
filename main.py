"""Blur vehicle license plates and human faces in one local MP4 video."""

from pathlib import Path
import os
import subprocess

import cv2
from imageio_ffmpeg import get_ffmpeg_exe


PROJECT_DIR = Path(__file__).resolve().parent
INPUT_PATH = PROJECT_DIR / "test_video.mp4"
OUTPUT_DIR = PROJECT_DIR / "output"
OUTPUT_PATH = OUTPUT_DIR / "blurred_faces_and_plates.mp4"
TEMP_VIDEO_PATH = OUTPUT_DIR / ".blurred_faces_and_plates_video_only.mp4"
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


def looks_like_road_plate(frame, box):
    """Reject obvious cascade false positives from signs and road markings."""
    x, y, width, height = box
    frame_height = frame.shape[0]
    if y + height / 2 < frame_height * 0.45:
        return False

    gray_region = cv2.cvtColor(frame[y : y + height, x : x + width], cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray_region, 80, 160)
    edge_density = cv2.countNonZero(edges) / edges.size
    return edge_density >= 0.12


def remux_original_audio(video_only_path, source_path, output_path):
    """Copy the processed video and original audio into the final MP4."""
    command = [
        get_ffmpeg_exe(),
        "-y",
        "-i",
        str(video_only_path),
        "-i",
        str(source_path),
        "-map",
        "0:v:0",
        "-map",
        "1:a?",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-shortest",
        str(output_path),
    ]
    subprocess.run(command, check=True, capture_output=True, text=True)


def main():
    if not INPUT_PATH.exists():
        raise FileNotFoundError(f"Input video not found: {INPUT_PATH}")

    OUTPUT_DIR.mkdir(exist_ok=True)
    detector_path = Path(cv2.data.haarcascades) / "haarcascade_russian_plate_number.xml"
    detector = cv2.CascadeClassifier(str(detector_path))
    if detector.empty():
        raise RuntimeError(f"Could not load plate detector: {detector_path}")
    if not FACE_MODEL_PATH.exists():
        raise FileNotFoundError(f"Face detector model not found: {FACE_MODEL_PATH}")

    capture = cv2.VideoCapture(str(INPUT_PATH))
    if not capture.isOpened():
        raise RuntimeError(f"Could not open input video: {INPUT_PATH}")

    fps = capture.get(cv2.CAP_PROP_FPS)
    width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
    frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
    face_detector = cv2.FaceDetectorYN.create(
        str(FACE_MODEL_PATH),
        "",
        (width, height),
        score_threshold=0.45,
        nms_threshold=0.3,
        top_k=5000,
    )
    writer = cv2.VideoWriter(
        str(TEMP_VIDEO_PATH), cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height)
    )
    if not writer.isOpened():
        capture.release()
        raise RuntimeError(f"Could not create temporary video: {TEMP_VIDEO_PATH}")

    print(f"Input: {width}x{height}, {fps:.3f} FPS, {frame_count} frames")
    plate_tracks = []
    face_tracks = []
    processed = 0

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                break

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)
            raw_boxes = detector.detectMultiScale(
                gray,
                scaleFactor=1.05,
                minNeighbors=3,
                minSize=(24, 6),
                maxSize=(400, 150),
            )
            detections = [
                tuple(map(int, box))
                for box in raw_boxes
                if looks_like_road_plate(frame, box)
            ]
            update_tracks(plate_tracks, detections)

            for track in plate_tracks:
                pixelate(frame, track["box"])

            _, raw_faces = face_detector.detect(frame)
            face_detections = []
            if raw_faces is not None:
                face_detections = [
                    tuple(map(int, face[:4])) for face in raw_faces
                ]
            update_tracks(face_tracks, face_detections)

            for track in face_tracks:
                pixelate(
                    frame,
                    track["box"],
                    pad_x_ratio=0.35,
                    pad_y_ratio=0.40,
                )

            writer.write(frame)
            processed += 1
            if processed % 24 == 0 or processed == frame_count:
                print(f"Processed {processed}/{frame_count} frames")
    finally:
        capture.release()
        writer.release()

    if processed != frame_count:
        raise RuntimeError(f"Decoded {processed} frames, expected {frame_count}")

    try:
        remux_original_audio(TEMP_VIDEO_PATH, INPUT_PATH, OUTPUT_PATH)
    except subprocess.CalledProcessError as error:
        print("Warning: audio remux failed; keeping the processed video without audio.")
        print(error.stderr)
        os.replace(TEMP_VIDEO_PATH, OUTPUT_PATH)
    else:
        TEMP_VIDEO_PATH.unlink()

    print(f"Created: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
