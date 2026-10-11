"""Properties controls share, as mixins a control class lists to have them: BackColor,
Font, TabStop and the rest. Control.prop_defaults() sees which a class has."""

from __future__ import annotations

import tkinter as tk

from readymade import appearance, layout, menus


LOOK_CHOICES = {"alignment": appearance.ALIGNMENTS, "valignment": appearance.VALIGNMENTS,
                "cursor": tuple(appearance.CURSORS), "anchor": layout.CHOICES}


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
