"""How controls look, in readymade's own terms: colours, fonts, alignment and mouse
cursors, and what they become in Tk.

Colours are "#rrggbb" strings, with "" for the usual colour. A font is a string like
"Arial, 12, bold" (family, size in points, then any of bold, italic and underline),
or the same as a tuple, ("Arial", 12, "bold"); empty parts mean the usual font's.
"""

from __future__ import annotations

import re

ALIGNMENTS = ("left", "center", "right")
VALIGNMENTS = ("top", "middle", "bottom")
FONT_STYLES = ("bold", "italic", "underline")
# Mouse cursors by readymade name, and Tk's names for them (which Tk maps to each system's own).
CURSORS = {
    "default": "",  # the control's usual cursor (a text box's is "text")
    "arrow": "arrow",
    "hand": "hand2",
    "text": "xterm",
    "cross": "crosshair",
    "wait": "watch",
    "move": "fleur",
    "help": "question_arrow",
    "resize_ew": "sb_h_double_arrow",
    "resize_ns": "sb_v_double_arrow",
}

_HEX = re.compile(r"#[0-9a-fA-F]{6}")


def check_color(value):
    """value as a "#rrggbb" colour (or "" for the usual); ValueError if it isn't one."""
    value = "" if value is None else str(value).strip()
    if value and not _HEX.fullmatch(value):
        raise ValueError(f"{value!r} isn't a colour; use \"#rrggbb\", like \"#ff0000\" for red (or \"\" for the usual colour)")
    return value.lower()


def lighter(color, amount=0.2):
    """A "#rrggbb" colour mixed with some white (for a hovered button)."""
    channels = [int(color[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(c + (255 - c) * amount):02x}" for c in channels)


def parse_font(value):
    """(family, size, styles) from a font string or tuple; "" and 0 mean the usual."""
    if value is None or value == "":
        return "", 0, ()
    parts = [p.strip() for p in value.split(",")] if isinstance(value, str) else [str(p).strip() for p in value]
    family = parts[0] if parts else ""
    size = 0
    if len(parts) > 1 and parts[1]:
        try:
            size = int(float(parts[1]))
        except ValueError:
            raise ValueError(f"{value!r}: the font's size, after the first comma, must be a number") from None
        if size < 0:
            raise ValueError(f"{value!r}: the font's size can't be negative")
    styles = []
    for word in " ".join(parts[2:]).lower().split():
        if word not in FONT_STYLES:
            raise ValueError(f"{value!r}: {word!r} isn't a font style; use bold, italic or underline")
        if word not in styles:
            styles.append(word)
    return family, size, tuple(s for s in FONT_STYLES if s in styles)


def format_font(value):
    """The tidy string form of a font: "Arial, 12, bold"; "" for the usual font."""
    family, size, styles = parse_font(value)
    parts = [family, str(size) if size else "", " ".join(styles)]
    while parts and not parts[-1]:
        parts.pop()
    return ", ".join(parts)


def tk_font(value, usual):
    """A Tk font description for a font, filling empty parts from usual (a dict like
    tkinter.font.Font.actual() gives)."""
    family, size, styles = parse_font(value)
    return (family or usual["family"], size or usual["size"], *styles)


def anchor(alignment, valignment="middle"):
    """Tk's compass-point anchor for an alignment pair: ("left", "top") is "nw"."""
    across = {"left": "w", "center": "", "right": "e"}[alignment]
    down = {"top": "n", "middle": "", "bottom": "s"}[valignment]
    return (down + across) or "center"


def check_choice(name, value, choices):
    if value not in choices:
        raise ValueError(f"{name} must be one of: {', '.join(choices)}")
    return value
