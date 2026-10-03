"""Small, reviewable label masks for a standard two-by-two meeting layout."""

import argparse


def parse_region(value):
    """Parse a pixel rectangle as x,y,width,height for the command line."""
    try:
        numbers = tuple(int(part.strip()) for part in value.split(","))
    except ValueError as error:
        raise argparse.ArgumentTypeError("Use x,y,width,height in pixels") from error
    if len(numbers) != 4 or min(numbers[:2]) < 0 or min(numbers[2:]) <= 0:
        raise argparse.ArgumentTypeError("Use nonnegative x,y and positive width,height")
    return numbers


def is_standard_two_by_two(analysis):
    """Only infer label positions when the sampled grid evidence is strong."""
    evidence = analysis.evidence
    return (evidence["multiple_large_faces"] >= 0.75
            and evidence["dark_center_dividers"] >= 0.75)


def standard_two_by_two_regions(width, height):
    """Approximate lower-left nameplate zones in each of four meeting tiles."""
    label_width = round(width * 0.21)
    label_height = round(height * 0.032)
    return [
        (round(width * x), round(height * y), label_width, label_height)
        for x, y in ((0.126, 0.447), (0.510, 0.447),
                     (0.126, 0.835), (0.510, 0.835))
    ]


def redact_regions(frame, regions):
    """Cover exact rectangles with an opaque fill; avoid leaking readable text."""
    height, width = frame.shape[:2]
    for x, y, box_width, box_height in regions:
        x1, y1 = min(x, width), min(y, height)
        x2, y2 = min(x + box_width, width), min(y + box_height, height)
        if x1 < x2 and y1 < y2:
            frame[y1:y2, x1:x2] = (18, 18, 18)
