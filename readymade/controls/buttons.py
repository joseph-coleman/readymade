"""The Button, CheckBox and OptionButton controls."""

from __future__ import annotations

import tkinter as tk
import weakref

from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import (Aligned, Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip,
                                       VAligned, WidgetText)


@register
class Button(WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, TabStop, Cursor, Tooltip, Anchored, Control):
    """A push button. Its click event runs when it's clicked, or pressed with Space while it has the focus.
    (On macOS, buttons keep the system's own colors.)"""

    type_name = "Button"
    can_be_default = True
    access_key_action = "press"
    default_alignment = "center"
    default_size = (96, 28)
    events = (Event("click"), *_FOCUS_EVENTS, Event("mousedown", ("x", "y")), Event("mouseup", ("x", "y")))
    extra_props = {"text": ""}

    def create_widget(self, parent):
        return tk.Button(parent)

    def bind_event(self, event, handler):
        # The button's command also covers keyboard activation and respects enabled.
        if event == "click":
            self.widget["command"] = handler
        else:
            super().bind_event(event, handler)


@register
class CheckBox(WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, TabStop, Cursor, Tooltip, Anchored, Control):
    """A box that can be ticked. value is True while it's ticked; click runs each time it changes."""

    type_name = "CheckBox"
    access_key_action = "choose"
    inherits_backcolor = True
    default_size = (120, 24)
    events = (Event("click", policy="latest"), *_FOCUS_EVENTS)
    extra_props = {"text": "", "value": False}

    def create_widget(self, parent):
        self._var = tk.BooleanVar(parent, False)
        return tk.Checkbutton(parent, variable=self._var, anchor="w")

    @property
    def value(self):
        """True while it's ticked."""
        return bool(self._var.get())

    @value.setter
    def value(self, checked):
        self._var.set(bool(checked))

    def bind_event(self, event, handler):
        if event == "click":
            self.widget["command"] = handler
        else:
            super().bind_event(event, handler)


# One shared variable per container, so the option buttons in it act as a group.
_option_groups: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


@register
class OptionButton(WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, TabStop, Cursor, Tooltip, Anchored, Control):
    """A radio button. Option buttons in the same container form one group, as in VB."""

    type_name = "OptionButton"
    access_key_action = "choose"
    inherits_backcolor = True
    default_size = (120, 24)
    events = (Event("click", policy="latest"), *_FOCUS_EVENTS)
    extra_props = {"text": "", "value": False}

    def create_widget(self, parent):
        if parent not in _option_groups:
            _option_groups[parent] = tk.StringVar(parent, "")
        self._group = _option_groups[parent]
        self._key = f"option{id(self)}"
        # tristatevalue defaults to "", which would draw every unselected option as "mixed".
        return tk.Radiobutton(parent, variable=self._group, value=self._key, tristatevalue="\x01", anchor="w")

    @property
    def value(self):
        """True when it's the chosen option of its group. Setting it True un-chooses the others."""
        return self._group.get() == self._key

    @value.setter
    def value(self, selected):
        if selected:
            self._group.set(self._key)
        elif self.value:
            self._group.set("")

    def bind_event(self, event, handler):
        if event == "click":
            self.widget["command"] = handler
        else:
            super().bind_event(event, handler)
