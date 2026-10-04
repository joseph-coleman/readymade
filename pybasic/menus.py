"""Form menus, as made in the Menu Editor.

A form's menu is a list of items in its .form file. Each item is a dict:

    {"name": "mnuOpen", "text": "&Open...", "shortcut": "Ctrl+O"}
    {"name": "mnuWrap", "text": "&Word Wrap", "checked": true}
    {"name": "mnuFile", "text": "&File", "items": [...]}    # a submenu
    {"text": "-"}                                         # a separator

As in VB, & marks the access key (&& is a literal &). Items may also have
"enabled": false. At runtime each named item is a MenuItem attribute of the
form, and clicking it calls the form's mnuName_click handler.
"""

from __future__ import annotations

import re
import string
import tkinter as tk

SEPARATOR = "-"

# The keys a shortcut can use, as written in shortcuts, with their Tk key names.
_NAMED = {
    "Del": "Delete", "Ins": "Insert", "Home": "Home", "End": "End", "PgUp": "Prior", "PgDn": "Next",
    "Up": "Up", "Down": "Down", "Left": "Left", "Right": "Right",
    "Enter": "Return", "Space": "space", "Backspace": "BackSpace", "Tab": "Tab", "Esc": "Escape",
}
_PUNCTUATION = {
    ",": "comma", ".": "period", "/": "slash", ";": "semicolon", "'": "apostrophe", "[": "bracketleft",
    "]": "bracketright", "-": "minus", "=": "equal", "\\": "backslash", "`": "grave",
}
_ALIASES = {"delete": "Del", "insert": "Ins", "pageup": "PgUp", "pagedown": "PgDn", "escape": "Esc", "return": "Enter"}
KEYS = (*string.ascii_uppercase, *string.digits, *(f"F{n}" for n in range(1, 25)), *_NAMED, *_PUNCTUATION)
MODIFIERS = ("Ctrl", "Alt", "Shift")  # in the order shortcuts are written: Ctrl+Alt+Shift+Key


def split_shortcut(shortcut):
    """ "ctrl + shift + s" -> ({"Ctrl", "Shift"}, "S"). Raises ValueError if it isn't a shortcut."""
    *names, key = [part.strip() for part in shortcut.split("+")]
    modifiers = set()
    for name in names:
        canonical = {"ctrl": "Ctrl", "control": "Ctrl", "alt": "Alt", "shift": "Shift"}.get(name.lower())
        if canonical is None:
            raise ValueError(f"{shortcut!r} isn't a shortcut like Ctrl+S, Ctrl+Shift+F5 or Del")
        modifiers.add(canonical)
    if len(key) == 1 and key.isalnum():
        key = key.upper()
    elif re.fullmatch(r"[Ff]([1-9]|1[0-9]|2[0-4])", key):
        key = key.upper()
    elif key.lower() in _ALIASES:
        key = _ALIASES[key.lower()]
    else:
        key = next((k for k in (*_NAMED, *_PUNCTUATION) if k.lower() == key.lower()), None)
        if key is None:
            raise ValueError(f"{shortcut!r} isn't a shortcut like Ctrl+S, Ctrl+Shift+F5 or Del")
    return modifiers, key


def join_shortcut(modifiers, key):
    return "+".join([*(m for m in MODIFIERS if m in modifiers), key])


def normalize_shortcut(shortcut):
    """The one way of writing a shortcut, e.g. "shift+ctrl+f5" -> "Ctrl+Shift+F5".
    Raises ValueError if it isn't a shortcut, or can't work as one."""
    modifiers, key = split_shortcut(shortcut)
    _check(modifiers, key)
    return join_shortcut(modifiers, key)


def _check(modifiers, key):
    typed = len(key) == 1  # a letter, digit or punctuation key
    if typed and not modifiers & {"Ctrl", "Alt"}:
        raise ValueError(f"{join_shortcut(modifiers, key)} needs Ctrl or Alt: on its own it would fire while typing")
    if typed and "Shift" in modifiers and not key.isalpha():
        raise ValueError(f"Shift changes which key {key} is, so {join_shortcut(modifiers, key)} can't work as a shortcut")


def shortcut_sequence(shortcut):
    """The Tk event sequence for a shortcut: "Ctrl+Shift+S" -> "<Control-KeyPress-S>".
    Raises ValueError if it isn't a shortcut, or can't work as one."""
    modifiers, key = split_shortcut(shortcut)
    _check(modifiers, key)
    if key.isalpha() and len(key) == 1:
        keysym = key if "Shift" in modifiers else key.lower()  # Tk tells Shift by the letter's case
        modifiers = modifiers - {"Shift"}
    else:
        keysym = _NAMED.get(key) or _PUNCTUATION.get(key) or key
    names = [tk_name for m, tk_name in (("Ctrl", "Control"), ("Alt", "Alt"), ("Shift", "Shift")) if m in modifiers]
    return "<" + "-".join([*names, "KeyPress", keysym]) + ">"  # KeyPress, or "<Control-1>" would mean mouse button 1


def parse_text(text):
    """VB-style menu text to (label, underline index): "&File" -> ("File", 0)."""
    label, underline, i = "", -1, 0
    while i < len(text):
        if text[i] == "&" and i + 1 < len(text):
            if text[i + 1] != "&" and underline < 0:
                underline = len(label)
            i += 1
            if text[i] != "&":
                continue
        label += text[i]
        i += 1
    return label, underline


def walk(items):
    """Every item in a menu, depth first, separators included."""
    for item in items:
        yield item
        yield from walk(item.get("items", []))


def names(items):
    return [item["name"] for item in walk(items) if item.get("name")]


def build(menu, items, on_entry):
    """Add items to a tk.Menu. Commands are check buttons, so any item can show a
    check mark. on_entry(item, menu, index, variable) is called for each named item
    and returns the command to run (or None for submenus)."""
    for item in items:
        if item.get("text") == SEPARATOR:
            menu.add_separator()
            continue
        label, underline = parse_text(item.get("text", ""))
        options = {
            "label": label, "underline": underline, "accelerator": item.get("shortcut", ""),
            "state": tk.NORMAL if item.get("enabled", True) else tk.DISABLED,
        }
        index = menu.index(tk.END)
        index = 0 if index is None else index + 1
        if item.get("items"):
            submenu = tk.Menu(menu, tearoff=False)
            build(submenu, item["items"], on_entry)
            menu.add_cascade(menu=submenu, **options)
            on_entry(item, menu, index, None)
        else:
            variable = tk.BooleanVar(menu, bool(item.get("checked", False)))
            menu.add_checkbutton(variable=variable, **options)
            command = on_entry(item, menu, index, variable)
            if command is not None:
                menu.entryconfigure(index, command=command)


class MenuItem:
    """A menu item at runtime: `self.mnuSave.enabled = False`, `self.mnuWrap.checked = True`."""

    def __init__(self, item, menu, index, variable):
        self.name = item["name"]
        self.shortcut = item.get("shortcut", "")
        self._text = item.get("text", "")
        self._menu = menu
        self._index = index
        self._variable = variable
        self._checked = bool(item.get("checked", False))

    def click(self, handler):
        """The command for this item: as in VB, clicking doesn't toggle the check mark itself."""
        def command():
            if self._variable is not None:
                self._variable.set(self._checked)  # undo Tk's automatic toggle
            if handler is not None:
                handler()
        return command

    @property
    def text(self):
        return self._text

    @text.setter
    def text(self, value):
        self._text = str(value)
        label, underline = parse_text(self._text)
        self._menu.entryconfigure(self._index, label=label, underline=underline)

    @property
    def enabled(self):
        return str(self._menu.entrycget(self._index, "state")) != tk.DISABLED

    @enabled.setter
    def enabled(self, value):
        self._menu.entryconfigure(self._index, state=tk.NORMAL if value else tk.DISABLED)

    @property
    def checked(self):
        return self._checked

    @checked.setter
    def checked(self, value):
        self._checked = bool(value)
        if self._variable is not None:
            self._variable.set(self._checked)

    def __repr__(self):
        return f"<MenuItem {self.name}>"
