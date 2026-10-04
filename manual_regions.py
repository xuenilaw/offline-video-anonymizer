"""Validate and time manual cover and face keep-clear areas."""

import argparse
import math

from meeting_names import parse_region


def parse_timed_region(value):
    """Read x,y,width,height[,start_seconds,end_seconds]."""
    parts = [part.strip() for part in value.split(",")]
    if len(parts) not in (4, 6):
        raise argparse.ArgumentTypeError(
            "Use x,y,width,height or x,y,width,height,start_seconds,end_seconds"
        )
    x, y, width, height = parse_region(",".join(parts[:4]))
    if len(parts) == 4:
        return x, y, width, height, 0.0, math.inf
    try:
        start, end = map(float, parts[4:])
    except ValueError as error:
        raise argparse.ArgumentTypeError("Start and end must be seconds") from error
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start < end):
        raise argparse.ArgumentTypeError("Use finite times with 0 <= start < end")
    return x, y, width, height, start, end


def region_active(region, seconds):
    return region[4] <= seconds < region[5]
