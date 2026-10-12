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

import copy
import inspect
import sys
import tkinter as tk
from pathlib import Path

from readymade import appearance, events, formfile, forms, keys, menus, names, pictures
from readymade.controls import (GRID_CELL, REGISTRY, ControlArray, Event, OptionButton, TabIndex, TabStop, WidgetText,
                                control_of, create, focus_widget, inner_for, option_group, repaint_inside,
                                show_as_default, tab_numbers)

FORM = "Form"
FORM_EVENTS = (
    Event("load"),
    Event("unload"),
    Event("resize"),
    Event("click"),
    Event("dblclick"),
    Event("keydown", ("key",)),
    Event("keyup", ("key",)),
)

_app: tk.Tk | None = None  # the hidden root window all forms belong to
_folder: Path | None = None  # set by readymade.run; otherwise worked out in app_path()


def loaded_forms():
    """Every form that's loaded (showing, or hidden but not closed)."""
    return set(_loaded)


def track_task(form, task):
    """An async event handler's task: canceled if the form closes before it's done."""
    form._tasks.add(task)
    task.add_done_callback(form._tasks.discard)


def app_path(*parts):
    """The program's folder, or a file in it: app_path("data", "prices.csv"). Like VB's
    App.Path, it works however the program runs: from the IDE, as `python Form1.py`, or
    made into a program with Make EXE (which bundles files listed in [tool.readymade]
    include). In a one-file program the bundled files are temporary copies: read them,
    but save your own files elsewhere, like the user's documents folder."""
    if _folder is not None:
        base = _folder
    elif getattr(sys, "frozen", False):
        base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    else:
        base = Path(sys.argv[0]).resolve().parent if sys.argv and sys.argv[0] else Path.cwd()
    return base.joinpath(*parts)


def set_app_path(folder):
    """Make app_path() the given folder (readymade.run uses the project's folder)."""
    global _folder
    _folder = Path(folder)
_loaded: set[Form] = set()


_icon = None  # the program's window icon (Tk forgets images nothing refers to)


def set_app_icon(path):
    """Use a picture as the icon of every window of the program, in its title bar and the
    taskbar: a PNG or GIF (with Pillow, also .ico and other formats). The IDE, `python
    Form1.py` and Make EXE do this with the project's icon (Project > Program Icon)."""
    global _icon
    try:
        photo, _ = pictures.load(path, master=app_root())
    except (OSError, tk.TclError) as e:
        print(f"Can't use {path} as the program's icon ({e})", file=sys.stderr)
        return False
    app_root().iconphoto(True, photo)  # True: every window, including those not made yet
    _icon = photo
    return True


def _project_icon(folder):
    """The project icon of the project in folder, as a full path, or None."""
    folder = Path(folder)
    if not (folder / "pyproject.toml").exists():
        return None
    from readymade.project import Project, ProjectError

    try:
        icon = Project(folder).setting("icon")
    except ProjectError:  # e.g. Python 3.10, which can't read pyproject.toml
        return None
    return folder / icon if icon else None


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
        events.collect_garbage_on(app_root())  # Tk objects must only be freed on this thread
        app_root().mainloop()
    events.shutdown()  # stop async handlers that are still running
    if _app is not None:
        try:
            _app.destroy()
        except tk.TclError:
            pass
        _app = None


class Form:
    """A window of the program, designed in the IDE. Its controls are attributes
    (self.Label1), and so are its menu items (self.mnuOpen). forms.Name is the
    shared instance of each form; show() displays it, close() closes it."""

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
        icon = _project_icon(Path(path).parent if path else Path(inspect.getfile(cls)).parent)
        if icon:
            set_app_icon(icon)
        form = cls(path)
        forms.register(cls.__name__, form)
        form.show()
        main_loop()

    def load(self):
        """Create the (hidden) window and controls, and raise Form_load. show() does this when needed."""
        if self.loaded:
            return
        design = formfile.load(self.path)
        for name, number in (tab_numbers(design.controls) or {}).items():  # (a form from before Labels had one)
            design.control(name)["tabindex"] = number
        self._handlers = {}  # "Form_load" etc. -> events.Handler
        self._tasks = set()  # running async handlers, canceled when the form closes
        self.root = tk.Toplevel(self._master or app_root())
        self.root.withdraw()
        self.root.title(design.text)
        self.root.geometry(f"{design.width}x{design.height}")
        self._size = (design.width, design.height)
        self._usual_background = self.root.cget("background")
        self.backcolor = design.backcolor  # before the controls, which may show it
        self.cursor = design.cursor
        self._resizable = design.resizable
        self._limits = {key: getattr(design, key) for key in SIZE_LIMITS}
        self._apply_limits()
        self.controls = {}
        self._containers = {}  # control name -> the Frame (or Grid) it's in, or None
        self._designed_size = self._configured_size = (design.width, design.height)
        self._on_form = []  # the controls straight on the form (the rest follow their Frame)
        self._specs = {}  # control name -> its .form spec (a control array's add() copies one)
        self._added = set()  # the names of controls made while the program runs (add_control, add())
        self._listeners = {}  # the form's own events -> [(handler as given, its events.Handler)], from on()
        self._key_tag = None  # see _listen_for_keys
        for spec in design.controls:
            check_name(spec["name"], self.controls)
            self._make(spec)
        for control in self.controls.values():  # (made before what's in them, so arranged now)
            if control.arranges_inside:
                control.arrange()
        self.menus = {}
        if design.menu:
            menubar = tk.Menu(self.root, tearoff=False)
            menus.build(menubar, design.menu, self._menu_entry)
            self.root["menu"] = menubar
        self._default_button = self._cancel_button = None
        self.default_button = design.default_button
        self.cancel_button = design.cancel_button
        self._design_order = list(self.controls)
        for sequence, action in (("<Tab>", lambda e: self._tab(1)), ("<<NextControl>>", lambda e: self._tab(1)),
                                 ("<Shift-Tab>", lambda e: self._tab(-1)), ("<<PrevWindow>>", lambda e: self._tab(-1)),
                                 ("<Return>", self._enter), ("<KP_Enter>", self._enter), ("<Escape>", self._escape)):
            self.root.bind(sequence, action)  # the form's own bindings see keys pressed in any of its controls
        self.root.bind(_access_sequence(self.root), self._access_key)
        for sequence, step in (("<Up>", -1), ("<Left>", -1), ("<Down>", 1), ("<Right>", 1)):
            self.root.bind(sequence, lambda e, s=step: self._arrow(s), add="+")
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
        order = self._tab_order()
        if order and self.root.focus_get() in (None, self.root):
            self._focus(order[0])  # as in VB, the first control in the tab order starts with the focus
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
        """The form's title, shown in its title bar."""
        return self.root.title()

    @text.setter
    def text(self, value):
        self.root.title(str(value))

    @property
    def width(self):
        """The form's width, in pixels (inside its border)."""
        return self._size[0]

    @width.setter
    def width(self, value):
        self._size = (int(value), self._size[1])
        self.root.geometry(f"{self._size[0]}x{self._size[1]}")

    @property
    def height(self):
        """The form's height, in pixels (inside its border, below any menu)."""
        return self._size[1]

    @height.setter
    def height(self, value):
        self._size = (self._size[0], int(value))
        self.root.geometry(f"{self._size[0]}x{self._size[1]}")

    @property
    def backcolor(self):
        """The form's background color, as "#rrggbb"; "" for the usual color. Labels, check
        boxes, option buttons, frames and pictures with no backcolor of their own show it too."""
        return self._backcolor

    @backcolor.setter
    def backcolor(self, value):
        self._backcolor = appearance.check_color(value)
        self.root["background"] = self._backcolor or self._usual_background
        repaint_inside(self.root)

    @property
    def cursor(self):
        """The mouse pointer over the form: "default", "arrow", "hand", "text", "cross", "wait",
        "move", "help", "resize_ew" or "resize_ns". Controls with their own cursor keep it."""
        return self._cursor

    @cursor.setter
    def cursor(self, value):
        self._cursor = appearance.check_choice("cursor", value, tuple(appearance.CURSORS))
        self.root["cursor"] = appearance.CURSORS[self._cursor]

    @property
    def resizable(self):
        """Whether the user can change the form's size. False: it stays the size it was
        designed (or code sets), as a dialog does."""
        return self._resizable

    @resizable.setter
    def resizable(self, value):
        self._resizable = bool(value)
        self._apply_limits()

    def _limit(key, doc):
        def get(self):
            return self._limits[key]

        def set(self, value):
            value = int(value)
            if value < 0:
                raise ValueError(f"{key} can't be negative (0: no limit)")
            limits = {**self._limits, key: value}
            check_limits(limits)
            self._limits = limits
            self._apply_limits()

        return property(get, set, doc=doc)

    minwidth = _limit("minwidth", "The narrowest the user can make the form, in pixels; 0 for no limit.")
    minheight = _limit("minheight", "The shortest the user can make the form, in pixels; 0 for no limit.")
    maxwidth = _limit("maxwidth", "The widest the user can make the form, in pixels; 0 for no limit.")
    maxheight = _limit("maxheight", "The tallest the user can make the form, in pixels; 0 for no limit.")
    del _limit

    def _apply_limits(self):
        limits, root = self._limits, self.root
        root.resizable(self._resizable, self._resizable)
        root.minsize(limits["minwidth"] or 1, limits["minheight"] or 1)
        # (No limit: the screen's size, Tk's own maximum.)
        root.maxsize(limits["maxwidth"] or root.winfo_screenwidth(), limits["maxheight"] or root.winfo_screenheight())

    @property
    def default_button(self):
        """The Button that Enter presses, as if clicked, or None. (Enter in a multi-line text
        box starts a new line instead, and Enter on a button presses that button.) Set it to
        a Button or a Button's name."""
        return self._default_button

    @default_button.setter
    def default_button(self, button):
        self._default_button = self._button(button, "default_button")
        for control in self.controls.values():
            if control.can_be_default:  # the default button shows a heavier border
                show_as_default(control, control is self._default_button)

    @property
    def cancel_button(self):
        """The Button that Esc presses, as if clicked, or None. Set it to a Button or a Button's name."""
        return self._cancel_button

    @cancel_button.setter
    def cancel_button(self, button):
        self._cancel_button = self._button(button, "cancel_button")

    def _button(self, button, prop):
        if button is None or button == "":
            return None
        if isinstance(button, str):
            button = self.controls.get(button)
        if button is None or not button.can_be_default:
            raise ValueError(f"{prop} must be one of the form's Buttons (or None)")
        return button

    # ----- the keyboard: Tab order, Enter and Esc -----

    def _tab_order(self):
        """The controls Tab moves through, in order: by tabindex, then as designed. Those with
        tabstop False are passed by, and of a group of OptionButtons only the chosen one stops
        (or with none chosen, the first): the arrow keys move between them, as in Windows."""
        stops, groups = [], set()
        for control in self._tab_sequence():
            if not isinstance(control, TabStop) or not control.tabstop:
                continue
            if isinstance(control, OptionButton):
                group = self._option_group(control)
                chosen = next((c for c in group if c.value), group[0])
                if control is not chosen or id(option_group(control)) in groups:
                    continue
                groups.add(id(option_group(control)))
            stops.append(control)
        return stops

    def _option_group(self, option):
        """The OptionButtons in option's group (the same Frame, or the form), in Tab order, that
        the keyboard can reach."""
        return [c for c in self._tab_sequence() if isinstance(c, OptionButton) and option_group(c) is option_group(option)
                and (c is option or (c.enabled and c.visible and c.tabstop))]

    def _arrow(self, step):
        """Up/Left and Down/Right in a group of OptionButtons choose the next one, as in Windows."""
        option = control_of(self._focus_get())
        if not isinstance(option, OptionButton):
            return None
        group = self._option_group(option)
        target = group[(group.index(option) + step) % len(group)]
        if target is not option:
            self._focus(target)
            target.widget.invoke()  # chosen, and its click event
        return "break"

    def _tab_sequence(self):
        """Every control with a place in the Tab order, Labels and Frames too, in that order."""
        placed = [c for c in self.controls.values() if isinstance(c, TabIndex)]
        return sorted(placed, key=lambda c: (c.tabindex, self._design_order.index(c.name) if c.name in self._design_order else 0))

    def _tab(self, step):
        reachable = [c for c in self._tab_order() if c.enabled and c.visible and c.widget.winfo_viewable()]
        if not reachable:
            return None  # Tk's own Tab order
        current = control_of(self._focus_get())
        if current in reachable:
            target = reachable[(reachable.index(current) + step) % len(reachable)]
        else:
            target = reachable[0 if step > 0 else -1]
        self._focus(target)
        return "break"

    @staticmethod
    def _focus(control):
        widget = focus_widget(control)
        widget.tk.call("tk::TabToWindow", widget)  # as Tab does: focus, and select a text box's text

    def _focus_get(self):
        try:
            return self.root.focus_get()
        except KeyError:  # a widget tkinter doesn't know, like a drop-down list's
            return None

    def _enter(self, e):
        focus = self._focus_get()
        if isinstance(focus, tk.Text):
            return None  # a new line in a multi-line text box
        focused = control_of(focus)
        return self._press(focused if focused is not None and focused.can_be_default else self._default_button)

    def _escape(self, e):
        return self._press(self._cancel_button)

    def _access_key(self, e):
        """Alt+letter (Ctrl+Option+letter on a Mac): the control whose text has &letter. A
        Button is clicked, a CheckBox or OptionButton chosen, and a Label or Frame goes to the
        next control (as in VB). Other keys go on to the menus."""
        letter = _access_letter(e)
        if not letter:
            return None
        for name in self._design_order:
            control = self.controls.get(name)
            if (isinstance(control, WidgetText) and control.access_key == letter and control.enabled
                    and control.visible and control.widget.winfo_viewable()):
                return self._use_access_key(control)
        return None

    def _use_access_key(self, control):
        if control.access_key_action == "press":
            return self._press(control)
        if control.access_key_action == "choose":
            self._focus(control)
            control.widget.invoke()
            return "break"
        target = self._after(control)
        if target is not None:
            self._focus(target)
        return "break"

    def _after(self, control):
        """Where a Label's or Frame's access key goes: a Frame's first control, or the next
        control after a Label in the Tab order that Tab stops at (as in VB)."""
        def reachable(c):
            return isinstance(c, TabStop) and c.enabled and c.visible and c.widget.winfo_viewable()

        def inside(name, frame):
            while name is not None:
                name = self._containers.get(name)
                if name == frame:
                    return True
            return False

        if control.is_container:
            found = [c for c in self._tab_order() if inside(c.name, control.name) and reachable(c)]
            return found[0] if found else None
        sequence = self._tab_sequence()
        after = sequence[sequence.index(control) + 1:] if control in sequence else []
        return next((c for c in after if reachable(c)), None)

    @staticmethod
    def _press(button):
        if button is None or not (button.enabled and button.visible):
            return None
        button.widget.invoke()
        return "break"

    def _parent_widget(self, spec):
        container = spec.get("container")
        if container is None:
            return self.root
        parent = self.controls.get(container)
        if parent is None or not parent.is_container:
            raise ValueError(f"{spec['name']!r} is in {container!r}, which isn't a container")
        return inner_for(parent, spec)

    def _menu_entry(self, item, menu, index, variable):
        check_name(item["name"], {**self.controls, **self.menus})
        entry = menus.MenuItem(item, menu, index, variable)
        self.menus[entry.name] = entry
        setattr(self, entry.name, entry)
        if item.get("shortcut"):
            # The shortcut works anywhere in the form, and only while the item is enabled.
            menus.bind_shortcut(self.root, item["shortcut"], lambda e: (menu.invoke(index), "break")[1])
        if variable is None:
            return None  # a submenu
        func = getattr(self, f"{entry.name}_click", None)
        return entry.click(events.Handler(self, func, events.policy_for(func, "click")) if callable(func) else None)

    def _fire(self, event, *args):
        """Run the form's handlers for one of its own events: Form_event, then those from on().
        The first answer that isn't None counts (Form_unload's True keeps the form open)."""
        name = f"{FORM}_{event}"
        if name not in self._handlers:
            func = getattr(self, name, None)
            self._handlers[name] = events.Handler(self, func, events.policy_for(func, event)) if callable(func) else None
        handler = self._handlers[name]
        result = handler(*args) if handler else None
        for _, more in list(self._listeners.get(event, ())):
            value = more(*args)
            result = value if result is None else result
        return result

    def on(self, event, handler=None):
        """Run handler too when one of the form's own events happens: self.on("resize", ...).

        It runs after any Form_event method, with the event's own arguments (keydown: key); a
        plain function wanting one more is given the form first. Returns handler, so it works
        as a decorator too: @self.on("resize")."""
        if handler is None:
            return lambda func: self.on(event, func)
        kind = next((e for e in FORM_EVENTS if e.name == event), None)
        if kind is None:
            raise ValueError(f"a form has no {event!r} event; its events: {', '.join(e.name for e in FORM_EVENTS)}")
        call = events.call_for(handler, self, len(kind.params))
        self._listeners.setdefault(event, []).append((handler, events.Handler(self, call, events.policy_for(handler, event))))
        if event in ("keydown", "keyup"):
            self._listen_for_keys()
        return handler

    def off(self, event, handler):
        """Stop running a handler that on() attached to one of the form's events. True if it was."""
        attached = self._listeners.get(event, [])
        kept = [entry for entry in attached if entry[0] != handler]
        removed = len(kept) < len(attached)
        attached[:] = kept
        return removed

    def _make(self, spec):
        """Create a control from its .form spec: self.Name, or in a control array self.Name[index]."""
        control = create(self._parent_widget(spec), spec, folder=self.path.parent)
        control.form = self
        if self._key_tag:  # (keydown and keyup see every widget's keys)
            widgets = [control.widget]
            while widgets:
                widget = widgets.pop()
                widget.bindtags((self._key_tag, *widget.bindtags()))
                widgets.extend(widget.winfo_children())
        self.controls[control.name] = control
        self._specs[control.name] = spec
        base, index = names.split_element(control.name)
        if index is None:
            setattr(self, base, control)
        else:
            array = self.__dict__.get(base)
            if not isinstance(array, ControlArray):
                array = ControlArray(base, self)
                setattr(self, base, array)
            array._items[index] = control
            control.index = index
        if spec.get("container") is None:
            self._on_form.append(control)
        self._containers[control.name] = spec.get("container")
        return control

    def _connect_events(self):
        for control in self.controls.values():
            self._connect(control)
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        # Bindings on the root also see events from every control, so filter to the form itself.
        self.root.bind("<Configure>", self._on_configure, add="+")
        self.root.bind("<ButtonRelease-1>", lambda e: self._on_form_mouse(e, "click"), add="+")
        self.root.bind("<Double-Button-1>", lambda e: self._on_form_mouse(e, "dblclick"), add="+")
        self.root.bind("<Destroy>", self._on_destroy, add="+")
        if callable(getattr(self, f"{FORM}_keydown", None)) or callable(getattr(self, f"{FORM}_keyup", None)):
            self._listen_for_keys()

    def _listen_for_keys(self):
        """keydown and keyup: from here on, every key press and release in the form."""
        if self._key_tag:
            return
        self._held = set()  # keys down, by key_name
        self._releasing = {}  # key -> after id: a release that may be the key repeating (on X11)
        # A bind tag of its own, first on every widget: the form's other key bindings (Tab,
        # Enter, arrows) would otherwise take those keys, as Tk runs one binding per tag.
        tag = self._key_tag = f"readymade-keys-{id(self)}"
        self.root.bind_class(tag, "<KeyPress>", self._key_down)
        self.root.bind_class(tag, "<KeyRelease>", self._key_up)
        widgets = [self.root]
        while widgets:
            widget = widgets.pop()
            widget.bindtags((tag, *widget.bindtags()))
            widgets.extend(widget.winfo_children())
        self.root.bind("<FocusOut>", lambda e: self.root.after_idle(self._focus_left), add="+")

    # ----- keydown and keyup: once per press and release, for games -----

    def _key_down(self, e):
        key = keys.key_name(e.keysym)
        job = self._releasing.pop(key, None)
        if job is not None:  # X11 repeats a held key as release-press pairs: it never went up
            self.root.after_cancel(job)
            return
        if key in self._held:
            return  # Windows and macOS repeat a held key as more presses
        self._held.add(key)
        self._fire("keydown", key)

    def _key_up(self, e):
        key = keys.key_name(e.keysym)
        if key in self._held and key not in self._releasing:
            self._releasing[key] = self.root.after(20, lambda: self._released(key))

    def _released(self, key):
        self._releasing.pop(key, None)
        if key in self._held:
            self._held.discard(key)
            self._fire("keyup", key)

    def _focus_left(self):
        """The window lost the keyboard (another window was clicked): its keys count as let go,
        as their releases will go elsewhere."""
        try:
            still_here = self.root.focus_get() is not None
        except (KeyError, tk.TclError):
            still_here = False
        if not still_here and self.loaded:
            for key in sorted(self._held):
                job = self._releasing.pop(key, None)
                if job is not None:
                    self.root.after_cancel(job)
                self._released(key)

    def _connect(self, control):
        """Attach control's handlers: Name_event, which for a control array's elements is told
        which one, by index, before the event's own arguments; then any its array's on() has."""
        base, index = names.split_element(control.name)
        first = () if index is None else (index,)
        for event in control.events:
            func = getattr(self, f"{base}_{event.name}", None)
            if callable(func):
                control._listen(event.name, func, first)
        array = self.__dict__.get(base) if index is not None else None
        for event, func in array._listeners if isinstance(array, ControlArray) else ():
            control._listen(event, func, first)

    # ----- controls made while the program runs -----

    def add_control(self, type_name, name, container=None, **props):
        """Make a control while the program runs, as the designer would, and return it.

            box = self.add_control("TextBox", "Search", left=8, top=40, width=200, text="")

        props are its properties (any of the Properties panel's; the rest as designed). name
        is how code knows it: self.Search, and a Search_change method handles its change
        event, as for a drawn control (or attach handlers with box.on("change", ...)). A name
        like "Digit[3]" puts it in the Digit control array (starting it, if need be).
        container is a Frame, TabStrip or Grid (or its name) to put it in, with page= for a
        TabStrip's page. It goes last in the Tab order."""
        if type_name not in REGISTRY:
            raise ValueError(f"there's no {type_name!r} control; the controls: {', '.join(REGISTRY)}")
        check_name(name, {**self.controls, **self.menus})
        base, index = names.split_element(name)
        array = self.__dict__.get(base)
        if isinstance(array, ControlArray) and len(array) and array[array.indexes[0]].type_name != type_name:
            raise ValueError(f"{base} is a control array of {array[array.indexes[0]].type_name}s, not {type_name}s")
        if container is not None:
            container = getattr(container, "name", container)
            if container not in self.controls or not self.controls[container].is_container:
                raise ValueError(f"{container!r} isn't a container on this form (a Frame, TabStrip or Grid)")
        kind = REGISTRY[type_name]
        known = set(kind.prop_defaults()) | set(GRID_CELL) | {"page"}
        unknown = sorted(set(props) - known)
        if unknown:
            raise ValueError(f"a {type_name} has no {', '.join(unknown)}; its properties: {', '.join(kind.prop_defaults())}")
        spec = kind.new_spec(name, props.pop("left", 0), props.pop("top", 0), container=container)
        spec.update(props)
        if "tabindex" in spec and "tabindex" not in props:  # (last in the Tab order)
            spec["tabindex"] = max((getattr(c, "tabindex", 0) for c in self.controls.values()), default=-1) + 1
        return self._settle(self._make(spec))

    def remove_control(self, control):
        """Take away a control that add_control() (or a control array's add()) made: the
        control, or its name. Those drawn in the designer stay (hide them with visible)."""
        name = getattr(control, "name", control)
        control = self.controls.get(name)
        if control is None:
            raise ValueError(f"there's no control named {name!r}")
        if name not in self._added:
            raise ValueError(f"{name} was made in the designer, so it can't be removed (set its visible to False "
                             "to hide it)")
        if any(container == name for container in self._containers.values()):
            raise ValueError(f"{name} has controls in it: remove those first")
        control.widget.destroy()
        base, index = names.split_element(name)
        if index is None:
            self.__dict__.pop(base, None)
        else:
            self.__dict__[base]._items.pop(index, None)
        for collection in (self.controls, self._specs, self._containers):
            collection.pop(name, None)
        self._added.discard(name)
        self._design_order.remove(name)
        if control in self._on_form:
            self._on_form.remove(control)

    def _add_element(self, array, index):
        """ControlArray.add(): a copy of the array's lowest-numbered control, hidden."""
        spec = copy.deepcopy(self._specs[array[array.indexes[0]].name])
        spec["name"] = names.element_name(array.name, index)
        spec["visible"] = False
        if "tabindex" in spec:  # (last in the Tab order)
            spec["tabindex"] = max(getattr(c, "tabindex", 0) for c in self.controls.values()) + 1
        return self._settle(self._make(spec))

    def _settle(self, control):
        """A control made while the program runs: in its place (its container's grown, say),
        and its handlers attached."""
        self._added.add(control.name)
        self._design_order.append(control.name)
        container = self.controls.get(self._containers[control.name])
        if container is None:
            grown = (self._size[0] - self._designed_size[0], self._size[1] - self._designed_size[1])
            control.follow_container(*grown)
        elif container.arranges_inside:
            container.arrange()
        else:
            container._place()  # (it puts what's in it where its size says)
        self._connect(control)
        return control

    def _on_configure(self, e):
        # (Compared with the last size seen here: the width and height setters change _size first.)
        if e.widget is self.root and (e.width, e.height) != self._configured_size and e.width > 1:
            self._size = self._configured_size = (e.width, e.height)
            across, down = e.width - self._designed_size[0], e.height - self._designed_size[1]
            for control in self._on_form:  # anchors: before Form_resize, so it sees where they went
                control.follow_container(across, down)
            self._fire("resize")

    def _on_form_mouse(self, e, event):
        if e.widget is self.root:
            self._fire(event)

    def _on_destroy(self, e):
        if e.widget is not self.root:
            return
        self.loaded = False
        _loaded.discard(self)
        for task in list(self._tasks):
            task.cancel()  # its busy async handlers stop quietly
        if not _loaded and _app is not None:
            _app.quit()  # ends main_loop()


SIZE_LIMITS = ("minwidth", "minheight", "maxwidth", "maxheight")


def check_limits(limits):
    """Raise ValueError unless each min is at most its max (0 is no limit)."""
    for low, high in (("minwidth", "maxwidth"), ("minheight", "maxheight")):
        if limits[low] and limits[high] and limits[low] > limits[high]:
            raise ValueError(f"{low} ({limits[low]}) can't be more than {high} ({limits[high]})")


_RESERVED = {name for name in dir(Form)} | {"root", "controls", "menus", "path", "loaded", FORM}


def check_name(name, existing=()):
    """Raise ValueError unless name can be used for a new control: a Python name, or a
    control array's element, "Digit[3]" (as long as Digit isn't a control by itself)."""
    names.check_control_name(name)
    base, index = names.split_element(name)
    if base in _RESERVED:
        raise ValueError(f"{base!r} is reserved by the Form class")
    if name in existing:
        raise ValueError(f"There is already a control named {name!r}")
    others = {names.split_element(n) for n in existing}
    if index is None and any(b == base and i is not None for b, i in others):
        raise ValueError(f"{base!r} is already the name of a control array")
    if index is not None and (base, None) in others:
        raise ValueError(f"There is already a control named {base!r} (not in a control array)")


def _access_sequence(widget):
    """The key events access keys come as: Alt+key, or on a Mac Control+Option+key (Option
    alone types characters, like é, and ⌘ is for the menus)."""
    if widget.tk.call("tk", "windowingsystem") == "aqua":
        return "<Control-Option-KeyPress>"
    return "<Alt-KeyPress>"


def _access_letter(e):
    """The letter or digit of an access key event, as a capital; "" for other keys."""
    if sys.platform == "darwin":  # Option changes the character, so go by the key's place
        key = menus.mac_key(e.keycode)
        return key if key.isalnum() else ""
    key = e.keysym if len(e.keysym) == 1 else ""
    return key.upper() if key.isalnum() else ""
