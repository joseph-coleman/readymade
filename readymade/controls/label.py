"""The Label control."""

from __future__ import annotations

import tkinter as tk

from readymade.controls.base import _MOUSE_EVENTS, Control, register
from readymade.controls.traits import (Aligned, Anchored, BackColor, Cursor, Font, ForeColor, TabIndex, Tooltip,
                                       VAligned, WidgetText)


@register
class Label(WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, TabIndex, Cursor, Tooltip, Anchored,
            Control):
    """Text on a form, such as a caption or a result. It can't be typed in, but it can be clicked."""

    type_name = "Label"
    inherits_backcolor = True
    default_size = (96, 24)
    events = _MOUSE_EVENTS
    extra_props = {"text": "", "accesskey": True}

    def create_widget(self, parent):
        return tk.Label(parent, anchor="w", justify="left")

    @property
    def accesskey(self):
        """Whether an & in the text marks an access key (VB's UseMnemonic). Turn it off for a
        Label showing words that may have an & in them, like "Q&A"."""
        return self._accesskey

    @accesskey.setter
    def accesskey(self, value):
        self._accesskey = bool(value)
        self.text = self.text  # shown again, with or without its underline
