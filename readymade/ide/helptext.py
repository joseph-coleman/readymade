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
    "keydown": "a key goes down anywhere in the form, once (not again as it repeats); key is the key itself, like "
               "\"A\", \"Left\", \"Space\" or \"Shift\": for games, with keyup",
    "keyup": "a key held down is let go (or the form loses the keyboard); key names it as keydown did",
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


def _table(rows):
    width = max(len(left) for left, _ in rows)
    return [f"  {left.ljust(width)}   {right}" for left, right in rows]


def finding(platform=sys.platform):
    """F1 in the find bar or the Find tab."""
    mac = platform == "darwin"

    def keys(shortcut):
        return menus.display(shortcut, platform)

    return Topic("Find and Replace", "in the code window, and in every file", "\n".join([
        f"{keys('Ctrl+F')} finds in the code that's showing; {keys('Ctrl+Alt+F' if mac else 'Ctrl+H')} replaces too.",
        "What's selected is what it looks for to start with. Every match is marked; the count",
        "says which one is chosen (2 of 5).",
        "",
        *_table([(f"Enter, \u2193 or {keys('Ctrl+G' if mac else 'F3')}", "the next match (after the last, the first)"),
                 (f"Shift+Enter, \u2191 or {keys('Ctrl+Shift+G' if mac else 'Shift+F3')}", "the one before"),
                 ("Esc or \u00d7", "close the find bar")]),
        "",
        "  Aa   Match case: with it on, \"Count\" doesn't find \"count\".",
        "  ab   Whole word: \"price\" doesn't find the start of \"prices\".",
        "  .*   Regular expression, as Python's re reads it: pric\\w+ finds price and prices,",
        "       ^def finds def at the start of a line. Replace can use \\1, \\2 for what the",
        "       ( ) groups found: find (\\w+) = (\\w+), replace with \\2 = \\1 to swap them.",
        "",
        "Replace changes the chosen match and goes to the next; Replace All changes every one",
        "(Undo takes them all back at once).",
        "",
        f"Find in Files ({keys('Ctrl+Shift+F')}, the Find tab) looks in all the project's code and other text",
        "files, open ones as they are in their tabs (changes not saved yet included), with the",
        "same three choices. Click a result to go to it.",
    ]))


def panel(name, platform=sys.platform):
    """F1 in one of the IDE's windows: "immediate", "problems", "explorer", "toolbox",
    "locals", "watches", "call stack" or "breakpoints"."""
    def keys(shortcut):
        return menus.display(shortcut, platform)

    topics = {
        "immediate": ("Immediate window", "Python, typed in", [
            "Type a line of Python and press Enter; Up and Down bring back earlier lines.",
            "\"? expression\" prints a value, as VB's Print did: ? Label1.text",
            "",
            "Where it runs:",
            *_table([("Nothing running", "in the IDE itself, to try things out"),
                     ("The program running", "in the program: form is the startup form, its controls go by name"),
                     ("", "(Label1.text), and so does every form that's loaded (forms.Settings)"),
                     ("Paused", "in the paused function, with its variables (from Python 3.13 you"),
                     ("", "can change them: count = 0); Call Stack chooses which function")]),
            "",
            "The program's print() output and its errors appear here too. When the prompt says",
            "input:, the program is waiting for input(), and the next line typed answers it.",
        ]),
        "problems": ("Problems", "what the lint tools find", [
            "Every problem the lint tools find in the project's code, open files or not.",
            "Click one, or press Enter, to go to it.",
            "",
            "Project > Linting... chooses the tools (ruff, pyflakes and the like); they check as you",
            "type and when you save. In the code a problem is underlined, with a dot in the line",
            "numbers (rest the mouse on it to read it), and the bar under the code says what's",
            "wrong on the cursor's line.",
        ]),
        "explorer": ("Project Explorer", "the project's parts", [
            "Forms and Modules: the project's code. Double-click to open; right-click for more",
            "(View Code, Set as Startup, Rename, Remove). F2 renames a module, Delete removes.",
            "(startup) marks the form F5 shows first.",
            "",
            "The Python row: the interpreter that runs the program. Double-click to choose another;",
            "right-click to create an environment (.venv) for the project.",
            "Libraries: what the program uses (pyproject.toml's dependencies), installed in its",
            "environment. Double-click to add one.",
            "",
            "Files: everything else in the project folder. Text opens in a tab; pictures and the",
            "like in their own program. Right-click for new files and folders, renaming, removing",
            "(to the Recycle Bin or Trash), and Bundle with Make EXE, for files the program needs.",
            "(bundled) marks what Make EXE puts in the program, including the pictures forms show.",
            "Changes made outside readymade show when you come back to it.",
        ]),
        "toolbox": ("Toolbox", "the controls to draw", [
            "Choose a control, then drag on the form to draw it (double-click a tool to drop one in",
            "the middle of the form). Pointer selects and moves controls; it comes back after each",
            "control is drawn. Rest the mouse on a tool to see what it's for; F1 with one chosen",
            "is help on it.",
        ]),
        "locals": ("Locals", "the paused function's variables", [
            "While the program is paused: the variables of the function chosen in Call Stack (the",
            "one it's paused in, to start with), with their values and types.",
            "",
            "Open an object, list or dict (\u25b8) to see its parts; they stay open as you step.",
            "Double-click a value, or press F2, to change it: type any Python expression and press",
            "Enter (a paused function's own variables can change from Python 3.13).",
            "Resting the mouse on a name in the code shows its value too.",
        ]),
        "watches": ("Watches", "expressions you keep an eye on", [
            "Debug > Add Watch... adds one. The columns: the expression, its value and type, what",
            "it does (Watch), and where it applies (Context).",
            "",
            *_table([("\u0394", "it pauses the program on the line after its value changes"),
                     ("\u25cf", "it pauses the program when its value becomes true"),
                     ("(no mark)", "it only shows its value")]),
            "",
            "While the program runs, a watch not tied to a function shows its value as it changes;",
            "a function's watch shows its value as the function left it. View > Watches shows them",
            "when the program isn't paused. Double-click or Enter to change one, Delete to remove",
            "it, right-click for more.",
        ]),
        "call stack": ("Call Stack", "how the program got here", [
            "While the program is paused: the function it's in at the top, the one that called it",
            "below, and so on (only your project's code; readymade's and Python's are left out).",
            "",
            "Click one to see its place in the code and its variables in Locals; the Immediate",
            "window then runs Python there, and the Watches show their values there.",
        ]),
        "breakpoints": ("Breakpoints", "where the program pauses", [
            "Every breakpoint in the project, and the watches that pause the program.",
            "",
            *_table([("\u25cf  on", "the program pauses before the line runs"),
                     ("\u25cb  off", "switched off: it stays, but the program goes by (click to switch)"),
                     ("\u0394  watch", "a watch that pauses the program (see Watches)")]),
            "",
            "Click a row to go to its line; double-click or Enter for its condition, hit count or",
            f"message; Delete removes it; right-click for more. {keys('Ctrl+Shift+F9')} removes them all.",
        ]),
    }
    title, subtitle, lines = topics[name]
    return Topic(title, subtitle, "\n".join(lines))


def dialog(name, platform=sys.platform):
    """The Help button (or F1) in a dialog: "watch", "breakpoint", "options" or "make exe"."""
    topics = {
        "watch": ("Add Watch", "keeping an eye on an expression", [
            "Expression: any Python expression: a name (total), a part (self.basket[0]), a test",
            "(total > 100).",
            "",
            "Context: where it applies. A function: worked out only while that function runs, with",
            "its variables. A file: its module's own names. Anywhere: what the paused function sees,",
            "or while the program runs, the forms and controls (as the Immediate window does).",
            "",
            "Watch type:",
            *_table([("Watch the expression", "shows its value when the program is paused (and while"),
                     ("", "it runs, for watches not tied to a function)"),
                     ("Break when true", "pauses the program as soon as it becomes true"),
                     ("Break when it changes", "pauses on the line after its value changes; the message"),
                     ("", "names the line that changed it, marked green (a variable first"),
                     ("", "getting a value counts as a change)")]),
            "",
            "The two that break check after every line in their context, which slows the program,",
            "so choose a function when you can. They're listed in the Breakpoints tab too.",
        ]),
        "breakpoint": ("Breakpoint Condition", "pausing only sometimes", [
            "When this is true: a Python expression, like total > 100. The program pauses only when",
            "it's true. It's checked before the line runs, so the names in it must exist then; one",
            "that fails pauses the program and says why. Empty: whenever the line is reached.",
            "",
            "Hit count: how many times the line has been reached (counted from the start of each",
            "run, and only when the condition is true):",
            *_table([("Always", "every time"),
                     ("is", "only that time: is 3 pauses the third time"),
                     ("at least", "from that time on"),
                     ("a multiple of", "every so many times: 10 pauses the 10th, 20th, ...")]),
            "",
            "Instead of stopping, write this (a logpoint): the program carries on, and writes the",
            "message in the Immediate window each time, with names in {braces} worked out, as a",
            "Python f-string does: total is {subtotal}, or {price:.2f}. It's the print() you'd add",
            "and later remove. A logpoint is a diamond in the line numbers.",
        ]),
        "options": ("Options", "yours, for all your projects", [
            "Code font and Indent: how the code looks, and how many spaces Tab puts in.",
            "Theme: Light, or Dark throughout the IDE. The forms keep their own colors.",
            "",
            "Break on errors in event handlers: when an event handler fails, the program pauses",
            "at the line that failed, with its variables in Locals, instead of just printing the",
            "error. Continue skips the rest of that event.",
            "",
            "Also where an error is raised, even if a try catches it: pauses as soon as an error",
            "is raised in your code, before any try sees it (VB's Break on All Errors). It finds",
            "errors a try is hiding. It watches every line of your code, so the program runs a",
            "little slower: leave it off until you need it.",
        ]),
        "make exe": ("Make EXE", "a program that runs without Python", [
            "Program name: the program file's name. Version, Company, Description and Copyright:",
            "Windows shows them in the program's Properties > Details; a Mac's Get Info shows the",
            "version and copyright.",
            "",
            "One file: a single program file, easy to hand to people; it starts a little slower,",
            "as it unpacks itself each time. One folder: the program with what it needs beside it;",
            "it starts quicker; hand people the whole folder. On a Mac it's always an .app.",
            "",
            "LICENSES.txt: Python, Tcl/Tk, readymade and most libraries ask for their license",
            "notices to come along when you give a program away; this gathers them, beside it.",
            "",
            "It's made in the project's dist folder, by PyInstaller in the project's own",
            "environment (installed there the first time).",
        ]),
    }
    title, subtitle, lines = topics[name]
    return Topic(title, subtitle, "\n".join(lines))


def home(platform=sys.platform):
    """The overview, with shortcuts as this system writes them (⌘ on a Mac)."""
    mac = platform == "darwin"

    def keys(shortcut):
        return menus.display(shortcut, platform)

    click = "\u2318-click" if mac else "Ctrl+click"
    ctrl = "\u2318" if mac else "Ctrl"
    redo = "Ctrl+Shift+Z" if mac else "Ctrl+Y"
    complete = "\u2303Space" if mac else "Ctrl+Space"  # the Control key on a Mac too
    step_into = keys("Ctrl+F11") if mac else "F11"  # (macOS keeps F11 for Show Desktop)
    return Topic("readymade", "Visual Basic style forms for Python", "\n".join([
        "Press F1 for help on whatever you're working on: a name in the code, the control",
        "selected in the designer, or a property in the Properties panel.",
        "",
        "Designing",
        "  Draw controls from the Toolbox; double-click one to write its event handler.",
        f"  {click.capitalize()} and drag a box to select several; the Format menu aligns and sizes them.",
        f"  Arrows move the selection ({ctrl}: 1 pixel); Shift+arrows resize it.",
        f"  {keys('Ctrl+Z')} / {keys(redo)} undo and redo; {keys('Ctrl+X')}, C and V cut, copy and paste controls.",
        f"  {keys('Ctrl+Shift+V')} (Paste with Code) brings their event handlers too, renamed to match.",
        f"  {click.capitalize()}-drag inside a Frame boxes the controls in it.",
        "  An & in a caption makes an access key: \"&Save\" is " + ("Ctrl+Option+S" if mac else "Alt+S") + ", which clicks",
        "  it (a Label's goes to the control after it). && shows an &." + (
            " Macs don't underline the letter," if mac else ""),
        *(["  and their menus have no access keys (macOS draws them)."] if mac else []),
        f"  Tools > Menu Editor ({keys('Ctrl+E')}) designs the form's menus.",
        "  A control's anchor keeps it to edges of the form (or its Frame) as that resizes:",
        "  \"bottom right\" for OK buttons, \"top left right\" to stretch across.",
        "  A Grid lays controls out in rows and columns (columns = \"auto, *, 2*, 120\"):",
        "  draw controls into its cells; arrows move them between cells, Shift+arrows span more.",
        "  Format > Tab Order: click the controls in the order Tab should visit them. Click a",
        "  Label just before its box: Tab passes it by, but its access key goes to the next one.",
        "",
        "Code",
        f"  F12 or {click} goes to a definition; {complete} completes a name.",
        f"  Tab and Shift+Tab indent and outdent; {keys('Ctrl+/')} comments lines out and in.",
        f"  {keys('Ctrl+F')} finds, {keys('Ctrl+Alt+F' if mac else 'Ctrl+H')} replaces ({keys('Ctrl+G' if mac else 'F3')} for the next);"
        f" {keys('Ctrl+Shift+F')} finds in every file.",
        f"  {keys('Shift+Alt+F')} formats the code (choose a formatter in Project > Formatting).",
        f"  {'Preferences' if mac else 'Tools > Options'}: the code font, indent width and a dark theme.",
        "",
        "Running",
        "  F5 runs the program. The Immediate window runs Python inside it while it runs;",
        "  \"? expression\" prints a value. Shift+F5 ends it.",
        "  File > Make EXE packages the program to run without Python: its name, version and",
        "  details, one file or one folder, with the license notices of what it carries.",
        "  Project > Program Icon gives it, and its windows, an icon.",
        "",
        "The project",
        "  The Project Explorer: double-click to open. Right-click for new files and folders, to",
        f"  rename (F2), or to remove (to the {'Recycle Bin' if platform == 'win32' else 'Trash'}). Files lists the project's other files:",
        "  text opens here, anything else in its own program. Right-click > Bundle with Make EXE",
        "  for files the program needs (the pictures forms show are bundled already). Changes",
        "  made outside readymade show when you come back to it.",
        "",
        "Debugging (break mode)",
        "  An error in an event handler pauses the program at the failed line (Tools > Options",
        "  can turn that off). F9 or a click in the line numbers sets a breakpoint.",
        "  While paused: Locals shows the function's variables, Call Stack how it got there, and",
        "  the Immediate window runs Python in that function. F5 continues, F10 steps over,",
        f"  {step_into} steps into, {keys('Shift+F11')} steps out, {keys('Ctrl+F10')} runs to the cursor; F6 pauses at the",
        "  next event. After an error, Continue skips the rest of that event.",
        f"  {keys('Ctrl+Shift+F10')} (Set Next Statement) goes on from the cursor's line instead, in the",
        f"  same function. F10 or {step_into} with nothing running starts it, pausing as its first event starts.",
        "  Right-click a line number for a breakpoint's condition (stop when total > 100) or hit",
        "  count (stop on the 5th time); those breakpoints show a +. Or have it write a message",
        "  in the Immediate window instead of stopping (\"total is {subtotal}\"): a diamond.",
        "  While paused, rest the mouse on a name to see its value; double-click a value in Locals",
        "  to change it; drag the yellow arrow to choose the next line. View > Breakpoints lists",
        "  them all: click a dot there to switch one off (hollow) without losing it.",
        "  Tools > Options can also pause where an error is raised, even if a try catches it.",
        "  Debug > Add Watch: an expression to watch in a function or file, which can break the",
        "  program when it becomes true or changes. Shift+F9 shows a value at once.",
        "  View > Watches shows them while the program runs too; a function's watch shows its",
        "  value as the function left it. A watch that breaks names (and marks) the line that",
        "  changed the value: the program pauses on the next one, as that's when it's noticed.",
        "",
        "In your code",
        "  from readymade import msgbox, inputbox, open_file_dialog, save_file_dialog,",
        "      folder_dialog, color_dialog, font_dialog, pause, in_thread, doevents, while_running",
        "  forms.Name is a form's shared instance: forms.Settings.show(modal=True)",
        "  app_path(\"data\", \"prices.csv\") is a file in the program's folder, even after",
        "  Make EXE (bundle them with the Project Explorer: right-click > Bundle with Make EXE).",
    ]))
