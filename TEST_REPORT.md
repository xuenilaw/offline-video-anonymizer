# Test & validation report

**Tester:** Claude Code · **Last tested commit:** `5a26623` (Improve face masking and handle unreliable frame counts) · **Date:** 2026-10-06
**Platform tested:** macOS (Apple Silicon), Python 3.14 `.venv`, and the built `dist/OfflineVideoAnonymizer.app`. Windows was not tested.

## How to use this report (for Codex)

1. Work through the **open** bugs below, in the listed order of priority.
2. Each bug has **Acceptance criteria**. A fix is done only when those pass. Add or extend tests in `tests/` where the criteria can be automated.
3. Don't break the items under **Verified working**. Run `python -m unittest discover tests` before finishing.
4. When you're done, fill in the **Codex response** section at the bottom: what you changed, which bugs you consider fixed, and anything you chose not to fix and why. Claude Code will re-test from that section.

## Status overview

| # | Bug | Severity | Status |
|---|---|---|---|
| 1 | Large faces get weak pixelation | High | ✅ Fixed in `5a26623` (keep as regression guard) |
| 2 | Small/distant faces missed in dashcam footage | High | ⚠️ Open (improved, not fixed) |
| 3 | Crash when the reported frame count is wrong | Medium | ✅ Fixed in `5a26623` |
| 4 | Audio/video drift on variable-frame-rate (VFR) input | Medium | ❌ Open |
| 5 | "Keep original sound" copies codecs that MP4 players can't play | Medium | ❌ Open |
| 6 | Hidden temp file can be left behind after a failure | Low | ⚠️ Open (main trigger gone; cleanup not robust) |
| 7 | Output video codec is legacy MPEG-4 Part 2 (`mp4v`) | Low | ❌ Open |
| 8 | Single-video mode overwrites an existing result without warning | Low | ❌ Open |
| 9 | Processing errors show a dialog titled "Analysis failed" | Low | ❌ Open |
| 10 | Meeting profile padding leaves hair/ear outline visible | Low | ❌ Open |

## Test videos

The bugs were reproduced with videos generated from the checked-in sample clips. Create them in a scratch folder (not committed; `*.mp4`/`*.mkv` are git-ignored) with:

```bash
FF=$(.venv/bin/python -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
mkdir -p /tmp/anon-tests && cd /tmp/anon-tests
P=<project folder>
q() { "$FF" -hide_banner -loglevel error -y "$@"; }
q -ss 1.3 -i $P/test_video_1.mp4 -t 4 -c copy cut.mp4                     # edit list: reported 130 frames, decodes 98
q -ss 1.3 -i $P/test_video_1.mp4 -t 4 -c copy cut.mkv                     # reported 134, decodes 130
q -i $P/test_video.mp4 -c:v libx264 -c:a aac -f matroska - > piped.mkv    # no duration: reported count is negative
q -i $P/test_video.mp4 -vf "select='not(between(n,40,59))'" -fps_mode vfr -c:v libx264 -c:a aac vfr_av.mp4   # VFR with audio
q -i $P/test_video.mp4 -t 3 -c:v libx264 -c:a pcm_s16le pcm.mov           # PCM audio
q -i $P/test_video.mp4 -t 3 -c:v mpeg4   -c:a pcm_s16le pcm.avi
q -i $P/test_video.mp4 -t 3 -c:v libx264 -c:a libvorbis vorbis.mkv       # Vorbis audio
q -i $P/test_video.mp4 -t 3 -c:v libx264 -c:a libopus opus.mkv
```

**Close-up face video (bug 1):** take the face at roughly `x=700..1060, y=300..660` from frame 50 of `test_video.mp4`. Upscale it to 1000×1000 and paste it at `(460, 40)` on a grey 1920×1080 frame. Write 25 frames at 25 FPS.

**Leak check (bugs 1, 2):** re-run YuNet (`models/face_detection_yunet_2023mar.onnx`, `score_threshold=0.45`, input size = frame size) on every frame of the **output**. Count the frames and detections that are still found. A face the production detector can still find in the output is treated as a likely leak, so confirm the result visually with crops.

---

## Open bugs

### Bug 2 — Small/distant faces missed in dashcam footage (High)

**Where:** `main.py` → `detect_faces()` (dashcam tile pass) and the YuNet threshold.

**Repro:** `python main.py --input test_video_1.mp4 --output out/dash.mp4` (auto-detected as dashcam).

**Evidence (leak check at 0.45 on the output):**

| Version | Frames with a detectable face | Detections |
|---|---|---|
| Before `5a26623` | 139 / 192 | 227 |
| `5a26623` | 67 / 192 | 76 |

Visual check (crop source vs. output around `(290..430, 240..340)` in frames 4, 6 and 9): the 3rd and 4th pedestrians at the crossing in frame 4 and the bald man in frame 9 are still unmasked. Their faces are about 7–12 px tall. The tile pass enlarges each tile only about 1.8× (0.56-size tiles scaled to the full frame), so an 8 px face becomes about 14 px. That is still below what YuNet detects reliably.

**Cost:** dashcam processing time doubled (≈11 s → ≈22 s for the 8 s clip on an M-series Mac). Keep any further slowdown proportionate.

**Suggested directions (pick what works, measure it):**
- Use a stronger magnification for the tile pass: smaller tiles (for example a 3×3 grid with overlap, about 3× enlargement) limited to the band where pedestrians appear (roughly y = 25–75 % of the frame in dashcam footage).
- Use a lower score threshold (for example 0.35) only for detections from the tile pass, combined with the existing tracking.
- Optionally use a pedestrian/person detector and mask the head area of each person box. This is more robust than face detection at these sizes.
- At a minimum, make the README and the in-app text tell users clearly to review dashcam results and draw cover areas, because automatic detection will not catch every distant face.

**Acceptance criteria:**
- Leak check on the `test_video_1.mp4` output: **≤ 20 detections**, and none in frames 4, 6 and 9 at the coordinates above.
- No regression on the meeting video: the leak check on the `test_video.mp4` output stays at ≤ 2 detections.
- Dashcam processing time ≤ 3× the time before `5a26623` (≈ 33 s for `test_video_1.mp4` on this Mac).

### Bug 4 — Audio/video drift on variable-frame-rate input (Medium)

**Where:** `main.py`. The `cv2.VideoWriter` uses one constant `fps` (`CAP_PROP_FPS`, the *average*), and timed regions use `seconds = processed / fps`.

**Repro:** process `vfr_av.mp4` (20 frames removed in the middle; the audio stays continuous).

**Evidence:** the source has 172 frames at an average of 21.5 FPS. The output replays all frames evenly at 21.5 FPS, so the frame originally shown at 2.50 s appears at about 1.86 s, **≈0.64 s ahead of the audio**. Phone videos and Zoom/Teams/screen recordings are often VFR, so this affects real inputs.

**Suggested direction:** keep the original timestamps. Read each frame's time with `capture.get(cv2.CAP_PROP_POS_MSEC)`. Then either pipe the frames to FFmpeg with matching timestamps (for example raw frames plus a timestamp file / `-vf setpts`), or remux the processed video with the source's timing. Use the real frame time for `region_active()` as well. If the manual-region editor shows times, it should use the same clock.

**Acceptance criteria:**
- For `vfr_av.mp4`, each output frame's timestamp is within one frame duration (≈ 50 ms) of the matching source frame's timestamp. Compare with `ffprobe -show_frames` or OpenCV `CAP_PROP_POS_MSEC`.
- Constant-frame-rate inputs (`test_video.mp4`, `test_video_1.mp4`) produce the same frame count and duration as before.
- A timed `--hide-region ...,2,4` on a VFR input covers the frames whose source timestamps fall in 2–4 s.

### Bug 5 — "Keep original sound" copies codecs that MP4 players can't play (Medium)

**Where:** `audio_processing.py:43` (`-c:a copy` in `keep` mode).

**Repro:** keep-mode on `pcm.mov`, `pcm.avi`, `vorbis.mkv`.

**Evidence:** the output MP4s contain `pcm_s16le` (`ipcm`) or `vorbis` audio. FFmpeg writes them, but QuickTime, most browsers and many platforms won't play that audio. Opus-in-MP4 also has limited support (QuickTime/Safari).

**Suggested direction:** copy only when the source codec is MP4-friendly (`aac`, `mp3`, `alac`). Otherwise re-encode to AAC (`-c:a aac -b:a 192k`). Probe the codec with FFmpeg (`ffmpeg -i` output) or `ffprobe` if it is available in the bundle.

**Acceptance criteria:**
- Keep-mode outputs for `pcm.mov`, `pcm.avi`, `vorbis.mkv` and `opus.mkv` contain an `aac` audio stream.
- Keep-mode on `test_video.mp4` (already AAC) still copies the audio without re-encoding.

### Bug 6 — Hidden temp file can be left behind after a failure (Low)

**Where:** `main.py`. The temp file `.<output-stem>_video_only.mp4` is created next to the output. The desktop app (`desktop_app.py`, `_run_command_with_progress`) deletes temp files only when the user **cancels**, not on failure.

**Status:** the main trigger (the frame-count `RuntimeError`) was removed in `5a26623`, and `finish_video()` cleans up on audio errors. Any other exception between creating the writer and calling `finish_video()` still leaves the temp file in the user's output folder (for example a detector or I/O error, or `KeyboardInterrupt`).

**Suggested direction:** wrap the processing section in `try/except BaseException: temp_video_path.unlink(missing_ok=True); raise`. In the desktop app, also run the existing temp cleanup when `returncode != 0`, not only on cancel.

**Acceptance criteria:**
- A unit test that forces an exception mid-processing (for example by patching `detect_faces` to raise on frame 5) leaves no `.*_video_only.mp4` or `.*.audio_tmp.mp4` file in the output folder.

### Bug 7 — Output video codec is legacy MPEG-4 Part 2 (`mp4v`) (Low)

**Where:** `main.py`, `cv2.VideoWriter_fourcc(*"mp4v")`. In mute mode the OpenCV file becomes the final output unchanged.

**Evidence:** the output bitrate is about 1.6× the source's, and the codec is `mpeg4 (Simple Profile)`. Browsers and many upload platforms don't play MPEG-4 Part 2.

**Suggested direction:** FFmpeg already runs in `finish_video()` for keep/alter. Encode the video there with `-c:v libx264 -pix_fmt yuv420p -crf 18 -preset veryfast` instead of `-c:v copy`, and add the same FFmpeg pass in mute mode. Alternatively pipe raw frames straight into FFmpeg; this also helps with bug 4. Check that the bundled imageio-ffmpeg binary includes libx264 (it does on macOS arm64: `--enable-libx264`) and check the Windows build. Note the GPL implication of libx264 in `THIRD_PARTY.md`.

**Acceptance criteria:**
- Outputs in all three audio modes have an `h264` video stream with `yuv420p`.
- The output plays in QuickTime and in a browser `<video>` tag.

### Bug 8 — Single-video mode overwrites an existing result without warning (Low)

**Where:** `desktop_app.py` → `_browse_input()` sets the default `~/Movies/Offline Video Anonymizer/<stem>_anonymized.mp4`. `main.py`/`finish_video()` then `os.replace` onto it. Folder mode already avoids this with `unique_destination()`.

**Repro:** process the same video twice in single-video mode with the default output path. The first result is silently replaced.

**Suggested direction:** when the default path is filled in, use `unique_destination()` (numbered suffix). If the user picked an existing file explicitly in the Save dialog, the OS dialog has already confirmed the overwrite, so leave that case alone.

**Acceptance criteria:** processing the same file twice with default settings leaves both `x_anonymized.mp4` and `x_anonymized_2.mp4`.

### Bug 9 — Processing errors show a dialog titled "Analysis failed" (Low)

**Where:** `desktop_app.py` → `_drain_events()`, branch `kind == "error"`. It always sets the suggestion text to "Analysis failed…" and shows `messagebox.showerror("Analysis failed", ...)`. The processing worker (`_process`) also sends `("error", ...)` for `OSError`/`ValueError`. Since `5a26623`, that includes "No video frames could be decoded" from `video_frame_count()`.

**Suggested direction:** use separate event kinds (`analysis_error` and `processing_error`) with their own titles. Don't overwrite the type-suggestion text when processing fails.

**Acceptance criteria:** a processing failure shows "Processing failed" and leaves the analysis suggestion text unchanged.

### Bug 10 — Meeting profile padding leaves hair/ear outline visible (Low)

**Where:** `main.py`, `pad_x, pad_y = (0.15, 0.10) if video_type == "meeting" else (0.35, 0.40)`.

**Evidence:** on `test_video.mp4` frame 50, the top of the hair and the ear edges remain outside the mosaic. Hairstyle and outline are minor identifying cues.

**Suggested direction:** increase meeting padding to about (0.25, 0.30), and check that it doesn't cover the participant-name bars (those are drawn opaque anyway).

**Acceptance criteria:** visual check that hair and ears fall inside the mosaic on frame 50, and the name-label masks are unaffected.

---

## Fixed bugs (keep as regression guards)

### Bug 1 — Large faces got weak pixelation ✅
The old `tiny_width = (x2 - x1) // 14` gave about 14 px blocks, so a 600 px face kept about 40 blocks and stayed recognizable. `5a26623` caps the mosaic at 8 blocks. Verified visually on the close-up video and on the meeting video. Covered by `tests/test_processing_regressions.py::test_large_face_has_at_most_eight_blocks_across`.

### Bug 3 — Crash when the reported frame count was wrong ✅
`cut.mp4`, `cut.mkv` and `piped.mkv` now process fully (98, 130 and 192 frames). A folder batch through the desktop app went from 1/4 to 4/4 succeeded. Covered by `test_missing_and_inaccurate_frame_counts_do_not_fail_processing`.

## Informational (no action needed)
- The `-shortest` option in `finish_video()` trims 2–3 trailing frames (~0.1 s) when the audio track is slightly shorter than the video (seen on `cut.mp4`, `cut.mkv`, and a rotated clip). This is acceptable.

## Verified working (don't break)
- Type suggestion: meeting / dashcam / normal on the sample clips and synthetic videos.
- Name masks on the standard 2×2 meeting layout.
- Plate masking on the lead car in `test_video_1.mp4`.
- Moving-face tracking up to 40 px/frame with no gaps in the mask.
- Manual hide/blur/keep-clear regions: time boundaries, clipping when a box extends past the frame, cover winning over keep-clear.
- Rotated phone video (displaymatrix 90°) gives a correctly oriented 720×1280 output.
- Unicode and spaces in filenames.
- Global and stream metadata (title, location) are stripped.
- Alter mode: 44.1 kHz mono input works, and a source without audio gives a clear error.
- Folder batch: per-file failures don't stop the batch, and counts and progress are correct.
- Built `.app`: the smoke test passes, and its output matches the source output exactly on the close-up and dashcam videos.

---

## Codex response

- **Commit(s):** The commit containing this response (see Git history).
- **Bugs fixed:**
  - **2:** The dashcam detector uses six higher-magnification tiles over the pedestrian band, a 0.35 tile threshold, and stronger coverage for tiny faces. On `test_video_1.mp4`, the default keep-audio output had 9 YuNet leak-check detections across 192 frames, none in frames 4, 6, or 9; processing took 24.9 s on this Mac (limit 33 s). The meeting output had 0 detections across 192 frames (limit 2).
  - **4:** VFR frames retain source presentation times, and timed manual regions use that clock in processing and the editor. On `vfr_av.mp4`-style input, all 172 output frames were present, maximum source/output timestamp difference was 20 ms, and the 2–4 s cover followed source time. Both sample CFR clips kept 192 frames and 8.0 s duration.
  - **5:** Keep mode copies AAC/MP3/ALAC; PCM, Vorbis, and Opus are encoded to AAC. The four reported source formats produced AAC, while the sample AAC audio bytes were identical after remuxing.
  - **6:** Processing exceptions now remove intermediate video and frame files. Desktop failed/cancelled workers also clean up intermediate files. An injected detector error on frame 5 leaves no hidden video or audio temp file.
  - **8:** Single-video default destinations now get numbered names on repeat runs; an explicitly chosen Save path retains the Save dialog's overwrite decision. A two-run processing check left both `x_anonymized.mp4` and `x_anonymized_2.mp4`.
  - **9:** Analysis and processing errors have separate events. Processing errors show **Processing failed** without changing the type suggestion.
- **Bugs not fully accepted yet:**
  - **7:** All three audio modes now output H.264 `yuv420p`, and FFmpeg decodes them. The rebuilt macOS app passed its smoke test. Playback in QuickTime and a browser `<video>` element was not directly verified, so the full acceptance criterion remains open. Windows `libx264` availability also needs a Windows build check.
  - **10:** Meeting padding was widened to (0.40, 0.45). Frame 50 shows the top hair and ears inside the mosaic and the name bars intact, but some long hair remains visible around the lower participant. I have not marked the full visual criterion as passed; a larger symmetric box started to obscure other meeting content.
- **New or changed tests:** `tests/test_report_regressions.py` covers VFR timestamp and timed-cover behavior, four incompatible audio codecs plus AAC stream copying, H.264 output in all audio modes, mid-processing cleanup, numbered destinations, and processing-error dialog behavior. `python -m unittest discover tests` passed (8 tests). The macOS bundle was rebuilt; its smoke test and bundled VFR worker check passed.
- **Anything Claude Code should test specially:** Recheck dashcam faces and plates visually, especially frames 4/6/9; inspect frame 50 of the meeting output for residual hair and subtitle coverage; play keep/mute/alter MP4s in QuickTime and a browser; build and test the Windows executable, including `libx264` support. VFR processing uses temporary JPEG frames beside the output, so test long recordings and cancellation with limited free disk space.
