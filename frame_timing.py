"""Read source presentation times for processing and manual region editing."""

import math

import cv2


def scan_frame_times(capture, fps):
    """Return per-frame seconds and whether timing differs from a steady rate."""
    times = []
    while capture.grab():
        times.append(capture.get(cv2.CAP_PROP_POS_MSEC) / 1000)
    if not times:
        return [], False
    valid = all(math.isfinite(t) and t >= 0 for t in times)
    valid = valid and all(b > a for a, b in zip(times, times[1:]))
    if not valid:
        return [index / fps for index in range(len(times))], False
    origin = times[0]
    times = [time - origin for time in times]
    intervals = [b - a for a, b in zip(times, times[1:])]
    variable = bool(intervals) and max(intervals) - min(intervals) > max(0.005, 0.2 / fps)
    return times, variable
