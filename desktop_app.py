"""Small offline desktop front end for the video anonymizer."""

import json
from pathlib import Path
import queue
import subprocess
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError as error:
    raise SystemExit(
        "Tkinter is missing. On Homebrew Python, install the matching python-tk package "
        "(for example: brew install python-tk@3.14), then run this file again."
    ) from error

from video_preview import VideoPreview
from video_type import analyze_video


PROJECT_DIR = Path(__file__).resolve().parent
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi"}
TYPE_LABELS = {
    "Let the app suggest": "auto",
    "Online meeting": "meeting",
    "Dashcam footage": "dashcam",
    "Phone or camera video": "normal",
}


def unique_destination(source, output_folder, reserved):
    """Keep every batch output separate, including across repeated runs."""
    base = source.stem + "_anonymized"
    counter = 1
    while True:
        suffix = "" if counter == 1 else f"_{counter}"
        destination = output_folder / f"{base}{suffix}.mp4"
        if not destination.exists() and destination not in reserved:
            reserved.add(destination)
            return destination
        counter += 1


class AnonymizerApp:
    def __init__(self, root):
        self.root = root
        root.title("Offline Video Anonymizer")
        root.minsize(1050, 700)
        root.geometry("1120x760")
        self.events = queue.Queue()
        self.running = False
        self.analysis = None
        self.results = []
        self.result_index = -1
        self.input_mode = tk.StringVar(value="video")
        self.input_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.video_type = tk.StringVar(value="Let the app suggest")
        self.auto_batch = tk.BooleanVar(value=True)
        self.faces = tk.BooleanVar(value=True)
        self.plates = tk.BooleanVar(value=False)
        self.names = tk.BooleanVar(value=False)
        self.name_regions = tk.StringVar()
        self.audio_mode = tk.StringVar(value="keep")
        self.pitch = tk.StringVar(value="-4")
        self.suggestion = tk.StringVar(value="Select a video, then analyze it locally.")
        self.mask_summary = tk.StringVar()
        self.progress = tk.StringVar()
        self.result_position = tk.StringVar(value="No results yet")

        container = ttk.Frame(root, padding=18)
        container.pack(fill="both", expand=True)
        container.columnconfigure(0, weight=3)
        container.columnconfigure(1, weight=2)
        container.rowconfigure(1, weight=1)
        ttk.Label(container, text="Offline Video Anonymizer", font=("TkDefaultFont", 20, "bold")).grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        left_area = ttk.Frame(container)
        left_area.grid(row=1, column=0, sticky="nsew", padx=(0, 18), pady=(14, 0))
        left_area.columnconfigure(0, weight=1)
        left_area.rowconfigure(0, weight=1)
        left_canvas = tk.Canvas(left_area, highlightthickness=0)
        left_canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(left_area, orient="vertical", command=left_canvas.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        left_canvas.configure(yscrollcommand=scrollbar.set)
        left = ttk.Frame(left_canvas)
        left.columnconfigure(0, weight=1)
        left_window = left_canvas.create_window((0, 0), window=left, anchor="nw")
        left.bind("<Configure>", lambda _event: left_canvas.configure(scrollregion=left_canvas.bbox("all")))
        left_canvas.bind("<Configure>", lambda event: left_canvas.itemconfigure(left_window, width=event.width))
        left_canvas.bind("<MouseWheel>",
                         lambda event: left_canvas.yview_scroll(-1 if event.delta > 0 else 1, "units"))
        right = ttk.Frame(container)
        right.grid(row=1, column=1, sticky="nsew", pady=(14, 0))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        files = ttk.LabelFrame(left, text="1  Choose video or folder", padding=12)
        files.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        files.columnconfigure(1, weight=1)
        ttk.Radiobutton(files, text="One video", variable=self.input_mode, value="video",
                        command=self._mode_changed).grid(row=0, column=0, sticky="w")
        ttk.Radiobutton(files, text="Folder of videos", variable=self.input_mode, value="folder",
                        command=self._mode_changed).grid(row=0, column=1, sticky="w")
        self.input_label = self._file_row(files, 1, "Video to anonymize", self.input_path, self._browse_input)
        self.output_label = self._file_row(files, 2, "Save result as", self.output_path, self._browse_output)

        source = ttk.LabelFrame(left, text="2  Choose a starting point", padding=12)
        source.grid(row=1, column=0, sticky="ew", pady=(0, 10))
        source.columnconfigure(0, weight=1)
        ttk.Label(source, text="What kind of recording is this?").grid(row=0, column=0, sticky="w")
        type_box = ttk.Combobox(source, textvariable=self.video_type, values=list(TYPE_LABELS), state="readonly")
        type_box.grid(row=1, column=0, sticky="ew", pady=(6, 4))
        type_box.bind("<<ComboboxSelected>>", self._type_changed)
        self.analyze_button = ttk.Button(source, text="Analyze again", command=self._analyze)
        self.analyze_button.grid(row=1, column=1, padx=(8, 0))
        ttk.Label(source, textvariable=self.suggestion, wraplength=550, justify="left").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(2, 0)
        )
        self.batch_checkbox = ttk.Checkbutton(
            source, text="Use recommended masks for each video in the folder",
            variable=self.auto_batch, command=self._mask_changed
        )
        self.batch_checkbox.grid(row=3, column=0, columnspan=2, sticky="w", pady=(5, 0))
        self.batch_checkbox.grid_remove()

        masks = ttk.LabelFrame(left, text="3  What should be hidden?", padding=12)
        masks.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        masks.columnconfigure(0, weight=1)
        choices = (
            ("Faces", "People visible in the picture", self.faces),
            ("Vehicle plates", "Usually for dashcam footage; may affect screen text", self.plates),
            ("Participant names", "Meeting name labels; standard 2×2 layout is automatic", self.names),
        )
        for row, (label, help_text, variable) in enumerate(choices):
            ttk.Checkbutton(masks, text=label, variable=variable, command=self._mask_changed).grid(
                row=row * 2, column=0, sticky="w"
            )
            ttk.Label(masks, text=help_text, foreground="#555555").grid(
                row=row * 2 + 1, column=0, sticky="w", padx=(22, 0), pady=(0, 5)
            )
        ttk.Label(masks, textvariable=self.mask_summary, wraplength=550).grid(
            row=6, column=0, sticky="w", pady=(4, 6)
        )
        ttk.Button(masks, text="Advanced: add name areas", command=self._toggle_advanced).grid(
            row=7, column=0, sticky="w"
        )
        self.advanced = ttk.Frame(masks)
        self.advanced.grid(row=8, column=0, sticky="ew", pady=(7, 0))
        self.advanced.columnconfigure(0, weight=1)
        ttk.Label(self.advanced, text="Extra name areas: x,y,width,height; separate areas with semicolons.",
                  wraplength=530).grid(row=0, column=0, sticky="w")
        ttk.Entry(self.advanced, textvariable=self.name_regions).grid(row=1, column=0, sticky="ew", pady=(4, 0))
        self.advanced.grid_remove()

        audio = ttk.LabelFrame(left, text="4  What should happen to the sound?", padding=12)
        audio.grid(row=3, column=0, sticky="ew", pady=(0, 10))
        for row, (label, value) in enumerate((("Keep original sound", "keep"),
                                               ("Mute all sound", "mute"),
                                               ("Change voice pitch", "alter"))):
            ttk.Radiobutton(audio, text=label, variable=self.audio_mode, value=value,
                            command=self._audio_changed).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Label(audio, text="Pitch shift (semitones)").grid(row=2, column=1, padx=(20, 5))
        self.pitch_entry = ttk.Entry(audio, textvariable=self.pitch, width=5)
        self.pitch_entry.grid(row=2, column=2)
        self._audio_changed()

        self.run_button = ttk.Button(left, text="Create anonymized video", command=self._process)
        self.run_button.grid(row=4, column=0, sticky="ew", pady=(2, 0))
        ttk.Label(left, textvariable=self.progress, wraplength=550).grid(row=5, column=0, sticky="w", pady=(6, 0))
        ttk.Label(left, text="Review every result before sharing. Automatic detection can miss details.",
                  wraplength=550).grid(row=6, column=0, sticky="w", pady=(6, 0))

        ttk.Label(right, text="Result preview", font=("TkDefaultFont", 14, "bold")).grid(
            row=0, column=0, sticky="w", pady=(0, 8)
        )
        self.preview = VideoPreview(right)
        self.preview.grid(row=1, column=0, sticky="nsew")
        navigation = ttk.Frame(right)
        navigation.grid(row=2, column=0, sticky="ew", pady=(8, 0))
        self.previous_button = ttk.Button(navigation, text="‹ Previous", command=lambda: self._show_result(-1),
                                           state="disabled")
        self.previous_button.pack(side="left")
        ttk.Label(navigation, textvariable=self.result_position, anchor="center").pack(
            side="left", fill="x", expand=True, padx=8
        )
        self.next_button = ttk.Button(navigation, text="Next ›", command=lambda: self._show_result(1),
                                       state="disabled")
        self.next_button.pack(side="right")
        details = ttk.LabelFrame(right, text="Processing details", padding=8)
        details.grid(row=3, column=0, sticky="ew", pady=(14, 0))
        self.log = tk.Text(details, height=7, state="disabled", wrap="word")
        self.log.pack(fill="both", expand=True)
        self._mask_changed()
        root.protocol("WM_DELETE_WINDOW", self._close)
        root.after(100, self._drain_events)

    def _toggle_advanced(self):
        if self.advanced.winfo_ismapped():
            self.advanced.grid_remove()
        else:
            self.advanced.grid()

    def _mask_changed(self):
        selected = [label for label, variable in (("faces", self.faces), ("plates", self.plates),
                                                  ("names", self.names)) if variable.get()]
        fallback = (self.input_mode.get() == "folder" and self.video_type.get() == "Let the app suggest"
                    and self.auto_batch.get())
        prefix = "Fallback for uncertain videos: " if fallback else "Selected for processing: "
        self.mask_summary.set(prefix + (", ".join(selected) if selected else "nothing — choose at least one"))

    def _audio_changed(self):
        self.pitch_entry.configure(state="normal" if self.audio_mode.get() == "alter" else "disabled")

    def _close(self):
        if self.running:
            messagebox.showinfo("Processing", "Wait for the current operation to finish before closing the app.")
        else:
            self.preview.close()
            self.root.destroy()

    def _file_row(self, panel, row, label, variable, browse):
        caption = ttk.Label(panel, text=label)
        caption.grid(row=row, column=0, sticky="w", pady=8)
        ttk.Entry(panel, textvariable=variable).grid(row=row, column=1, sticky="ew", pady=8)
        ttk.Button(panel, text="Browse", command=browse).grid(row=row, column=2, padx=(8, 0))
        return caption

    def _mode_changed(self):
        folder = self.input_mode.get() == "folder"
        self.input_path.set("")
        self.output_path.set("")
        self.analysis = None
        self.input_label.configure(text="Folder to anonymize" if folder else "Video to anonymize")
        self.output_label.configure(text="Save results in" if folder else "Save result as")
        self.run_button.configure(text="Create anonymized videos" if folder else "Create anonymized video")
        self.analyze_button.configure(state="disabled" if folder else "normal")
        if folder:
            self.batch_checkbox.grid()
            self.suggestion.set("Select a folder. Videos in that folder will be processed one at a time.")
        else:
            self.batch_checkbox.grid_remove()
            self.suggestion.set("Select a video, then analyze it locally.")
        self._type_changed()

    def _videos_in_folder(self, folder):
        return sorted((path for path in folder.iterdir()
                       if path.is_file() and path.suffix.lower() in VIDEO_EXTENSIONS),
                      key=lambda path: path.name.lower())

    def _browse_input(self):
        if self.input_mode.get() == "folder":
            selected = filedialog.askdirectory(title="Choose a folder of videos")
        else:
            selected = filedialog.askopenfilename(filetypes=[("Video files", "*.mp4 *.mov *.mkv *.avi"), ("All files", "*")])
        if selected:
            self.input_path.set(selected)
            self.analysis = None
            if self.input_mode.get() == "folder":
                self.output_path.set(str(Path(selected) / "anonymized"))
                count = len(self._videos_in_folder(Path(selected)))
                self.suggestion.set(f"Found {count} video file(s) in this folder. Subfolders are not included.")
            else:
                self.output_path.set(str(PROJECT_DIR / "output" / f"{Path(selected).stem}_anonymized.mp4"))
                self.suggestion.set("Checking a few frames locally…")
                self._analyze()

    def _browse_output(self):
        if self.input_mode.get() == "folder":
            selected = filedialog.askdirectory(title="Choose an output folder")
        else:
            selected = filedialog.asksaveasfilename(defaultextension=".mp4", filetypes=[("MP4 video", "*.mp4")])
        if selected:
            self.output_path.set(selected)

    def _type_changed(self, _event=None):
        selected = TYPE_LABELS[self.video_type.get()]
        if selected == "auto" and self.analysis:
            selected = self.analysis["video_type"]
        self.faces.set(True)
        self.plates.set(selected == "dashcam")
        self.names.set(selected == "meeting")
        self.batch_checkbox.configure(state="normal" if selected == "auto" else "disabled")
        self._mask_changed()

    def _start(self, worker):
        if self.running:
            return
        self.running = True
        self.run_button.configure(state="disabled")
        self.analyze_button.configure(state="disabled")
        threading.Thread(target=worker, daemon=True).start()

    def _analyze(self):
        if self.input_mode.get() == "folder":
            return
        source = Path(self.input_path.get())
        if not source.is_file():
            messagebox.showerror("Input needed", "Select an existing video file first.")
            return
        self.suggestion.set("Analyzing sampled frames locally…")

        def worker():
            try:
                result = subprocess.run([sys.executable, str(PROJECT_DIR / "video_type.py"), str(source)],
                                        capture_output=True, text=True)
                if result.returncode:
                    self.events.put(("error", result.stderr.strip() or result.stdout.strip()))
                else:
                    self.events.put(("analysis", (str(source.resolve()), result.stdout)))
            except OSError as error:
                self.events.put(("error", str(error)))
            finally:
                self.events.put(("done", None))

        self._start(worker)

    def _settings(self):
        source = Path(self.input_path.get())
        destination = Path(self.output_path.get())
        folder = self.input_mode.get() == "folder"
        if folder:
            if not source.is_dir():
                raise ValueError("Select an existing folder of videos.")
            sources = self._videos_in_folder(source)
            if not sources:
                raise ValueError("This folder has no MP4, MOV, MKV, or AVI videos.")
        else:
            if not source.is_file():
                raise ValueError("Select an existing input video.")
            sources = [source]
        if not self.output_path.get().strip() or source.resolve() == destination.resolve():
            raise ValueError("Choose a separate output location.")
        if folder and destination.exists() and not destination.is_dir():
            raise ValueError("The output location must be a folder.")
        if not folder and destination.exists() and destination.is_dir():
            raise ValueError("The output location must be an MP4 file.")
        if not any((self.faces.get(), self.plates.get(), self.names.get())):
            raise ValueError("Select at least one item to hide.")
        if self.name_regions.get().strip() and not self.names.get():
            raise ValueError("Select Participant names to use extra name rectangles.")
        pitch = -4
        if self.audio_mode.get() == "alter":
            try:
                pitch = int(self.pitch.get())
            except ValueError as error:
                raise ValueError("Enter a whole number for the pitch shift.") from error
            if pitch == 0 or not -6 <= pitch <= 6:
                raise ValueError("Pitch must be -6 to -1 or 1 to 6 semitones.")
        regions = []
        for rectangle in self.name_regions.get().split(";"):
            if rectangle.strip():
                parts = rectangle.strip().split(",")
                if (len(parts) != 4 or any(not part.strip().isdigit() for part in parts)
                        or any(int(part) <= 0 for part in parts[2:])):
                    raise ValueError("Name rectangles must use x,y,width,height in pixels.")
                regions.append(rectangle.strip())
        return {
            "folder": folder,
            "sources": sources,
            "destination": destination,
            "video_type": TYPE_LABELS[self.video_type.get()],
            "auto_batch": self.auto_batch.get(),
            "masks": (self.faces.get(), self.plates.get(), self.names.get()),
            "audio_mode": self.audio_mode.get(),
            "pitch": pitch,
            "regions": regions,
        }

    def _command(self, source, destination, settings, video_type, masks):
        faces, plates, names = masks
        command = [sys.executable, "-u", str(PROJECT_DIR / "main.py"), "--input", str(source),
                   "--output", str(destination), "--video-type", video_type,
                   "--faces" if faces else "--no-faces",
                   "--plates" if plates else "--no-plates",
                   "--names" if names else "--no-names",
                   "--audio-mode", settings["audio_mode"], "--pitch-semitones", str(settings["pitch"])]
        if names:
            for rectangle in settings["regions"]:
                command.extend(("--name-region", rectangle))
        return command

    def _process(self):
        try:
            settings = self._settings()
        except ValueError as error:
            messagebox.showerror("Check settings", str(error))
            return
        self.results = []
        self.result_index = -1
        self._update_result_navigation()
        self.preview.clear()
        total = len(settings["sources"])
        self.progress.set(f"Processing {total} video(s) locally…")
        self._log(f"Starting {total} video(s).\n")

        def worker():
            completed = 0
            failed = 0
            reserved = set()
            try:
                for index, source in enumerate(settings["sources"], 1):
                    destination = (unique_destination(source, settings["destination"], reserved)
                                   if settings["folder"] else settings["destination"])
                    self.events.put(("progress", f"Processing {index} of {total}: {source.name}"))
                    self.events.put(("log", f"\n[{index}/{total}] {source.name}\n"))
                    try:
                        video_type = settings["video_type"]
                        masks = settings["masks"]
                        if settings["folder"] and video_type == "auto" and settings["auto_batch"]:
                            analysis = analyze_video(source)
                            video_type = analysis.video_type if analysis.video_type != "unknown" else "auto"
                            masks = {
                                "meeting": (True, False, True),
                                "dashcam": (True, True, False),
                                "normal": (True, False, False),
                            }.get(analysis.video_type, masks)
                            self.events.put(("log", f"Suggested type: {analysis.video_type}; "
                                                    f"masks: faces={masks[0]}, plates={masks[1]}, names={masks[2]}\n"))
                        command = self._command(source, destination, settings, video_type, masks)
                        process = subprocess.Popen(command, stdout=subprocess.PIPE,
                                                   stderr=subprocess.STDOUT, text=True, bufsize=1)
                        for line in process.stdout:
                            self.events.put(("log", line))
                        if process.wait() != 0:
                            failed += 1
                            self.events.put(("log", f"Failed: {source.name}. See the error above.\n"))
                        else:
                            completed += 1
                            self.events.put(("file_completed", destination.resolve()))
                    except (OSError, ValueError, RuntimeError) as error:
                        failed += 1
                        self.events.put(("log", f"Failed: {source.name}: {error}\n"))
                self.events.put(("batch_completed", (completed, failed)))
            except OSError as error:
                self.events.put(("error", str(error)))
            finally:
                self.events.put(("done", None))

        self._start(worker)

    def _log(self, message):
        self.log.configure(state="normal")
        self.log.insert("end", message)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _update_result_navigation(self):
        count = len(self.results)
        if self.result_index < 0:
            self.result_position.set("No results yet")
        else:
            current = self.results[self.result_index]
            self.result_position.set(f"{self.result_index + 1} / {count}  ·  {current.name}")
        self.previous_button.configure(state="normal" if self.result_index > 0 else "disabled")
        self.next_button.configure(state="normal" if self.result_index >= 0
                                   and self.result_index < count - 1 else "disabled")

    def _show_result(self, direction):
        target = self.result_index + direction
        if not 0 <= target < len(self.results):
            return
        self.result_index = target
        self.preview.load(self.results[target])
        self._update_result_navigation()

    def _drain_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "analysis":
                    source, data = payload
                    if source == str(Path(self.input_path.get()).resolve()):
                        self.analysis = json.loads(data)
                        result = self.analysis
                        if result["video_type"] == "unknown":
                            self.suggestion.set("No clear video type found. Choose a source above or select the masks yourself.")
                        else:
                            self.suggestion.set(
                                f"Suggested: {result['video_type']} (evidence score {result['confidence']:.2f}). "
                                "The checkboxes below are editable."
                            )
                        if self.video_type.get() == "Let the app suggest":
                            self._type_changed()
                elif kind == "log":
                    self._log(payload)
                elif kind == "progress":
                    self.progress.set(payload)
                elif kind == "error":
                    self.suggestion.set("Analysis failed. Check the error and choose a type manually.")
                    messagebox.showerror("Analysis failed", payload)
                elif kind == "file_completed":
                    self.results.append(payload)
                    if self.result_index == -1:
                        self._show_result(1)
                    else:
                        self._update_result_navigation()
                elif kind == "batch_completed":
                    completed, failed = payload
                    self.progress.set(f"Finished: {completed} succeeded, {failed} failed. "
                                      "Use ‹ and › to review each result.")
                    self._log(f"\nFinished: {completed} succeeded, {failed} failed.\n")
                elif kind == "done":
                    self.running = False
                    self.run_button.configure(state="normal")
                    self.analyze_button.configure(state="disabled" if self.input_mode.get() == "folder"
                                                  else "normal")
        except queue.Empty:
            pass
        self.root.after(100, self._drain_events)


def main():
    root = tk.Tk()
    AnonymizerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
