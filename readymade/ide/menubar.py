"""The IDE's menu bar and keyboard shortcuts, from one table: MENUS.

Each command is written once, as an Item: its label, what it does, its shortcut, and when
it can be used. build() makes the menus and binds the shortcuts from the table, so the key a
menu shows is the key that works (tests/test_menubar.py checks no key does two things).

Shortcuts are written as on Windows and Linux; on a Mac, Ctrl is ⌘ and Alt is Option (see
readymade.menus). Commands take the App: Item("Save All", lambda app: app.save(), "Ctrl+S").
"""

from __future__ import annotations

import sys
import tkinter as tk
from dataclasses import dataclass
from typing import Callable

from readymade import menus
from readymade.ide import helptext
from readymade.ide.tooldialog import formatting_dialog, linting_dialog
from readymade.protocol import Cmd

MAC = sys.platform == "darwin"
# Replace is Ctrl+H, as in VS Code; a Mac uses ⌘H to hide a program, so there it's Option+⌘F
# (also VS Code's). Find Next is F3, and on a Mac ⌘G, its usual (F3 works there too).
REPLACE_KEY = "Ctrl+Alt+F" if MAC else "Ctrl+H"
FIND_NEXT, FIND_PREVIOUS = ("Ctrl+G", "Ctrl+Shift+G") if MAC else ("F3", "Shift+F3")
REDO = "Ctrl+Shift+Z" if MAC else "Ctrl+Y"  # each system's usual (both work everywhere)
# Step Into is F11, as in VS Code; macOS takes F11 for Show Desktop, so a Mac's menu shows
# ⌘F11 (both work everywhere, and F11 does on a Mac with that system shortcut turned off).
STEP_INTO = "Ctrl+F11" if MAC else "F11"


@dataclass(frozen=True)
class Item:
    """A menu command. key is the shortcut it shows and binds; also, more keys that do the
    same (not shown). on_key(app), if given, is what the keys do instead of command: for keys
    that act only sometimes, it returns None to leave the key to the widget with the focus.
    With bind False the key is only shown: another item's binding, or the widgets, do it."""

    label: str
    command: Callable
    key: str = ""
    also: tuple[str, ...] = ()
    on_key: Callable | None = None
    enabled: Callable | None = None  # enabled(app), checked as its menu opens
    bind: bool = True


@dataclass(frozen=True)
class Check:
    """A menu item with a tick. variable(app) is the BooleanVar it shows and sets; or with
    checked(app), whether it's ticked is worked out as its menu opens."""

    label: str
    command: Callable
    variable: Callable | None = None
    checked: Callable | None = None
    enabled: Callable | None = None


@dataclass(frozen=True)
class Menu:
    label: str
    items: tuple
    enabled: Callable | None = None  # for a submenu: whether it can be opened


SEPARATOR = None


# ----- when commands can be used -----

def _editing(app):
    """(the editor showing, whether its form's design is showing, whether controls are selected)."""
    editor = app.current_editor()
    designing = editor is not None and editor.showing_design()
    return editor, designing, bool(designing and editor.selected_controls())


def _text_or_selection(app):
    editor, designing, selected = _editing(app)
    return selected or (editor is not None and not designing)


def _can_undo(app, redo=False):
    editor, designing, _ = _editing(app)
    if designing:
        return editor.can_redo() if redo else editor.can_undo()
    return editor is not None


def _can_paste(app, with_code=False):
    editor, designing, _ = _editing(app)
    if designing:
        return bool(app.clipboard and (app.clipboard_handlers or not with_code))
    return editor is not None


def _selected(app, needs):
    """Whether the form being designed has at least needs controls selected."""
    return app.designing() and len(app.form.selected_controls()) >= needs


def _on_form(action, needs=1):
    """A Format command: action(form editor), with at least needs controls selected."""
    return lambda app: _selected(app, needs) and action(app.form)


# ----- the table -----

MENUS = (
    Menu("File", (
        Item("New Project...", lambda app: app.new_project(), "Ctrl+N"),
        Item("Open Project...", lambda app: app.open_project(), "Ctrl+O"),
        Item("Save All", lambda app: app.save(), "Ctrl+S"),
        Item("Close", lambda app: app.close_document(), "Ctrl+W"),
        SEPARATOR,
        Item("Make EXE...", lambda app: app.envs.make_exe()),
        SEPARATOR,
        Item("Exit", lambda app: app.exit()),
    )),
    Menu("Edit", (
        Item("Undo", lambda app: app.undo(), "Ctrl+Z", on_key=lambda app: app.undo_key(False),
             enabled=_can_undo),
        Item("Redo", lambda app: app.undo(redo=True), REDO, also=("Ctrl+Shift+Z" if REDO == "Ctrl+Y" else "Ctrl+Y",),
             on_key=lambda app: app.undo_key(True), enabled=lambda app: _can_undo(app, redo=True)),
        SEPARATOR,
        Item("Cut", lambda app: app.edit("cut"), "Ctrl+X", on_key=lambda app: app.clipboard_key("cut"),
             enabled=_text_or_selection),
        Item("Copy", lambda app: app.edit("copy"), "Ctrl+C", on_key=lambda app: app.clipboard_key("copy"),
             enabled=_text_or_selection),
        Item("Paste", lambda app: app.edit("paste"), "Ctrl+V", on_key=lambda app: app.clipboard_key("paste"),
             enabled=_can_paste),
        Item("Paste with Code", lambda app: app.edit("paste_code"), "Ctrl+Shift+V",
             on_key=lambda app: app.clipboard_key("paste_code"), enabled=lambda app: _can_paste(app, with_code=True)),
        Item("Delete", lambda app: app.edit("delete"), "Del", bind=False,  # (the code and the designer take Del)
             enabled=_text_or_selection),
        SEPARATOR,
        Item("Find...", lambda app: app.find(), "Ctrl+F"),
        Item("Replace...", lambda app: app.find(replace=True), REPLACE_KEY),
        Item("Find Next", lambda app: app.find_next(1), FIND_NEXT, also=("F3",) if MAC else ()),
        Item("Find Previous", lambda app: app.find_next(-1), FIND_PREVIOUS, also=("Shift+F3",) if MAC else ()),
        Item("Find in Files...", lambda app: app.find_in_files(), "Ctrl+Shift+F"),
        SEPARATOR,
        Item("Toggle Comment", lambda app: app.toggle_comment(), "Ctrl+/", bind=False,  # (the code's own key)
             enabled=lambda app: _editing(app)[0] is not None and not _editing(app)[1]),
        Item("Format Document", lambda app: app.format_document(), "Shift+Alt+F"),
        Item("Go to Definition", lambda app: app.go_to_definition(), "F12"),
    )),
    Menu("Format", (  # VB's, for the selected controls of the form being designed
        Menu("Align", (
            *(Item(label, _on_form(lambda form, e=edge: form.align(e), needs=2))
              for label, edge in (("Lefts", "lefts"), ("Centers", "centers"), ("Rights", "rights"),
                                  ("Tops", "tops"), ("Middles", "middles"), ("Bottoms", "bottoms"))),
            SEPARATOR,
            Item("to Grid", _on_form(lambda form: form.align_to_grid())),
        ), enabled=lambda app: _selected(app, 1)),
        Menu("Make Same Size", (
            Item("Width", _on_form(lambda form: form.make_same_size(height=False), needs=2)),
            Item("Height", _on_form(lambda form: form.make_same_size(width=False), needs=2)),
            Item("Both", _on_form(lambda form: form.make_same_size(), needs=2)),
        ), enabled=lambda app: _selected(app, 2)),
        Menu("Horizontal Spacing", (
            Item("Make Equal", _on_form(lambda form: form.space_evenly("x"), needs=3)),
        ), enabled=lambda app: _selected(app, 3)),
        Menu("Vertical Spacing", (
            Item("Make Equal", _on_form(lambda form: form.space_evenly("y"), needs=3)),
        ), enabled=lambda app: _selected(app, 3)),
        Menu("Center in Form", (
            Item("Horizontally", _on_form(lambda form: form.center_in_container("x"))),
            Item("Vertically", _on_form(lambda form: form.center_in_container("y"))),
        ), enabled=lambda app: _selected(app, 1)),
        Menu("Order", (
            Item("Bring to Front", _on_form(lambda form: form.change_order(to_front=True))),
            Item("Send to Back", _on_form(lambda form: form.change_order(to_front=False))),
        ), enabled=lambda app: _selected(app, 1)),
        SEPARATOR,
        Check("Tab Order", lambda app: app.toggle_tab_order(), enabled=lambda app: app.designing(),
              checked=lambda app: app.designing() and app.form.surface.tab_order_next is not None),
    )),
    Menu("Project", (
        Item("Add Form...", lambda app: app.add_form()),
        Item("Add Module...", lambda app: app.add_module()),
        Item("Refresh", lambda app: app.explorer_refresh()),
        SEPARATOR,
        Item("Create Environment...", lambda app: app.envs.ask_create_environment()),
        Item("Add Library...", lambda app: app.envs.add_library()),
        SEPARATOR,
        Item("Choose Python Interpreter...", lambda app: app.envs.choose_python()),
        SEPARATOR,
        Item("Linting...", lambda app: app.project and linting_dialog(app)),
        Item("Formatting...", lambda app: app.project and formatting_dialog(app)),
        Item("Use Default Python", lambda app: app.envs.set_python(None)),
        SEPARATOR,
        Item("Program Icon...", lambda app: app.files.choose_icon()),
        Item("Remove Program Icon", lambda app: app.files.set_icon(None)),
    )),
    Menu("View", (
        Item("Code", lambda app: app.form and app.form.show_code(), "F7"),
        Item("Object", lambda app: app.form and app.form.show_design(), "Shift+F7"),
        SEPARATOR,
        Check("Debug Windows", lambda app: app.debug.debug_windows_toggled(),
              variable=lambda app: app.debug.keep_debug_windows),
        Item("Locals", lambda app: app.debug.show_debug_window(app.locals)),
        Item("Watches", lambda app: app.debug.show_debug_window(app.watches_panel)),
        Item("Call Stack", lambda app: app.debug.show_debug_window(app.call_stack)),
        Item("Breakpoints", lambda app: app.debug.show_debug_window(app.breakpoints_panel)),
    )),
    Menu("Tools", (
        Item("Menu Editor...", lambda app: app.menu_editor(), "Ctrl+E"),
        SEPARATOR,
        Item("Options...", lambda app: app.show_options()),
    )),
    Menu("Debug", (
        Item("Continue", lambda app: app.debug.debug_go(Cmd.CONTINUE), "F5", bind=False,  # (Run > Start's F5 does it)
             enabled=lambda app: app.debug.is_paused()),
        Item("Step Into", lambda app: app.debug.debug_go(Cmd.STEP), STEP_INTO,
             also=("F11" if STEP_INTO == "Ctrl+F11" else "Ctrl+F11",),
             enabled=lambda app: app.debug.can_step() or app.debug.can_start()),
        Item("Step Over", lambda app: app.debug.debug_go(Cmd.NEXT), "F10",
             enabled=lambda app: app.debug.can_step() or app.debug.can_start()),
        Item("Step Out", lambda app: app.debug.debug_go(Cmd.RETURN), "Shift+F11",
             enabled=lambda app: app.debug.can_step()),
        Item("Run to Cursor", lambda app: app.debug.run_to_cursor(), "Ctrl+F10",
             enabled=lambda app: app.debug.can_step()),
        Item("Set Next Statement", lambda app: app.debug.set_next_statement(), "Ctrl+Shift+F10",
             enabled=lambda app: app.debug.can_step()),
        Item("Pause", lambda app: app.debug.pause(), "F6", enabled=lambda app: app.debug.can_pause()),
        SEPARATOR,
        Item("Toggle Breakpoint", lambda app: app.debug.toggle_breakpoint(), "F9"),
        Item("Breakpoint Condition...", lambda app: app.debug.breakpoint_condition()),
        Item("Clear All Breakpoints", lambda app: app.debug.clear_breakpoints(), "Ctrl+Shift+F9"),
        SEPARATOR,
        Item("Add Watch...", lambda app: app.debug.add_watch()),
        Item("Quick Watch...", lambda app: app.debug.quick_watch(), "Shift+F9",
             enabled=lambda app: app.debug.is_paused()),
    )),
    Menu("Run", (
        Item("Start", lambda app: app.runner.run(), "F5"),  # (and Continue, while paused)
        Item("End", lambda app: app.runner.stop(), "Shift+F5"),
    )),
    Menu("Help", (
        Item("Help on This", lambda app: app.show_help(), "F1"),
        Item("readymade Overview", lambda app: app.show_topic(helptext.home())),
    )),
)


# ----- making them -----

def walk(menus_=MENUS):
    """Every Item and Check in the table (and in its submenus)."""
    for entry in menus_:
        if isinstance(entry, Menu):
            yield from walk(entry.items)
        elif entry is not SEPARATOR:
            yield entry


def bound_keys(table=MENUS):
    """{key: the Item it runs}, for every key the table binds."""
    keys = {}
    for item in walk(table):
        if isinstance(item, Item) and item.bind:
            for key in (item.key, *item.also) if item.key else item.also:
                keys.setdefault(key, []).append(item)
    return keys


def build(app, table=MENUS):
    """Make the menu bar for app's window, and bind its shortcuts there."""
    root = app.root
    menubar = tk.Menu(root)
    for entry in table:
        menubar.add_cascade(label=entry.label, menu=_make(app, menubar, entry))
    menus.defer_commands(menubar)  # or dialogs opened from it freeze on macOS
    for key, (item, *_) in bound_keys(table).items():  # (a key used twice fails the tests)
        menus.bind_shortcut(root, key, lambda e, i=item: _key_pressed(app, i))
    root.configure(menu=menubar)
    return menubar


def _key_pressed(app, item):
    if item.on_key is not None:
        return item.on_key(app)
    item.command(app)
    return "break"


def _make(app, parent, menu):
    widget = tk.Menu(parent, tearoff=False)
    rules = []  # (index, enabled, checked variable, checked)
    for entry in menu.items:
        if entry is SEPARATOR:
            widget.add_separator()
            continue
        last = widget.index("end")
        index = 0 if last is None else last + 1
        if isinstance(entry, Menu):
            widget.add_cascade(label=entry.label, menu=_make(app, widget, entry))
            variable = None
        elif isinstance(entry, Check):
            variable = entry.variable(app) if entry.variable else tk.BooleanVar(app.root, False)
            widget.add_checkbutton(label=entry.label, variable=variable, command=lambda c=entry.command: c(app))
        else:
            widget.add_command(label=entry.label, accelerator=menus.accelerator(entry.key) if entry.key else "",
                               command=lambda c=entry.command: c(app))
            variable = None
        if entry.enabled is not None or getattr(entry, "checked", None) is not None:
            rules.append((index, entry.enabled, variable, getattr(entry, "checked", None)))
    if rules:
        def update():
            for index, enabled, variable, checked in rules:
                if enabled is not None:
                    widget.entryconfigure(index, state=tk.NORMAL if enabled(app) else tk.DISABLED)
                if checked is not None:
                    variable.set(bool(checked(app)))

        widget.configure(postcommand=update)
    return widget
