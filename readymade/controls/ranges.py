"""Controls for a whole number in a range: ScrollBar, Slider, UpDown and ProgressBar.

They share min, max and value (traits.Ranged); change runs when value changes, whether the
user or code changed it. ttk's widgets underneath: Scrollbar, Scale, Spinbox, Progressbar.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade.controls.base import _FOCUS_EVENTS, _MOUSE_EVENTS, Control, Event, register
from readymade.controls.traits import (Aligned, Anchored, BackColor, Cursor, Font, ForeColor, Oriented, Ranged,
                                       TabStop, Tooltip, _whole)


class _Steps:
    """smallchange and largechange: how far the arrows (or keys) and the bigger jumps move it."""

    _small = 1
    _large = 1

    @property
    def smallchange(self):
        """How far the arrows (or arrow keys) move the value."""
        return self._small

    @smallchange.setter
    def smallchange(self, value):
        self._small = max(1, _whole(value, "smallchange"))

    @property
    def largechange(self):
        """How far a bigger jump moves the value: a click beside the thumb, or Page Up and Page Down."""
        return self._large

    @largechange.setter
    def largechange(self, value):
        self._large = max(1, _whole(value, "largechange"))
        self._show_value()


class _TtkEnabled:
    """enabled for ttk widgets that keep it as a state rather than a state option."""

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.widget.state(["!disabled"] if self._enabled else ["disabled"])


def _style(control, kind):
    """The ttk style for one of these: in the designer the preview style, which stays light in
    a dark IDE, as the program will be."""
    base = f"{control._orientation.capitalize()}.{kind}" if isinstance(control, Oriented) else kind
    return f"Preview.{base}" if control.design else base


@register
class ScrollBar(_TtkEnabled, Ranged, _Steps, Oriented, Cursor, Tooltip, Anchored, Control):
    """A bar to choose a value from min to max by scrolling: VB's HScrollBar and VScrollBar,
    in one (orientation). Its arrows move the value by smallchange, a click beside the thumb
    by largechange, and dragging the thumb anywhere. change runs as the value changes."""

    type_name = "ScrollBar"
    default_size = (160, 17)
    default_event = "change"
    recreate_props = ("orientation",)
    events = (Event("change"),)
    extra_props = {"min": 0, "max": 100, "value": 0, "smallchange": 1, "largechange": 10,
                   "orientation": "horizontal"}

    def create_widget(self, parent):
        self._enabled = True
        bar = ttk.Scrollbar(parent, orient=self._orientation, command=self._scrolled, style=_style(self, "TScrollbar"))
        return bar

    def _scrolled(self, how, amount, units=None):
        if not self._enabled or self.design:
            return
        if how == "moveto":  # the thumb dragged: amount is where its start is, as a fraction of the bar
            self._user_value(self._min + float(amount) * (self._max - self._min + self._large))
        else:
            self._user_value(self._value + int(amount) * (self._small if units == "units" else self._large))

    def _show_value(self):
        # The thumb's length shows largechange as a part of the whole range, as on Windows.
        span = self._max - self._min + self._large
        first = (self._value - self._min) / span
        self.widget.set(first, first + self._large / span)


@register
class Slider(_TtkEnabled, Ranged, _Steps, Oriented, TabStop, Cursor, Tooltip, Anchored, Control):
    """A knob to slide along a track, choosing a whole number from min to max. The arrow keys
    move it by smallchange, Page Up and Page Down by largechange, Home and End to the ends.
    change runs as the value changes."""

    type_name = "Slider"
    default_size = (160, 24)
    default_event = "change"
    recreate_props = ("orientation",)
    events = (Event("change"), *_FOCUS_EVENTS)
    extra_props = {"min": 0, "max": 10, "value": 0, "smallchange": 1, "largechange": 5, "orientation": "horizontal"}

    def create_widget(self, parent):
        self._enabled = True
        scale = ttk.Scale(parent, orient=self._orientation, command=self._moved, style=_style(self, "TScale"))
        if not self.design:
            for sequence, step in (("<Left>", -1), ("<Up>", -1), ("<Right>", 1), ("<Down>", 1)):
                scale.bind(sequence, lambda e, s=step: self._key(self._value + s * self._small))
            scale.bind("<Prior>", lambda e: self._key(self._value - self._large))
            scale.bind("<Next>", lambda e: self._key(self._value + self._large))
            scale.bind("<Home>", lambda e: self._key(self._min))
            scale.bind("<End>", lambda e: self._key(self._max))
            scale.bind("<ButtonPress-1>", lambda e: self.tabstop and scale.focus_set(), add="+")
        return scale

    def _key(self, value):
        if self._enabled:
            self._user_value(value)
        return "break"

    def _moved(self, position):
        """The knob moved (dragged, or set): to the nearest whole number."""
        if self._enabled and not self.design:
            self._user_value(float(position))
        if float(position) != self._value:
            self.widget.set(self._value)  # (snapped to it; this calls _moved again, with the value)

    def _show_value(self):
        # (A scale needs some length: with min and max the same it's one long, and stays at min.)
        self.widget.configure(from_=self._min, to=max(self._max, self._min + 1))
        if float(self.widget.get()) != self._value:
            self.widget.set(self._value)


@register
class UpDown(Ranged, BackColor, ForeColor, Font, Aligned, TabStop, Cursor, Tooltip, Anchored, Control):
    """A box for a whole number from min to max, with arrows that step it by increment (the Up
    and Down keys too). With wrap, stepping past max goes round to min. Typing works too: the
    value changes once the text is a number in range. change runs as the value changes."""

    type_name = "UpDown"
    default_size = (72, 24)
    default_event = "change"
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"min": 0, "max": 100, "value": 0, "increment": 1, "wrap": False}

    def create_widget(self, parent):
        self._increment, self._wrap, self._enabled = 1, False, True
        self._typing = False
        self._var = tk.StringVar(parent)
        spin = ttk.Spinbox(parent, textvariable=self._var)
        self._var.trace_add("write", lambda *_: self._typed())
        spin.bind("<FocusOut>", lambda e: self._show_text(), add="+")  # what's shown is the value again
        return spin

    @property
    def increment(self):
        """How far the arrows (or Up and Down keys) step the value."""
        return self._increment

    @increment.setter
    def increment(self, value):
        self._increment = max(1, _whole(value, "increment"))
        self.widget.configure(increment=self._increment)

    @property
    def wrap(self):
        """Whether stepping past max goes round to min (and below min to max)."""
        return self._wrap

    @wrap.setter
    def wrap(self, value):
        self._wrap = bool(value)
        self.widget.configure(wrap=self._wrap)

    def _typed(self):
        """The text changed (typed, or an arrow): its number, if it's one in range, is the value."""
        try:
            number = int(self._var.get().strip())
        except ValueError:
            return  # (not yet a number, like "" or "-": the value stays until it is)
        if self._min <= number <= self._max and not self.design:
            self._typing = True
            try:
                self._user_value(number)
            finally:
                self._typing = False

    def _show_value(self):
        self.widget.configure(from_=self._min, to=self._max)
        if not self._typing:
            self._show_text()

    def _show_text(self):
        if self._var.get() != str(self._value):
            self._var.set(str(self._value))

    def _paint(self):
        # A ttk widget takes its colors from a style, so each colored UpDown gets its own.
        if not self._ready:
            return
        bg, fg = self._background(), self._foreground()
        if bg or fg:
            name = f"readymade{id(self)}.TSpinbox"
            style = ttk.Style(self.widget)
            style.configure(name, **{k: v for k, v in (("fieldbackground", bg), ("foreground", fg)) if v})
            self.widget["style"] = name
        else:
            self.widget["style"] = _style(self, "TSpinbox")

    def _align(self, alignment, valignment):
        self.widget["justify"] = alignment


@register
class ProgressBar(_TtkEnabled, Ranged, Oriented, Cursor, Tooltip, Anchored, Control):
    """Shows how far a long job has got: the bar fills as value goes from min to max. With
    marquee True it shows the program is busy without saying how far (a block moving back
    and forth), for jobs whose length isn't known."""

    type_name = "ProgressBar"
    default_size = (160, 20)
    default_event = "click"
    recreate_props = ("orientation",)
    events = _MOUSE_EVENTS
    extra_props = {"min": 0, "max": 100, "value": 0, "marquee": False, "orientation": "horizontal"}

    def create_widget(self, parent):
        self._marquee, self._enabled = False, True
        return ttk.Progressbar(parent, orient=self._orientation, mode="determinate",
                               style=_style(self, "TProgressbar"))

    @property
    def marquee(self):
        """Whether it shows a block moving back and forth (busy, for how long isn't known)
        instead of value. It moves while the program runs, not in the designer."""
        return self._marquee

    @marquee.setter
    def marquee(self, value):
        self._marquee = bool(value)
        self.widget.stop()
        if self._marquee:
            self.widget.configure(mode="indeterminate", value=0)
            if not self.design:
                self.widget.start(15)
        else:
            self.widget.configure(mode="determinate")
            self._show_value()

    def _show_value(self):
        if not self._marquee:
            self.widget.configure(maximum=max(self._max - self._min, 1), value=self._value - self._min)
