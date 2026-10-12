"""Properties controls share, as mixins a control class lists to have them: BackColor,
Font, TabStop and the rest. Control.prop_defaults() sees which a class has."""

from __future__ import annotations

import sys
import tkinter as tk

from readymade import appearance, layout, menus, pictures


ORIENTATIONS = ("horizontal", "vertical")
PICTURE_POSITIONS = ("left", "top", "right", "bottom", "center")  # (center: the text over the picture)
LOOK_CHOICES = {"alignment": appearance.ALIGNMENTS, "valignment": appearance.VALIGNMENTS,
                "cursor": tuple(appearance.CURSORS), "anchor": layout.CHOICES,
                "orientation": ORIENTATIONS, "dock": layout.DOCKS, "picture_position": PICTURE_POSITIONS}


class BackColor:
    """A backcolor property."""

    default_backcolor = ""
    _backcolor: str

    @property
    def backcolor(self):
        """The background color, as "#rrggbb"; "" for the usual color (for a label, check box,
        option button, frame or picture: the color of the form or Frame it's on)."""
        return self._backcolor

    @backcolor.setter
    def backcolor(self, value):
        self._backcolor = appearance.check_color(value)
        self._paint()


class ForeColor:
    """A forecolor property."""

    _forecolor: str

    @property
    def forecolor(self):
        """The text color, as "#rrggbb"; "" for the usual color."""
        return self._forecolor

    @forecolor.setter
    def forecolor(self, value):
        self._forecolor = appearance.check_color(value)
        self._paint()


class Font:
    """A font property."""

    _font: str

    @property
    def font(self):
        """The font, like "Arial, 12, bold": its family, its size in points, then any of bold,
        italic and underline. Leave parts out for the usual ones: ", 14" is the usual font at
        14 points, and "" the usual font. Code can also use a tuple: ("Arial", 12, "bold")."""
        return self._font

    @font.setter
    def font(self, value):
        self._font = appearance.format_font(value)
        self._apply_font()


class Aligned:
    """An alignment property."""

    default_alignment = "left"
    _alignment: str

    @property
    def alignment(self):
        """Where its text goes across: "left", "center" or "right"."""
        return self._alignment

    @alignment.setter
    def alignment(self, value):
        self._alignment = appearance.check_choice("alignment", value, appearance.ALIGNMENTS)
        self._apply_alignment()


class VAligned:
    """A valignment property."""

    default_valignment = "middle"
    _valignment: str

    @property
    def valignment(self):
        """Where its text goes up and down: "top", "middle" or "bottom"."""
        return self._valignment

    @valignment.setter
    def valignment(self, value):
        self._valignment = appearance.check_choice("valignment", value, appearance.VALIGNMENTS)
        self._apply_alignment()


class Cursor:
    """A cursor property."""

    _cursor: str

    @property
    def cursor(self):
        """The mouse pointer over it: "default" (its usual one), "arrow", "hand", "text",
        "cross", "wait", "move", "help", "resize_ew" (left and right) or "resize_ns" (up and down)."""
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = appearance.check_choice("cursor", value, tuple(appearance.CURSORS))
        self._apply_cursor()


class TabIndex:
    """A tabindex property: a place in the form's Tab order."""

    widget: tk.Widget
    _tabindex: int

    @property
    def tabindex(self):
        """Its place in the order Tab moves through the form's controls, counting from 0
        (Shift+Tab goes backwards). The designer's Format > Tab Order sets them by clicking.
        Tab doesn't stop at a Label or Frame, but as in VB they have a place in the order:
        a Label's access key (an & in its text) goes to the control after it."""
        return self._tabindex

    @tabindex.setter
    def tabindex(self, value):
        self._tabindex = int(value)


class TabStop(TabIndex):
    """A control the keyboard can reach: Tab stops at it (unless its tabstop is False)."""

    _tabstop = True

    @property
    def tabstop(self):
        """Whether Tab stops at it. With False it keeps its place in the order, and can still
        be clicked, or reached with its access key; Tab just passes it by (as VB's TabStop)."""
        return self._tabstop

    @tabstop.setter
    def tabstop(self, value):
        self._tabstop = bool(value)
        if not self.design:
            self._focus_widget()["takefocus"] = 1 if self._tabstop else 0  # (Tk's own Tab order too)

    def _focus_widget(self):
        """The widget that takes the keyboard focus."""
        return self.widget


class Anchored:
    """An anchor property (see readymade.layout)."""

    _anchor: str
    _dock = "none"

    @property
    def anchor(self):
        """The edges of its container (the form, or a Frame) it keeps its distance to when that
        changes size: "top left" (it stays put), "bottom right" (it stays in that corner),
        "top left right" (it stretches across), "top bottom left right" (both ways). With
        neither left nor right it stays centered across; "none" centers it both ways.
        In a Grid, the edges of its cell it sticks to: all four fill the cell."""
        return self._anchor

    @anchor.setter
    def anchor(self, value):
        grid = self._grid() if self._ready else None
        if grid is not None:  # in a Grid: the edges of its cell it sticks to
            self._anchor = layout.normalize(value)
            grid.arrange()
            return
        rect = self._rect() if self._ready else None
        self._anchor = layout.normalize(value)
        if rect is not None:  # it stays where it is now; from here on it follows the new edges
            self._left, self._top, self._width, self._height = self._unfollow(rect)
            self._place()


    @property
    def dock(self):
        """The edge of its container (the form, a Frame, a TabStrip page) it fills: "top" or
        "bottom" (keeping its height), "left" or "right" (keeping its width), "fill" (what the
        others leave), or "none". Docked ones take their edges in the order they were drawn
        (Format > Order changes it), and their anchor doesn't apply. Not in a Grid."""
        return self._dock

    @dock.setter
    def dock(self, value):
        value = str(value or "none").lower()
        if value not in layout.DOCKS:
            raise ValueError(f"dock must be one of: {', '.join(layout.DOCKS)}")
        self._dock = value
        if not self._ready:
            return
        if value == "none":
            self._dock_rect = None
            self._place()
        from readymade.controls.base import arrange_docked, watch_docks  # (base uses these traits)

        watch_docks(self.widget.master)
        arrange_docked(self.widget.master)

    def _cell_prop(name, doc, smallest):
        def get(self):
            return getattr(self, "_" + name)

        def set(self, value):
            value = int(value)
            if value < smallest:
                raise ValueError(f"{name} can't be less than {smallest}")
            setattr(self, "_" + name, value)
            grid = self._grid() if getattr(self, "_ready", False) else None
            if grid is not None:
                grid.arrange()

        return property(get, set, doc=doc)

    row = _cell_prop("row", "In a Grid: the row it's in, counting from 0.", 0)
    column = _cell_prop("column", "In a Grid: the column it's in, counting from 0.", 0)
    rowspan = _cell_prop("rowspan", "In a Grid: how many rows it covers.", 1)
    columnspan = _cell_prop("columnspan", "In a Grid: how many columns it covers.", 1)
    del _cell_prop


# A control's place in a Grid, kept in the .form only for controls in one (with these defaults).
GRID_CELL = {"row": 0, "column": 0, "rowspan": 1, "columnspan": 1}


class Tooltip:
    """A tooltip property."""

    _tooltip: str

    @property
    def tooltip(self):
        """Text shown in a small box when the mouse rests over it while the program runs; "" for none."""
        return self._tooltip

    @tooltip.setter
    def tooltip(self, value):
        self._tooltip = str(value or "")
        if self._tooltip:
            self._connect_tooltip()


class WidgetText:
    """A text property backed by the widget's own text option. As in VB, an & marks the
    letter of an access key, shown underlined: "&Save" is Alt+S (on a Mac Ctrl+Option+S),
    which clicks a Button, or for a Label or Frame goes to the next control. && is an &."""

    widget: tk.Widget
    _accesskey = True
    # What its access key does: "press" it (a Button), "choose" it (a CheckBox or OptionButton),
    # or go to the "next" control (a Label's, or a Frame's first; see Form._after).
    access_key_action = "next"

    @property
    def text(self):
        """The text it shows: a Label's words, a Button's or CheckBox's label, a Frame's title."""
        return getattr(self, "_caption", "")

    @text.setter
    def text(self, value):
        self._caption = str(value)
        shown, underline = menus.parse_text(self._caption) if self._accesskey else (self._caption, -1)
        self.widget["text"] = shown
        try:
            self.widget["underline"] = underline
        except tk.TclError:
            pass  # (a Frame's title can't underline; its key still works)

    @property
    def access_key(self):
        """The letter of its access key, as a capital ("S" for "&Save"), or ""."""
        if not self._accesskey:
            return ""
        shown, underline = menus.parse_text(self.text)
        return shown[underline].upper() if 0 <= underline < len(shown) else ""


class Ranged:
    """min, max and value properties: a whole number from min to max (a ProgressBar's,
    Slider's, UpDown's or ScrollBar's). A control lists them in its extra_props, with its
    defaults, shows them in _show_value(), and calls _user_value() when the user changes it."""

    _min: int
    _max: int
    _value: int

    def __init__(self, parent, spec, design=False, folder=None):
        # (Set together first, so any order of setting them below is within range.)
        self._min, self._max = (_whole(spec.get(p, self.extra_props[p]), p) for p in ("min", "max"))
        if self._min > self._max:
            raise ValueError(f"min ({self._min}) can't be more than max ({self._max})")
        self._value = min(max(_whole(spec.get("value", self.extra_props["value"]), "value"), self._min), self._max)
        self._on_change = []
        super().__init__(parent, spec, design, folder)

    @classmethod
    def designer_changed(cls, spec, prop):
        super().designer_changed(spec, prop)
        low, high = (spec.get(p, cls.extra_props[p]) for p in ("min", "max"))
        if low > high:
            raise ValueError(f"min ({low}) can't be more than max ({high})")
        if prop != "value":  # a new min or max takes the value along, as in VB
            spec["value"] = min(max(spec.get("value", cls.extra_props["value"]), low), high)

    @property
    def min(self):
        """The smallest value."""
        return self._min

    @min.setter
    def min(self, value):
        value = _whole(value, "min")
        if value > self._max:
            raise ValueError(f"min can't be more than max ({self._max})")
        self._min = value
        self._set_value(max(self._value, value))

    @property
    def max(self):
        """The largest value."""
        return self._max

    @max.setter
    def max(self, value):
        value = _whole(value, "max")
        if value < self._min:
            raise ValueError(f"max can't be less than min ({self._min})")
        self._max = value
        self._set_value(min(self._value, value))

    @property
    def value(self):
        """The number it shows, from min to max."""
        return self._value

    @value.setter
    def value(self, value):
        value = _whole(value, "value")
        if not self._min <= value <= self._max:
            raise ValueError(f"value must be from {self._min} to {self._max}, not {value}")
        self._set_value(value)

    def _set_value(self, value):
        changed = value != self._value
        self._value = value
        self._show_value()
        if changed:
            for handler in self._on_change:
                handler()

    def _user_value(self, value):
        """The user moved it: value, kept within min and max."""
        self._set_value(min(max(int(round(value)), self._min), self._max))

    def _show_value(self):
        raise NotImplementedError

    def bind_event(self, event, handler):
        if event == "change":
            self._on_change.append(handler)
        else:
            super().bind_event(event, handler)


def _whole(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value != int(value):
        try:
            value = int(str(value).strip())
        except ValueError:
            raise ValueError(f"{name} must be a whole number, not {value!r}") from None
    return int(value)


class Oriented:
    """An orientation property, set in the designer: "horizontal" or "vertical"."""

    def __init__(self, parent, spec, design=False, folder=None):
        self._orientation = spec.get("orientation", "horizontal")
        if self._orientation not in ORIENTATIONS:
            raise ValueError(f"orientation must be horizontal or vertical, not {self._orientation!r}")
        super().__init__(parent, spec, design, folder)

    @classmethod
    def designer_changed(cls, spec, prop):
        super().designer_changed(spec, prop)
        if prop == "orientation" and "width" in spec:
            # Turned on its side: long the other way (a 160 x 20 bar becomes 20 x 160).
            if (spec["orientation"] == "vertical") == (spec["width"] > spec["height"]):
                spec["width"], spec["height"] = spec["height"], spec["width"]

    @property
    def orientation(self):
        """Whether it lies "horizontal" or stands "vertical". Set in the designer."""
        return self._orientation

    @orientation.setter
    def orientation(self, value):
        self._design_only("orientation", self._orientation, value)


class _TtkEnabled:
    """enabled for ttk widgets that keep it as a state, not a state option (a Scale, a Treeview...)."""

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.widget.state(["!disabled"] if self._enabled else ["disabled"])


class Picture:
    """picture and picture_position: a picture shown with its text (a Button's, a Label's)."""

    file_props = {"picture": pictures.FILE_TYPES}  # (the Properties panel offers picture files)
    _picture = ""
    _picture_position = "left"
    _photo = None  # (Tk drops an image nothing in Python holds)

    @property
    def picture(self):
        """A picture file shown with its text, like "images/save.png" (in the program's folder)
        or a full path; "" for none. With no text, just the picture."""
        return self._picture

    @picture.setter
    def picture(self, path):
        self._picture = str(path or "")
        self._show_picture()

    @property
    def picture_position(self):
        """Where its picture is, beside its text: "left", "top", "right", "bottom", or "center"
        (the text over the picture)."""
        return self._picture_position

    @picture_position.setter
    def picture_position(self, value):
        self._picture_position = appearance.check_choice("picture_position", value, PICTURE_POSITIONS)
        if self._photo is not None:  # (just where it goes: no need to read the file again)
            self.widget.configure(compound=self._picture_position)

    def _show_picture(self):
        photo = None
        if self._picture:
            try:
                photo, _ = pictures.load(self.folder / self._picture, master=self.widget)
            except (OSError, tk.TclError) as e:
                if not self.design:
                    print(f"{self.name}: can't show the picture {self._picture!r} ({e})", file=sys.stderr)
        self._photo = photo
        self.widget.configure(image=photo or "", compound=self._picture_position if photo else "none")


class Flat:
    """flat, set in the designer: a toolbar's button (a Button's; a CheckBox's or OptionButton's
    with appearance "button"). ttk's Toolbutton style draws it, so each system draws it its own
    way: flat until the mouse is over it on Windows and Linux, the Mac's own toolbar button there."""

    def __init__(self, parent, spec, design=False, folder=None):
        self._flat = bool(spec.get("flat", False))  # (it decides which widget is made)
        super().__init__(parent, spec, design, folder)

    @property
    def flat(self):
        """Whether it's a toolbar's button: flat until the mouse is over it (on macOS, the Mac's
        own toolbar button). A CheckBox or OptionButton with appearance "button" still shows
        when it's on. Set in the designer."""
        return self._flat

    @flat.setter
    def flat(self, value):
        self._design_only("flat", self._flat, bool(value))
