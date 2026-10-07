"""Offline audio choices for a processed MP4 video."""

import os
from pathlib import Path
import re
import subprocess

from imageio_ffmpeg import get_ffmpeg_exe


def _pitch_filter(semitones):
    """Shift pitch and formants, then restore roughly the original duration."""
    factor = 2 ** (semitones / 12)
    shifted_rate = round(48000 * factor)
    return (
        f"aresample=48000,asetrate={shifted_rate},aresample=48000,"
        f"atempo={1 / factor:.6f}"
    )


def source_audio_codec(source_path):
    """Read the first audio codec from the bundled FFmpeg's stream listing."""
    result = subprocess.run(
        [get_ffmpeg_exe(), "-hide_banner", "-i", str(source_path)],
        capture_output=True, text=True,
    )
    match = re.search(r"Stream #\d+:\d+[^\n]*? Audio: ([\w]+)", result.stderr)
    return match.group(1).lower() if match else None


def encode_timed_frames(frame_paths, timestamps, output_path, fps):
    """Encode image frames with their source presentation times via FFmpeg concat."""
    output_path = Path(output_path)
    manifest = output_path.with_name(f"{output_path.stem}.frames.ffconcat")
    try:
        lines = ["ffconcat version 1.0"]
        for index, path in enumerate(frame_paths):
            duration = (timestamps[index + 1] - timestamps[index]
                        if index + 1 < len(timestamps) else 1 / fps)
            escaped_path = Path(path).resolve().as_posix().replace("'", "'\\''")
            lines.extend((f"file '{escaped_path}'",
                          f"duration {duration:.9f}"))
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        command = [get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
                   "-safe", "0", "-f", "concat", "-i", str(manifest),
                   "-fps_mode", "vfr", "-frames:v", str(len(frame_paths)),
                   "-c:v", "libx264", "-pix_fmt", "yuv420p", "-crf", "18",
                   "-preset", "veryfast", str(output_path)]
        subprocess.run(command, check=True, capture_output=True, text=True)
    finally:
        manifest.unlink(missing_ok=True)


def finish_video(video_only_path, source_path, output_path, *, mode, semitones=-4,
                 video_already_h264=False):
    """Add original, altered, or no audio without uploading media."""
    video_only_path = Path(video_only_path)
    source_path = Path(source_path)
    output_path = Path(output_path)
    if mode not in {"keep", "mute", "alter"}:
        raise ValueError(f"Unsupported audio mode: {mode}")
    if mode == "alter" and (semitones == 0 or not -6 <= semitones <= 6):
        raise ValueError("Altered voice requires a pitch shift from -6 to -1 or 1 to 6 semitones")

    partial_path = output_path.with_name(f".{output_path.stem}.audio_tmp.mp4")
    command = [
        get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_only_path),
    ]
    if mode != "mute":
        command.extend(("-i", str(source_path)))
    command.extend(("-map", "0:v:0"))
    if mode != "mute":
        command.extend(("-map", "1:a?" if mode == "keep" else "1:a:0"))
    command.extend(("-map_metadata", "-1", "-map_chapters", "-1"))
    if video_already_h264:
        command.extend(("-c:v", "copy"))
    else:
        command.extend(("-c:v", "libx264", "-pix_fmt", "yuv420p",
                        "-crf", "18", "-preset", "veryfast"))
    if mode == "keep":
        if source_audio_codec(source_path) in {"aac", "mp3", "alac"}:
            command.extend(("-c:a", "copy"))
        else:
            command.extend(("-c:a", "aac", "-b:a", "192k"))
    elif mode == "alter":
        command.extend(["-af", _pitch_filter(semitones), "-c:a", "aac", "-b:a", "192k"])
    if mode != "mute":
        command.append("-shortest")
    command.extend(["-movflags", "+faststart", str(partial_path)])

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
        os.replace(partial_path, output_path)
    except subprocess.CalledProcessError as error:
        detail = error.stderr.strip() or "FFmpeg could not process the audio"
        if mode == "alter" and "matches no streams" in detail:
            detail = "the source video has no audio track to alter"
        raise RuntimeError(f"Audio mode '{mode}' failed: {detail}") from error
    finally:
        partial_path.unlink(missing_ok=True)
        video_only_path.unlink(missing_ok=True)
