"""The runtime base class for forms.

A form's code subclasses Form and adds handlers named Object_event, where
Object is a control's name, or "Form" for the form itself:

    class Form1(Form):
        def Form_load(self): ...
        def Button1_click(self): ...

Handlers are found by name and connected automatically when the form loads.

As in VB, creating a form loads it (hidden) and raises Form_load; show()
displays it; close() destroys its window but keeps the object, so showing it
again reloads it. Every form is a window of one hidden Tk root, and the
program ends when the last loaded form closes.
"""

from __future__ import annotations

import inspect
import keyword
import tkinter as tk
from pathlib import Path

from pybasic import formfile, forms, menus
from pybasic.controls import Event, create

FORM = "Form"
FORM_EVENTS = (
    Event("load"),
    Event("unload"),
    Event("resize"),
    Event("click"),
    Event("dblclick"),
)

_app: tk.Tk | None = None  # the hidden root window all forms belong to
_loaded: set[Form] = set()


def app_root():
    global _app
    if _app is None:
        _app = tk.Tk()
        _app.withdraw()
    return _app


def main_loop():
    """Run the program until the last loaded form closes."""
    global _app
    if _loaded:
        app_root().mainloop()
    if _app is not None:
        try:
            _app.destroy()
        except tk.TclError:
            pass
        _app = None


class Form:
    default_event = "load"
    events = FORM_EVENTS
    root: tk.Toplevel

    def __init__(self, path=None, master=None):
        """Load the form. By default Form1's layout is the Form1.form beside Form1.py."""
        if path is None:
            path = Path(inspect.getfile(type(self))).with_suffix(".form")
        self.path = Path(path)
        self._master = master
        self.loaded = False
        self.load()

    @classmethod
    def run(cls, path=None):
        """Start a program with this form, e.g. from `python Form1.py`."""
        form = cls(path)
        forms.register(cls.__name__, form)
        form.show()
        main_loop()

    def load(self):
        """Create the (hidden) window and controls, and raise Form_load. show() does this when needed."""
        if self.loaded:
            return
        design = formfile.load(self.path)
        self.root = tk.Toplevel(self._master or app_root())
        self.root.withdraw()
        self.root.title(design.text)
        self.root.geometry(f"{design.width}x{design.height}")
        self._size = (design.width, design.height)
        self.controls = {}
        for spec in design.controls:
            check_name(spec["name"], self.controls)
            control = create(self._parent_widget(spec), spec)
            self.controls[control.name] = control
            setattr(self, control.name, control)
        self.menus = {}
        if design.menu:
            menubar = tk.Menu(self.root, tearoff=False)
            menus.build(menubar, design.menu, self._menu_entry)
            self.root["menu"] = menubar
        self.loaded = True
        _loaded.add(self)
        self._connect_events()
        self._fire("load")

    def show(self, modal=False):
        """Show the form, loading it first if needed. A modal form blocks until it closes."""
        self.load()
        self.root.deiconify()
        self.root.lift()
        self.root.focus_set()
        if modal:
            self.root.grab_set()
            self.root.wait_window()

    def hide(self):
        """Hide the form without closing it. A hidden form keeps the program running."""
        self.root.withdraw()

    def close(self):
        """Close the form, like VB's `Unload Me`. A Form_unload returning True cancels."""
        if not self.loaded or self._fire("unload") is True:
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

    def _menu_entry(self, item, menu, index, variable):
        check_name(item["name"], {**self.controls, **self.menus})
        entry = menus.MenuItem(item, menu, index, variable)
        self.menus[entry.name] = entry
        setattr(self, entry.name, entry)
        if item.get("shortcut"):
            # The shortcut works anywhere in the form, and only while the item is enabled.
            self.root.bind(menus.shortcut_sequence(item["shortcut"]), lambda e: (menu.invoke(index), "break")[1])
        if variable is None:
            return None  # a submenu
        return entry.click(getattr(self, f"{entry.name}_click", None))

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
        self.root.bind("<Destroy>", self._on_destroy, add="+")

    def _on_configure(self, e):
        if e.widget is self.root and (e.width, e.height) != self._size:
            self._size = (e.width, e.height)
            self._fire("resize")

    def _on_form_mouse(self, e, event):
        if e.widget is self.root:
            self._fire(event)

    def _on_destroy(self, e):
        if e.widget is not self.root:
            return
        self.loaded = False
        _loaded.discard(self)
        if not _loaded and _app is not None:
            _app.quit()  # ends main_loop()


_RESERVED = {name for name in dir(Form)} | {"root", "controls", "menus", "path", "loaded", FORM}


def check_name(name, existing=()):
    """Raise ValueError unless name can be used for a new control."""
    if not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"{name!r} is not a valid Python name")
    if name in _RESERVED:
        raise ValueError(f"{name!r} is reserved by the Form class")
    if name in existing:
        raise ValueError(f"There is already a control named {name!r}")
