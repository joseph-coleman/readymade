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
