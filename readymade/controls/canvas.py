"""The Canvas control: shapes to draw, move and click."""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont

from readymade import appearance, pictures
from readymade import shapes as _shapes
from readymade.controls.base import Control, Event, _inside, register
from readymade.controls.traits import Anchored, BackColor, Cursor, Tooltip
from readymade.shapes import Shape


@register
class Canvas(BackColor, Cursor, Tooltip, Anchored, Control):
    """A drawing surface. Its drawing methods (line, rectangle, oval, circle, arc, polygon,
    text, picture, point) each return a Shape, which stays until it's deleted: move it,
    recolor it, hide it, check what it overlaps. Mouse events say where the mouse is and
    which shape is there (None for the background):

        ball = self.Canvas1.circle(100, 80, 20, fill="#e04040")
        ball.move(5, 0)

        def Canvas1_click(self, x, y, shape):
            if shape is ball: ...

    Coordinates are pixels from its top left corner; colors are "#rrggbb", "" for none.
    click needs the mouse to stay put between press and release; for dragging, use
    mousedown, drag and mouseup."""

    type_name = "Canvas"
    default_size = (200, 150)
    events = (
        Event("click", ("x", "y", "shape")), Event("dblclick", ("x", "y", "shape")),
        Event("mousedown", ("x", "y", "shape")), Event("mouseup", ("x", "y", "shape")),
        Event("mousemove", ("x", "y")), Event("drag", ("x", "y")),
    )
    extra_props = {"border": False}
    default_backcolor = "#ffffff"
    inherits_backcolor = True

    # Each event: (Tk binding, whether the handler gets the shape).
    _events = {
        "click": ("<ButtonRelease-1>", True),
        "dblclick": ("<Double-Button-1>", True),
        "mousedown": ("<ButtonPress-1>", True),
        "mouseup": ("<ButtonRelease-1>", True),
        "mousemove": ("<Motion>", False),
        "drag": ("<B1-Motion>", False),
    }

    def create_widget(self, parent):
        self._border = False
        self._pressed_at = None
        canvas = tk.Canvas(parent, highlightthickness=0, bd=0, background="#ffffff")
        self._shape_set = _shapes.ShapeSet(canvas)
        canvas.bind("<ButtonPress-1>", lambda e: setattr(self, "_pressed_at", (e.x, e.y)), add="+")
        return canvas

    def _is_click(self, e):
        # A click is a press and release in about the same place; the end of a drag isn't one.
        if self._pressed_at is None or not _inside(e):
            return False
        x, y = self._pressed_at
        return abs(e.x - x) <= 4 and abs(e.y - y) <= 4

    @property
    def border(self):
        """Whether a thin line is drawn around it."""
        return self._border

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self.widget.configure(bd=int(self._border), relief="solid" if self._border else "flat")

    def bind_event(self, event, handler):
        if event not in self._events:
            return super().bind_event(event, handler)
        sequence, with_shape = self._events[event]

        def callback(e):
            if event == "click" and not self._is_click(e):
                return
            x, y = int(self.widget.canvasx(e.x)), int(self.widget.canvasy(e.y))
            handler(*(x, y, self.shape_at(x, y)) if with_shape else (x, y))

        self.widget.bind(sequence, callback, add="+")

    # ----- drawing -----

    def line(self, x1, y1, x2, y2, *more, color="#000000", thickness=1, dashed=False, arrow="", group="") -> Shape:
        """A line from (x1, y1) to (x2, y2), on through any more points given (x3, y3, ...).
        arrow puts an arrowhead at the "start", the "end" or "both"."""
        _shapes.check_choice("arrow", arrow, tuple(_shapes.ARROWS))
        return self._add("line", "line", (x1, y1, x2, y2, *more), group, fill=color, width=thickness,
                         dash=_shapes.DASH if dashed else "", arrow=_shapes.ARROWS[arrow], capstyle="round")

    def rectangle(self, left, top, width, height, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """A rectangle with its top left corner at (left, top)."""
        return self._add("rectangle", "rectangle", (left, top, left + width, top + height), group,
                         **_outlined(color, fill, thickness, dashed))

    def oval(self, left, top, width, height, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """An oval (an ellipse) filling the rectangle with its top left corner at (left, top)."""
        return self._add("oval", "oval", (left, top, left + width, top + height), group,
                         **_outlined(color, fill, thickness, dashed))

    def circle(self, x, y, radius, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """A circle centered on (x, y)."""
        return self._add("circle", "oval", (x - radius, y - radius, x + radius, y + radius), group,
                         **_outlined(color, fill, thickness, dashed))

    def arc(self, left, top, width, height, start, extent, style="pie", color="#000000", fill="",
            thickness=1, dashed=False, group="") -> Shape:
        """Part of the oval filling the rectangle at (left, top): from start degrees (0 is
        three o'clock) through extent more, counter-clockwise (negative: clockwise). style
        "pie" draws a slice, "chord" a straight edge across, "arc" just the curve."""
        _shapes.check_choice("style", style, _shapes.ARC_STYLES)
        return self._add("arc", "arc", (left, top, left + width, top + height), group, start=start,
                         extent=extent, style=style, **_outlined(color, fill if style != "arc" else "", thickness, dashed))

    def polygon(self, *points, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """A closed shape through the points: polygon(10, 10, 60, 10, 35, 50) or
        polygon((10, 10), (60, 10), (35, 50))."""
        flat = _shapes.flatten(points)
        if len(flat) < 6:
            raise ValueError("a polygon needs at least 3 points")
        return self._add("polygon", "polygon", flat, group, **_outlined(color, fill, thickness, dashed))

    def text(self, x, y, text, color="#000000", font=None, anchor="nw", group="") -> Shape:
        """Words at (x, y). anchor is which part of the text is at (x, y): "nw" (top left),
        "n", "ne", "w", "center", "e", "sw", "s" or "se". font is like "Arial, 12, bold"."""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        options = {}
        if font:
            options["font"] = appearance.tk_font(font, tkfont.nametofont("TkDefaultFont", root=self.widget).actual())
        return self._add("text", "text", (x, y), group, text=str(text), fill=color, anchor=anchor, **options)

    def picture(self, x, y, path, anchor="nw", group="") -> Shape:
        """A picture from a file (see the Image control), with its anchor point at (x, y)."""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        photo, _ = pictures.load(self.folder / path, master=self.widget)
        return self._add("picture", "image", (x, y), group, photo=photo, image=photo, anchor=anchor)

    def point(self, x, y, color="#000000", group="") -> Shape:
        """A single pixel: a tiny shape, fine by the hundred. For many thousands, draw on an Image instead."""
        return self._add("point", "line", (x, y, x + 1, y), group, fill=color)

    def _add(self, kind, tk_type, coords, group, photo=None, **options) -> Shape:
        try:
            item = getattr(self.widget, f"create_{tk_type}")(*coords, **options)
        except tk.TclError as e:
            raise ValueError(str(e)) from None
        return self._shape_set.add(kind, item, group, photo)

    # ----- finding and removing shapes -----

    def shapes(self, group=None) -> list[Shape]:
        """Its shapes, from the back to the front; only those in group if given."""
        items = self.widget.find_withtag(_shapes.group_tag(group)) if group else self.widget.find_all()
        return [shape for shape in map(self._shape_set.get, items) if shape is not None]

    def shape_at(self, x, y) -> Shape | None:
        """The front-most visible shape at (x, y), or None."""
        for item in reversed(self.widget.find_overlapping(x, y, x, y)):
            shape = self._shape_set.get(item)
            if shape is not None and self.widget.itemcget(item, "state") != tk.HIDDEN:
                return shape
        return None

    def clear(self, group=None):
        """Delete every shape, or every shape in group."""
        for shape in self.shapes(group):
            shape.delete()


def _outlined(color, fill, thickness, dashed):
    return {"outline": color or "", "fill": fill or "", "width": thickness, "dash": _shapes.DASH if dashed else ""}
