"""The Timer control."""

from __future__ import annotations

import tkinter as tk

from readymade.controls.base import Control, Event, register


@register
class Timer(Control):
    """Raises its timer event every `interval` milliseconds while enabled. Invisible at runtime."""

    type_name = "Timer"
    default_size = (32, 32)
    default_event = "timer"
    resizable = False
    events = (Event("timer"),)

    @classmethod
    def prop_defaults(cls):
        return {"interval": 1000, "left": 0, "top": 0, "enabled": True, "tag": ""}

    width = property(lambda self: self.default_size[0])
    height = property(lambda self: self.default_size[1])

    def _rect(self):
        return (self._left, self._top, *self.default_size)  # always its icon's size, and no anchor

    def _unfollow(self, rect):
        return tuple(rect)

    def create_widget(self, parent):
        self._handler = None
        self._job = None
        self._interval = 1000
        self._enabled = True
        if not self.design:
            return tk.Frame(parent)  # never shown; it just schedules the ticks
        size = self.default_size[0]
        icon = tk.Canvas(parent, width=size, height=size, highlightthickness=1, highlightbackground="gray40")
        icon.create_oval(5, 5, size - 5, size - 5, fill="white", width=2)
        icon.create_line(size // 2, size // 2, size // 2, 9, width=2)
        icon.create_line(size // 2, size // 2, size - 10, size // 2, width=2)
        return icon

    @property
    def interval(self):
        """Milliseconds between timer events; 0 stops them."""
        return self._interval

    @interval.setter
    def interval(self, milliseconds):
        self._interval = max(0, int(milliseconds))
        self._restart()

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self._restart()

    def _place(self):
        if self._ready and self.design:
            self.widget.place(x=self._left, y=self._top, width=self.width, height=self.height)

    def bind_event(self, event, handler):
        self._handler = handler
        self._restart()

    def _restart(self):
        if self._job is not None:
            self.widget.after_cancel(self._job)
            self._job = None
        if not self.design and self._handler and self._enabled and self._interval > 0:
            self._job = self.widget.after(self._interval, self._tick)

    def _tick(self):
        self._job = None
        self._restart()  # schedule the next tick first, so the handler can stop the timer
        if self._handler:
            self._handler()
