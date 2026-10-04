"""Draw time-limited screen areas to cover or exempt from face pixelation."""

import base64
import tkinter as tk
from tkinter import messagebox, ttk

import cv2

from manual_regions import region_active


def canvas_box_to_video(start, end, offset, scale, width, height):
    """Map a dragged rectangle to source-video pixel coordinates."""
    values = []
    for first, second, origin, limit in zip(start, end, offset, (width, height)):
        low = max(0, min(limit, round((min(first, second) - origin) / scale)))
        high = max(0, min(limit, round((max(first, second) - origin) / scale)))
        values.append((low, high))
    (x1, x2), (y1, y2) = values
    return x1, y1, x2 - x1, y2 - y1


class RegionEditor(tk.Toplevel):
    """Edit source-video regions with a time range for each drawn box."""

    def __init__(self, parent, source, existing=None):
        super().__init__(parent)
        self.title(f"Edit areas — {source.name}")
        self.resizable(False, False)
        self.transient(parent)
        self.result = None
        self.capture = cv2.VideoCapture(str(source))
        if not self.capture.isOpened():
            self.destroy()
            raise ValueError(f"Could not open source video: {source}")
        self.width = int(self.capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        self.height = int(self.capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self.frame_count = int(self.capture.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.capture.get(cv2.CAP_PROP_FPS) or 24.0
        if self.width < 1 or self.height < 1 or self.frame_count < 1:
            self.capture.release()
            self.destroy()
            raise ValueError(f"Source video has no usable frames: {source}")
        self.duration = self.frame_count / self.fps
        existing = existing or {}
        self.regions = ([ ("hide", self._with_time(box)) for box in existing.get("hide", []) ]
                        + [ ("blur", self._with_time(box)) for box in existing.get("blur", []) ]
                        + [ ("keep", self._with_time(box)) for box in existing.get("keep", []) ])
        self.mode = tk.StringVar(value="hide")
        self.position = tk.StringVar(value="Frame 1")
        self.start_seconds = tk.StringVar(value="0.000")
        self.end_seconds = tk.StringVar(value=f"{self.duration:.3f}")
        self.image = None
        self.drag_start = None
        self.draft = None
        self.scale = 1.0
        self.offset = (0, 0)
        self.canvas_width = 820
        self.canvas_height = 340

        body = ttk.Frame(self, padding=14)
        body.pack(fill="both", expand=True)
        ttk.Label(body, text="Draw on the source video", font=("TkDefaultFont", 16, "bold")).pack(anchor="w")
        ttk.Label(body, text="Choose when a box starts and ends, then draw it. Its screen position stays "
                  "fixed during that time. Move the slider to check other moments.",
                  wraplength=820).pack(anchor="w", pady=(4, 10))
        self.canvas = tk.Canvas(body, width=self.canvas_width, height=self.canvas_height,
                                background="#151a24", highlightthickness=0)
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._press)
        self.canvas.bind("<B1-Motion>", self._drag)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.slider = ttk.Scale(body, from_=0, to=max(0, self.frame_count - 1),
                                command=self._seek)
        self.slider.pack(fill="x", pady=(10, 0))
        ttk.Label(body, textvariable=self.position).pack(anchor="w")

        timing = ttk.Frame(body)
        timing.pack(fill="x", pady=(10, 2))
        ttk.Label(timing, text="From (seconds)").pack(side="left")
        ttk.Entry(timing, textvariable=self.start_seconds, width=8).pack(side="left", padx=(5, 12))
        ttk.Button(timing, text="Start at this frame", command=self._set_start).pack(side="left")
        ttk.Label(timing, text="To (seconds)").pack(side="left", padx=(20, 5))
        ttk.Entry(timing, textvariable=self.end_seconds, width=8).pack(side="left", padx=(0, 12))
        ttk.Button(timing, text="End after this frame", command=self._set_end).pack(side="left")
        ttk.Button(body, text="Use whole video", command=self._full_duration).pack(anchor="w")

        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=(12, 5))
        ttk.Radiobutton(controls, text="Solid dark cover (red)", variable=self.mode,
                        value="hide").pack(side="left", padx=(0, 14))
        ttk.Radiobutton(controls, text="Strong blur (orange)", variable=self.mode,
                        value="blur").pack(side="left", padx=(0, 14))
        ttk.Radiobutton(controls, text="Keep faces clear here (green)", variable=self.mode,
                        value="keep").pack(side="left")
        ttk.Label(body, text="A cover box wins if it overlaps a keep-clear box. "
                  "Solid cover wins over blur. Keep-clear affects face masking only.",
                  wraplength=820).pack(anchor="w", pady=(0, 8))
        self.listbox = tk.Listbox(body, height=5, exportselection=False)
        self.listbox.pack(fill="x")
        buttons = ttk.Frame(body)
        buttons.pack(fill="x", pady=(8, 0))
        ttk.Button(buttons, text="Remove selected box", command=self._remove).pack(side="left")
        ttk.Button(buttons, text="Apply From/To to selected box", command=self._change_time).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="Change selected effect", command=self._change_effect).pack(
            side="left", padx=(8, 0)
        )
        ttk.Button(buttons, text="Cancel", command=self._cancel).pack(side="right")
        ttk.Button(buttons, text="Save areas", command=self._save).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._cancel)
        self._refresh_list()
        self._show_frame(0)
        self.grab_set()

    def _with_time(self, box):
        return tuple(box) if len(box) == 6 else (*box, 0.0, self.duration)

    def _time_range(self):
        try:
            start = float(self.start_seconds.get())
            end = float(self.end_seconds.get())
        except ValueError as error:
            raise ValueError("Enter start and end times in seconds.") from error
        if not (0 <= start < end <= self.duration + 0.001):
            raise ValueError(f"Use 0 ≤ start < end ≤ {self.duration:.3f} seconds.")
        return start, min(end, self.duration)

    def _set_start(self):
        self.start_seconds.set(f"{round(self.slider.get()) / self.fps:.3f}")

    def _set_end(self):
        self.end_seconds.set(f"{min(self.duration, (round(self.slider.get()) + 1) / self.fps):.3f}")

    def _full_duration(self):
        self.start_seconds.set("0.000")
        self.end_seconds.set(f"{self.duration:.3f}")

    def _show_frame(self, index):
        self.capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.capture.read()
        if not ok:
            return
        self.scale = min(self.canvas_width / self.width, self.canvas_height / self.height)
        display_width = round(self.width * self.scale)
        display_height = round(self.height * self.scale)
        self.offset = ((self.canvas_width - display_width) // 2,
                       (self.canvas_height - display_height) // 2)
        frame = cv2.resize(frame, (display_width, display_height), interpolation=cv2.INTER_AREA)
        ok, encoded = cv2.imencode(".png", frame)
        if not ok:
            return
        self.image = tk.PhotoImage(data=base64.b64encode(encoded.tobytes()).decode("ascii"))
        self.canvas.delete("all")
        self.canvas.create_image(*self.offset, image=self.image, anchor="nw")
        seconds = index / self.fps
        for kind, region in self.regions:
            if not region_active(region, seconds):
                continue
            x, y, width, height = region[:4]
            color = {"hide": "#ff4747", "blur": "#ffa43b", "keep": "#47d478"}[kind]
            x1, y1 = self.offset[0] + x * self.scale, self.offset[1] + y * self.scale
            self.canvas.create_rectangle(x1, y1, x1 + width * self.scale,
                                         y1 + height * self.scale, outline=color, width=3)
        self.position.set(f"Frame {index + 1} / {self.frame_count}  ·  {seconds:.1f} seconds")

    def _seek(self, value):
        self._show_frame(round(float(value)))

    def _press(self, event):
        self.drag_start = (event.x, event.y)
        if self.draft is not None:
            self.canvas.delete(self.draft)
        color = {"hide": "#ff4747", "blur": "#ffa43b", "keep": "#47d478"}[self.mode.get()]
        self.draft = self.canvas.create_rectangle(event.x, event.y, event.x, event.y,
                                                   outline=color, width=3)

    def _drag(self, event):
        if self.draft is not None and self.drag_start is not None:
            self.canvas.coords(self.draft, *self.drag_start, event.x, event.y)

    def _release(self, event):
        if self.drag_start is None:
            return
        box = canvas_box_to_video(self.drag_start, (event.x, event.y), self.offset,
                                  self.scale, self.width, self.height)
        self.drag_start = None
        if self.draft is not None:
            self.canvas.delete(self.draft)
            self.draft = None
        if box[2] < 5 or box[3] < 5:
            return
        try:
            start, end = self._time_range()
        except ValueError as error:
            messagebox.showerror("Check time range", str(error), parent=self)
            return
        self.regions.append((self.mode.get(), (*box, start, end)))
        self._refresh_list()
        self._show_frame(round(self.slider.get()))

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for kind, box in self.regions:
            label = {"hide": "Solid cover", "blur": "Strong blur", "keep": "Keep faces clear"}[kind]
            self.listbox.insert("end", f"{label}: {','.join(map(str, box[:4]))}  "
                                f"from {box[4]:.2f}s to {box[5]:.2f}s")

    def _remove(self):
        selected = self.listbox.curselection()
        if selected:
            self.regions.pop(selected[0])
            self._refresh_list()
            self._show_frame(round(self.slider.get()))

    def _change_time(self):
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showinfo("Select a box", "Select a box from the list first.", parent=self)
            return
        try:
            start, end = self._time_range()
        except ValueError as error:
            messagebox.showerror("Check time range", str(error), parent=self)
            return
        index = selected[0]
        kind, box = self.regions[index]
        self.regions[index] = (kind, (*box[:4], start, end))
        self._refresh_list()
        self.listbox.selection_set(index)
        self._show_frame(round(self.slider.get()))

    def _change_effect(self):
        selected = self.listbox.curselection()
        if not selected:
            messagebox.showinfo("Select a box", "Select a box from the list first.", parent=self)
            return
        index = selected[0]
        self.regions[index] = (self.mode.get(), self.regions[index][1])
        self._refresh_list()
        self.listbox.selection_set(index)
        self._show_frame(round(self.slider.get()))

    def _save(self):
        self.result = {
            "hide": [box for kind, box in self.regions if kind == "hide"],
            "blur": [box for kind, box in self.regions if kind == "blur"],
            "keep": [box for kind, box in self.regions if kind == "keep"],
        }
        self._close()

    def _cancel(self):
        self._close()

    def _close(self):
        self.grab_release()
        self.capture.release()
        self.destroy()


def edit_regions(parent, source, existing=None):
    editor = RegionEditor(parent, source, existing)
    parent.wait_window(editor)
    return editor.result
