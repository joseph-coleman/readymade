"""Help topics for F1: controls, forms and menu items (from readymade's own docstrings
and event lists), and a short overview of the IDE. Help on code comes from Jedi;
see assist.py."""

from __future__ import annotations

import inspect
import sys
from dataclasses import dataclass

from readymade import menus
from readymade.controls import REGISTRY
from readymade.form import FORM_EVENTS, Form
from readymade.menus import MenuItem


@dataclass(frozen=True)
class Topic:
    title: str
    subtitle: str = ""
    text: str = ""
    docs_url: str = ""  # the Python documentation's page about it, if there is one


# What makes each event's handler run.
EVENTS = {
    "click": "it's clicked (for a list or check box: its choice changes)",
    "dblclick": "it's double-clicked",
    "mousedown": "a mouse button is pressed over it; x and y say where",
    "mouseup": "the mouse button is released; x and y say where",
    "mousemove": "the mouse moves over it; x and y say where",
    "drag": "the mouse moves with its button held down; x and y say where",
    "gotfocus": "it gets the keyboard focus",
    "lostfocus": "it loses the keyboard focus",
    "keypress": "a key is pressed while it has the focus; key is the character typed, or a name like \"Enter\", \"Esc\" or \"Ctrl+S\"",
    "change": "its contents change",
    "timer": "interval milliseconds have passed",
    "load": "the form is loaded, before it's first shown",
    "unload": "the form is closing; return True to keep it open",
    "resize": "the form changes size",
}


def _doc(thing):
    return inspect.getdoc(thing) or ""


def _first_line(thing):
    return _doc(thing).split("\n\n")[0].replace("\n", " ")


def _members(cls, names):
    width = max(len(n) for n in names)
    return "\n".join(f"  {name:<{width}}  {_first_line(getattr(cls, name, None))}" for name in names)


def _events(owner, events):
    return "\n".join(
        f"  {owner}_{e.name}({', '.join(('self', *e.params))})\n      runs when {EVENTS.get(e.name, e.name)}"
        for e in events
    )


def _methods(cls):
    return [name for name, value in inspect.getmembers(cls)
            if not name.startswith("_") and inspect.isfunction(value) and _doc(value)
            and name not in ("create_widget", "widgets", "design_widgets", "bind_event", "connect",
                             "prop_defaults", "new_spec", "run", "load")]


def control(type_name, name=None):
    """Help on a control type; with name, about that control (its handlers' names use it)."""
    cls = REGISTRY[type_name]
    title = name or type_name
    name = name or f"{type_name}1"
    designable = list(cls.prop_defaults())
    parts = [_doc(cls), "Properties\n" + _members(cls, designable)]
    in_code = [n for n, v in inspect.getmembers(cls) if isinstance(v, property) and not n.startswith("_")
               and n not in designable and _doc(v)]
    if in_code:
        parts.append("More properties, for code\n" + _members(cls, in_code))
    methods = _methods(cls)
    if methods:
        parts.append("Methods\n" + _members(cls, methods))
    parts.append(f"Events (double-click {name} in the designer to write one)\n" + _events(name, cls.events))
    return Topic(title, f"{type_name} control, readymade.controls.{type_name}",
                 "\n\n".join(parts))


def form(name="Form1"):
    parts = [
        _doc(Form),
        "Properties\n" + _members(Form, ["text", "width", "height", "backcolor", "cursor", "default_button", "cancel_button"]),
        "Methods\n" + _members(Form, ["show", "hide", "close", "run"]),
        "Events (double-click the form in the designer to write Form_load)\n" + _events("Form", FORM_EVENTS),
    ]
    return Topic(name, "Form, readymade.Form", "\n\n".join(parts))


def menu_item(name):
    parts = [_doc(MenuItem), "Properties\n" + _members(MenuItem, ["text", "enabled", "checked"]),
             f"Event\n  {name}_click(self)\n      runs when it's chosen, or its shortcut is pressed"]
    return Topic(name, "menu item, readymade.menus.MenuItem (Tools > Menu Editor)", "\n\n".join(parts))


def prop(type_name, name):
    """Help on one property: of a control type, or of the form (type_name "Form")."""
    cls = Form if type_name == "Form" else REGISTRY[type_name]
    if name == "name":
        text = "The name your code uses for it, as in self.Label1, and in its handlers' names, like Label1_click."
    else:
        text = _doc(getattr(cls, name, None)) or "(No help for this property yet.)"
    return Topic(name, f"property of {type_name}", text)


def home(platform=sys.platform):
    """The overview, with shortcuts as this system writes them (⌘ on a Mac)."""
    mac = platform == "darwin"

    def keys(shortcut):
        return menus.display(shortcut, platform)

    click = "\u2318-click" if mac else "Ctrl+click"
    ctrl = "\u2318" if mac else "Ctrl"
    redo = "Ctrl+Shift+Z" if mac else "Ctrl+Y"
    complete = "\u2303Space" if mac else "Ctrl+Space"  # the Control key on a Mac too
    return Topic("readymade", "Visual Basic style forms for Python", "\n".join([
        "Press F1 for help on whatever you're working on: a name in the code, the control",
        "selected in the designer, or a property in the Properties panel.",
        "",
        "Designing",
        "  Draw controls from the Toolbox; double-click one to write its event handler.",
        f"  {click.capitalize()} and drag a box to select several; the Format menu aligns and sizes them.",
        f"  Arrows move the selection ({ctrl}: 1 pixel); Shift+arrows resize it.",
        f"  {keys('Ctrl+Z')} / {keys(redo)} undo and redo; {keys('Ctrl+X')}, C and V cut, copy and paste controls.",
        f"  Tools > Menu Editor ({keys('Ctrl+E')}) designs the form's menus.",
        "  A control's anchor keeps it to edges of the form (or its Frame) as that resizes:",
        "  \"bottom right\" for OK buttons, \"top left right\" to stretch across.",
        "  Format > Tab Order: click the controls in the order Tab should visit them.",
        "",
        "Code",
        f"  F12 or {click} goes to a definition; {complete} completes a name.",
        f"  Tab and Shift+Tab indent and outdent; {keys('Ctrl+/')} comments lines out and in.",
        f"  {keys('Shift+Alt+F')} formats the code (choose a formatter in Project > Formatting).",
        f"  {'Preferences' if mac else 'Tools > Options'}: the code font, indent width and a dark theme.",
        "",
        "Running",
        "  F5 runs the program. The Immediate window runs Python inside it while it runs;",
        "  \"? expression\" prints a value. Errors take you to the line that failed.",
        "  File > Make EXE packages the program to run without Python;",
        "  Project > Program Icon gives it, and its windows, an icon.",
        "",
        "In your code",
        "  from readymade import msgbox, inputbox, open_file_dialog, save_file_dialog,",
        "      folder_dialog, color_dialog, font_dialog, pause, in_thread, doevents, while_running",
        "  forms.Name is a form's shared instance: forms.Settings.show(modal=True)",
        "  app_path(\"data\", \"prices.csv\") is a file in the program's folder, even after",
        "  Make EXE (list files to bundle in pyproject.toml: [tool.readymade] include = [\"data\"]).",
    ]))
