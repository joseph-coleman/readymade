"""The Button, CheckBox and OptionButton controls.

A flat one (a toolbar's) is a ttk widget in the Toolbutton style, which each system draws its
own way; the rest are Tk's classic buttons, whose colors and fonts are their own options.
"""

from __future__ import annotations

import tkinter as tk
import weakref
from tkinter import font as tkfont
from tkinter import ttk

from readymade import appearance
from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import (Aligned, Anchored, BackColor, Cursor, Flat, Font, ForeColor, Picture, TabStop,
                                       Tooltip, VAligned, WidgetText)

APPEARANCES = ("normal", "button")


class _ToolLook:
    """For a control drawn by ttk's Toolbutton style (see _toolbutton): a ttk widget takes its
    colors, font and alignment from a style, so each such control gets one of its own."""

    _toolbutton = False

    def _base_style(self):
        # (In the designer, the light preview style: it shows the program, not the IDE.)
        return "Preview.Toolbutton" if self.design else "Toolbutton"

    def _style_name(self):
        return f"readymade{id(self)}.{self._base_style()}"

    def _paint(self):
        if not self._toolbutton:
            return super()._paint()
        if not self._ready:
            return None
        style, base = ttk.Style(self.widget), self._base_style()
        bg, fg = self._background(), self._foreground()
        # (macOS's theme draws a Toolbutton's background itself: there only the text color shows.)
        style.configure(self._style_name(), background=bg or style.lookup(base, "background"),
                        foreground=fg or style.lookup(base, "foreground"))
        # While a toggle is on, the theme's own text color (a dark one on the Mac's blue reads badly).
        on = style.lookup(base, "foreground", ["selected"]) if fg else ""
        style.map(self._style_name(), foreground=[("selected", on)] if on else [])
        return None

    def _apply_font(self):
        if not self._toolbutton:
            return super()._apply_font()
        if not self._ready:
            return None
        usual = tkfont.nametofont("TkDefaultFont", root=self.widget).actual()
        font = appearance.tk_font(self._font, usual) if self._font else "TkDefaultFont"
        ttk.Style(self.widget).configure(self._style_name(), font=font)
        return None

    def _align(self, alignment, valignment):
        if not self._toolbutton:
            return super()._align(alignment, valignment)
        ttk.Style(self.widget).configure(self._style_name(), anchor=appearance.anchor(alignment, valignment))
        return None


class _Appearance:
    """appearance, set in the designer: a CheckBox or OptionButton drawn as itself, or as a
    button that stays pressed while it's on (a toolbar's Bold, or Left / Center / Right)."""

    prop_choices = {"appearance": APPEARANCES}

    def __init__(self, parent, spec, design=False, folder=None):
        self._appearance = spec.get("appearance", "normal")  # (it decides which widget is made)
        appearance.check_choice("appearance", self._appearance, APPEARANCES)
        super().__init__(parent, spec, design, folder)

    @property
    def appearance(self):
        """"normal", or "button": no box or circle, a button that stays pressed in while it's
        on. Set in the designer."""
        return self._appearance

    @appearance.setter
    def appearance(self, value):
        self._design_only("appearance", self._appearance, value)

    def _wants_toolbutton(self, parent):
        """A button-look toggle is a Toolbutton when flat, and always on macOS (whose classic
        toggle shows "on" in a maroon of Tk's; its Toolbutton, in the system's accent color)."""
        return self._appearance == "button" and (
            self._flat or parent.tk.call("tk", "windowingsystem") == "aqua")


@register
class Button(_ToolLook, WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, Picture, Flat, TabStop, Cursor,
             Tooltip, Anchored, Control):
    """A push button, with a picture too if you like. Its click event runs when it's clicked, or
    pressed with Space while it has the focus. With flat, a toolbar's button. (On macOS, buttons
    keep the system's own colors.)"""

    type_name = "Button"
    can_be_default = True
    access_key_action = "press"
    default_alignment = "center"
    default_size = (96, 28)
    recreate_props = ("flat",)
    events = (Event("click"), *_FOCUS_EVENTS, Event("mousedown", ("x", "y")), Event("mouseup", ("x", "y")))
    extra_props = {"text": ""}

    def create_widget(self, parent):
        self._toolbutton = self._flat
        if self._toolbutton:
            return ttk.Button(parent, style=self._style_name())
        return tk.Button(parent)

    def bind_event(self, event, handler):
        # The button's command also covers keyboard activation and respects enabled.
        if event == "click":
            self.widget["command"] = handler
        else:
            super().bind_event(event, handler)


@register
class CheckBox(_ToolLook, _Appearance, WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, Picture, Flat,
               TabStop, Cursor, Tooltip, Anchored, Control):
    """A box that can be ticked (or with appearance "button", a button that stays pressed). value
    is True while it's ticked; click runs each time it changes."""

    type_name = "CheckBox"
    access_key_action = "choose"
    inherits_backcolor = True
    default_size = (120, 24)
    recreate_props = ("flat", "appearance")
    events = (Event("click", policy="latest"), *_FOCUS_EVENTS)
    extra_props = {"text": "", "value": False, "appearance": "normal"}

    def create_widget(self, parent):
        self._var = tk.BooleanVar(parent, False)
        self._toolbutton = self._wants_toolbutton(parent)
        if self._toolbutton:
            return ttk.Checkbutton(parent, variable=self._var, style=self._style_name())
        return tk.Checkbutton(parent, variable=self._var, anchor="w", indicatoron=self._appearance == "normal")

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
class OptionButton(_ToolLook, _Appearance, WidgetText, BackColor, ForeColor, Font, Aligned, VAligned, Picture, Flat,
                   TabStop, Cursor, Tooltip, Anchored, Control):
    """A radio button. Option buttons in the same container form one group, as in VB: one chosen
    at a time (with appearance "button", the one pressed in, as a toolbar's Left / Center / Right)."""

    type_name = "OptionButton"
    access_key_action = "choose"
    inherits_backcolor = True
    default_size = (120, 24)
    recreate_props = ("flat", "appearance")
    events = (Event("click", policy="latest"), *_FOCUS_EVENTS)
    extra_props = {"text": "", "value": False, "appearance": "normal"}

    def create_widget(self, parent):
        if parent not in _option_groups:
            _option_groups[parent] = tk.StringVar(parent, "")
        self._group = _option_groups[parent]
        self._key = f"option{id(self)}"
        self._toolbutton = self._wants_toolbutton(parent)
        if self._toolbutton:
            return ttk.Radiobutton(parent, variable=self._group, value=self._key, style=self._style_name())
        # tristatevalue defaults to "", which would draw every unselected option as "mixed".
        return tk.Radiobutton(parent, variable=self._group, value=self._key, tristatevalue="\x01", anchor="w",
                              indicatoron=self._appearance == "normal")

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
