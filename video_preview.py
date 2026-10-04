"""Embedded local video review widget for the Tkinter desktop app."""

import base64
import os
from pathlib import Path
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tkinter as tk
from tkinter import ttk

import cv2
import imageio_ffmpeg


class VideoPreview(ttk.Frame):
    """Show the processed MP4 in the window, with local audio when available."""

    def __init__(self, parent):
        super().__init__(parent)
        self.video_path = None
        self.capture = None
        self.frame_count = 0
        self.fps = 24.0
        self.playing = False
        self.start_time = 0.0
        self.current_frame = -1
        self.after_id = None
        self.audio_process = None
        self.audio_path = None
        self.audio_directory = None
        self.audio_ready = False
        self.generation = 0
        self.events = queue.Queue()
        self.image = None
        self.status = tk.StringVar(value="The anonymized video will appear here after processing.")
        self.clock = tk.StringVar(value="00:00 / 00:00")

        self.screen = tk.Label(self, text="Preview will appear here", bg="#151a24", fg="white",
                               width=64, height=18, compound="center")
        self.screen.pack(fill="both", expand=True)
        controls = ttk.Frame(self)
        controls.pack(fill="x", pady=(8, 0))
        self.play_button = ttk.Button(controls, text="▶ Play", command=self.play, state="disabled")
        self.play_button.pack(side="left")
        self.stop_button = ttk.Button(controls, text="■ Stop", command=self.stop, state="disabled")
        self.stop_button.pack(side="left", padx=(6, 0))
        ttk.Label(controls, textvariable=self.clock).pack(side="left", padx=12)
        self.open_button = ttk.Button(controls, text="Open full video", command=self.open_external,
                                      state="disabled")
        self.open_button.pack(side="right")
        ttk.Label(self, textvariable=self.status, wraplength=470, justify="left").pack(
            fill="x", anchor="w", pady=(8, 0)
        )
        self.after(100, self._drain_events)

    def load(self, path):
        """Load the finished file and show its first frame immediately."""
        self.clear()
        self.video_path = Path(path).resolve()
        self.capture = cv2.VideoCapture(str(self.video_path))
        if not self.capture.isOpened():
            self.capture = None
            self.status.set("Could not open the finished video for preview. Use Open full video.")
            self.open_button.configure(state="normal")
            return
        self.fps = self.capture.get(cv2.CAP_PROP_FPS) or 24.0
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.current_frame = -1
        if not self._show_next_frame():
            self.status.set("The finished video contains no readable frames.")
            self.play_button.configure(state="disabled")
            return
        self._set_clock()
        self.open_button.configure(state="normal")
        self.status.set("Preparing preview sound locally…")
        threading.Thread(target=self._prepare_audio, args=(self.generation, self.video_path),
                         daemon=True).start()

    def _prepare_audio(self, generation, path):
        if sys.platform != "darwin" or not shutil.which("afplay"):
            self.events.put((generation, None, None, "Sound plays in the full video player."))
            return
        directory = tempfile.TemporaryDirectory(prefix="anonymizer_preview_")
        audio_path = Path(directory.name) / "preview.mp3"
        command = [imageio_ffmpeg.get_ffmpeg_exe(), "-y", "-loglevel", "error",
                   "-i", str(path), "-map", "0:a:0", "-vn", "-c:a", "libmp3lame",
                   "-b:a", "128k", str(audio_path)]
        try:
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 0 and audio_path.is_file():
                self.events.put((generation, directory, audio_path, "Ready. Play the result here, then review the full video."))
            else:
                directory.cleanup()
                self.events.put((generation, None, None, "Ready. This video has no preview sound."))
        except OSError:
            directory.cleanup()
            self.events.put((generation, None, None, "Ready. Open the full video to check sound."))

    def _drain_events(self):
        try:
            while True:
                generation, directory, audio_path, status = self.events.get_nowait()
                if generation != self.generation:
                    if directory is not None:
                        directory.cleanup()
                    continue
                self.audio_directory = directory
                self.audio_path = audio_path
                self.audio_ready = True
                self.status.set(status)
                if self.capture is not None:
                    self.play_button.configure(state="normal")
        except queue.Empty:
            pass
        self.after(100, self._drain_events)

    def _show_next_frame(self):
        ok, frame = self.capture.read()
        if not ok:
            return False
        self.current_frame += 1
        height, width = frame.shape[:2]
        scale = min(480 / width, 300 / height)
        frame = cv2.resize(frame, (max(1, round(width * scale)), max(1, round(height * scale))),
                           interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            return False
        self.image = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()).decode("ascii"))
        self.screen.configure(image=self.image, text="")
        return True

    def _set_clock(self):
        current = max(0, self.current_frame) / self.fps
        total = self.frame_count / self.fps
        self.clock.set(f"{int(current // 60):02d}:{int(current % 60):02d} / "
                       f"{int(total // 60):02d}:{int(total % 60):02d}")

    def play(self):
        if self.capture is None or not self.audio_ready:
            return
        self.stop()
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, 0)
        self.current_frame = -1
        if not self._show_next_frame():
            return
        self._set_clock()
        self.playing = True
        self.start_time = time.monotonic()
        if self.audio_path is not None:
            try:
                self.audio_process = subprocess.Popen(["afplay", str(self.audio_path)],
                                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.status.set("Preview sound could not start. Open the full video to check sound.")
        self.play_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self._tick()

    def _tick(self):
        if not self.playing:
            return
        if self.audio_process is not None and self.audio_process.poll() not in (None, 0):
            self.status.set("Preview sound could not play here. Use Open full video to check it.")
            self.audio_process = None
        target = min(int((time.monotonic() - self.start_time) * self.fps), self.frame_count - 1)
        while self.current_frame < target:
            if not self._show_next_frame():
                self.stop()
                return
        self._set_clock()
        if self.current_frame >= self.frame_count - 1:
            self.stop()
        else:
            self.after_id = self.after(15, self._tick)

    def stop(self):
        self.playing = False
        if self.after_id is not None:
            self.after_cancel(self.after_id)
            self.after_id = None
        if self.audio_process is not None:
            if self.audio_process.poll() is None:
                self.audio_process.terminate()
            self.audio_process = None
        self.stop_button.configure(state="disabled")
        self.play_button.configure(state="normal" if self.capture is not None and self.audio_ready else "disabled")

    def open_external(self):
        if self.video_path is None:
            return
        self.stop()
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(self.video_path)])
        elif os.name == "nt":
            os.startfile(self.video_path)
        else:
            subprocess.Popen(["xdg-open", str(self.video_path)])

    def close(self):
        self.clear()

    def clear(self):
        """Release the current result and any temporary preview audio."""
        self.stop()
        self.generation += 1
        if self.capture is not None:
            self.capture.release()
            self.capture = None
        if self.audio_directory is not None:
            self.audio_directory.cleanup()
            self.audio_directory = None
        self.video_path = None
        self.audio_path = None
        self.audio_ready = False
        self.frame_count = 0
        self.current_frame = -1
        self.image = None
        self.screen.configure(image="", text="Preview will appear here")
        self.clock.set("00:00 / 00:00")
        self.status.set("The anonymized video will appear here after processing.")
        self.play_button.configure(state="disabled")
        self.stop_button.configure(state="disabled")
        self.open_button.configure(state="disabled")
