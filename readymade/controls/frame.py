"""The Frame control: a box that holds other controls."""

from __future__ import annotations

import tkinter as tk

from readymade.controls.base import _MOUSE_EVENTS, Control, _controls, register, repaint_inside
from readymade.controls.traits import (Aligned, Anchored, BackColor, Cursor, Font, ForeColor, TabIndex, Tooltip,
                                       WidgetText)


@register
class Frame(WidgetText, BackColor, ForeColor, Font, Aligned, TabIndex, Cursor, Tooltip, Anchored, Control):
    """A captioned box that groups controls. Controls drawn inside it belong to it: they're
    positioned relative to it and move with it, and its OptionButtons form their own group."""

    inner: tk.Frame
    type_name = "Frame"
    default_size = (200, 120)
    is_container = True
    inherits_backcolor = True
    events = _MOUSE_EVENTS
    extra_props = {"text": "", "border": True}

    def create_widget(self, parent):
        frame = tk.LabelFrame(parent)
        # Children go in an inner frame so that (0, 0) is just inside the border and caption.
        self.inner = tk.Frame(frame)
        self.inner.pack(fill=tk.BOTH, expand=True)
        return frame

    def widgets(self):
        return [self.widget, self.inner]

    @property
    def border(self):
        """Whether it's drawn with its edge. Without (False), just what's in it shows: a row of
        buttons for a toolbar, say. (The designer still outlines it, so it can be found.)"""
        return getattr(self, "_border", True)

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self._set(self.widget, "borderwidth", None if self._border else 0)
        if self.design:  # a thin outline instead, in the designer only
            self._set(self.widget, "highlightthickness", None if self._border else 1)
            self._set(self.widget, "highlightbackground", None if self._border else "gray60")

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        # A LabelFrame has no state of its own, so a disabled frame just grays its caption.
        self._enabled = bool(value)
        self._paint()

    def _foreground(self):
        return super()._foreground() if self._enabled else "gray50"

    def _paint(self):
        super()._paint()
        if self._ready:
            repaint_inside(self.inner)  # controls showing its color follow it

    def _place(self):
        super()._place()
        if not self._ready or self.design:
            return  # (the designer moves anchored controls itself, in the form's design)
        # The controls inside follow its size, measured from the size it was designed at.
        _, _, width, height = self._rect()
        designed = getattr(self, "_designed_size", None)
        if designed is None:
            designed = self._designed_size = (width, height)
        for child in self.inner.winfo_children():
            ref = _controls.get(child)
            control = ref() if ref else None
            if control is not None:
                control.follow_container(width - designed[0], height - designed[1])

    def _align(self, alignment, valignment):
        self.widget["labelanchor"] = {"left": "nw", "center": "n", "right": "ne"}[alignment]
