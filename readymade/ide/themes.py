"""The IDE's colors: Light, in VS Code's light colors for code and the system's look for
the rest, and Dark, in VS Code's Dark+ throughout. The form being designed keeps its
own colors either way, as it shows what the program will look like."""

from __future__ import annotations

from dataclasses import dataclass, field

from readymade.ide import highlight


@dataclass(frozen=True)
class Chrome:
    """The colors of the IDE around the code: panels, fields, buttons, tabs."""

    window: str  # panels and dialogs
    text: str
    field: str  # entries, lists, trees
    button: str
    button_active: str
    border: str
    tab: str  # the tabs not showing
    trough: str  # behind scrollbars
    note: str  # quieter text, like a status line
    disabled: str
    selection: str
    workspace: str  # the designer's background, around the form


@dataclass(frozen=True)
class Theme:
    name: str
    background: str
    foreground: str
    cursor: str
    selection: str
    gutter: str
    number: str  # line numbers
    number_current: str  # the cursor's line number
    error: str  # behind a run-time error's line
    error_text: str
    problem: str  # lint problems: underlines, marks and messages
    problem_bg: str
    current: str  # behind the line a paused program is at
    arrow: str  # the gutter's arrow at that line
    breakpoint: str  # the gutter's breakpoint dots
    breakpoint_bg: str  # behind lines with breakpoints
    tokens: dict = field(default_factory=dict)  # syntax coloring: highlight tag -> color
    chrome: Chrome | None = None  # None: the system's look


LIGHT = Theme(
    "light", background="#ffffff", foreground="#000000", cursor="#000000", selection="#add6ff",
    gutter="#f0f0f0", number="#999999", number_current="#333333", error="#fff59d", error_text="#000000",
    problem="#e51400", problem_bg="#fdecea", current="#fff59d", arrow="#e0a800", breakpoint="#e51400",
    breakpoint_bg="#f8d7d7", tokens=dict(highlight.COLORS),
)
DARK = Theme(
    "dark", background="#1e1e1e", foreground="#d4d4d4", cursor="#aeafad", selection="#264f78",
    gutter="#1e1e1e", number="#858585", number_current="#c6c6c6", error="#4b4600", error_text="#d4d4d4",
    problem="#f14c4c", problem_bg="#3c1e1e", current="#4b4600", arrow="#ffcc00", breakpoint="#e51400",
    breakpoint_bg="#4b1d1d",
    tokens={"keyword": "#569cd6", "control": "#c586c0", "string": "#ce9178", "escape": "#d7ba7d",
            "comment": "#6a9955", "number": "#b5cea8", "function": "#dcdcaa", "class": "#4ec9b0",
            "variable": "#9cdcfe"},
    chrome=Chrome(window="#252526", text="#cccccc", field="#1e1e1e", button="#3c3c3c", button_active="#505050",
                  border="#454545", tab="#2d2d2d", trough="#1e1e1e", note="#9d9d9d", disabled="#6e6e6e",
                  selection="#04395e", workspace="#1b1b1b"),
)
THEMES = {theme.name: theme for theme in (LIGHT, DARK)}
