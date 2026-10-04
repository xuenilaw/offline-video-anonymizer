"""Offline audio choices for a processed MP4 video."""

import os
from pathlib import Path
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


def finish_video(video_only_path, source_path, output_path, *, mode, semitones=-4):
    """Add original, altered, or no audio without uploading media."""
    video_only_path = Path(video_only_path)
    source_path = Path(source_path)
    output_path = Path(output_path)
    if mode not in {"keep", "mute", "alter"}:
        raise ValueError(f"Unsupported audio mode: {mode}")
    if mode == "alter" and (semitones == 0 or not -6 <= semitones <= 6):
        raise ValueError("Altered voice requires a pitch shift from -6 to -1 or 1 to 6 semitones")

    if mode == "mute":
        # The OpenCV-created MP4 has no audio stream.
        os.replace(video_only_path, output_path)
        return

    partial_path = output_path.with_name(f".{output_path.stem}.audio_tmp.mp4")
    command = [
        get_ffmpeg_exe(), "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_only_path), "-i", str(source_path),
        "-map", "0:v:0", "-map", "1:a?" if mode == "keep" else "1:a:0",
        "-c:v", "copy", "-map_metadata", "-1",
    ]
    if mode == "keep":
        command.extend(["-c:a", "copy"])
    else:
        command.extend(["-af", _pitch_filter(semitones), "-c:a", "aac", "-b:a", "192k"])
    command.extend(["-shortest", "-movflags", "+faststart", str(partial_path)])

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
