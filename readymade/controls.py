"""Control types shared by the designer and the runtime.

Each Control subclass wraps one Tk widget and gives it VB-style properties
(text, left, top, width, height, enabled, visible) and a list of events.
REGISTRY maps a type name to its class. The designer's toolbox is built from
it, in registration order, so registering a new control type makes it
available everywhere.
"""

from __future__ import annotations

import copy
import sys
import tkinter as tk
import weakref
from dataclasses import dataclass
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from readymade import appearance, keys, layout, menus, pictures
from readymade import shapes as _shapes
from readymade.shapes import Shape


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
        if not self._ready or grid is not None:
            # (In a Grid: width and height are the size it asks for; its place is the Grid's to decide.)
            setattr(self, "_" + attr, int(value))
            if grid is not None:
                grid.arrange()
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
        if isinstance(self, _Anchored):  # its cell, if it's in a Grid
            for prop, default in GRID_CELL.items():
                setattr(self, prop, spec.get(prop, default))
        self._ready = True
        self._paint()
        self._apply_font()
        self._apply_alignment()
        self._apply_cursor()
        self._place()

    @classmethod
    def prop_defaults(cls):
        """Every designable property with its default, in Properties panel order."""
        width, height = cls.default_size
        look = {}
        if issubclass(cls, _BackColor):
            look["backcolor"] = cls.default_backcolor
        if issubclass(cls, _ForeColor):
            look["forecolor"] = ""
        if issubclass(cls, _Font):
            look["font"] = ""
        if issubclass(cls, _Aligned):
            look["alignment"] = cls.default_alignment
        if issubclass(cls, _VAligned):
            look["valignment"] = cls.default_valignment
        return {
            **copy.deepcopy(cls.extra_props),
            **look,
            "left": 0,
            "top": 0,
            "width": width,
            "height": height,
            **({"anchor": layout.DEFAULT} if issubclass(cls, _Anchored) else {}),
            "enabled": True,
            "visible": True,
            **({"tabindex": 0} if issubclass(cls, _TabIndex) else {}),
            **({"cursor": "default"} if issubclass(cls, _Cursor) else {}),
            **({"tooltip": ""} if issubclass(cls, _Tooltip) else {}),
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

    def _grid(self):
        """The Grid it's in, or None."""
        ref = _controls.get(self.widget.master)
        container = ref() if ref else None
        return container if isinstance(container, Grid) else None

    def _rect(self):
        """(left, top, width, height) now: where it was put, moved or stretched by its anchor
        (or in a Grid, where its row, column and anchor put it)."""
        if self._grid_rect is not None and self._grid() is not None:
            return self._grid_rect
        base = (self._left, self._top, self._width, self._height)
        if self._grown == (0, 0) or not isinstance(self, _Anchored):
            return base
        return layout.follow(base, self._anchor, *self._grown)

    def _unfollow(self, rect):
        """Where a control now at rect was put, for the container's designed size."""
        if self._grown == (0, 0) or not isinstance(self, _Anchored):
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
        if not self._ready or not isinstance(self, _Font):
            return
        for widget in self._font_widgets():
            if not self._font:
                self._set(widget, "font", None)
                continue
            self._set(widget, "font", None)  # remember (and start from) its usual font
            usual = tkfont.Font(root=widget, font=widget.cget("font")).actual()
            self._set(widget, "font", appearance.tk_font(self._font, usual))

    def _apply_alignment(self):
        if self._ready and isinstance(self, _Aligned):
            self._align(self._alignment, getattr(self, "_valignment", "middle"))

    def _align(self, alignment, valignment):
        self.widget.configure(anchor=appearance.anchor(alignment, valignment), justify=alignment)

    def _apply_cursor(self):
        if not self._ready or not isinstance(self, _Cursor) or self.design:
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


LOOK_CHOICES = {"alignment": appearance.ALIGNMENTS, "valignment": appearance.VALIGNMENTS,
                "cursor": tuple(appearance.CURSORS), "anchor": layout.CHOICES}


class _BackColor:
    """A backcolor property."""

    default_backcolor = ""
    _backcolor: str

    @property
    def backcolor(self):
        """The background color, as "#rrggbb"; "" for the usual color (for a label, check box,
        option button, frame or picture: the color of the form or Frame it's on)."""
        return self._backcolor

    @backcolor.setter
    def backcolor(self, value):
        self._backcolor = appearance.check_color(value)
        self._paint()


class _ForeColor:
    """A forecolor property."""

    _forecolor: str

    @property
    def forecolor(self):
        """The text color, as "#rrggbb"; "" for the usual color."""
        return self._forecolor

    @forecolor.setter
    def forecolor(self, value):
        self._forecolor = appearance.check_color(value)
        self._paint()


class _Font:
    """A font property."""

    _font: str

    @property
    def font(self):
        """The font, like "Arial, 12, bold": its family, its size in points, then any of bold,
        italic and underline. Leave parts out for the usual ones: ", 14" is the usual font at
        14 points, and "" the usual font. Code can also use a tuple: ("Arial", 12, "bold")."""
        return self._font

    @font.setter
    def font(self, value):
        self._font = appearance.format_font(value)
        self._apply_font()


class _Aligned:
    """An alignment property."""

    default_alignment = "left"
    _alignment: str

    @property
    def alignment(self):
        """Where its text goes across: "left", "center" or "right"."""
        return self._alignment

    @alignment.setter
    def alignment(self, value):
        self._alignment = appearance.check_choice("alignment", value, appearance.ALIGNMENTS)
        self._apply_alignment()


class _VAligned:
    """A valignment property."""

    default_valignment = "middle"
    _valignment: str

    @property
    def valignment(self):
        """Where its text goes up and down: "top", "middle" or "bottom"."""
        return self._valignment

    @valignment.setter
    def valignment(self, value):
        self._valignment = appearance.check_choice("valignment", value, appearance.VALIGNMENTS)
        self._apply_alignment()


class _Cursor:
    """A cursor property."""

    _cursor: str

    @property
    def cursor(self):
        """The mouse pointer over it: "default" (its usual one), "arrow", "hand", "text",
        "cross", "wait", "move", "help", "resize_ew" (left and right) or "resize_ns" (up and down)."""
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = appearance.check_choice("cursor", value, tuple(appearance.CURSORS))
        self._apply_cursor()


class _TabIndex:
    """A tabindex property: a place in the form's Tab order."""

    widget: tk.Widget
    _tabindex: int

    @property
    def tabindex(self):
        """Its place in the order Tab moves through the form's controls, counting from 0
        (Shift+Tab goes backwards). The designer's Format > Tab Order sets them by clicking.
        Tab doesn't stop at a Label or Frame, but as in VB they have a place in the order:
        a Label's access key (an & in its text) goes to the control after it."""
        return self._tabindex

    @tabindex.setter
    def tabindex(self, value):
        self._tabindex = int(value)


def tab_numbers(specs):
    """For a form's controls (.form specs, in the order they were drawn) where some have no
    tabindex yet, like a Label or Frame from before they had one: {name: number} for all
    that have a place in the Tab order. One without is put just before the next numbered
    control drawn after it (where a Label's access key went then), or at the end. None if
    every one has its number."""
    placed = [s for s in specs if issubclass(REGISTRY[s["type"]], _TabIndex)]
    if all("tabindex" in s for s in placed):
        return None
    numbered = [s for s in placed if "tabindex" in s]
    ordered = sorted(numbered, key=lambda s: s["tabindex"])  # (ties: as drawn)
    for i, spec in enumerate(placed):
        if "tabindex" not in spec:
            following = next((s for s in placed[i + 1:] if "tabindex" in s), None)
            ordered.insert(ordered.index(following) if following is not None else len(ordered), spec)
    return {spec["name"]: number for number, spec in enumerate(ordered)}


class _TabStop(_TabIndex):
    """A control the keyboard can reach: Tab stops at it."""

    def _focus_widget(self):
        """The widget that takes the keyboard focus."""
        return self.widget


class _Anchored:
    """An anchor property (see readymade.layout)."""

    _anchor: str

    @property
    def anchor(self):
        """The edges of its container (the form, or a Frame) it keeps its distance to when that
        changes size: "top left" (it stays put), "bottom right" (it stays in that corner),
        "top left right" (it stretches across), "top bottom left right" (both ways). With
        neither left nor right it stays centered across; "none" centers it both ways.
        In a Grid, the edges of its cell it sticks to: all four fill the cell."""
        return self._anchor

    @anchor.setter
    def anchor(self, value):
        grid = self._grid() if self._ready else None
        if grid is not None:  # in a Grid: the edges of its cell it sticks to
            self._anchor = layout.normalize(value)
            grid.arrange()
            return
        rect = self._rect() if self._ready else None
        self._anchor = layout.normalize(value)
        if rect is not None:  # it stays where it is now; from here on it follows the new edges
            self._left, self._top, self._width, self._height = self._unfollow(rect)
            self._place()


    def _cell_prop(name, doc, smallest):
        def get(self):
            return getattr(self, "_" + name)

        def set(self, value):
            value = int(value)
            if value < smallest:
                raise ValueError(f"{name} can't be less than {smallest}")
            setattr(self, "_" + name, value)
            grid = self._grid() if getattr(self, "_ready", False) else None
            if grid is not None:
                grid.arrange()

        return property(get, set, doc=doc)

    row = _cell_prop("row", "In a Grid: the row it's in, counting from 0.", 0)
    column = _cell_prop("column", "In a Grid: the column it's in, counting from 0.", 0)
    rowspan = _cell_prop("rowspan", "In a Grid: how many rows it covers.", 1)
    columnspan = _cell_prop("columnspan", "In a Grid: how many columns it covers.", 1)
    del _cell_prop


# A control's place in a Grid, kept in the .form only for controls in one (with these defaults).
GRID_CELL = {"row": 0, "column": 0, "rowspan": 1, "columnspan": 1}


class _Tooltip:
    """A tooltip property."""

    _tooltip: str

    @property
    def tooltip(self):
        """Text shown in a small box when the mouse rests over it while the program runs; "" for none."""
        return self._tooltip

    @tooltip.setter
    def tooltip(self, value):
        self._tooltip = str(value or "")
        if self._tooltip:
            self._connect_tooltip()


class _WidgetText:
    """A text property backed by the widget's own text option. As in VB, an & marks the
    letter of an access key, shown underlined: "&Save" is Alt+S (on a Mac Ctrl+Option+S),
    which clicks a Button, or for a Label or Frame goes to the next control. && is an &."""

    widget: tk.Widget
    _accesskey = True

    @property
    def text(self):
        """The text it shows: a Label's words, a Button's or CheckBox's label, a Frame's title."""
        return getattr(self, "_caption", "")

    @text.setter
    def text(self, value):
        self._caption = str(value)
        shown, underline = menus.parse_text(self._caption) if self._accesskey else (self._caption, -1)
        self.widget["text"] = shown
        try:
            self.widget["underline"] = underline
        except tk.TclError:
            pass  # (a Frame's title can't underline; its key still works)

    @property
    def access_key(self):
        """The letter of its access key, as a capital ("S" for "&Save"), or ""."""
        if not self._accesskey:
            return ""
        shown, underline = menus.parse_text(self.text)
        return shown[underline].upper() if 0 <= underline < len(shown) else ""


@register
class Label(_WidgetText, _BackColor, _ForeColor, _Font, _Aligned, _VAligned, _TabIndex, _Cursor, _Tooltip, _Anchored,
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


SCROLLBARS = ("none", "horizontal", "vertical", "both")


@register
class TextBox(_BackColor, _ForeColor, _Font, _Aligned, _TabStop, _Cursor, _Tooltip, _Anchored, Control):
    """A text field. With multiline True it's a multi-line text area, optionally with
    scrollbars. As in VB, both are set in the designer, and scrollbars only apply to
    multi-line boxes. readonly, password and maxlength limit what the user can do;
    code can always set text. `editor` is the Entry or Text the user types in.
    """

    type_name = "TextBox"
    default_size = (120, 24)
    default_event = "change"
    recreate_props = ("multiline", "scrollbars")
    prop_choices = {"scrollbars": SCROLLBARS}
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS, Event("click"), Event("dblclick"))
    extra_props = {"text": "", "multiline": False, "scrollbars": "none", "readonly": False, "password": False,
                   "maxlength": 0}

    def __init__(self, parent, spec, design=False, folder=None):
        self._multiline = bool(spec.get("multiline", False))
        self._scrollbars = spec.get("scrollbars", "none")
        if self._scrollbars not in SCROLLBARS:
            raise ValueError(f"scrollbars must be one of: {', '.join(SCROLLBARS)}")
        super().__init__(parent, spec, design, folder)

    def create_widget(self, parent):
        self._readonly = self._password = False
        self._maxlength = 0
        if not self._multiline:
            self._var = tk.StringVar(parent)
            self.editor = tk.Entry(parent, textvariable=self._var)
            # Tk checks each edit the user makes (not code's) with this before making it.
            self.editor.configure(validate="key", validatecommand=(self.editor.register(self._fits), "%P"))
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
        self.editor.bind("<KeyPress>", self._limit_typing, add="+")  # maxlength (a Text can't validate)
        self.editor.bind("<<Paste>>", self._limit_paste, add="+")
        # A Text has no alignment of its own, only its tags', so keep all of its text tagged.
        self.editor.tag_configure("readymade-align", justify="left")
        for sequence in ("<KeyRelease>", "<ButtonRelease-2>"):
            self.editor.bind(sequence, self._retag, add="+")
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

    def _painted(self):
        return [w for w in self._parts if not isinstance(w, tk.Scrollbar)]

    def _paint(self):
        super()._paint()
        if self._ready and not self._multiline:
            self.editor["readonlybackground"] = self.editor["background"]  # read-only looks the same, as in VB
    def _font_widgets(self):
        return [self.editor]

    def _align(self, alignment, valignment):
        if self._multiline:
            self.editor.tag_configure("readymade-align", justify=alignment)
            self._retag()
        else:
            self.editor["justify"] = alignment

    def _retag(self, _=None):
        self.editor.tag_add("readymade-align", "1.0", "end")

    def _focus_widget(self):
        return self.editor

    @staticmethod
    def _tab_out(e):
        # As in VB, Tab moves to the next control rather than inserting a tab; the form does that.
        e.widget.event_generate("<<NextControl>>")
        return "break"

    @property
    def text(self):
        """What's in the box. Setting it replaces the contents (and raises change)."""
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
        self._retag()
        self.editor["state"] = state

    @property
    def multiline(self):
        """Whether it's a multi-line text area rather than a single line. Set in the designer."""
        return self._multiline

    @multiline.setter
    def multiline(self, value):
        self._design_only("multiline", self._multiline, bool(value))

    @property
    def scrollbars(self):
        """A multi-line box's scrollbars: "none", "horizontal", "vertical" or "both". Set in the designer."""
        return self._scrollbars

    @scrollbars.setter
    def scrollbars(self, value):
        self._design_only("scrollbars", self._scrollbars, value)

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self._update_state()

    @property
    def readonly(self):
        """Whether the user can't change the text, as with VB's Locked. They can still select
        it (and in a single-line box, copy it). Code can still set text."""
        return self._readonly

    @readonly.setter
    def readonly(self, value):
        self._readonly = bool(value)
        self._update_state()

    @property
    def password(self):
        """Whether the text shows as dots, for passwords. Single-line boxes only."""
        return self._password

    @password.setter
    def password(self, value):
        self._password = bool(value)
        if not self._multiline:
            self.editor["show"] = "\u2022" if self._password else ""

    @property
    def maxlength(self):
        """The most characters the user can type or paste in; 0 for no limit. Code can still set longer text."""
        return self._maxlength

    @maxlength.setter
    def maxlength(self, value):
        value = int(value)
        if value < 0:
            raise ValueError("maxlength can't be negative (0 means no limit)")
        self._maxlength = value

    def _update_state(self):
        if not getattr(self, "_enabled", True):
            state = tk.DISABLED
        elif self._readonly:
            state = tk.DISABLED if self._multiline else "readonly"  # a Text has no read-only state
        else:
            state = tk.NORMAL
        self.editor["state"] = state

    def _fits(self, proposed):
        return not self._maxlength or len(proposed) <= self._maxlength

    def _limit_typing(self, e):
        """Stop typing into a full multi-line box (unless it replaces a selection)."""
        typing = (e.char and e.char.isprintable()) or e.keysym in ("Return", "KP_Enter")
        if self._maxlength and typing and not self.editor.tag_ranges("sel") and len(self.text) >= self._maxlength:
            return "break"
        return None

    def _limit_paste(self, e):
        """Paste only as much as fits into a multi-line box."""
        if not self._maxlength:
            return None
        try:
            pasted = self.editor.clipboard_get()
        except tk.TclError:
            return "break"  # nothing to paste
        selected = self.editor.tag_ranges("sel")
        replaced = len(self.editor.get(*selected)) if selected else 0
        room = max(0, self._maxlength - len(self.text) + replaced)
        if len(pasted) <= room:
            return None  # it all fits: paste as usual
        if selected:
            self.editor.delete(*selected)
        self.editor.insert("insert", pasted[:room])
        return "break"

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
class Frame(_WidgetText, _BackColor, _ForeColor, _Font, _Aligned, _TabIndex, _Cursor, _Tooltip, _Anchored, Control):
    """A captioned box that groups controls. Controls drawn inside it belong to it: they're
    positioned relative to it and move with it, and its OptionButtons form their own group."""

    inner: tk.Frame
    type_name = "Frame"
    default_size = (200, 120)
    is_container = True
    inherits_backcolor = True
    events = _MOUSE_EVENTS
    extra_props = {"text": ""}

    def create_widget(self, parent):
        frame = tk.LabelFrame(parent)
        # Children go in an inner frame so that (0, 0) is just inside the border and caption.
        self.inner = tk.Frame(frame)
        self.inner.pack(fill=tk.BOTH, expand=True)
        return frame

    def widgets(self):
        return [self.widget, self.inner]

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        # A LabelFrame has no state of its own, so a disabled frame just grays its caption.
        self._enabled = bool(value)
        self._paint()

    def _foreground(self):
        return super()._foreground() if self._enabled else "gray50"

    def _paint(self):
        super()._paint()
        if self._ready:
            repaint_inside(self.inner)  # controls showing its color follow it

    def _place(self):
        super()._place()
        if not self._ready or self.design:
            return  # (the designer moves anchored controls itself, in the form's design)
        # The controls inside follow its size, measured from the size it was designed at.
        _, _, width, height = self._rect()
        designed = getattr(self, "_designed_size", None)
        if designed is None:
            designed = self._designed_size = (width, height)
        for child in self.inner.winfo_children():
            ref = _controls.get(child)
            control = ref() if ref else None
            if control is not None:
                control.follow_container(width - designed[0], height - designed[1])

    def _align(self, alignment, valignment):
        self.widget["labelanchor"] = {"left": "nw", "center": "n", "right": "ne"}[alignment]


@register
class Button(_WidgetText, _BackColor, _ForeColor, _Font, _Aligned, _VAligned, _TabStop, _Cursor, _Tooltip, _Anchored, Control):
    """A push button. Its click event runs when it's clicked, or pressed with Space while it has the focus.
    (On macOS, buttons keep the system's own colors.)"""

    type_name = "Button"
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
class CheckBox(_WidgetText, _BackColor, _ForeColor, _Font, _Aligned, _VAligned, _TabStop, _Cursor, _Tooltip, _Anchored, Control):
    """A box that can be ticked. value is True while it's ticked; click runs each time it changes."""

    type_name = "CheckBox"
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
class OptionButton(_WidgetText, _BackColor, _ForeColor, _Font, _Aligned, _VAligned, _TabStop, _Cursor, _Tooltip, _Anchored, Control):
    """A radio button. Option buttons in the same container form one group, as in VB."""

    type_name = "OptionButton"
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


class _ListMixin:
    """VB-style list methods for controls with an `items` list."""

    @property
    def items(self) -> list[str]:
        """The list's items, as strings. Assigning a list replaces them all."""
        raise NotImplementedError

    @items.setter
    def items(self, values):
        raise NotImplementedError

    @property
    def list_count(self):
        """How many items there are."""
        return len(self.items)

    def add_item(self, item, index=None):
        """Add an item at the end, or at position index (counting from 0)."""
        items = self.items
        items.insert(len(items) if index is None else index, str(item))
        self.items = items

    def remove_item(self, index):
        """Remove the item at position index (counting from 0)."""
        items = self.items
        del items[index]
        self.items = items

    def clear(self):
        """Remove every item."""
        self.items = []


@register
class ComboBox(_ListMixin, _BackColor, _ForeColor, _Font, _Aligned, _TabStop, _Cursor, _Tooltip, _Anchored, Control):
    """A drop-down list. With editable False the user can only pick from the list."""

    type_name = "ComboBox"
    default_size = (120, 24)
    default_event = "change"
    events = (Event("change"), Event("click", policy="latest"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"text": "", "items": [], "editable": True}

    def create_widget(self, parent):
        self._var = tk.StringVar(parent)
        self._editable = True
        self._enabled = True
        self._combo = ttk.Combobox(parent, textvariable=self._var)
        return self._combo

    @property
    def text(self):
        """The text in the box: the chosen item, or what was typed if it's editable."""
        return self._var.get()

    @text.setter
    def text(self, value):
        self._var.set(str(value))

    @property
    def items(self):
        """The list's items, as strings. Assigning a list replaces them all."""
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
        """Whether the user can type their own text (True) or only choose from the list (False)."""
        return self._editable

    @editable.setter
    def editable(self, value):
        self._editable = bool(value)
        self._update_state()

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
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

    def _paint(self):
        # A ttk widget takes its colors from a style, so each colored ComboBox gets its own.
        if not self._ready:
            return
        bg, fg = self._background(), self._foreground()
        if bg or fg:
            name = f"readymade{id(self)}.TCombobox"
            style = ttk.Style(self._combo)
            style.configure(name, **{k: v for k, v in (("fieldbackground", bg), ("foreground", fg)) if v})
            style.map(name, **{k: [("readonly", v)] for k, v in (("fieldbackground", bg), ("foreground", fg)) if v})
            self._combo["style"] = name
        else:
            # In the designer, the preview style: it stays light in a dark IDE, as the program will be.
            self._combo["style"] = "Preview.TCombobox" if self.design else "TCombobox"
        self._list_option("background", bg)
        self._list_option("foreground", fg)

    def _apply_font(self):
        super()._apply_font()
        if self._ready:
            self._list_option("font", self._combo.cget("font") if self._font else None)

    def _align(self, alignment, valignment):
        self._combo["justify"] = alignment

    def _list_option(self, option, value):
        """Set an option of the drop-down list (a Tk widget readymade doesn't otherwise see)."""
        call = self._combo.tk.call
        path = call("ttk::combobox::PopdownWindow", self._combo) + ".f.l"
        key = (path, option)
        if key not in self._originals:
            self._originals[key] = call(path, "cget", f"-{option}")
        call(path, "configure", f"-{option}", self._originals[key] if value is None else value)

    def bind_event(self, event, handler):
        if event == "change":
            self._var.trace_add("write", lambda *_: handler())
        elif event == "click":
            self.widget.bind("<<ComboboxSelected>>", lambda e: handler(), add="+")
        else:
            super().bind_event(event, handler)


@register
class ListBox(_ListMixin, _BackColor, _ForeColor, _Font, _TabStop, _Cursor, _Tooltip, _Anchored, Control):
    """A list to choose from. click runs when the choice changes; list_index and text tell
    which item is chosen."""

    type_name = "ListBox"
    default_size = (120, 96)
    events = (Event("click", policy="latest"), Event("dblclick"), *_FOCUS_EVENTS)
    extra_props = {"items": []}

    def create_widget(self, parent):
        # exportselection=False keeps the selection when text is selected elsewhere.
        self._list = tk.Listbox(parent, exportselection=False, activestyle="none")
        return self._list

    @property
    def items(self):
        """The list's items, as strings. Assigning a list replaces them all."""
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


# Which point of a text is at (x, y), in Pillow's terms.
_TEXT_ANCHORS = {"nw": "la", "n": "ma", "ne": "ra", "w": "lm", "center": "mm", "e": "rm",
                 "sw": "ld", "s": "md", "se": "rd"}


@register
class Image(_BackColor, _Cursor, _Tooltip, _Anchored, Control):
    """A picture from a file: PNG or GIF, and with Pillow installed also JPEG and others.
    picture is the file's path, relative to the program's folder (see app_path); sizing
    chooses how picture and control fit each other. In code, picture can also be set to
    any file, like one the user chose: self.Image1.picture = open_file_dialog()

    With Pillow, code can also draw on the picture's pixels, or on a new one:

        self.Image1.new(320, 200)
        self.Image1.line(0, 0, 319, 199, color="#ff0000", thickness=2)
        self.Image1.save("drawing.png")

    The drawing methods have the same names as a Canvas's, but nothing drawn can be moved
    or changed afterwards: it's just pixels. Coordinates are the picture's pixels (the
    same as the mouse's, unless the picture is scaled). The screen catches up when the
    handler finishes, so drawing thousands of points stays quick."""

    type_name = "Image"
    default_size = (96, 96)
    inherits_backcolor = True
    events = (*_MOUSE_EVENTS, Event("mousemove", ("x", "y")), Event("drag", ("x", "y")))
    extra_props = {"picture": "", "sizing": "autosize", "border": False}
    prop_choices = {"sizing": ("autosize", "normal", "center", "stretch", "zoom")}
    file_props = {"picture": pictures.FILE_TYPES}

    def create_widget(self, parent):
        self._picture = ""
        self._sizing = "autosize"
        self._border = False
        self._photo = None  # Tk forgets images nothing refers to
        self._natural = None  # the picture's own size
        self._drawing = None  # the picture as a Pillow image, once code draws on it
        self._draw = None
        self._version = 0  # counts drawing changes, so the screen knows to catch up
        self._refresh_pending = False
        self._shown = None
        return tk.Label(parent, bd=0, highlightthickness=0, padx=0, pady=0, compound="center")

    @property
    def picture(self):
        """The picture file's path, like "images/logo.png" (in the program's folder) or a full path; "" for none."""
        return self._picture

    @picture.setter
    def picture(self, path):
        self._picture = str(path or "")
        self._drawing = self._draw = None
        self._show()

    @property
    def sizing(self):
        """How picture and control fit: "autosize" (the control takes the picture's size),
        "normal" (the picture at its own size, from the top left), "center" (at its own size,
        centered), "stretch" (scaled to fill the control) or "zoom" (scaled to fit inside the
        control, keeping its shape)."""
        return self._sizing

    @sizing.setter
    def sizing(self, value):
        if value not in self.prop_choices["sizing"]:
            raise ValueError(f"sizing must be one of: {', '.join(self.prop_choices['sizing'])}")
        self._sizing = value
        self._show()

    @property
    def border(self):
        """Whether a thin line is drawn around it."""
        return self._border

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self._show()

    @property
    def picture_size(self):
        """(width, height) of the picture itself, in pixels; None without one."""
        if self._drawing is not None:
            return self._drawing.size
        return self._natural

    @property
    def resizable(self):
        # An autosized Image's size is its picture's (the designer has no resize handles for it).
        return self._sizing != "autosize" or self._photo is None

    def _place(self):
        if self._ready and self._sizing == "autosize" and self._photo is not None:
            edge = 2 * self._border
            self._width, self._height = self._photo.width() + edge, self._photo.height() + edge
        super()._place()
        if self._ready and self._shown != self._showing():
            self._show()  # first shown, or a scaled picture's new size needs a new scaling

    def _inner_size(self):
        edge = 2 * self._border
        _, _, width, height = self._rect()
        return max(1, width - edge), max(1, height - edge)

    def _showing(self):
        scaled = self._sizing in ("stretch", "zoom")
        return self._picture, self._version, self._sizing, self._border, self._inner_size() if scaled else None

    def _show(self):
        if not self._ready:
            return  # shown once all the properties are set
        self._shown = self._showing()
        self._photo = None
        message = ""
        size = self._inner_size() if self._sizing in ("stretch", "zoom") else None
        keep_shape = self._sizing == "zoom"
        if self._drawing is not None:
            self._photo = pictures.to_photo(self._drawing, size, keep_shape, master=self.widget)
        elif self._picture:
            try:
                self._photo, self._natural = pictures.load(self.folder / self._picture, size, keep_shape,
                                                           master=self.widget)
            except (OSError, tk.TclError) as e:
                self._natural = None
                message = f"Can't show {self._picture}"
                if not self.design:
                    print(f"{self.name}: can't show the picture {self._picture!r} ({e})", file=sys.stderr)
        else:
            self._natural = None
            if self.design:
                message = "(no picture)"  # so it can be seen and clicked in the designer
        self.widget.configure(
            image=self._photo or "", text=message, wraplength=max(1, self._rect()[2] - 4),
            anchor="nw" if self._sizing in ("autosize", "normal") else "center",
            relief="solid" if self._border else "flat", bd=int(self._border),
        )
        if self._sizing == "autosize":
            self._place()  # take the picture's size

    # ----- drawing on the pixels (needs Pillow) -----

    def new(self, width, height, background="#ffffff"):
        """Start a new picture of the given size to draw on, filled with background ("" for transparent)."""
        pictures.need_pillow("Drawing on an Image")
        self._picture = ""
        self._drawing = pictures.blank((int(width), int(height)), background)
        self._draw = pictures.drawer(self._drawing)
        self._version += 1
        self._show()

    def _surface(self):
        if self._draw is None:
            pictures.need_pillow("Drawing on an Image")
            if self._picture:
                self._drawing = pictures.open_for_drawing(self.folder / self._picture)
            else:  # a blank picture the size of the control
                self._drawing = pictures.blank(self._inner_size())
            self._draw = pictures.drawer(self._drawing)
        return self._draw

    def _drawn(self):
        """Show the changes once the handler is done (once, however many there were)."""
        self._version += 1
        if not self._refresh_pending:
            try:
                self.widget.after_idle(self._refresh)
                self._refresh_pending = True
            except tk.TclError:
                pass  # the form has closed

    def _refresh(self):
        self._refresh_pending = False
        if self.widget.winfo_exists() and self._shown != self._showing():
            self._show()

    def line(self, x1, y1, x2, y2, *more, color="#000000", thickness=1):
        """A line from (x1, y1) to (x2, y2), on through any more points given (x3, y3, ...)."""
        self._surface().line((x1, y1, x2, y2, *more), fill=pictures.rgba(color), width=int(thickness),
                             joint="curve" if more else None)
        self._drawn()

    def rectangle(self, left, top, width, height, color="#000000", fill="", thickness=1):
        """A rectangle with its top left corner at (left, top)."""
        self._surface().rectangle((left, top, left + width - 1, top + height - 1), **_pixel_style(color, fill, thickness))
        self._drawn()

    def oval(self, left, top, width, height, color="#000000", fill="", thickness=1):
        """An oval (an ellipse) filling the rectangle with its top left corner at (left, top)."""
        self._surface().ellipse((left, top, left + width - 1, top + height - 1), **_pixel_style(color, fill, thickness))
        self._drawn()

    def circle(self, x, y, radius, color="#000000", fill="", thickness=1):
        """A circle centered on (x, y)."""
        self._surface().ellipse((x - radius, y - radius, x + radius, y + radius), **_pixel_style(color, fill, thickness))
        self._drawn()

    def arc(self, left, top, width, height, start, extent, style="pie", color="#000000", fill="", thickness=1):
        """Part of the oval filling the rectangle at (left, top): from start degrees (0 is
        three o'clock) through extent more, counter-clockwise (negative: clockwise). style
        "pie" draws a slice, "chord" a straight edge across, "arc" just the curve."""
        _shapes.check_choice("style", style, _shapes.ARC_STYLES)
        # Pillow goes clockwise, from its start to its end.
        begin = -(start + extent) if extent >= 0 else -start
        end = begin + abs(extent)
        box = (left, top, left + width - 1, top + height - 1)
        draw = self._surface()
        if style == "arc":
            draw.arc(box, begin, end, fill=pictures.rgba(color), width=int(thickness))
        else:
            method = draw.pieslice if style == "pie" else draw.chord
            method(box, begin, end, **_pixel_style(color, fill, thickness))
        self._drawn()

    def polygon(self, *points, color="#000000", fill="", thickness=1):
        """A closed shape through the points: polygon(10, 10, 60, 10, 35, 50) or
        polygon((10, 10), (60, 10), (35, 50))."""
        flat = _shapes.flatten(points)
        if len(flat) < 6:
            raise ValueError("a polygon needs at least 3 points")
        self._surface().polygon(flat, **_pixel_style(color, fill, thickness))
        self._drawn()

    def text(self, x, y, text, color="#000000", font=None, anchor="nw"):
        """Words at (x, y). anchor is which part of the text is at (x, y): "nw" (top left),
        "n", "ne", "w", "center", "e", "sw", "s" or "se". font is like "Arial, 12, bold"."""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        draw = self._surface()
        typeface = pictures.font(appearance.format_font(font) or None, self.widget.winfo_fpixels("1p"))
        draw.text((x, y), str(text), fill=pictures.rgba(color), font=typeface, anchor=_TEXT_ANCHORS[anchor])
        self._drawn()

    def paste(self, x, y, path, anchor="nw"):
        """Draw a picture from a file onto this one, with its anchor point at (x, y).
        (On a Canvas, picture() does this.)"""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        self._surface()
        other = pictures.open_for_drawing(self.folder / path)
        dx = 0 if anchor.endswith("w") else 1 if anchor.endswith("e") else 0.5
        dy = 0 if anchor.startswith("n") else 1 if anchor.startswith("s") else 0.5
        self._drawing.alpha_composite(other, (int(x - dx * other.width), int(y - dy * other.height)))
        self._drawn()

    def point(self, x, y, color="#000000"):
        """Set one pixel's color."""
        self._surface().point((x, y), fill=pictures.rgba(color))
        self._drawn()

    def pixel(self, x, y):
        """A pixel's color, as "#rrggbb" ("" if it's transparent)."""
        self._surface()
        width, height = self._drawing.size
        if not (0 <= x < width and 0 <= y < height):
            raise IndexError(f"({x}, {y}) is outside the picture, which is {width} x {height}")
        return pictures.to_hex(self._drawing.getpixel((int(x), int(y))))

    def clear(self, color="#ffffff"):
        """Fill the whole picture with one color ("" for transparent)."""
        self._surface()
        self._drawing.paste(pictures.rgba(color), (0, 0, *self._drawing.size))
        self._drawn()

    def save(self, path):
        """Save the picture to a file; its extension chooses the format (.png, .jpg, .bmp, .gif, ...).
        A path that isn't a full one is in the program's folder."""
        self._surface()
        pictures.save(self._drawing, self.folder / path)


def _pixel_style(color, fill, thickness):
    return {"outline": pictures.rgba(color) if color else None, "fill": pictures.rgba(fill) if fill else None,
            "width": int(thickness)}


@register
class Canvas(_BackColor, _Cursor, _Tooltip, _Anchored, Control):
    """A drawing surface. Its drawing methods (line, rectangle, oval, circle, arc, polygon,
    text, picture, point) each return a Shape, which stays until it's deleted: move it,
    recolor it, hide it, check what it overlaps. Mouse events say where the mouse is and
    which shape is there (None for the background):

        ball = self.Canvas1.circle(100, 80, 20, fill="#e04040")
        ball.move(5, 0)

        def Canvas1_click(self, x, y, shape):
            if shape is ball: ...

    Coordinates are pixels from its top left corner; colors are "#rrggbb", "" for none.
    click needs the mouse to stay put between press and release; for dragging, use
    mousedown, drag and mouseup."""

    type_name = "Canvas"
    default_size = (200, 150)
    events = (
        Event("click", ("x", "y", "shape")), Event("dblclick", ("x", "y", "shape")),
        Event("mousedown", ("x", "y", "shape")), Event("mouseup", ("x", "y", "shape")),
        Event("mousemove", ("x", "y")), Event("drag", ("x", "y")),
    )
    extra_props = {"border": False}
    default_backcolor = "#ffffff"
    inherits_backcolor = True

    # Each event: (Tk binding, whether the handler gets the shape).
    _events = {
        "click": ("<ButtonRelease-1>", True),
        "dblclick": ("<Double-Button-1>", True),
        "mousedown": ("<ButtonPress-1>", True),
        "mouseup": ("<ButtonRelease-1>", True),
        "mousemove": ("<Motion>", False),
        "drag": ("<B1-Motion>", False),
    }

    def create_widget(self, parent):
        self._items = {}  # Tk item -> Shape
        self._border = False
        self._pressed_at = None
        canvas = tk.Canvas(parent, highlightthickness=0, bd=0, background="#ffffff")
        canvas.bind("<ButtonPress-1>", lambda e: setattr(self, "_pressed_at", (e.x, e.y)), add="+")
        return canvas

    def _is_click(self, e):
        # A click is a press and release in about the same place; the end of a drag isn't one.
        if self._pressed_at is None or not _inside(e):
            return False
        x, y = self._pressed_at
        return abs(e.x - x) <= 4 and abs(e.y - y) <= 4

    @property
    def border(self):
        """Whether a thin line is drawn around it."""
        return self._border

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self.widget.configure(bd=int(self._border), relief="solid" if self._border else "flat")

    def bind_event(self, event, handler):
        if event not in self._events:
            return super().bind_event(event, handler)
        sequence, with_shape = self._events[event]

        def callback(e):
            if event == "click" and not self._is_click(e):
                return
            x, y = int(self.widget.canvasx(e.x)), int(self.widget.canvasy(e.y))
            handler(*(x, y, self.shape_at(x, y)) if with_shape else (x, y))

        self.widget.bind(sequence, callback, add="+")

    # ----- drawing -----

    def line(self, x1, y1, x2, y2, *more, color="#000000", thickness=1, dashed=False, arrow="", group="") -> Shape:
        """A line from (x1, y1) to (x2, y2), on through any more points given (x3, y3, ...).
        arrow puts an arrowhead at the "start", the "end" or "both"."""
        _shapes.check_choice("arrow", arrow, tuple(_shapes.ARROWS))
        return self._add("line", "line", (x1, y1, x2, y2, *more), group, fill=color, width=thickness,
                         dash=_shapes.DASH if dashed else "", arrow=_shapes.ARROWS[arrow], capstyle="round")

    def rectangle(self, left, top, width, height, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """A rectangle with its top left corner at (left, top)."""
        return self._add("rectangle", "rectangle", (left, top, left + width, top + height), group,
                         **_outlined(color, fill, thickness, dashed))

    def oval(self, left, top, width, height, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """An oval (an ellipse) filling the rectangle with its top left corner at (left, top)."""
        return self._add("oval", "oval", (left, top, left + width, top + height), group,
                         **_outlined(color, fill, thickness, dashed))

    def circle(self, x, y, radius, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """A circle centered on (x, y)."""
        return self._add("circle", "oval", (x - radius, y - radius, x + radius, y + radius), group,
                         **_outlined(color, fill, thickness, dashed))

    def arc(self, left, top, width, height, start, extent, style="pie", color="#000000", fill="",
            thickness=1, dashed=False, group="") -> Shape:
        """Part of the oval filling the rectangle at (left, top): from start degrees (0 is
        three o'clock) through extent more, counter-clockwise (negative: clockwise). style
        "pie" draws a slice, "chord" a straight edge across, "arc" just the curve."""
        _shapes.check_choice("style", style, _shapes.ARC_STYLES)
        return self._add("arc", "arc", (left, top, left + width, top + height), group, start=start,
                         extent=extent, style=style, **_outlined(color, fill if style != "arc" else "", thickness, dashed))

    def polygon(self, *points, color="#000000", fill="", thickness=1, dashed=False, group="") -> Shape:
        """A closed shape through the points: polygon(10, 10, 60, 10, 35, 50) or
        polygon((10, 10), (60, 10), (35, 50))."""
        flat = _shapes.flatten(points)
        if len(flat) < 6:
            raise ValueError("a polygon needs at least 3 points")
        return self._add("polygon", "polygon", flat, group, **_outlined(color, fill, thickness, dashed))

    def text(self, x, y, text, color="#000000", font=None, anchor="nw", group="") -> Shape:
        """Words at (x, y). anchor is which part of the text is at (x, y): "nw" (top left),
        "n", "ne", "w", "center", "e", "sw", "s" or "se". font is like "Arial, 12, bold"."""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        options = {}
        if font:
            options["font"] = appearance.tk_font(font, tkfont.nametofont("TkDefaultFont", root=self.widget).actual())
        return self._add("text", "text", (x, y), group, text=str(text), fill=color, anchor=anchor, **options)

    def picture(self, x, y, path, anchor="nw", group="") -> Shape:
        """A picture from a file (see the Image control), with its anchor point at (x, y)."""
        _shapes.check_choice("anchor", anchor, _shapes.ANCHORS)
        photo, _ = pictures.load(self.folder / path, master=self.widget)
        shape = self._add("picture", "image", (x, y), group, image=photo, anchor=anchor)
        shape._photo = photo
        return shape

    def point(self, x, y, color="#000000", group="") -> Shape:
        """A single pixel: a tiny shape, fine by the hundred. For many thousands, draw on an Image instead."""
        return self._add("point", "line", (x, y, x + 1, y), group, fill=color)

    def _add(self, kind, tk_type, coords, group, **options) -> Shape:
        try:
            item = getattr(self.widget, f"create_{tk_type}")(*coords, **options)
        except tk.TclError as e:
            raise ValueError(str(e)) from None
        shape = self._items[item] = Shape(self, kind, item, group)
        return shape

    # ----- finding and removing shapes -----

    def shapes(self, group=None) -> list[Shape]:
        """Its shapes, from the back to the front; only those in group if given."""
        items = self.widget.find_withtag(_shapes.group_tag(group)) if group else self.widget.find_all()
        return [self._items[i] for i in items if i in self._items]

    def shape_at(self, x, y) -> Shape | None:
        """The front-most visible shape at (x, y), or None."""
        for item in reversed(self.widget.find_overlapping(x, y, x, y)):
            if item in self._items and self.widget.itemcget(item, "state") != tk.HIDDEN:
                return self._items[item]
        return None

    def clear(self, group=None):
        """Delete every shape, or every shape in group."""
        for shape in self.shapes(group):
            self._forget(shape)

    def _forget(self, shape):
        if self._items.pop(shape._item, None) is not None:
            self.widget.delete(shape._item)


def _outlined(color, fill, thickness, dashed):
    return {"outline": color or "", "fill": fill or "", "width": thickness, "dash": _shapes.DASH if dashed else ""}


@register
class Grid(_BackColor, _Cursor, _Tooltip, _Anchored, Control):
    """Rows and columns of controls. columns and rows are lists like "auto, *, 2*, 120": auto
    fits what's in it, * and 2*, 3*... share the space left over by weight, and a number is
    fixed pixels. Each control in it has a row and column (counting from 0), may span
    several, and its anchor names the edges of its cell it sticks to (all four fill it).
    Its width and height are the size it asks for: what auto rows and columns fit."""

    inner: tk.Canvas
    type_name = "Grid"
    default_size = (240, 160)
    is_container = True
    inherits_backcolor = True
    events = _MOUSE_EVENTS
    extra_props = {"columns": "*, *", "rows": "*, *", "gap": 4, "padding": 4, "border": False}

    def create_widget(self, parent):
        self._columns, self._rows = "*, *", "*, *"
        self._gap = self._padding = 4
        self._border = False
        self.column_lines = self.row_lines = None  # where its columns and rows are, once arranged
        # A canvas, so the designer can draw the cells; the controls are placed on it.
        self.inner = tk.Canvas(parent, highlightthickness=0, bd=0)
        return self.inner

    def _tracks(name, doc):
        def get(self):
            return getattr(self, "_" + name)

        def set(self, value):
            setattr(self, "_" + name, layout.normalize_tracks(value))
            self.arrange()

        return property(get, set, doc=doc)

    columns = _tracks("columns", """Its columns' widths, like "auto, *, 2*, 120": auto fits what's in it,
        * and 2*, 3*... share the space left over by weight, and a number is fixed pixels.""")
    rows = _tracks("rows", """Its rows' heights, like "auto, auto, *": as for columns.""")
    del _tracks

    @property
    def gap(self):
        """Pixels between its rows and columns."""
        return self._gap

    @gap.setter
    def gap(self, value):
        self._gap = max(0, int(value))
        self.arrange()

    @property
    def padding(self):
        """Pixels between its edge and its cells."""
        return self._padding

    @padding.setter
    def padding(self, value):
        self._padding = max(0, int(value))
        self.arrange()

    @property
    def border(self):
        """Whether a thin line is drawn around it."""
        return self._border

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self.widget.configure(bd=int(self._border), relief="solid" if self._border else "flat")
        self.arrange()

    def _place(self):
        super()._place()
        self.arrange()

    def _paint(self):
        super()._paint()
        if self._ready:
            repaint_inside(self.inner)

    def children(self):
        """The controls in it."""
        found = []
        for widget in self.inner.winfo_children():
            ref = _controls.get(widget)
            control = ref() if ref else None
            if control is not None:
                found.append(control)
        return found

    def arrange(self):
        """Put the controls in it in their cells (it does this itself when anything changes)."""
        if not getattr(self, "_ready", False):
            return
        _, _, width, height = self._rect()
        edge = int(self._border)
        children = [c for c in self.children() if c.visible or c.design]
        cells = [(c.row, c.column, c.rowspan, c.columnspan, c.anchor, (c._width, c._height)) for c in children]
        rects, self.column_lines, self.row_lines = layout.arrange_grid(
            self._columns, self._rows, width - 2 * edge, height - 2 * edge, cells, self._gap, self._padding)
        for control, rect in zip(children, rects):
            control._grid_rect = rect
            control._place()
        if self.design:
            self._draw_cells(width - 2 * edge, height - 2 * edge)

    def _draw_cells(self, width, height):
        """The designer shows where the cells are."""
        self.inner.delete("cells")
        for lines, across in ((self.column_lines, True), (self.row_lines, False)):
            for start, size in zip(lines.starts, lines.sizes):
                for edge in (start, start + size):
                    points = (edge, 0, edge, height) if across else (0, edge, width, edge)
                    self.inner.create_line(*points, fill="#9a9a9a", dash=(2, 3), tags="cells")

    def cell_at(self, x, y):
        """The (row, column) at a point inside it (the nearest cell, outside its cells)."""
        if self.row_lines is None:
            return 0, 0
        return self.row_lines.index_at(y), self.column_lines.index_at(x)

    def cell_box(self, row, column, rowspan=1, columnspan=1):
        """(left, top, width, height) of a cell, or of several spanned, inside it."""
        x, width = layout._span(self.column_lines, column, columnspan, self._gap)
        y, height = layout._span(self.row_lines, row, rowspan, self._gap)
        return x, y, width, height


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
