"""Control types shared by the designer and the runtime.

Each Control subclass wraps one Tk widget and gives it VB-style properties
(text, left, top, width, height, enabled, visible) and a list of events.
REGISTRY maps a type name to its class. The designer's toolbox is built from
it, so registering a new control type makes it available everywhere.
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass


@dataclass(frozen=True)
class Event:
    """An event a control can raise, and the arguments its handler receives."""

    name: str
    params: tuple[str, ...] = ()


def _key(e):
    return e.char if e.char and e.char.isprintable() else e.keysym


def _inside(e):
    return 0 <= e.x < e.widget.winfo_width() and 0 <= e.y < e.widget.winfo_height()


# Events that map directly onto a Tk binding: (sequence, filter, handler arguments).
_BINDINGS = {
    "click": ("<ButtonRelease-1>", _inside, lambda e: ()),
    "dblclick": ("<Double-Button-1>", None, lambda e: ()),
    "mousedown": ("<ButtonPress-1>", None, lambda e: (e.x, e.y)),
    "mouseup": ("<ButtonRelease-1>", None, lambda e: (e.x, e.y)),
    "gotfocus": ("<FocusIn>", None, lambda e: ()),
    "lostfocus": ("<FocusOut>", None, lambda e: ()),
    "keypress": ("<KeyPress>", None, lambda e: (_key(e),)),
}

REGISTRY: dict[str, type[Control]] = {}


def register(cls):
    REGISTRY[cls.type_name] = cls
    return cls


def create(parent, spec, design=False):
    """Create the control described by a .form control entry."""
    try:
        cls = REGISTRY[spec["type"]]
    except KeyError:
        raise ValueError(f"Unknown control type {spec['type']!r}") from None
    return cls(parent, spec, design)


def _geometry(attr):
    def get(self):
        return getattr(self, "_" + attr)

    def set(self, value):
        setattr(self, "_" + attr, int(value))
        self._place()

    return property(get, set)


class Control:
    widget: tk.Widget
    _left: int
    _top: int
    _width: int
    _height: int
    type_name = ""
    default_size = (96, 24)
    default_event = "click"
    events: tuple[Event, ...] = ()
    # Type-specific properties and their defaults. A default's type is the property's type.
    extra_props: dict[str, object] = {}

    def __init__(self, parent, spec, design=False):
        self.name = spec["name"]
        self.design = design
        self.widget = self.create_widget(parent)
        if design:
            self.widget["takefocus"] = 0
            self.widget["cursor"] = "arrow"
        self._ready = False
        for prop, default in self.prop_defaults().items():
            setattr(self, prop, spec.get(prop, default))
        self._ready = True
        self._place()

    @classmethod
    def prop_defaults(cls):
        """Every designable property with its default, in Properties panel order."""
        width, height = cls.default_size
        return {
            **cls.extra_props,
            "left": 0,
            "top": 0,
            "width": width,
            "height": height,
            "enabled": True,
            "visible": True,
        }

    @classmethod
    def new_spec(cls, name, left, top, width=None, height=None):
        """The .form entry for a newly drawn control."""
        spec = {"type": cls.type_name, "name": name, **cls.prop_defaults(), "left": left, "top": top}
        if width:
            spec["width"] = width
        if height:
            spec["height"] = height
        if "text" in spec:
            spec["text"] = name
        return spec

    def create_widget(self, parent):
        raise NotImplementedError

    left = _geometry("left")
    top = _geometry("top")
    width = _geometry("width")
    height = _geometry("height")

    @property
    def visible(self):
        return self._visible

    @visible.setter
    def visible(self, value):
        self._visible = bool(value)
        self._place()

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.widget["state"] = tk.NORMAL if self._enabled else tk.DISABLED

    def _place(self):
        if not self._ready:
            return
        # The designer always shows invisible controls, as VB did.
        if self._visible or self.design:
            self.widget.place(x=self._left, y=self._top, width=self._width, height=self._height)
        else:
            self.widget.place_forget()

    def bind_event(self, event, handler):
        sequence, accept, args = _BINDINGS[event]

        def callback(e):
            if accept is None or accept(e):
                handler(*args(e))

        self.widget.bind(sequence, callback, add="+")

    def __repr__(self):
        return f"<{self.type_name} {self.name}>"


class _WidgetText:
    """A text property backed by the widget's own text option."""

    widget: tk.Widget

    @property
    def text(self):
        return self.widget.cget("text")

    @text.setter
    def text(self, value):
        self.widget["text"] = str(value)


@register
class Label(_WidgetText, Control):
    type_name = "Label"
    default_size = (96, 24)
    events = (
        Event("click"),
        Event("dblclick"),
        Event("mousedown", ("x", "y")),
        Event("mouseup", ("x", "y")),
    )
    extra_props = {"text": ""}

    def create_widget(self, parent):
        return tk.Label(parent, anchor="w", justify="left")


@register
class Button(_WidgetText, Control):
    type_name = "Button"
    default_size = (96, 28)
    events = (
        Event("click"),
        Event("gotfocus"),
        Event("lostfocus"),
        Event("mousedown", ("x", "y")),
        Event("mouseup", ("x", "y")),
    )
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
class TextBox(Control):
    type_name = "TextBox"
    default_size = (120, 24)
    default_event = "change"
    events = (
        Event("change"),
        Event("keypress", ("key",)),
        Event("gotfocus"),
        Event("lostfocus"),
        Event("click"),
        Event("dblclick"),
    )
    extra_props = {"text": ""}

    def create_widget(self, parent):
        self._var = tk.StringVar(parent)
        return tk.Entry(parent, textvariable=self._var)

    @property
    def text(self):
        return self._var.get()

    @text.setter
    def text(self, value):
        self._var.set(str(value))

    def bind_event(self, event, handler):
        if event == "change":
            self._var.trace_add("write", lambda *_: handler())
        else:
            super().bind_event(event, handler)
