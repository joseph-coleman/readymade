"""Shapes drawn on a Canvas control.

Each drawing method of a Canvas returns a Shape, which stays on the canvas until
it's deleted: change its color, move it, hide it, put it in front, ask whether it
overlaps another. Coordinates are pixels from the canvas's top left corner, colors
are "#rrggbb" strings ("" for none), and angles are degrees counter-clockwise from
three o'clock.
"""

from __future__ import annotations

import tkinter as tk

ARROWS = {"": tk.NONE, "start": tk.FIRST, "end": tk.LAST, "both": tk.BOTH}
ARC_STYLES = ("pie", "chord", "arc")
ANCHORS = ("nw", "n", "ne", "w", "center", "e", "sw", "s", "se")
DASH = (6, 4)


class Shape:
    """A shape on a Canvas, from one of its drawing methods (line, rectangle, oval,
    circle, arc, polygon, text, picture, point). x and y are where it is: a circle's
    center, a line's first point, a text's or picture's anchor point, otherwise the top
    left corner. Shapes that have no fill can only be clicked on their outline."""

    def __init__(self, canvas, kind, item, group=""):
        self._canvas = canvas  # the Canvas control
        self.kind = kind
        self._item = item
        self._photo = None  # a picture's image (Tk forgets images nothing refers to)
        self._group = ""
        self.group = group

    # ----- where it is -----

    @property
    def x(self):
        """Where it is across: see Shape. Setting it moves the shape."""
        return self._origin()[0]

    @x.setter
    def x(self, value):
        self.move(value - self.x, 0)

    @property
    def y(self):
        """Where it is down: see Shape. Setting it moves the shape."""
        return self._origin()[1]

    @y.setter
    def y(self, value):
        self.move(0, value - self.y)

    def _origin(self):
        points = self._tk.coords(self._item)
        if self.kind == "circle":
            return _number((points[0] + points[2]) / 2), _number((points[1] + points[3]) / 2)
        return _number(points[0]), _number(points[1])

    @property
    def points(self):
        """Its points as [(x, y), ...]: a line's or polygon's corners, a rectangle's, oval's or
        arc's top left and bottom right corners, a text's or picture's anchor point."""
        values = [_number(v) for v in self._tk.coords(self._item)]
        return list(zip(values[::2], values[1::2]))

    @points.setter
    def points(self, points):
        self._tk.coords(self._item, *flatten(points))

    @property
    def bounds(self):
        """(left, top, right, bottom) of the area it covers, including its outline."""
        return self._tk.bbox(self._item)

    def move(self, dx, dy):
        """Move it dx pixels right and dy pixels down (negative numbers go left and up)."""
        self._tk.move(self._item, dx, dy)

    def overlaps(self, other):
        """Whether its area (its bounds) overlaps another shape's: a simple collision test."""
        mine, theirs = self.bounds, other.bounds
        if not mine or not theirs:
            return False
        return mine[0] < theirs[2] and theirs[0] < mine[2] and mine[1] < theirs[3] and theirs[1] < mine[3]

    # ----- how it looks -----

    @property
    def color(self):
        """Its line color, or a text's color, as "#rrggbb"; "" for none."""
        return self._tk.itemcget(self._item, self._color_option())

    @color.setter
    def color(self, value):
        self._configure(**{self._color_option(): value or ""})

    def _color_option(self):
        if self.kind in ("line", "point", "text"):
            return "fill"  # Tk's name for these shapes' only color
        if self.kind == "picture":
            raise AttributeError("a picture has no color")
        return "outline"

    @property
    def fill(self):
        """The color inside it, as "#rrggbb"; "" for none (it can then only be clicked on its outline)."""
        if self.kind in ("line", "point", "text", "picture"):
            raise AttributeError(f"a {self.kind} has no fill; use color")
        return self._tk.itemcget(self._item, "fill")

    @fill.setter
    def fill(self, value):
        if self.kind in ("line", "point", "text", "picture"):
            raise AttributeError(f"a {self.kind} has no fill; use color")
        self._configure(fill=value or "")

    @property
    def thickness(self):
        """How thick its line is, in pixels."""
        if self.kind in ("text", "picture"):
            raise AttributeError(f"a {self.kind} has no thickness")
        return _number(float(self._tk.itemcget(self._item, "width")))

    @thickness.setter
    def thickness(self, value):
        if self.kind in ("text", "picture"):
            raise AttributeError(f"a {self.kind} has no thickness")
        self._tk.itemconfigure(self._item, width=value)

    @property
    def text(self):
        """A text shape's words."""
        if self.kind != "text":
            raise AttributeError(f"a {self.kind} has no text")
        return self._tk.itemcget(self._item, "text")

    @text.setter
    def text(self, value):
        if self.kind != "text":
            raise AttributeError(f"a {self.kind} has no text")
        self._tk.itemconfigure(self._item, text=str(value))

    @property
    def visible(self):
        """Whether it's shown. A hidden shape can't be clicked."""
        return self._tk.itemcget(self._item, "state") != tk.HIDDEN

    @visible.setter
    def visible(self, value):
        self._tk.itemconfigure(self._item, state=tk.NORMAL if value else tk.HIDDEN)

    def _configure(self, **options):
        try:
            self._tk.itemconfigure(self._item, **options)
        except tk.TclError as e:
            raise ValueError(str(e)) from None

    # ----- groups, order, deleting -----

    @property
    def group(self):
        """The name of the group it's in, or "": canvas.shapes(group) and canvas.clear(group) use it."""
        return self._group

    @group.setter
    def group(self, name):
        if self._group:
            self._tk.dtag(self._item, group_tag(self._group))
        self._group = str(name or "")
        if self._group:
            self._tk.addtag_withtag(group_tag(self._group), self._item)

    def bring_to_front(self):
        """Put it in front of every other shape."""
        self._tk.tag_raise(self._item)

    def send_to_back(self):
        """Put it behind every other shape."""
        self._tk.tag_lower(self._item)

    def delete(self):
        """Remove it from the canvas."""
        self._canvas._forget(self)

    @property
    def deleted(self):
        """Whether it has been deleted (from delete, or the canvas's clear)."""
        return self._item not in self._canvas._items

    @property
    def _tk(self):
        return self._canvas.widget

    def __repr__(self):
        return f"<{self.kind} at {self.x}, {self.y}{' (deleted)' if self.deleted else ''}>"


def group_tag(group):
    return f"group:{group}"  # never just digits, which Tk would read as an item number


def _number(value):
    return int(value) if float(value).is_integer() else value


def flatten(points):
    """(x1, y1, x2, y2, ...) from numbers or (x, y) pairs."""
    flat = []
    for point in points:
        if isinstance(point, (tuple, list)):
            flat.extend(point)
        else:
            flat.append(point)
    if len(flat) % 2:
        raise ValueError("points need an x and a y each")
    return flat


def check_choice(name, value, choices):
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(repr(c) for c in choices)}")
