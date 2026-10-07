"""Key names for the keypress event, the same as menu shortcuts use.

A key that types a character is that character: "a", "A", "7", "!", " ". Other keys
have names: "Enter", "Esc", "Tab", "Backspace", "Del", "Ins", "Home", "End", "PgUp",
"PgDn", "Up", "Down", "Left", "Right", "F1" to "F24", and on their own "Shift",
"Ctrl", "Alt", "CapsLock" and the like. With Ctrl or Alt held, or Shift with a named
key, the name says so the way shortcuts are written: "Ctrl+S", "Ctrl+Shift+Z",
"Alt+F4", "Shift+Tab".

On a Mac, as in Qt, "Ctrl" is the Command key, so "Ctrl+S" is the save shortcut on
every system (Cmd+S on a Mac, Ctrl+S elsewhere). The Mac's own Control key is
"MacCtrl", and Option is "Alt", except when it types a character (Option+S is "ß").
fn on its own is "Fn"; with another key it changes the key itself (fn+Delete is "Del").
macOS keeps some keys for itself: by default Control+Left/Right switch desktops.
"""

from __future__ import annotations

import sys

# Tk's key names (keysyms) for keys that have a name of their own.
_NAMES = {
    "Return": "Enter", "KP_Enter": "Enter", "Escape": "Esc", "Tab": "Tab", "ISO_Left_Tab": "Tab",
    "BackSpace": "Backspace", "Delete": "Del", "KP_Delete": "Del", "Insert": "Ins", "KP_Insert": "Ins",
    "Home": "Home", "KP_Home": "Home", "End": "End", "KP_End": "End",
    "Prior": "PgUp", "KP_Prior": "PgUp", "Next": "PgDn", "KP_Next": "PgDn",
    "Up": "Up", "KP_Up": "Up", "Down": "Down", "KP_Down": "Down",
    "Left": "Left", "KP_Left": "Left", "Right": "Right", "KP_Right": "Right",
    "space": "Space",
    "Shift_L": "Shift", "Shift_R": "Shift", "Control_L": "Ctrl", "Control_R": "Ctrl",
    "Alt_L": "Alt", "Alt_R": "Alt", "Meta_L": "Alt", "Meta_R": "Alt", "Option_L": "Alt", "Option_R": "Alt",
    "Super_L": "Win", "Super_R": "Win", "Win_L": "Win", "Win_R": "Win",
    "Caps_Lock": "CapsLock", "Num_Lock": "NumLock", "Scroll_Lock": "ScrollLock",
    "Print": "PrintScreen", "Pause": "Pause", "Menu": "Menu", "App": "Menu",
}
# On a Mac, Command is "Ctrl" and the Control key "MacCtrl" (Tk calls Command Meta or Command),
# and the fn key is "Fn" (Tk calls it Super, as a Windows key is elsewhere).
_MAC_NAMES = {"Control_L": "MacCtrl", "Control_R": "MacCtrl", "Meta_L": "Ctrl", "Meta_R": "Ctrl",
              "Command": "Ctrl", "Command_L": "Ctrl", "Command_R": "Ctrl", "Super_L": "Fn", "Super_R": "Fn"}
_PUNCTUATION = {
    "comma": ",", "period": ".", "slash": "/", "semicolon": ";", "apostrophe": "'", "bracketleft": "[",
    "bracketright": "]", "minus": "-", "equal": "=", "backslash": "\\", "grave": "`",
}
MODIFIER_KEYS = frozenset({"Shift", "Ctrl", "Alt", "Win", "MacCtrl", "Fn"})
_ORDER = ("MacCtrl", "Ctrl", "Alt", "Shift")  # as shortcuts are written: Ctrl+Alt+Shift+Key


def _modifier_bits(platform):
    """Which bits of a Tk event's state mean which modifier on each system."""
    if platform == "win32":
        return {"Ctrl": 0x4, "Alt": 0x20000, "Shift": 0x1}
    if platform == "darwin":
        return {"MacCtrl": 0x4, "Ctrl": 0x8, "Alt": 0x10, "Shift": 0x1}  # Ctrl: Command; Alt: Option
    return {"Ctrl": 0x4, "Alt": 0x8, "Shift": 0x1}  # X11: Alt is Mod1 (AltGr is Mod5, so it types)


def name(char, keysym, state, platform=sys.platform):
    """The readymade name of a key press, from a Tk event's char, keysym and state."""
    held = {m for m, bit in _modifier_bits(platform).items() if state & bit}
    if char and char.isprintable() and _types(held, platform):
        return char
    if platform == "darwin" and keysym in _MAC_NAMES:
        key = _MAC_NAMES[keysym]
    else:
        key = _NAMES.get(keysym) or (keysym.upper() if len(keysym) == 1 else _PUNCTUATION.get(keysym, keysym))
    if key in MODIFIER_KEYS:
        return key  # a modifier on its own
    if len(key) == 1 and not held & {"MacCtrl", "Ctrl", "Alt"}:
        held.discard("Shift")  # Shift only shows with named keys or other modifiers: Shift+a is "A"
    return "+".join([*(m for m in _ORDER if m in held), key])


def _types(held, platform):
    """Whether a key with these modifiers held types its character, rather than being a shortcut."""
    if platform == "darwin":
        return not held & {"Ctrl", "MacCtrl"}  # Option types characters: Option+E, E is "é"
    if platform == "win32" and {"Ctrl", "Alt"} <= held:
        return True  # AltGr, which Windows reports as Ctrl+Alt
    return not held & {"Ctrl", "Alt"}
