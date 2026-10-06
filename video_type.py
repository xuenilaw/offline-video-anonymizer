"""Suggest a video type from a few local frames, without uploading the video."""

import argparse
from dataclasses import asdict, dataclass
import json
import math
from pathlib import Path

import cv2
import numpy as np


PROJECT_DIR = Path(__file__).resolve().parent
FACE_MODEL_PATH = PROJECT_DIR / "models" / "face_detection_yunet_2023mar.onnx"
VIDEO_TYPES = ("meeting", "dashcam", "normal")
MIN_CONFIDENCE = 0.75
MIN_MARGIN = 0.15


@dataclass(frozen=True)
class VideoTypeResult:
    video_type: str
    confidence: float
    suggested_type: str
    sampled_frames: int
    scores: dict[str, float]
    evidence: dict[str, float]


def _clamp(value):
    return max(0.0, min(1.0, value))


def looks_like_road_plate(frame, box):
    """Keep the existing plate filter; plate hits alone cannot prove video type."""
    x, y, width, height = map(int, box)
    if y + height / 2 < frame.shape[0] * 0.45:
        return False
    region = frame[y : y + height, x : x + width]
    if region.size == 0:
        return False
    gray = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 80, 160)
    return cv2.countNonZero(edges) / edges.size >= 0.12


def _sample_indices(frame_count, maximum):
    if frame_count <= maximum:
        return list(range(frame_count))
    # Avoid introductions and end cards while covering the whole clip.
    return sorted({round((frame_count - 1) * (0.05 + 0.90 * i / (maximum - 1)))
                   for i in range(maximum)})


def _sample_frames(capture, frame_count, fps, maximum):
    if frame_count > 0:
        found = 0
        for index in _sample_indices(frame_count, maximum):
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if ok:
                found += 1
                yield frame
        if found:
            return
        capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
    # Some MKVs report no frame count, and some files report positions that
    # cannot be sought. Sample sequentially until EOF or the limit.
    stride = max(1, round(fps)) if math.isfinite(fps) and fps > 0 else 24
    index = samples = 0
    while samples < maximum:
        ok, frame = capture.read()
        if not ok:
            break
        if index % stride == 0:
            yield frame
            samples += 1
        index += 1


def _dark_center_dividers(gray):
    height, width = gray.shape
    vertical = gray[int(height * 0.13) : int(height * 0.85), width // 2 - 5 : width // 2 + 5]
    horizontal = gray[height // 2 - 5 : height // 2 + 5, int(width * 0.12) : int(width * 0.88)]
    return bool(vertical.size and horizontal.size and vertical.mean() < 70 and horizontal.mean() < 70)


def analyze_video(video_path, *, face_model_path=FACE_MODEL_PATH, max_samples=7):
    """Return a conservative, heuristic type suggestion and evidence.

    Confidence is an evidence score, not a calibrated probability. The caller
    should ask the user to choose a type when ``video_type`` is ``unknown``.
    """
    video_path = Path(video_path)
    if not video_path.is_file():
        raise FileNotFoundError(f"Video not found: {video_path}")
    if not Path(face_model_path).is_file():
        raise FileNotFoundError(f"Face model not found: {face_model_path}")
    if max_samples < 2:
        raise ValueError("max_samples must be at least 2")

    capture = cv2.VideoCapture(str(video_path))
    if not capture.isOpened():
        raise ValueError(f"Could not open video: {video_path}")
    try:
        reported_count = capture.get(cv2.CAP_PROP_FRAME_COUNT)
        frame_count = (int(reported_count)
                       if math.isfinite(reported_count) and reported_count > 0 else 0)
        fps = capture.get(cv2.CAP_PROP_FPS)
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if width < 20 or height < 20:
            raise ValueError(f"Video has no usable frames: {video_path}")

        face_detector = cv2.FaceDetectorYN.create(
            str(face_model_path), "", (width, height),
            score_threshold=0.45, nms_threshold=0.3, top_k=5000,
        )
        plate_path = Path(cv2.data.haarcascades) / "haarcascade_russian_plate_number.xml"
        plate_detector = cv2.CascadeClassifier(str(plate_path))
        if plate_detector.empty():
            raise RuntimeError(f"Could not load plate detector: {plate_path}")

        observations = []
        previous_small = None
        motions = []
        for frame in _sample_frames(capture, frame_count, fps, max_samples):
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            _, raw_faces = face_detector.detect(frame)
            large_faces = 0
            if raw_faces is not None:
                large_faces = sum(
                    face[2] >= width * 0.04 and face[3] >= height * 0.055
                    for face in raw_faces
                )
            raw_plates = plate_detector.detectMultiScale(
                cv2.equalizeHist(gray), scaleFactor=1.05, minNeighbors=3,
                minSize=(24, 6), maxSize=(400, 150),
            )
            lower_plate = any(looks_like_road_plate(frame, box) for box in raw_plates)
            small = cv2.resize(gray, (160, 90), interpolation=cv2.INTER_AREA)
            if previous_small is not None:
                motions.append(float(cv2.absdiff(small, previous_small).mean()) / 255)
            previous_small = small
            observations.append((large_faces, _dark_center_dividers(gray), lower_plate))
    finally:
        capture.release()

    if not observations:
        raise ValueError(f"Could not decode sampled frames: {video_path}")

    count = len(observations)
    multiple_faces = sum(faces >= 2 for faces, _, _ in observations) / count
    single_face = sum(faces == 1 for faces, _, _ in observations) / count
    any_large_face = sum(faces >= 1 for faces, _, _ in observations) / count
    dark_dividers = sum(dark for _, dark, _ in observations) / count
    lower_plates = sum(plate for _, _, plate in observations) / count
    motion = sum(motions) / len(motions) if motions else 0.0
    quiet = _clamp((0.06 - motion) / 0.05)
    moving = _clamp((motion - 0.02) / 0.06)

    scores = {
        "meeting": 0.50 * multiple_faces + 0.30 * dark_dividers + 0.20 * quiet,
        # A prominent person usually means a recording or screen capture;
        # avoid routing its subtitle-like plate hits to the dashcam profile.
        "dashcam": (0.40 * lower_plates + 0.40 * moving + 0.20 * (1 - any_large_face))
                   * _clamp((0.50 - any_large_face) / 0.50),
        "normal": 0.45 * single_face + 0.25 * (1 - dark_dividers)
                  + 0.15 * quiet + 0.15 * (1 - lower_plates),
    }
    ranked = sorted(scores, key=scores.get, reverse=True)
    best, runner_up = ranked[:2]
    confident = scores[best] >= MIN_CONFIDENCE and scores[best] - scores[runner_up] >= MIN_MARGIN
    return VideoTypeResult(
        video_type=best if confident else "unknown",
        confidence=round(scores[best], 3),
        suggested_type=best,
        sampled_frames=count,
        scores={key: round(value, 3) for key, value in scores.items()},
        evidence={
            "multiple_large_faces": round(multiple_faces, 3),
            "single_large_face": round(single_face, 3),
            "dark_center_dividers": round(dark_dividers, 3),
            "lower_plate_candidates": round(lower_plates, 3),
            "frame_change": round(motion, 3),
        },
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("video", type=Path, help="Video to analyze locally")
    args = parser.parse_args()
    print(json.dumps(asdict(analyze_video(args.video)), indent=2))


if __name__ == "__main__":
    main()
