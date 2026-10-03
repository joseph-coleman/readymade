"""Control types shared by the designer and the runtime.

Each Control subclass wraps one Tk widget and gives it VB-style properties
(text, left, top, width, height, enabled, visible) and a list of events.
REGISTRY maps a type name to its class. The designer's toolbox is built from
it, in registration order, so registering a new control type makes it
available everywhere.
"""

from __future__ import annotations

import copy
import tkinter as tk
import weakref
from dataclasses import dataclass
from tkinter import ttk


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
_MOUSE_EVENTS = (Event("click"), Event("dblclick"), Event("mousedown", ("x", "y")), Event("mouseup", ("x", "y")))
_FOCUS_EVENTS = (Event("gotfocus"), Event("lostfocus"))

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
    _enabled: bool
    _visible: bool
    type_name = ""
    default_size = (96, 24)
    default_event = "click"
    is_container = False  # containers hold other controls in their `inner` widget
    resizable = True
    # Design-time properties that change which widget is used; the designer rebuilds the control.
    recreate_props: tuple[str, ...] = ()
    # Properties limited to a fixed set of string values; the Properties panel offers a dropdown.
    prop_choices: dict[str, tuple[str, ...]] = {}
    events: tuple[Event, ...] = ()
    # Type-specific properties and their defaults. A default's type is the property's type.
    extra_props: dict[str, object] = {}

    def __init__(self, parent, spec, design=False):
        self.name = spec["name"]
        self.design = design
        self.widget = self.create_widget(parent)
        if design:
            for widget in self.design_widgets():
                widget["takefocus"] = 0
                widget["cursor"] = "arrow"
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
            **copy.deepcopy(cls.extra_props),
            "left": 0,
            "top": 0,
            "width": width,
            "height": height,
            "enabled": True,
            "visible": True,
        }

    @classmethod
    def new_spec(cls, name, left, top, width=None, height=None, container=None):
        """The .form entry for a newly drawn control."""
        defaults = cls.prop_defaults()
        spec = {"type": cls.type_name, "name": name}
        if container:
            spec["container"] = container
        spec.update(defaults, left=left, top=top)
        if width and "width" in defaults:
            spec["width"] = width
        if height and "height" in defaults:
            spec["height"] = height
        if "text" in spec:
            spec["text"] = name
        return spec

    def create_widget(self, parent):
        raise NotImplementedError

    def widgets(self):
        """The Tk widgets that receive this control's events."""
        return [self.widget]

    def design_widgets(self):
        """Every Tk widget making up the control, which the designer makes clickable."""
        return self.widgets()

    def _design_only(self, prop, current, value):
        if value != current:
            raise AttributeError(f"{prop} can only be changed in the designer")

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

        for widget in self.widgets():
            widget.bind(sequence, callback, add="+")

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
    events = _MOUSE_EVENTS
    extra_props = {"text": ""}

    def create_widget(self, parent):
        return tk.Label(parent, anchor="w", justify="left")


SCROLLBARS = ("none", "horizontal", "vertical", "both")


@register
class TextBox(Control):
    """A text field. With multiline True it's a multi-line text area, optionally with
    scrollbars. As in VB, both are set in the designer, and scrollbars only apply to
    multi-line boxes. `editor` is the Entry or Text the user types in.
    """

    type_name = "TextBox"
    default_size = (120, 24)
    default_event = "change"
    recreate_props = ("multiline", "scrollbars")
    prop_choices = {"scrollbars": SCROLLBARS}
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS, Event("click"), Event("dblclick"))
    extra_props = {"text": "", "multiline": False, "scrollbars": "none"}

    def __init__(self, parent, spec, design=False):
        self._multiline = bool(spec.get("multiline", False))
        self._scrollbars = spec.get("scrollbars", "none")
        if self._scrollbars not in SCROLLBARS:
            raise ValueError(f"scrollbars must be one of: {', '.join(SCROLLBARS)}")
        super().__init__(parent, spec, design)

    def create_widget(self, parent):
        if not self._multiline:
            self._var = tk.StringVar(parent)
            self.editor = tk.Entry(parent, textvariable=self._var)
            self._parts = [self.editor]
            return self.editor
        horizontal = self._scrollbars in ("horizontal", "both")
        vertical = self._scrollbars in ("vertical", "both")
        frame = tk.Frame(parent)
        # Long lines wrap unless there's a horizontal scrollbar, as in VB. The 1x1 size
        # request lets the frame's placed size decide the real size.
        self.editor = tk.Text(frame, width=1, height=1, font="TkTextFont", wrap="none" if horizontal else "word", undo=True)
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.editor.bind("<Tab>", self._tab_out)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._parts = [frame, self.editor]
        if vertical:
            bar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=self.editor.yview)
            self.editor["yscrollcommand"] = bar.set
            bar.grid(row=0, column=1, sticky="ns")
            self._parts.append(bar)
        if horizontal:
            bar = tk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.editor.xview)
            self.editor["xscrollcommand"] = bar.set
            bar.grid(row=1, column=0, sticky="ew")
            self._parts.append(bar)
        return frame

    def widgets(self):
        return [self.editor]

    def design_widgets(self):
        return self._parts

    @staticmethod
    def _tab_out(e):
        # As in VB, Tab moves to the next control rather than inserting a tab.
        target = e.widget.tk_focusNext()
        if target is not None:
            target.focus_set()
        return "break"

    @property
    def text(self):
        return self.editor.get("1.0", "end-1c") if self._multiline else self._var.get()

    @text.setter
    def text(self, value):
        if not self._multiline:
            self._var.set(str(value))
            return
        # A disabled Text ignores edits, even from code.
        state = self.editor.cget("state")
        self.editor["state"] = tk.NORMAL
        self.editor.replace("1.0", "end-1c", str(value))
        self.editor["state"] = state

    @property
    def multiline(self):
        return self._multiline

    @multiline.setter
    def multiline(self, value):
        self._design_only("multiline", self._multiline, bool(value))

    @property
    def scrollbars(self):
        return self._scrollbars

    @scrollbars.setter
    def scrollbars(self, value):
        self._design_only("scrollbars", self._scrollbars, value)

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.editor["state"] = tk.NORMAL if self._enabled else tk.DISABLED

    def bind_event(self, event, handler):
        if event != "change":
            super().bind_event(event, handler)
        elif not self._multiline:
            self._var.trace_add("write", lambda *_: handler())
        else:
            # Text raises <<Modified>> when its modified flag goes from clear to set, so
            # clear it each time, and compare the text so each change is reported once.
            editor = self.editor
            self._last_text = self.text
            editor.edit_modified(False)

            def modified(_):
                if not editor.edit_modified():
                    return
                editor.edit_modified(False)
                if self.text != self._last_text:
                    self._last_text = self.text
                    handler()

            editor.bind("<<Modified>>", modified, add="+")


@register
class Frame(_WidgetText, Control):
    """A captioned container. Controls drawn inside it are positioned relative to it."""

    inner: tk.Frame
    type_name = "Frame"
    default_size = (200, 120)
    is_container = True
    events = _MOUSE_EVENTS
    extra_props = {"text": ""}

    def create_widget(self, parent):
        frame = tk.LabelFrame(parent)
        self._caption_color = frame.cget("fg")
        # Children go in an inner frame so that (0, 0) is just inside the border and caption.
        self.inner = tk.Frame(frame)
        self.inner.pack(fill=tk.BOTH, expand=True)
        return frame

    def widgets(self):
        return [self.widget, self.inner]

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        # A LabelFrame has no state of its own, so a disabled frame just greys its caption.
        self._enabled = bool(value)
        self.widget["fg"] = self._caption_color if self._enabled else "gray50"


@register
class Button(_WidgetText, Control):
    type_name = "Button"
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
class CheckBox(_WidgetText, Control):
    type_name = "CheckBox"
    default_size = (120, 24)
    events = (Event("click"), *_FOCUS_EVENTS)
    extra_props = {"text": "", "value": False}

    def create_widget(self, parent):
        self._var = tk.BooleanVar(parent, False)
        return tk.Checkbutton(parent, variable=self._var, anchor="w")

    @property
    def value(self):
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
class OptionButton(_WidgetText, Control):
    """A radio button. Option buttons in the same container form one group, as in VB."""

    type_name = "OptionButton"
    default_size = (120, 24)
    events = (Event("click"), *_FOCUS_EVENTS)
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


class _ListMixin:
    """VB-style list methods for controls with an `items` list."""

    @property
    def items(self) -> list[str]:
        raise NotImplementedError

    @items.setter
    def items(self, values):
        raise NotImplementedError

    @property
    def list_count(self):
        return len(self.items)

    def add_item(self, item, index=None):
        items = self.items
        items.insert(len(items) if index is None else index, str(item))
        self.items = items

    def remove_item(self, index):
        items = self.items
        del items[index]
        self.items = items

    def clear(self):
        self.items = []


@register
class ComboBox(_ListMixin, Control):
    """A drop-down list. With editable False the user can only pick from the list."""

    type_name = "ComboBox"
    default_size = (120, 24)
    default_event = "change"
    events = (Event("change"), Event("click"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"text": "", "items": [], "editable": True}

    def create_widget(self, parent):
        self._var = tk.StringVar(parent)
        self._editable = True
        self._enabled = True
        self._combo = ttk.Combobox(parent, textvariable=self._var)
        return self._combo

    @property
    def text(self):
        return self._var.get()

    @text.setter
    def text(self, value):
        self._var.set(str(value))

    @property
    def items(self):
        return list(self._combo.tk.splitlist(self._combo.cget("values")))

    @items.setter
    def items(self, values):
        self.widget["values"] = [str(v) for v in values]

    @property
    def list_index(self):
        """The index of the chosen item, or -1."""
        return self._combo.current()

    @list_index.setter
    def list_index(self, index):
        if index < 0:
            self.text = ""
        else:
            self._combo.current(index)

    @property
    def editable(self):
        return self._editable

    @editable.setter
    def editable(self, value):
        self._editable = bool(value)
        self._update_state()

    @property
    def enabled(self):
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self._update_state()

    def _update_state(self):
        if not self._enabled:
            self.widget["state"] = "disabled"
        else:
            self.widget["state"] = "normal" if self._editable else "readonly"

    def bind_event(self, event, handler):
        if event == "change":
            self._var.trace_add("write", lambda *_: handler())
        elif event == "click":
            self.widget.bind("<<ComboboxSelected>>", lambda e: handler(), add="+")
        else:
            super().bind_event(event, handler)


@register
class ListBox(_ListMixin, Control):
    type_name = "ListBox"
    default_size = (120, 96)
    events = (Event("click"), Event("dblclick"), *_FOCUS_EVENTS)
    extra_props = {"items": []}

    def create_widget(self, parent):
        # exportselection=False keeps the selection when text is selected elsewhere.
        self._list = tk.Listbox(parent, exportselection=False, activestyle="none")
        return self._list

    @property
    def items(self):
        return list(self._list.get(0, tk.END))

    @items.setter
    def items(self, values):
        self._list.delete(0, tk.END)
        self._list.insert(tk.END, *[str(v) for v in values])

    @property
    def list_index(self):
        """The index of the selected item, or -1."""
        selection = self._list.curselection()
        return selection[0] if selection else -1

    @list_index.setter
    def list_index(self, index):
        self._list.selection_clear(0, tk.END)
        if index >= 0:
            self._list.selection_set(index)
            self._list.see(index)

    @property
    def text(self):
        """The selected item's text, or ""."""
        index = self.list_index
        return self._list.get(index) if index >= 0 else ""

    def bind_event(self, event, handler):
        if event == "click":
            self.widget.bind("<<ListboxSelect>>", lambda e: handler(), add="+")
        else:
            super().bind_event(event, handler)


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
        return {"interval": 1000, "left": 0, "top": 0, "enabled": True}

    width = property(lambda self: self.default_size[0])
    height = property(lambda self: self.default_size[1])

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
        return self._interval

    @interval.setter
    def interval(self, milliseconds):
        self._interval = max(0, int(milliseconds))
        self._restart()

    @property
    def enabled(self):
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
