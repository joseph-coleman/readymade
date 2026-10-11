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
import sys
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


# Shortcuts are written the same everywhere ("Ctrl+S"), and mean each system's usual keys:
# on a Mac, as in Qt and Electron, Ctrl is the Command key (⌘) and Alt is Option (⌥).
# (The Mac's Control key is for completion, ⌃Space, and Control+click is a right click.)


def _on_mac(platform):
    return platform == "darwin"


def tk_modifier(modifier, platform=sys.platform):
    """Tk's name for a shortcut modifier on this system: "Ctrl" is "Control", or "Command" on a Mac."""
    if _on_mac(platform):
        return {"Ctrl": "Command", "Alt": "Option", "Shift": "Shift"}[modifier]
    return {"Ctrl": "Control", "Alt": "Alt", "Shift": "Shift"}[modifier]


def primary_mask(platform=sys.platform):
    """The bit of a Tk event's state for "Ctrl" (Command on a Mac), as in Ctrl+click."""
    return 0x8 if _on_mac(platform) else 0x4


def shortcut_sequence(shortcut, platform=sys.platform):
    """The Tk event sequence for a shortcut: "Ctrl+Shift+S" -> "<Control-KeyPress-S>"
    ("<Command-KeyPress-S>" on a Mac). Raises ValueError if it isn't a shortcut, or can't
    work as one."""
    modifiers, key = split_shortcut(shortcut)
    _check(modifiers, key)
    if key.isalpha() and len(key) == 1:
        keysym = key if "Shift" in modifiers else key.lower()  # Tk tells Shift by the letter's case
        modifiers = modifiers - {"Shift"}
    else:
        keysym = _NAMED.get(key) or _PUNCTUATION.get(key) or key
    names = [tk_modifier(m, platform) for m in MODIFIERS if m in modifiers]
    return "<" + "-".join([*names, "KeyPress", keysym]) + ">"  # KeyPress, or "<Control-1>" would mean mouse button 1


# macOS's codes for the keys of a US keyboard (kVK_ANSI_*), which Tk puts in the top byte of a
# key event's keycode on a Mac. Option changes the character a key types (Option+F is "ƒ"),
# so a Mac shortcut with Alt is found by its key's position instead.
_MAC_KEYCODES = {
    "A": 0, "S": 1, "D": 2, "F": 3, "H": 4, "G": 5, "Z": 6, "X": 7, "C": 8, "V": 9, "B": 11, "Q": 12,
    "W": 13, "E": 14, "R": 15, "Y": 16, "T": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
    "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "O": 31, "U": 32, "[": 33, "I": 34,
    "P": 35, "L": 37, "J": 38, "'": 39, "K": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "N": 45, "M": 46,
    ".": 47, "`": 50,
}
_MAC_MASKS = {"Shift": 0x1, "Ctrl": 0x8, "Alt": 0x10}  # Command is Ctrl; the Mac's Control key isn't used


def mac_key(keycode):
    """The key (as in _MAC_KEYCODES: "S", "5") of a Mac key event's keycode, or ""."""
    code = keycode >> 24
    return next((key for key, number in _MAC_KEYCODES.items() if number == code), "")


def bind_shortcut(widget, shortcut, callback, platform=sys.platform):
    """Run callback(event) when shortcut is pressed in widget (for a window: anywhere in it).
    Raises ValueError if it isn't a shortcut, or can't work as one."""
    modifiers, key = split_shortcut(shortcut)
    _check(modifiers, key)
    if not (_on_mac(platform) and "Alt" in modifiers and key in _MAC_KEYCODES):
        widget.bind(shortcut_sequence(shortcut, platform), callback, add="+")
        return
    wanted = sum(_MAC_MASKS[m] for m in modifiers)

    def check(e):
        if e.keycode >> 24 == _MAC_KEYCODES[key] and e.state & sum(_MAC_MASKS.values()) == wanted:
            return callback(e)
        return None

    widget.bind("<Option-KeyPress>", check, add="+")


def accelerator(shortcut, platform=sys.platform):
    """The text a menu item shows for its shortcut: "Ctrl+S", or on a Mac "Command-S", which
    Tk draws as ⌘S (and Option, Shift as ⌥, ⇧)."""
    modifiers, key = split_shortcut(shortcut)
    if not _on_mac(platform):
        return join_shortcut(modifiers, key)
    names = [tk_modifier(m, platform) for m in ("Alt", "Shift", "Ctrl") if m in modifiers]  # ⌥⇧⌘, the Mac's order
    return "-".join([*names, _NAMED.get(key, key)])


def modifier_label(modifier, platform=sys.platform):
    """How the Menu Editor names a modifier: "Ctrl", or on a Mac "Ctrl (⌘)", "Alt (⌥)"."""
    if not _on_mac(platform):
        return modifier
    return {"Ctrl": "Ctrl (\u2318)", "Alt": "Alt (\u2325)"}.get(modifier, modifier)


def display(shortcut, platform=sys.platform):
    """A shortcut as people read it on this system: "Ctrl+Shift+Z", or on a Mac "⇧⌘Z"."""
    modifiers, key = split_shortcut(shortcut)
    if not _on_mac(platform):
        return join_shortcut(modifiers, key)
    symbols = "".join(symbol for m, symbol in (("Alt", "\u2325"), ("Shift", "\u21e7"), ("Ctrl", "\u2318")) if m in modifiers)
    return symbols + key


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


def context_clicks(widget):
    """The mouse clicks that open a right-click (context) menu: the right button, and on a
    Mac also Control+click. Tk 8.6 calls a Mac's right button 2 (Tk 9 calls it 3, as
    everywhere else); elsewhere 2 is the middle button, which pastes on Linux."""
    if widget.tk.call("tk", "windowingsystem") == "aqua":
        return ("<Button-2>", "<Button-3>", "<Control-Button-1>")
    return ("<Button-3>",)


def later(widget, command):
    """command, run once the menu that chose it has closed rather than while it's still
    open. On macOS, a dialog (or anything else with its own wait loop) started from
    inside a menu bar command never paints and freezes the program; elsewhere the
    moment's delay is harmless."""
    return lambda: widget.after_idle(command)


def defer_commands(menu):
    """Make every command in menu, and in its submenus, run later() (see there)."""
    end = menu.index("end")
    if end is None:
        return
    for index in range(end + 1):
        kind = menu.type(index)
        if kind == "cascade":
            defer_commands(menu.nametowidget(menu.entrycget(index, "menu")))
        elif kind in ("command", "checkbutton", "radiobutton"):
            command = menu.entrycget(index, "command")
            if command:  # the name of the Tcl command tkinter made for the Python function
                menu.entryconfigure(index, command=later(menu, lambda c=command: menu.tk.eval(c)))


def _accelerator_or_blank(shortcut):
    try:
        return accelerator(shortcut) if shortcut else ""
    except ValueError:
        return shortcut  # not a shortcut: shown as written (the Menu Editor doesn't allow these)


def build(menu, items, on_entry):
    """Add items to a tk.Menu. Commands are check buttons, so any item can show a
    check mark. on_entry(item, menu, index, variable) is called for each named item
    and returns the command to run (or None for submenus)."""
    # Each item, separators too, is one entry, so its place in the list is its index in the
    # menu. (Counted, not asked: for an empty menu Tk 8.6 says "none" and Tk 9 says "", which
    # older tkinter can't read. These menus have no tear-off entry.)
    for index, item in enumerate(items):
        if item.get("text") == SEPARATOR:
            menu.add_separator()
            continue
        label, underline = parse_text(item.get("text", ""))
        options = {
            "label": label, "underline": underline, "accelerator": _accelerator_or_blank(item.get("shortcut", "")),
            "state": tk.NORMAL if item.get("enabled", True) else tk.DISABLED,
        }
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
                menu.entryconfigure(index, command=later(menu, command))


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
        """The item's text, with & before its access key (like "&Open...")."""
        return self._text

    @text.setter
    def text(self, value):
        self._text = str(value)
        label, underline = parse_text(self._text)
        self._menu.entryconfigure(self._index, label=label, underline=underline)

    @property
    def enabled(self):
        """Whether it can be chosen. A disabled item is grayed out, and its shortcut does nothing."""
        return str(self._menu.entrycget(self._index, "state")) != tk.DISABLED

    @enabled.setter
    def enabled(self, value):
        self._menu.entryconfigure(self._index, state=tk.NORMAL if value else tk.DISABLED)

    @property
    def checked(self):
        """Whether it shows a check mark. Clicking doesn't change it; the click handler can."""
        return self._checked

    @checked.setter
    def checked(self, value):
        self._checked = bool(value)
        if self._variable is not None:
            self._variable.set(self._checked)

    def __repr__(self):
        return f"<MenuItem {self.name}>"
