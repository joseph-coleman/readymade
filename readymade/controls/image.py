"""The Image control: a picture, and drawing on one."""

from __future__ import annotations

import sys
import tkinter as tk

from readymade import appearance, pictures
from readymade import shapes as _shapes
from readymade.controls.base import _MOUSE_EVENTS, Control, Event, register
from readymade.controls.traits import Anchored, BackColor, Cursor, Tooltip


_TEXT_ANCHORS = {"nw": "la", "n": "ma", "ne": "ra", "w": "lm", "center": "mm", "e": "rm",
                 "sw": "ld", "s": "md", "se": "rd"}


@register
class Image(BackColor, Cursor, Tooltip, Anchored, Control):
    """A picture from a file: PNG or GIF, and with Pillow installed also JPEG and others.
    picture is the file's path, relative to the program's folder (see app_path); sizing
    chooses how picture and control fit each other. In code, picture can also be set to
    any file, like one the user chose: self.Image1.picture = open_file_dialog()

    With Pillow, code can also draw on the picture's pixels, or on a new one:

        self.Image1.new(320, 200)
        self.Image1.line(0, 0, 319, 199, color="#ff0000", thickness=2)
        self.Image1.save("drawing.png")

    The drawing methods have the same names as a Canvas's, but nothing drawn can be moved
    or changed afterwards: it's just pixels. Coordinates are the picture's pixels (the
    same as the mouse's, unless the picture is scaled). The screen catches up when the
    handler finishes, so drawing thousands of points stays quick."""

    type_name = "Image"
    default_size = (96, 96)
    inherits_backcolor = True
    events = (*_MOUSE_EVENTS, Event("mousemove", ("x", "y")), Event("drag", ("x", "y")))
    extra_props = {"picture": "", "sizing": "autosize", "border": False}
    prop_choices = {"sizing": ("autosize", "normal", "center", "stretch", "zoom")}
    file_props = {"picture": pictures.FILE_TYPES}

    def create_widget(self, parent):
        self._picture = ""
        self._sizing = "autosize"
        self._border = False
        self._photo = None  # Tk forgets images nothing refers to
        self._natural = None  # the picture's own size
        self._drawing = None  # the picture as a Pillow image, once code draws on it
        self._draw = None
        self._version = 0  # counts drawing changes, so the screen knows to catch up
        self._refresh_pending = False
        self._shown = None
        return tk.Label(parent, bd=0, highlightthickness=0, padx=0, pady=0, compound="center")

    @property
    def picture(self):
        """The picture file's path, like "images/logo.png" (in the program's folder) or a full path; "" for none."""
        return self._picture

    @picture.setter
    def picture(self, path):
        self._picture = str(path or "")
        self._drawing = self._draw = None
        self._show()

    @property
    def sizing(self):
        """How picture and control fit: "autosize" (the control takes the picture's size),
        "normal" (the picture at its own size, from the top left), "center" (at its own size,
        centered), "stretch" (scaled to fill the control) or "zoom" (scaled to fit inside the
        control, keeping its shape)."""
        return self._sizing

    @sizing.setter
    def sizing(self, value):
        if value not in self.prop_choices["sizing"]:
            raise ValueError(f"sizing must be one of: {', '.join(self.prop_choices['sizing'])}")
        self._sizing = value
        self._show()

    @property
    def border(self):
        """Whether a thin line is drawn around it."""
        return self._border

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self._show()

    @property
    def picture_size(self):
        """(width, height) of the picture itself, in pixels; None without one."""
        if self._drawing is not None:
            return self._drawing.size
        return self._natural

    @property
    def resizable(self):
        # An autosized Image's size is its picture's (the designer has no resize handles for it).
        return self._sizing != "autosize" or self._photo is None

    def _place(self):
        if self._ready and self._sizing == "autosize" and self._photo is not None:
            edge = 2 * self._border
            self._width, self._height = self._photo.width() + edge, self._photo.height() + edge
        super()._place()
        if self._ready and self._shown != self._showing():
            self._show()  # first shown, or a scaled picture's new size needs a new scaling

    def _inner_size(self):
        edge = 2 * self._border
        _, _, width, height = self._rect()
        return max(1, width - edge), max(1, height - edge)

    def _showing(self):
        scaled = self._sizing in ("stretch", "zoom")
        return self._picture, self._version, self._sizing, self._border, self._inner_size() if scaled else None

    def _show(self):
        if not self._ready:
            return  # shown once all the properties are set
        self._shown = self._showing()
        self._photo = None
        message = ""
        size = self._inner_size() if self._sizing in ("stretch", "zoom") else None
        keep_shape = self._sizing == "zoom"
        if self._drawing is not None:
            self._photo = pictures.to_photo(self._drawing, size, keep_shape, master=self.widget)
        elif self._picture:
            try:
                self._photo, self._natural = pictures.load(self.folder / self._picture, size, keep_shape,
                                                           master=self.widget)
            except (OSError, tk.TclError) as e:
                self._natural = None
                message = f"Can't show {self._picture}"
                if not self.design:
                    print(f"{self.name}: can't show the picture {self._picture!r} ({e})", file=sys.stderr)
        else:
            self._natural = None
            if self.design:
                message = "(no picture)"  # so it can be seen and clicked in the designer
        self.widget.configure(
            image=self._photo or "", text=message, wraplength=max(1, self._rect()[2] - 4),
            anchor="nw" if self._sizing in ("autosize", "normal") else "center",
            relief="solid" if self._border else "flat", bd=int(self._border),
        )
        if self._sizing == "autosize":
            self._place()  # take the picture's size

    # ----- drawing on the pixels (needs Pillow) -----

    def new(self, width, height, background="#ffffff"):
        """Start a new picture of the given size to draw on, filled with background ("" for transparent)."""
        pictures.need_pillow("Drawing on an Image")
        self._picture = ""
        self._drawing = pictures.blank((int(width), int(height)), background)
        self._draw = pictures.drawer(self._drawing)
        self._version += 1
        self._show()

    def _surface(self):
        if self._draw is None:
            pictures.need_pillow("Drawing on an Image")
            if self._picture:
                self._drawing = pictures.open_for_drawing(self.folder / self._picture)
            else:  # a blank picture the size of the control
                self._drawing = pictures.blank(self._inner_size())
            self._draw = pictures.drawer(self._drawing)
        return self._draw

    def _drawn(self):
        """Show the changes once the handler is done (once, however many there were)."""
        self._version += 1
        if not self._refresh_pending:
            try:
                self.widget.after_idle(self._refresh)
                self._refresh_pending = True
            except tk.TclError:
                pass  # the form has closed

    def _refresh(self):
        self._refresh_pending = False
        if self.widget.winfo_exists() and self._shown != self._showing():
            self._show()

    def line(self, x1, y1, x2, y2, *more, color="#000000", thickness=1):
        """A line from (x1, y1) to (x2, y2), on through any more points given (x3, y3, ...)."""
        self._surface().line((x1, y1, x2, y2, *more), fill=pictures.rgba(color), width=int(thickness),
                             joint="curve" if more else None)
        self._drawn()

    def rectangle(self, left, top, width, height, color="#000000", fill="", thickness=1):
        """A rectangle with its top left corner at (left, top)."""
        self._surface().rectangle((left, top, left + width - 1, top + height - 1), **_pixel_style(color, fill, thickness))
        self._drawn()

    def oval(self, left, top, width, height, color="#000000", fill="", thickness=1):
        """An oval (an ellipse) filling the rectangle with its top left corner at (left, top)."""
        self._surface().ellipse((left, top, left + width - 1, top + height - 1), **_pixel_style(color, fill, thickness))
        self._drawn()

    def circle(self, x, y, radius, color="#000000", fill="", thickness=1):
        """A circle centered on (x, y)."""
        self._surface().ellipse((x - radius, y - radius, x + radius, y + radius), **_pixel_style(color, fill, thickness))
        self._drawn()

    def arc(self, left, top, width, height, start, extent, style="pie", color="#000000", fill="", thickness=1):
        """Part of the oval filling the rectangle at (left, top): from start degrees (0 is
        three o'clock) through extent more, counter-clockwise (negative: clockwise). style
        "pie" draws a slice, "chord" a straight edge across, "arc" just the curve."""
        _shapes.check_choice("style", style, _shapes.ARC_STYLES)
        # Pillow goes clockwise, from its start to its end.
        begin = -(start + extent) if extent >= 0 else -start
        end = begin + abs(extent)
        box = (left, top, left + width - 1, top + height - 1)
        draw = self._surface()
        if style == "arc":
            draw.arc(box, begin, end, fill=pictures.rgba(color), width=int(thickness))
        else:
            method = draw.pieslice if style == "pie" else draw.chord
            method(box, begin, end, **_pixel_style(color, fill, thickness))
        self._drawn()

    def polygon(self, *points, color="#000000", fill="", thickness=1):
        """A closed shape through the points: polygon(10, 10, 60, 10, 35, 50) or
        polygon((10, 10), (60, 10), (35, 50))."""
        flat = _shapes.flatten(points)
        if len(flat) < 6:
            raise ValueError("a polygon needs at least 3 points")
        self._surface().polygon(flat, **_pixel_style(color, fill, thickness))
        self._drawn()

    def text(self, x, y, text, color="#000000", font=None, anchor="nw"):
        """Words at (x, y). anchor is which part of the text is at (x, y): "nw" (top left),
        "n", "ne", "w", "center", "e", "sw", "s" or "se". font is like "Arial, 12, bold"."""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        draw = self._surface()
        typeface = pictures.font(appearance.format_font(font) or None, self.widget.winfo_fpixels("1p"))
        draw.text((x, y), str(text), fill=pictures.rgba(color), font=typeface, anchor=_TEXT_ANCHORS[anchor])
        self._drawn()

    def paste(self, x, y, path, anchor="nw"):
        """Draw a picture from a file onto this one, with its anchor point at (x, y).
        (On a Canvas, picture() does this.)"""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        self._surface()
        other = pictures.open_for_drawing(self.folder / path)
        dx = 0 if anchor.endswith("w") else 1 if anchor.endswith("e") else 0.5
        dy = 0 if anchor.startswith("n") else 1 if anchor.startswith("s") else 0.5
        self._drawing.alpha_composite(other, (int(x - dx * other.width), int(y - dy * other.height)))
        self._drawn()

    def point(self, x, y, color="#000000"):
        """Set one pixel's color."""
        self._surface().point((x, y), fill=pictures.rgba(color))
        self._drawn()

    def pixel(self, x, y):
        """A pixel's color, as "#rrggbb" ("" if it's transparent)."""
        self._surface()
        width, height = self._drawing.size
        if not (0 <= x < width and 0 <= y < height):
            raise IndexError(f"({x}, {y}) is outside the picture, which is {width} x {height}")
        return pictures.to_hex(self._drawing.getpixel((int(x), int(y))))

    def clear(self, color="#ffffff"):
        """Fill the whole picture with one color ("" for transparent)."""
        self._surface()
        self._drawing.paste(pictures.rgba(color), (0, 0, *self._drawing.size))
        self._drawn()

    def save(self, path):
        """Save the picture to a file; its extension chooses the format (.png, .jpg, .bmp, .gif, ...).
        A path that isn't a full one is in the program's folder."""
        self._surface()
        pictures.save(self._drawing, self.folder / path)


def _pixel_style(color, fill, thickness):
    return {"outline": pictures.rgba(color) if color else None, "fill": pictures.rgba(fill) if fill else None,
            "width": int(thickness)}
