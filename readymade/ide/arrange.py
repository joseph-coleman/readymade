"""The designer's Format menu, as plain geometry.

Each function takes the selected controls as {name: (left, top, width, height)}
and returns their new rectangles. This only makes sense for controls positioned
absolutely (Tk's place), which is all readymade has today. A container using a
layout manager (grid, pack) would offer its own equivalents instead, such as
sticky, anchor and padding.
"""

from __future__ import annotations

EDGES = ("lefts", "centers", "rights", "tops", "middles", "bottoms")


def align(rects, reference, edge):
    """Line every control up with the reference control's edge or center."""
    rl, rt, rw, rh = rects[reference]
    out = {}
    for name, (left, top, width, height) in rects.items():
        if edge == "lefts":
            left = rl
        elif edge == "centers":
            left = rl + (rw - width) // 2
        elif edge == "rights":
            left = rl + rw - width
        elif edge == "tops":
            top = rt
        elif edge == "middles":
            top = rt + (rh - height) // 2
        elif edge == "bottoms":
            top = rt + rh - height
        else:
            raise ValueError(f"edge must be one of: {', '.join(EDGES)}")
        out[name] = (left, top, width, height)
    return out


def to_grid(rects, grid):
    """Move each control's top-left corner to the nearest grid point."""
    return {name: (round(l / grid) * grid, round(t / grid) * grid, w, h) for name, (l, t, w, h) in rects.items()}


def same_size(rects, reference, width=True, height=True, fixed=()):
    """Give every control the reference control's width and/or height. Controls
    named in fixed (like a Timer) keep their size."""
    _, _, rw, rh = rects[reference]
    return {
        name: (l, t, rw if width else w, rh if height else h) if name not in fixed else (l, t, w, h)
        for name, (l, t, w, h) in rects.items()
    }


def space_evenly(rects, axis):
    """Make the gaps between controls equal, keeping the first and last where they are.
    axis is "x" (side by side) or "y" (one above another)."""
    i = 0 if axis == "x" else 1
    order = sorted(rects, key=lambda name: rects[name][i])
    if len(order) < 3:
        return dict(rects)
    first, last = rects[order[0]], rects[order[-1]]
    start, end = first[i], last[i] + last[i + 2]
    gap = (end - start - sum(rects[name][i + 2] for name in order)) / (len(order) - 1)
    out, position = {}, float(start)
    for name in order:
        rect = list(rects[name])
        rect[i] = round(position)
        out[name] = tuple(rect)
        position += rect[i + 2] + gap
    return out


def center(rects, container_size, axis):
    """Center the controls, as a group, in their container. axis is "x" or "y"."""
    i = 0 if axis == "x" else 1
    low = min(r[i] for r in rects.values())
    high = max(r[i] + r[i + 2] for r in rects.values())
    shift = (container_size[i] - (high - low)) // 2 - low
    out = {}
    for name, rect in rects.items():
        rect = list(rect)
        rect[i] += shift
        out[name] = tuple(rect)
    return out
