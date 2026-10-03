"""The runtime base class for forms.

A form's code subclasses Form and adds handlers named Object_event, where
Object is a control's name, or "Form" for the form itself:

    class Form1(Form):
        def Form_load(self): ...
        def Button1_click(self): ...

Handlers are found by name and connected automatically when the form loads.
"""

from __future__ import annotations

import keyword
import sys
import tkinter as tk
from pathlib import Path

from pybasic import formfile
from pybasic.controls import Event, create

FORM = "Form"
FORM_EVENTS = (
    Event("load"),
    Event("unload"),
    Event("resize"),
    Event("click"),
    Event("dblclick"),
)


class Form:
    default_event = "load"
    events = FORM_EVENTS

    def __init__(self, path, master=None):
        design = formfile.load(path)
        self.path = Path(path)
        self.root = tk.Tk() if master is None else tk.Toplevel(master)
        self.root.title(design.text)
        self.root.geometry(f"{design.width}x{design.height}")
        self._size = (design.width, design.height)
        self.controls = {}
        for spec in design.controls:
            check_name(spec["name"], self.controls)
            control = create(self._parent_widget(spec), spec)
            self.controls[control.name] = control
            setattr(self, control.name, control)
        self._connect_events()
        self._fire("load")

    @classmethod
    def run(cls, path=None):
        """Show the form until it closes. By default Form1.py uses the Form1.form beside it."""
        if path is None:
            path = Path(sys.modules[cls.__module__].__file__).with_suffix(".form")
        cls(path).root.mainloop()

    def close(self):
        """Close the form, like VB's `Unload Me`. A Form_unload returning True cancels."""
        if self._fire("unload") is True:
            return
        self.root.destroy()

    @property
    def text(self):
        return self.root.title()

    @text.setter
    def text(self, value):
        self.root.title(str(value))

    @property
    def width(self):
        return self._size[0]

    @width.setter
    def width(self, value):
        self._size = (int(value), self._size[1])
        self.root.geometry(f"{self._size[0]}x{self._size[1]}")

    @property
    def height(self):
        return self._size[1]

    @height.setter
    def height(self, value):
        self._size = (self._size[0], int(value))
        self.root.geometry(f"{self._size[0]}x{self._size[1]}")

    def _parent_widget(self, spec):
        container = spec.get("container")
        if container is None:
            return self.root
        parent = self.controls.get(container)
        if parent is None or not parent.is_container:
            raise ValueError(f"{spec['name']!r} is in {container!r}, which isn't a container")
        return parent.inner

    def _fire(self, event, *args):
        handler = getattr(self, f"{FORM}_{event}", None)
        return handler(*args) if callable(handler) else None

    def _connect_events(self):
        for name, control in self.controls.items():
            for event in control.events:
                handler = getattr(self, f"{name}_{event.name}", None)
                if callable(handler):
                    control.bind_event(event.name, handler)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # Bindings on the root also see events from every control, so filter to the form itself.
        self.root.bind("<Configure>", self._on_configure, add="+")
        self.root.bind("<ButtonRelease-1>", lambda e: self._on_form_mouse(e, "click"), add="+")
        self.root.bind("<Double-Button-1>", lambda e: self._on_form_mouse(e, "dblclick"), add="+")

    def _on_configure(self, e):
        if e.widget is self.root and (e.width, e.height) != self._size:
            self._size = (e.width, e.height)
            self._fire("resize")

    def _on_form_mouse(self, e, event):
        if e.widget is self.root:
            self._fire(event)


_RESERVED = {name for name in dir(Form)} | {"root", "controls", "path", FORM}


def check_name(name, existing=()):
    """Raise ValueError unless name can be used for a new control."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"{name!r} is not a valid Python name")
    if name in _RESERVED:
        raise ValueError(f"{name!r} is reserved by the Form class")
    if name in existing:
        raise ValueError(f"There is already a control named {name!r}")
