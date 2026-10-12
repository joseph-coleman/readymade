"""The machinery every control shares: the Control base class, its events, and the
registry of control types (see readymade.controls)."""

from __future__ import annotations

import copy
import tkinter as tk
import weakref
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont

from readymade import appearance, keys, layout
from readymade.controls.traits import (GRID_CELL, LOOK_CHOICES, Aligned, Anchored, BackColor, Cursor, Flat, Font,
                                       ForeColor, Picture, TabIndex, TabStop, Tooltip, VAligned)


@dataclass(frozen=True)
class Event:
    """An event a control can raise, and the arguments its handler receives."""

    name: str
    params: tuple[str, ...] = ()
    policy: str = ""  # what happens while its handler is busy; see readymade.events (default: by name)


def _key(e):
    return keys.name(e.char, e.keysym, e.state)


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
    "mousemove": ("<Motion>", None, lambda e: (e.x, e.y)),
    "drag": ("<B1-Motion>", None, lambda e: (e.x, e.y)),
}
_MOUSE_EVENTS = (Event("click"), Event("dblclick"), Event("mousedown", ("x", "y")), Event("mouseup", ("x", "y")))
_FOCUS_EVENTS = (Event("gotfocus"), Event("lostfocus"))

REGISTRY: dict[str, type[Control]] = {}


def register(cls):
    REGISTRY[cls.type_name] = cls
    return cls


def create(parent, spec, design=False, folder=None):
    """Create the control described by a .form control entry. folder is the program's
    folder, where file paths in properties (like an Image's picture) are found."""
    try:
        cls = REGISTRY[spec["type"]]
    except KeyError:
        raise ValueError(f"Unknown control type {spec['type']!r}") from None
    return cls(parent, spec, design, folder)


def _geometry(attr, doc):
    """A position or size property. _left and the rest hold where the control was put for
    its container's designed size; with an anchor, it follows the container from there."""
    index = ("left", "top", "width", "height").index(attr)

    def get(self):
        return self._rect()[index]

    def set(self, value):
        grid = self._grid() if self._ready else None
        if not self._ready or grid is not None or self._docked():
            # (In a Grid: width and height are the size it asks for; its place is the Grid's to decide.
            # Docked: its own width or height, along its edge; where it goes is the docking's.)
            setattr(self, "_" + attr, int(value))
            if grid is not None:
                grid.arrange()
            elif self._ready:
                arrange_docked(self.widget.master)
            return
        rect = list(self._rect())
        rect[index] = int(value)
        self._left, self._top, self._width, self._height = self._unfollow(rect)
        self._place()

    return property(get, set, doc=doc)


class Control:
    """A control on a form. Every control has left, top, width and height (in pixels,
    within its container: the form or a Frame), enabled and visible. `widget` is
    its Tk widget, for anything readymade doesn't cover."""

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
    arranges_inside = False  # a container that places what's in it (a Grid), rather than its own left and top
    has_pages = False  # a container with pages (a TabStrip): each control in it is on one, its "page" in the .form
    can_be_default = False  # a button: Enter presses it when it has the focus, and a form's default_button
                            # and cancel_button can be it
    resizable = True
    # Design-time properties that change which widget is used; the designer rebuilds the control.
    recreate_props: tuple[str, ...] = ()
    # Properties limited to a fixed set of string values; the Properties panel offers a dropdown.
    prop_choices: dict[str, tuple[str, ...]] = {}
    events: tuple[Event, ...] = ()
    # Type-specific properties and their defaults. A default's type is the property's type.
    extra_props: dict[str, object] = {}

    # Properties holding a file path, and the files to offer for them: {prop: {label: patterns}}.
    file_props: dict[str, dict[str, str]] = {}
    # With no backcolor of its own, a label-like control shows its container's color.
    inherits_backcolor = False

    index = None  # in a control array, its index (self.Digit[3].index is 3); otherwise None
    form = None  # the Form it's on, while a program runs (None in the designer)
    _listeners = None  # event name -> [(the handler as given, its events.Handler)]

    def __init__(self, parent, spec, design=False, folder=None):
        self.name = spec["name"]
        self.design = design
        self.folder = Path(folder) if folder else Path.cwd()
        self._ready = False
        self._originals = {}  # (widget, Tk option) -> its value before readymade changed it
        self.widget = self.create_widget(parent)
        _controls[self.widget] = weakref.ref(self)
        if design:
            for widget in self.design_widgets():
                widget["takefocus"] = 0
                widget["cursor"] = "arrow"
        for prop, default in self.prop_defaults().items():
            setattr(self, prop, spec.get(prop, default))
        if isinstance(self, Anchored):  # its cell, if it's in a Grid
            for prop, default in GRID_CELL.items():
                setattr(self, prop, spec.get(prop, default))
        self._ready = True
        self._paint()
        self._apply_font()
        self._apply_alignment()
        self._apply_cursor()
        self._place()
        if self._docked():
            watch_docks(self.widget.master)
            arrange_docked(self.widget.master)

    @classmethod
    def prop_defaults(cls):
        """Every designable property with its default, in Properties panel order."""
        width, height = cls.default_size
        look = {}
        if issubclass(cls, BackColor):
            look["backcolor"] = cls.default_backcolor
        if issubclass(cls, ForeColor):
            look["forecolor"] = ""
        if issubclass(cls, Font):
            look["font"] = ""
        if issubclass(cls, Aligned):
            look["alignment"] = cls.default_alignment
        if issubclass(cls, VAligned):
            look["valignment"] = cls.default_valignment
        if issubclass(cls, Picture):
            look["picture"] = ""
            look["picture_position"] = "left"
        if issubclass(cls, Flat):
            look["flat"] = False
        return {
            **copy.deepcopy(cls.extra_props),
            **look,
            "left": 0,
            "top": 0,
            "width": width,
            "height": height,
            **({"anchor": layout.DEFAULT, "dock": "none", "splitter": False} if issubclass(cls, Anchored) else {}),
            "enabled": True,
            "visible": True,
            **({"tabindex": 0} if issubclass(cls, TabIndex) else {}),
            **({"tabstop": True} if issubclass(cls, TabStop) else {}),
            **({"cursor": "default"} if issubclass(cls, Cursor) else {}),
            **({"tooltip": ""} if issubclass(cls, Tooltip) else {}),
            "tag": "",
        }

    @classmethod
    def choices(cls, prop):
        """The values a property is limited to, or None."""
        return {**LOOK_CHOICES, **cls.prop_choices}.get(prop) if prop in cls.prop_defaults() else None

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

    @classmethod
    def designer_changed(cls, spec, prop):
        """The designer changed prop in spec (a .form control entry): tidy the others to suit,
        like a value that must stay within a new max. Raise ValueError to refuse the change."""

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

    left = _geometry("left", "Distance from the left edge of its container (the form or a Frame), in pixels.")
    top = _geometry("top", "Distance from the top edge of its container (the form or a Frame), in pixels.")
    width = _geometry("width", "Width, in pixels.")
    height = _geometry("height", "Height, in pixels.")

    @property
    def tag(self):
        """Anything you'd like to keep with it, as text, like VB's Tag: readymade doesn't use it."""
        return self._tag

    @tag.setter
    def tag(self, value):
        self._tag = str(value)

    @property
    def visible(self):
        """Whether it's shown. A hidden control keeps its place and properties."""
        return self._visible

    @visible.setter
    def visible(self, value):
        self._visible = bool(value)
        self._place()
        if self._ready and self._docked():
            arrange_docked(self.widget.master)  # (a hidden one leaves its edge to the others)

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.widget["state"] = tk.NORMAL if self._enabled else tk.DISABLED

    # ----- where it is: anchors (see readymade.layout) -----

    _grown = (0, 0)  # how much its container has grown since it was designed (across, down)

    _grid_rect = None  # in a Grid: where the Grid put it
    _dock_rect = None  # docked: where docking put it (see arrange_docked)

    def _docked(self):
        return getattr(self, "_dock", "none") != "none" and self._grid() is None

    # ----- a docked control's splitter: a bar beyond its inner edge, dragged to resize it -----

    _splitter_bar = None

    def _splitter_size(self):
        """How thick its splitter bar is (0: none)."""
        return SPLITTER if getattr(self, "_splitter", False) and self._dock in ("top", "bottom", "left", "right") else 0

    def _show_splitter(self, rect):
        """Put its splitter bar at rect, or with None take it away."""
        if rect is None or (rect[2] <= 0 or rect[3] <= 0):
            if self._splitter_bar is not None:
                self._splitter_bar.place_forget()
            return
        bar = self._splitter_bar
        across = self._dock in ("left", "right")
        if bar is None:
            bar = self._splitter_bar = tk.Frame(self.widget.master, bd=0, highlightthickness=0)
            # (It isn't inside the control's widget, so it goes when that does.)
            self.widget.bind("<Destroy>", lambda e: e.widget is self.widget and bar.destroy(), add="+")
            if not self.design:  # (in the designer it shows where it'll be; dragging is the program's)
                bar["cursor"] = "sb_h_double_arrow" if across else "sb_v_double_arrow"
                bar.bind("<B1-Motion>", self._drag_splitter)
        bar["background"] = self.widget.master.cget("background")
        bar.place(x=rect[0], y=rect[1], width=rect[2], height=rect[3])
        bar.lift()

    def _drag_splitter(self, e):
        """Its bar dragged: its own size follows the mouse (keeping a little of each side)."""
        container = self.widget.master
        if self._dock in ("left", "right"):
            start = self.widget.winfo_rootx()
            size = e.x_root - start if self._dock == "left" else start + self.widget.winfo_width() - e.x_root
            room = container.winfo_width()
        else:
            start = self.widget.winfo_rooty()
            size = e.y_root - start if self._dock == "top" else start + self.widget.winfo_height() - e.y_root
            room = container.winfo_height()
        size = max(SPLITTER, min(int(size), room - 2 * SPLITTER))
        setattr(self, "width" if self._dock in ("left", "right") else "height", size)

    def _grid(self):
        """The Grid it's in, or None."""
        ref = _controls.get(self.widget.master)
        container = ref() if ref else None
        return container if container is not None and container.arranges_inside else None

    def _rect(self):
        """(left, top, width, height) now: where it was put, moved or stretched by its anchor
        (or in a Grid, where its row, column and anchor put it)."""
        if self._grid_rect is not None and self._grid() is not None:
            return self._grid_rect
        if self._dock_rect is not None and self._docked():
            return self._dock_rect
        base = (self._left, self._top, self._width, self._height)
        if self._grown == (0, 0) or not isinstance(self, Anchored):
            return base
        return layout.follow(base, self._anchor, *self._grown)

    def _unfollow(self, rect):
        """Where a control now at rect was put, for the container's designed size."""
        if self._grown == (0, 0) or not isinstance(self, Anchored):
            return tuple(rect)
        return layout.follow(rect, self._anchor, -self._grown[0], -self._grown[1])

    def follow_container(self, grown_across, grown_down):
        """Its container has grown (or shrunk, with negative numbers) since it was designed:
        move or stretch as its anchor says."""
        self._grown = (int(grown_across), int(grown_down))
        self._place()

    def _place(self):
        if not self._ready:
            return
        # The designer always shows invisible controls, as VB did.
        if self._visible or self.design:
            left, top, width, height = self._rect()
            self.widget.place(x=left, y=top, width=width, height=height)
        else:
            self.widget.place_forget()

    # ----- handlers attached from code -----

    def on(self, event, handler=None):
        """Run handler too when event happens: box.on("change", self.filter_list).

        Handlers run in the order attached, after a Name_event method on the form. Each gets
        the event's own arguments: none for click, x and y for mousedown, key for keypress
        (F1 on the control lists them). A method of the form (self.save), or a lambda or
        function made inside one, can use self; a plain function wanting one more argument
        is given the form first, def handler(form): ..., for handlers in another module.
        Returns handler, so it works as a decorator too: @self.Search.on("change")."""
        if handler is None:
            return lambda func: self.on(event, func)
        self._listen(event, handler)
        return handler

    def off(self, event, handler):
        """Stop running a handler that on() attached. True if it was attached."""
        attached = (self._listeners or {}).get(event, [])
        kept = [entry for entry in attached if entry[0] != handler]
        removed = len(kept) < len(attached)
        attached[:] = kept
        return removed

    def _listen(self, event, func, first=()):
        """Attach func to event (first: arguments before the event's, a control array's index)."""
        from readymade import events  # (events finds the form module when it runs handlers)

        kind = next((e for e in self.events if e.name == event), None)
        if kind is None:
            raise ValueError(f"a {self.type_name} has no {event!r} event; its events: "
                             f"{', '.join(e.name for e in self.events) or 'none'}")
        if self.form is None:
            raise RuntimeError(f"{self.name} isn't on a running form, so its events don't run")
        call = events.call_for(func, self.form, len(kind.params), first)
        handler = events.Handler(self.form, call, events.policy_for(func, event, kind.policy))
        if self._listeners is None:
            self._listeners = {}
        if event not in self._listeners:  # (Tk is told once; the handlers run from this list)
            self._listeners[event] = []
            self.bind_event(event, lambda *args, name=event: self._dispatch(name, args))
        self._listeners[event].append((func, handler))

    def _dispatch(self, event, args):
        result = None
        for _, handler in list(self._listeners.get(event, ())):
            value = handler(*args)
            result = value if result is None else result
        return result

    def bind_event(self, event, handler):
        sequence, accept, args = _BINDINGS[event]

        def callback(e):
            if accept is None or accept(e):
                handler(*args(e))

        for widget in self.widgets():
            widget.bind(sequence, callback, add="+")

    def __repr__(self):
        return f"<{self.type_name} {self.name}>"

    # ----- how it looks: colors, font, alignment, cursor (see the mixins below) -----

    def _set(self, widget, option, value):
        """Set a Tk option; None puts back the widget's own value."""
        key = (str(widget), option)
        if key not in self._originals:
            self._originals[key] = widget.cget(option)
        widget.configure({option: self._originals[key] if value is None else value})

    def _background(self):
        """The background to show, or None for the widget's usual one."""
        own = getattr(self, "_backcolor", "")
        if own:
            return own
        return self.widget.master.cget("background") if self.inherits_backcolor else None

    def _foreground(self):
        return getattr(self, "_forecolor", "") or None

    def _painted(self):
        """The widgets whose colors follow backcolor and forecolor."""
        return self.design_widgets()

    def _paint(self):
        if not self._ready:
            return
        bg, fg = self._background(), self._foreground()
        hover = appearance.lighter(bg) if bg and bg.startswith("#") else None
        for widget in self._painted():
            options = widget.keys()
            for option, value in (("background", bg), ("activebackground", hover), ("foreground", fg),
                                  ("activeforeground", fg), ("insertbackground", fg)):
                if option in options:
                    self._set(widget, option, value)
        if "highlightbackground" in self.widget.keys():  # the focus ring's surroundings: the container's color
            self.widget["highlightbackground"] = self.widget.master.cget("background")

    def _font_widgets(self):
        return [self.widget]

    def _apply_font(self):
        if not self._ready or not isinstance(self, Font):
            return
        for widget in self._font_widgets():
            if not self._font:
                self._set(widget, "font", None)
                continue
            self._set(widget, "font", None)  # remember (and start from) its usual font
            usual = tkfont.Font(root=widget, font=widget.cget("font")).actual()
            self._set(widget, "font", appearance.tk_font(self._font, usual))

    def _apply_alignment(self):
        if self._ready and isinstance(self, Aligned):
            self._align(self._alignment, getattr(self, "_valignment", "middle"))

    def _align(self, alignment, valignment):
        self.widget.configure(anchor=appearance.anchor(alignment, valignment), justify=alignment)

    def _apply_cursor(self):
        if not self._ready or not isinstance(self, Cursor) or self.design:
            return  # the designer keeps its own cursor
        for widget in self.design_widgets():
            self._set(widget, "cursor", appearance.CURSORS[self._cursor] or None)

    def _connect_tooltip(self):
        if self.design or getattr(self, "_tooltip_connected", False):
            return  # the designer shows no tooltips
        self._tooltip_connected = True
        for widget in self.design_widgets():
            widget.bind("<Enter>", lambda e: _tip.wait(self, e.x_root, e.y_root), add="+")
            for sequence in ("<Leave>", "<ButtonPress>", "<KeyPress>"):
                widget.bind(sequence, lambda e: _tip.hide(), add="+")


class _Tip:
    """The small box a tooltip shows in. There's one at a time, so one serves every control."""

    DELAY = 600  # milliseconds the mouse rests over a control before its tooltip shows

    def __init__(self):
        self.window = None
        self.job = None  # (widget, after id) while waiting to show

    def wait(self, control, x, y):
        self.hide()
        if control._tooltip:
            self.job = (control.widget, control.widget.after(self.DELAY, lambda: self.show(control, x, y)))

    def show(self, control, x, y):
        self.job = None
        if not control._tooltip or not control.widget.winfo_viewable():
            return
        window = self.window = tk.Toplevel(control.widget)
        window.wm_overrideredirect(True)  # no title bar or border from the window manager
        tk.Label(window, text=control._tooltip, background="#ffffe0", foreground="#000000", relief="solid", bd=1,
                 padx=4, pady=2, justify="left", wraplength=320).pack()
        window.wm_geometry(f"+{x + 12}+{y + 18}")

    def hide(self):
        if self.job:
            widget, job = self.job
            self.job = None
            try:
                widget.after_cancel(job)
            except tk.TclError:
                pass
        if self.window is not None:
            try:
                self.window.destroy()
            except tk.TclError:
                pass
            self.window = None


_tip = _Tip()


# Each control's Tk widget -> the control, so a container can repaint what's inside it.
_controls: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


# ----- for the form and the designer -----
# (Plain functions rather than methods: a control's public methods are part of what programs
# see, in completion and F1 help.)

def grid_of(control):
    """The Grid a control is in, or None."""
    return control._grid()


def focus_widget(control):
    """The Tk widget that takes the keyboard for a control (a TextBox's text, say)."""
    return control._focus_widget()


def option_group(option):
    """What an OptionButton's group is known by: the OptionButtons of a container share it."""
    return option._group


def show_as_default(button, default):
    """Give a Button the heavier border of the form's default button (Enter clicks it), or not."""
    button._set(button.widget, "default", "active" if default else None)


def arrange_docked(widget, width=None, height=None):
    """Lay out the docked controls in a container widget (the form, a Frame's inside, a
    TabStrip page), in the order they were made: see layout.dock. Until the widget has a size
    of its own there's nothing to do; its <Configure> (see watch_docks) does it then."""
    if width is None:
        width, height = widget.winfo_width(), widget.winfo_height()
    if width <= 1 and height <= 1:
        return
    docked = []
    for child in widget.winfo_children():
        ref = _controls.get(child)
        control = ref() if ref else None
        if control is None:
            continue
        if control._docked() and (control._visible or control.design):
            docked.append(control)
        else:
            control._show_splitter(None)
    rects = layout.dock(width, height, [(c._dock, (c._width, c._height), c._splitter_size()) for c in docked])
    for control, rect in zip(docked, rects):
        if control._dock_rect != rect:
            control._dock_rect = rect
            control._place()
        bar = control._splitter_size()
        control._show_splitter(layout.splitter_rect(control._dock, rect, bar) if bar else None)


SPLITTER = 6  # pixels: a docked control's splitter bar

_watching = weakref.WeakSet()  # container widgets that lay out their docked controls when resized


def watch_docks(widget):
    """Re-dock a container widget's controls whenever it changes size."""
    if widget in _watching:
        return
    _watching.add(widget)

    def resized(e):
        if e.widget is widget:  # (a window's bindings also see its controls' events)
            arrange_docked(widget, e.width, e.height)

    widget.bind("<Configure>", resized, add="+")


def inner_for(container, spec):
    """The Tk widget a control goes in, inside a container: a Frame's inside, or for a
    TabStrip the page its .form spec names."""
    return container._inner_for(spec.get("page", 0)) if container.has_pages else container.inner


def page_at(control, x_root, y_root):
    """For a TabStrip: the page whose tab is at a screen point; otherwise (or off its tabs) None."""
    return control._page_at(x_root, y_root) if control.has_pages else None


def shown_page(container):
    """The TabStrip page showing (in the designer, maybe not its starting tab)."""
    return container._shown()


def show_page(container, page):
    """Show one of a TabStrip's pages in the designer (its tab, the starting page, stays)."""
    container._show(page)


def control_of(widget):
    """The control a Tk widget belongs to (say, the one with the keyboard focus), or None."""
    while widget is not None:
        ref = _controls.get(widget)
        control = ref() if ref else None
        if control is not None:
            return control
        widget = widget.master
    return None


def repaint_inside(widget):
    """Repaint the controls in a container widget (a form, or a Frame), after its color changed."""
    for child in widget.winfo_children():
        ref = _controls.get(child)
        control = ref() if ref else None
        if control is not None:
            control._paint()


def tab_numbers(specs):
    """For a form's controls (.form specs, in the order they were drawn) where some have no
    tabindex yet, like a Label or Frame from before they had one: {name: number} for all
    that have a place in the Tab order. One without is put just before the next numbered
    control drawn after it (where a Label's access key went then), or at the end. None if
    every one has its number."""
    placed = [s for s in specs if issubclass(REGISTRY[s["type"]], TabIndex)]
    if all("tabindex" in s for s in placed):
        return None
    numbered = [s for s in placed if "tabindex" in s]
    ordered = sorted(numbered, key=lambda s: s["tabindex"])  # (ties: as drawn)
    for i, spec in enumerate(placed):
        if "tabindex" not in spec:
            following = next((s for s in placed[i + 1:] if "tabindex" in s), None)
            ordered.insert(ordered.index(following) if following is not None else len(ordered), spec)
    return {spec["name"]: number for number, spec in enumerate(ordered)}
