"""Anchors: how a control follows its container (the form, or a Frame) when that changes size.

A control's anchor names the edges of its container it keeps its distance to:
"top left" (the usual) keeps it where it was drawn; "bottom right" keeps it in that
corner; "top left right" stretches it across; "top bottom left right" stretches it
both ways. With neither left nor right it stays centered across (and with neither
top nor bottom, up and down), as in WinForms.

follow() is the whole rule, kept apart from any GUI toolkit so that any backend can
use it.
"""

from __future__ import annotations

from dataclasses import dataclass

EDGES = ("top", "bottom", "left", "right")
DEFAULT = "top left"
# Every combination, the common ones first: what the Properties panel offers.
CHOICES = (
    "top left", "top right", "bottom left", "bottom right",
    "top left right", "bottom left right", "top bottom left", "top bottom right",
    "top bottom left right",
    "top", "bottom", "left", "right", "top bottom", "left right", "none",
)


def parse(anchor):
    """The edges an anchor names: "bottom right" -> {"bottom", "right"}. ValueError if it isn't one."""
    words = str(anchor).lower().replace(",", " ").split()
    if words == ["none"]:
        return frozenset()
    unknown = [w for w in words if w not in EDGES]
    if unknown or not words:
        raise ValueError("anchor must name edges: top, bottom, left and right (like \"bottom right\"), or be \"none\"")
    return frozenset(words)


def normalize(anchor):
    """The one way of writing an anchor: "right, Top" -> "top right"; no edges -> "none"."""
    edges = parse(anchor)
    return " ".join(e for e in EDGES if e in edges) or "none"


def follow(rect, anchor, dx, dy):
    """Where a control at rect = (left, top, width, height) goes when its container grows by
    dx across and dy down (negative: shrinks)."""
    edges = parse(anchor)
    left, top, width, height = rect
    left, width = _one_way(left, width, dx, "left" in edges, "right" in edges)
    top, height = _one_way(top, height, dy, "top" in edges, "bottom" in edges)
    return left, top, width, height


def _one_way(start, size, grown, near, far):
    if near and far:
        return start, max(1, size + grown)  # both edges: stretch
    if far:
        return start + grown, size  # the far edge: move with it
    if near:
        return start, size  # the near edge: stay
    return start + round(grown / 2), size  # neither: stay centered


# ----- grids: rows and columns, sized WPF-style -----
#
# A Grid's columns (and rows) are a list like "auto, *, 2*, 120": auto fits what's in it,
# * and n* share the space left over by weight, and a number is fixed pixels. Fixed and
# auto tracks take their space first; the stars split the rest.



@dataclass(frozen=True)
class Track:
    kind: str  # "auto", "star" or "fixed"
    size: float = 0  # a star's weight, or a fixed track's pixels


def parse_tracks(text):
    """The tracks in a list like "auto, *, 2*, 120". ValueError if it isn't one."""
    tracks = []
    for part in (p.strip().lower() for p in str(text).replace(";", ",").split(",")):
        if not part:
            continue
        try:
            if part == "auto":
                tracks.append(Track("auto"))
            elif part.endswith("*"):
                weight = float(part[:-1]) if part[:-1] else 1.0
                if weight <= 0:
                    raise ValueError
                tracks.append(Track("star", weight))
            else:
                pixels = float(part.removesuffix("px"))
                if pixels < 0:
                    raise ValueError
                tracks.append(Track("fixed", pixels))
        except ValueError:
            raise ValueError(f"{part!r} isn't a size: use auto, * (or 2*, 3*...) or a number of pixels") from None
    if not tracks:
        raise ValueError("a Grid needs at least one row and one column, like \"*\"")
    return tuple(tracks)


def format_tracks(tracks):
    """The one way of writing tracks: "auto, *, 2*, 120"."""
    def one(track):
        size = int(track.size) if float(track.size).is_integer() else track.size
        if track.kind == "auto":
            return "auto"
        if track.kind == "star":
            return "*" if size == 1 else f"{size}*"
        return str(size)
    return ", ".join(one(t) for t in tracks)


def normalize_tracks(text):
    return format_tracks(parse_tracks(text))


@dataclass(frozen=True)
class GridLines:
    """Where a grid's columns or rows start, and how big they are."""

    starts: tuple
    sizes: tuple

    def index_at(self, position):
        """The track at a position (the nearest one, outside the grid)."""
        for i, (start, size) in enumerate(zip(self.starts, self.sizes)):
            if position < start + size:
                return i
        return len(self.starts) - 1


def arrange_grid(columns, rows, width, height, cells, gap=0, padding=0):
    """Lay controls out in a grid. columns and rows are lists like "auto, *"; cells are
    (row, column, rowspan, columnspan, anchor, (preferred width, preferred height)), one per
    control. Returns (rects, column lines, row lines): each control's (left, top, width,
    height) inside the grid, in the order given. As in WPF, a row or column past the last
    one means the last one, and a span stops at the grid's edge."""
    column_tracks, row_tracks = list(parse_tracks(columns)), list(parse_tracks(rows))
    cells = [(*fit_cell(row, column, rowspan, columnspan, len(row_tracks), len(column_tracks)), anchor, own)
             for row, column, rowspan, columnspan, anchor, own in cells]
    across = [(c[1], c[3], c[5][0]) for c in cells]
    down = [(c[0], c[2], c[5][1]) for c in cells]
    xs = _lines(column_tracks, width - 2 * padding, gap, padding, across)
    ys = _lines(row_tracks, height - 2 * padding, gap, padding, down)
    rects = []
    for row, column, rowspan, columnspan, anchor, (own_width, own_height) in cells:
        edges = parse(anchor)
        x, cell_width = span(xs, column, columnspan, gap)
        y, cell_height = span(ys, row, rowspan, gap)
        left, width_ = _in_cell(x, cell_width, own_width, "left" in edges, "right" in edges)
        top, height_ = _in_cell(y, cell_height, own_height, "top" in edges, "bottom" in edges)
        rects.append((left, top, width_, height_))
    return rects, xs, ys


def fit_cell(row, column, rowspan, columnspan, rows, columns):
    """A cell kept inside a grid of rows x columns: past the last row or column means the
    last one, and spans stop at the edge."""
    row, column = max(0, min(row, rows - 1)), max(0, min(column, columns - 1))
    return row, column, max(1, min(rowspan, rows - row)), max(1, min(columnspan, columns - column))


def _lines(tracks, space, gap, padding, items):
    """Sizes for one direction. items are (first track, span, preferred size)."""
    sizes = [t.size if t.kind == "fixed" else 0 for t in tracks]
    for first, span, own in items:  # auto tracks fit the controls in just them
        if span <= 1 and tracks[first].kind == "auto":
            sizes[first] = max(sizes[first], own)
    for first, span, own in items:  # a spanning control widens the last auto track it spans, if it must
        if span > 1:
            covered = range(first, first + span)
            short = own - (sum(sizes[i] for i in covered) + gap * (span - 1))
            autos = [i for i in covered if tracks[i].kind == "auto"]
            if short > 0 and autos and not any(tracks[i].kind == "star" for i in covered):
                sizes[autos[-1]] += short
    stars = [i for i, t in enumerate(tracks) if t.kind == "star"]
    left = space - sum(sizes) - gap * (len(tracks) - 1)
    if stars and left > 0:
        total = sum(tracks[i].size for i in stars)
        given = 0
        for n, i in enumerate(stars):
            share = left - given if n == len(stars) - 1 else int(left * tracks[i].size / total)
            sizes[i] = share
            given += share
    starts, position = [], padding
    for size in sizes:
        starts.append(position)
        position += size + gap
    return GridLines(tuple(starts), tuple(int(s) for s in sizes))


def span(lines, first, count, gap):
    """Where count tracks from first start, and how far they reach together (gaps between
    them included): (start, size). lines: a GridLines."""
    last = first + max(1, count) - 1
    return lines.starts[first], sum(lines.sizes[first:last + 1]) + gap * (last - first)


def _in_cell(start, cell, own, near, far):
    own = min(own, cell)
    if near and far:
        return start, max(1, cell)
    if far:
        return start + cell - own, max(1, own)
    if near:
        return start, max(1, own)
    return start + (cell - own) // 2, max(1, own)
