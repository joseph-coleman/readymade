"""Key names for the keypress event, the same as menu shortcuts use.

A key that types a character is that character: "a", "A", "7", "!", " ". Other keys
have names: "Enter", "Esc", "Tab", "Backspace", "Del", "Ins", "Home", "End", "PgUp",
"PgDn", "Up", "Down", "Left", "Right", "F1" to "F24", and on their own "Shift",
"Ctrl", "Alt", "CapsLock" and the like. With Ctrl or Alt held, or Shift with a named
key, the name says so the way shortcuts are written: "Ctrl+S", "Ctrl+Shift+Z",
"Alt+F4", "Shift+Tab".
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
    "Super_L": "Win", "Super_R": "Win", "Win_L": "Win", "Win_R": "Win", "Command": "Cmd",
    "Caps_Lock": "CapsLock", "Num_Lock": "NumLock", "Scroll_Lock": "ScrollLock",
    "Print": "PrintScreen", "Pause": "Pause", "Menu": "Menu", "App": "Menu",
}
_PUNCTUATION = {
    "comma": ",", "period": ".", "slash": "/", "semicolon": ";", "apostrophe": "'", "bracketleft": "[",
    "bracketright": "]", "minus": "-", "equal": "=", "backslash": "\\", "grave": "`",
}
MODIFIER_KEYS = frozenset({"Shift", "Ctrl", "Alt", "Win", "Cmd"})

# Which bits of a Tk event's state mean which modifier, per system.
_SHIFT, _CONTROL = 0x1, 0x4
if sys.platform == "win32":
    _ALT, _COMMAND = 0x20000, 0
elif sys.platform == "darwin":
    _ALT, _COMMAND = 0x10, 0x8
else:
    _ALT, _COMMAND = 0x8, 0


def name(char, keysym, state):
    """The pybasic name of a key press, from a Tk event's char, keysym and state."""
    ctrl, alt, shift, command = (bool(state & bit) for bit in (_CONTROL, _ALT, _SHIFT, _COMMAND))
    if char and char.isprintable() and ctrl == alt and not command:
        return char  # typed text (Ctrl+Alt together is AltGr on Windows, which types characters)
    key = _NAMES.get(keysym) or (keysym.upper() if len(keysym) == 1 else _PUNCTUATION.get(keysym, keysym))
    if key in MODIFIER_KEYS:
        return key  # a modifier on its own
    named = len(key) > 1  # Shift only shows with named keys: Shift+a is "A"
    modifiers = [m for m, held in (("Cmd", command), ("Ctrl", ctrl), ("Alt", alt), ("Shift", shift and (named or ctrl or alt)))
                 if held]
    return "+".join([*modifiers, key])
