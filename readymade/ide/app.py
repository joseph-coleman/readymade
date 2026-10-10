"""The readymade IDE: Toolbox, documents, Project Explorer, Properties and the
Immediate window in one Tk application.

App owns the open project, the open documents (editors.py) and the running
program. The Toolbox and Properties panel work on the form whose tab is showing.
"""

from __future__ import annotations

import argparse
import code
import contextlib
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from readymade import events, formatting, menus, package, remote, usersettings
from readymade.formfile import FormFileError
from readymade.ide import assist
from readymade.ide.editors import FormEditor, ModuleEditor, ViewerEditor, bring_in
from readymade.ide.linting import Linter
from readymade.ide.menueditor import MenuEditor
from readymade.ide import helptext
from readymade.ide.panels import (CallStackPanel, HelpPanel, ImmediateWindow, LocalsPanel, ProblemsPanel,
                                  ProjectExplorer, PropertiesPanel, Toolbox, WatchesPanel)
from readymade.ide import options
from readymade.ide.tooldialog import formatting_dialog, linting_dialog
from readymade.ide.debugging import STEPS, BreakpointDialog, DebugSession, WatchDialog, function_at
from readymade.ide.tracebacks import TracebackWatcher
from readymade.project import Project, ProjectError, describe_python, find_pythons, requirement_name

_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])  # the folder containing readymade/
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")  # terminal color and cursor codes


# Step Into is F11, as in VS Code; macOS takes F11 for Show Desktop, so a Mac's menu shows
# ⌘F11 (both work everywhere, and F11 does on a Mac with that system shortcut turned off).
STEP_INTO = "Ctrl+F11" if sys.platform == "darwin" else "F11"


class App:
    def __init__(self, root: tk.Tk, path: Path | None = None):
        self.root = root
        events.collect_garbage_on(root)  # the IDE's threads mustn't free Tk objects (see events.py)
        self.project: Project | None = None
        self.editors: list[FormEditor | ModuleEditor] = []
        self.form: FormEditor | None = None  # the form whose tab is showing
        self.process: subprocess.Popen | None = None  # the running program, or venv/pip
        self.session: DebugSession | None = None  # the link with the running program (debugging.py)
        self.in_break_mode = False  # the program is paused (at a breakpoint, a step or an error)
        self._break_split = 0.5  # with the debug windows showing, the Immediate window's share of the bottom's width
        self._debug_windows_shown = False
        # View > Debug Windows: Locals, Watches and Call Stack show while running or stopped too (always in break mode).
        self.keep_debug_windows = tk.BooleanVar(root, usersettings.get("debug-windows", False) is True)
        self._on_exit = None
        self._watcher: TracebackWatcher | None = None  # finds errors in the running program's output
        self._output: queue.Queue = queue.Queue()
        self._console = _DesignTimeConsole(self)
        self.linter = Linter(self)
        self.assistant = assist.Assistant(_PACKAGE_ROOT) if assist.AVAILABLE else None
        self._completions: queue.Queue = queue.Queue()  # answers from the assistant's thread
        self._python_info: dict[str, str] = {}
        self.clipboard: list[dict] = []  # copied controls, for pasting into any form  # interpreter path -> describe_python(), which is slow
        self._build_ui()
        if path is not None:
            self.open_path(path)
        self.update_title()

    def _build_ui(self):
        root = self.root
        root.geometry("1180x740")
        if "clam" in ttk.Style().theme_names():
            ttk.Style().theme_use("clam")
        self.light_theme = ttk.Style().theme_use()  # the Light option's look; Dark is its own theme (options.py)
        self._build_menu()

        outer = ttk.PanedWindow(root, orient=tk.VERTICAL)
        outer.pack(fill=tk.BOTH, expand=True)
        top = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        self.toolbox = Toolbox(top, on_double_click=lambda t: self.form and self.form.add_control_centered(t))
        self.documents = ttk.Notebook(top)
        self.documents.bind("<<NotebookTabChanged>>", self._tab_changed)
        side = ttk.PanedWindow(top, orient=tk.VERTICAL)
        self.explorer = ProjectExplorer(side, self)
        self.properties = PropertiesPanel(side)
        side.add(self.explorer, weight=1)
        side.add(self.properties, weight=2)
        top.add(self.toolbox, weight=0)
        top.add(self.documents, weight=1)
        top.add(side, weight=0)
        # Below: the Immediate window, and F1's help. In break mode Locals, Watches and Call Stack show beside them.
        self.bottom_area = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        self.bottom = ttk.Notebook(self.bottom_area)
        self.bottom_area.add(self.bottom, weight=1)
        self.debug_tabs = ttk.Notebook(self.bottom_area)
        self.locals = LocalsPanel(self.debug_tabs, on_expand=lambda path: self.session and self.session.expand(path))
        self.call_stack = CallStackPanel(self.debug_tabs, on_select=lambda i: self.session and self.session.choose_frame(i))
        self.watches_panel = WatchesPanel(self.debug_tabs, on_expand=lambda path: self.session and self.session.expand(path),
                                          on_edit=self.edit_watch, on_delete=self.delete_watch)
        self.debug_tabs.add(self.locals, text="Locals")
        self.debug_tabs.add(self.watches_panel, text="Watches")
        self.debug_tabs.add(self.call_stack, text="Call Stack")
        self.immediate = ImmediateWindow(self.bottom, on_line=self.immediate_line)
        self.problems = ProblemsPanel(self.bottom, on_open=self.go_to_problem)
        self.help = HelpPanel(self.bottom)
        self.bottom.add(self.immediate, text="Immediate")
        self.bottom.add(self.problems, text="Problems")
        self.bottom.add(self.help, text="Help")
        self.problems_changed()
        options.apply(self)  # the font, indent and colors chosen in Tools > Options
        if root.tk.call("tk", "windowingsystem") == "aqua":  # a Mac's app menu has Preferences... (⌘,)
            root.createcommand("::tk::mac::ShowPreferences", self.show_options)
        outer.add(top, weight=1)
        outer.add(self.bottom_area, weight=0)
        self._update_debug_windows()

        # Shortcuts are written as on Windows and Linux; on a Mac, Ctrl is ⌘ and Alt is Option (see menus).
        for shortcut, command in (
            ("Ctrl+N", self.new_project),
            ("Ctrl+O", self.open_project),
            ("Ctrl+S", self.save),
            ("Ctrl+W", self.close_document),
            ("Ctrl+E", self.menu_editor),
            ("F5", self.run),
            ("Shift+F5", self.stop),
            ("F6", self.pause),
            ("F9", self.toggle_breakpoint),
            ("Ctrl+Shift+F9", self.clear_breakpoints),
            ("F10", lambda: self.debug_go("next")),
            ("Ctrl+F10", self.run_to_cursor),
            ("Ctrl+Shift+F10", self.set_next_statement),
            ("F11", lambda: self.debug_go("step")),
            ("Ctrl+F11", lambda: self.debug_go("step")),  # ⌘F11: macOS keeps F11 for Show Desktop
            ("Shift+F11", lambda: self.debug_go("return")),
            ("Shift+F9", self.quick_watch),
            ("F7", lambda: self.form and self.form.show_code()),
            ("Shift+F7", lambda: self.form and self.form.show_design()),
            ("Shift+Alt+F", self.format_document),
            ("F12", self.go_to_definition),
            ("F1", self.show_help),
        ):
            menus.bind_shortcut(root, shortcut, lambda e, c=command: (c(), "break")[1])
        for shortcut, redo in (("Ctrl+Z", False), ("Ctrl+Y", True), ("Ctrl+Shift+Z", True)):
            menus.bind_shortcut(root, shortcut, lambda e, r=redo: self._undo_key(r))
        for shortcut, action in (("Ctrl+X", "cut"), ("Ctrl+C", "copy"), ("Ctrl+V", "paste")):
            menus.bind_shortcut(root, shortcut, lambda e, a=action: self._clipboard_key(a))
        root.protocol("WM_DELETE_WINDOW", self.exit)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file = tk.Menu(menubar, tearoff=False)
        file.add_command(label="New Project...", accelerator=menus.accelerator("Ctrl+N"), command=self.new_project)
        file.add_command(label="Open Project...", accelerator=menus.accelerator("Ctrl+O"), command=self.open_project)
        file.add_command(label="Save All", accelerator=menus.accelerator("Ctrl+S"), command=self.save)
        file.add_command(label="Close", accelerator=menus.accelerator("Ctrl+W"), command=self.close_document)
        file.add_separator()
        file.add_command(label="Make EXE...", command=self.make_exe)
        file.add_separator()
        file.add_command(label="Exit", command=self.exit)
        edit = tk.Menu(menubar, tearoff=False, postcommand=lambda: self._update_edit_menu(edit))
        edit.add_command(label="Undo", accelerator=menus.accelerator("Ctrl+Z"), command=self.undo)
        redo = "Ctrl+Shift+Z" if sys.platform == "darwin" else "Ctrl+Y"  # each system's usual (both work)
        edit.add_command(label="Redo", accelerator=menus.accelerator(redo), command=lambda: self.undo(redo=True))
        edit.add_separator()
        for label, action, key in (("Cut", "cut", "Ctrl+X"), ("Copy", "copy", "Ctrl+C"),
                                   ("Paste", "paste", "Ctrl+V"), ("Delete", "delete", "Del")):
            edit.add_command(label=label, accelerator=menus.accelerator(key), command=lambda a=action: self.edit(a))
        edit.add_separator()
        edit.add_command(label="Toggle Comment", accelerator=menus.accelerator("Ctrl+/"), command=self.toggle_comment)
        edit.add_command(label="Format Document", accelerator=menus.accelerator("Shift+Alt+F"), command=self.format_document)
        edit.add_command(label="Go to Definition", accelerator=menus.accelerator("F12"), command=self.go_to_definition)
        format_menu = self._build_format_menu(menubar)
        project = tk.Menu(menubar, tearoff=False)
        project.add_command(label="Add Form...", command=self.add_form)
        project.add_command(label="Add Module...", command=self.add_module)
        project.add_command(label="Refresh", command=self.explorer_refresh)
        project.add_separator()
        project.add_command(label="Create Environment...", command=self.ask_create_environment)
        project.add_command(label="Add Library...", command=self.add_library)
        project.add_separator()
        project.add_command(label="Choose Python Interpreter...", command=self.choose_python)
        project.add_separator()
        project.add_command(label="Linting...", command=lambda: self.project and linting_dialog(self))
        project.add_command(label="Formatting...", command=lambda: self.project and formatting_dialog(self))
        project.add_command(label="Use Default Python", command=lambda: self.set_python(None))
        project.add_separator()
        project.add_command(label="Program Icon...", command=self.choose_icon)
        project.add_command(label="Remove Program Icon", command=lambda: self.set_icon(None))
        view = tk.Menu(menubar, tearoff=False)
        view.add_command(label="Code", accelerator=menus.accelerator("F7"), command=lambda: self.form and self.form.show_code())
        view.add_command(label="Object", accelerator=menus.accelerator("Shift+F7"), command=lambda: self.form and self.form.show_design())
        view.add_separator()
        view.add_checkbutton(label="Debug Windows", variable=self.keep_debug_windows, command=self._debug_windows_toggled)
        view.add_command(label="Locals", command=lambda: self.show_debug_window(self.locals))
        view.add_command(label="Watches", command=lambda: self.show_debug_window(self.watches_panel))
        view.add_command(label="Call Stack", command=lambda: self.show_debug_window(self.call_stack))
        tools = tk.Menu(menubar, tearoff=False)
        tools.add_command(label="Menu Editor...", accelerator=menus.accelerator("Ctrl+E"), command=self.menu_editor)
        tools.add_separator()
        tools.add_command(label="Options...", command=self.show_options)
        debug = tk.Menu(menubar, tearoff=False, postcommand=lambda: self._update_debug_menu(debug))
        for item in (
            ("Continue", "F5", lambda: self.debug_go("continue")),
            ("Step Into", STEP_INTO, lambda: self.debug_go("step")),
            ("Step Over", "F10", lambda: self.debug_go("next")),
            ("Step Out", "Shift+F11", lambda: self.debug_go("return")),
            ("Run to Cursor", "Ctrl+F10", self.run_to_cursor),
            ("Set Next Statement", "Ctrl+Shift+F10", self.set_next_statement),
            ("Pause", "F6", self.pause),
            None,
            ("Toggle Breakpoint", "F9", self.toggle_breakpoint),
            ("Breakpoint Condition...", None, self.breakpoint_condition),
            ("Clear All Breakpoints", "Ctrl+Shift+F9", self.clear_breakpoints),
            None,
            ("Add Watch...", None, self.add_watch),
            ("Quick Watch...", "Shift+F9", self.quick_watch),
        ):
            if item is None:
                debug.add_separator()
            else:
                label, key, command = item
                debug.add_command(label=label, accelerator=menus.accelerator(key) if key else "", command=command)
        run = tk.Menu(menubar, tearoff=False)
        run.add_command(label="Start", accelerator=menus.accelerator("F5"), command=self.run)
        run.add_command(label="End", accelerator=menus.accelerator("Shift+F5"), command=self.stop)
        menubar.add_cascade(label="File", menu=file)
        menubar.add_cascade(label="Edit", menu=edit)
        menubar.add_cascade(label="Format", menu=format_menu)
        menubar.add_cascade(label="Project", menu=project)
        menubar.add_cascade(label="View", menu=view)
        menubar.add_cascade(label="Tools", menu=tools)
        menubar.add_cascade(label="Debug", menu=debug)
        menubar.add_cascade(label="Run", menu=run)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Help on This", accelerator=menus.accelerator("F1"), command=self.show_help)
        help_menu.add_command(label="readymade Overview", command=lambda: self.show_topic(helptext.home()))
        menubar.add_cascade(label="Help", menu=help_menu)
        menus.defer_commands(menubar)  # or dialogs opened from it freeze on macOS
        self.root.configure(menu=menubar)

    # ----- the project -----

    def open_path(self, path):
        """Open a project folder, its pyproject.toml or one of its .form files.
        A folder that doesn't exist yet becomes a new project."""
        path = Path(path)
        try:
            if not path.exists() and not path.suffix:
                project = Project.create(path)
            else:
                project = Project.find(path)
                project.settings()  # reports a broken pyproject.toml now
        except (OSError, ProjectError) as e:
            messagebox.showerror("Open Project", str(e), parent=self.root)
            return False
        if not self._close_all():
            return False
        self.project = project
        self.explorer_refresh()
        form = path.stem if path.suffix == ".form" else project.startup
        if form:
            self.open_form(form)
        self.linter.check_project()
        self.watches_panel.show(self.watches())
        self.update_title()
        return True

    def new_project(self):
        filename = filedialog.asksaveasfilename(
            parent=self.root, title="New Project: choose a name and place for its folder", initialfile="MyProject"
        )
        if filename:
            self.open_path(Path(filename))

    def open_project(self):
        folder = filedialog.askdirectory(parent=self.root, title="Open Project folder", mustexist=True)
        if folder:
            self.open_path(Path(folder))

    def explorer_refresh(self):
        self.explorer.refresh()

    def add_form(self):
        self._add("Form", self._next_name("Form"), lambda p, n: p.add_form(n), self.open_form)

    def add_module(self):
        self._add("Module", self._next_name("Module"), lambda p, n: p.add_module(n), self.open_module)

    def _add(self, kind, suggestion, create, open_it):
        if self.project is None:
            return
        name = simpledialog.askstring(f"Add {kind}", f"{kind} name:", initialvalue=suggestion, parent=self.root)
        if not name:
            return
        try:
            create(self.project, name.strip())
        except (OSError, ProjectError) as e:
            messagebox.showerror(f"Add {kind}", str(e), parent=self.root)
            return
        self.explorer_refresh()
        open_it(name.strip())

    def _next_name(self, prefix):
        taken = set(self.project.forms() + self.project.modules()) if self.project else set()
        n = 1
        while f"{prefix}{n}" in taken:
            n += 1
        return f"{prefix}{n}"

    def python(self):
        """The project's interpreter and where it came from, for running and for display."""
        path, where = self.project.python_choice() if self.project else (None, None)
        if path is None:
            return Path(sys.executable), "IDE"
        return path, where

    def python_label(self):
        path, where = self.python()
        if str(path) not in self._python_info:
            self._python_info[str(path)] = describe_python(path)
        return f"Python {self._python_info[str(path)]}  ({where})"

    def choose_python(self):
        if self.project is None:
            return
        filename = filedialog.askopenfilename(
            parent=self.root, title="Choose the project's Python interpreter", initialdir=self.project.folder
        )
        if filename:
            self.set_python(Path(filename))

    def set_python(self, path):
        if self.project is None:
            return
        try:
            self.project.set_python(path)
        except (OSError, ProjectError) as e:
            messagebox.showerror("Python Interpreter", str(e), parent=self.root)
        self._python_info.clear()  # look again, in case it was just installed or changed
        self.explorer_refresh()

    def set_startup(self, form):
        if self.project is None:
            return
        try:
            self.project.set_startup(form)
        except (OSError, ProjectError) as e:
            messagebox.showerror("Set as Startup", str(e), parent=self.root)
        self.explorer_refresh()

    def form_renamed(self, old, new):
        """A FormEditor saved a renamed form under its new file names."""
        if self.project and self.project.settings().get("tool", {}).get("readymade", {}).get("startup") == old:
            self.project.set_startup(new)
        self.explorer_refresh()
        self.update_title()

    def _build_format_menu(self, menubar):
        """VB's Format menu, for the selected controls of the form being designed."""
        def on_form(action, needs=1):
            return lambda: self._designing() and len(self.form.selected_controls()) >= needs and action(self.form)

        menu = tk.Menu(menubar, tearoff=False)
        align = tk.Menu(menu, tearoff=False)
        for label, edge in (("Lefts", "lefts"), ("Centers", "centers"), ("Rights", "rights"),
                            ("Tops", "tops"), ("Middles", "middles"), ("Bottoms", "bottoms")):
            align.add_command(label=label, command=on_form(lambda f, e=edge: f.align(e), needs=2))
        align.add_separator()
        align.add_command(label="to Grid", command=on_form(lambda f: f.align_to_grid()))
        size = tk.Menu(menu, tearoff=False)
        size.add_command(label="Width", command=on_form(lambda f: f.make_same_size(height=False), needs=2))
        size.add_command(label="Height", command=on_form(lambda f: f.make_same_size(width=False), needs=2))
        size.add_command(label="Both", command=on_form(lambda f: f.make_same_size(), needs=2))
        spacing = {}
        for axis, label in (("x", "Horizontal Spacing"), ("y", "Vertical Spacing")):
            spacing[label] = tk.Menu(menu, tearoff=False)
            spacing[label].add_command(label="Make Equal", command=on_form(lambda f, a=axis: f.space_evenly(a), needs=3))
        center = tk.Menu(menu, tearoff=False)
        center.add_command(label="Horizontally", command=on_form(lambda f: f.center_in_container("x")))
        center.add_command(label="Vertically", command=on_form(lambda f: f.center_in_container("y")))
        order = tk.Menu(menu, tearoff=False)
        order.add_command(label="Bring to Front", command=on_form(lambda f: f.change_order(to_front=True)))
        order.add_command(label="Send to Back", command=on_form(lambda f: f.change_order(to_front=False)))
        # Each submenu, with how many selected controls it needs.
        submenus = (("Align", align, 1), ("Make Same Size", size, 2),
                    ("Horizontal Spacing", spacing["Horizontal Spacing"], 3),
                    ("Vertical Spacing", spacing["Vertical Spacing"], 3),
                    ("Center in Form", center, 1), ("Order", order, 1))
        for label, submenu, _ in submenus:
            menu.add_cascade(label=label, menu=submenu)
        menu.add_separator()
        self._tab_order_mode = tk.BooleanVar(self.root, False)
        menu.add_checkbutton(label="Tab Order", variable=self._tab_order_mode, command=self.toggle_tab_order)

        def update():
            count = len(self.form.selected_controls()) if self._designing() else 0
            for label, _, needs in submenus:
                menu.entryconfigure(label, state=tk.NORMAL if count >= needs else tk.DISABLED)
            menu.entryconfigure("Tab Order", state=tk.NORMAL if self._designing() else tk.DISABLED)
            self._tab_order_mode.set(self._designing() and self.form.surface.tab_order_next is not None)

        menu.configure(postcommand=update)
        return menu

    def toggle_tab_order(self):
        """Format > Tab Order: click the form's controls in the order Tab should visit them
        (Esc, or the menu again, to finish)."""
        if not self._designing():
            return
        surface = self.form.surface
        if surface.tab_order_next is None:
            surface.start_tab_order()
            self.immediate.write("(Tab Order: click the controls in the order Tab should visit them; Esc when done.)\n")
        else:
            surface.stop_tab_order()

    def _designing(self):
        """True while a form's Design tab is showing."""
        return self.form is not None and self.form.frame.select() == str(self.form.surface)

    def undo(self, redo=False):
        """Edit > Undo/Redo: the designer's when a form's design is showing, otherwise the code editor's."""
        editor = self._current_editor()
        if isinstance(editor, FormEditor) and editor.frame.select() == str(editor.surface):
            editor.redo() if redo else editor.undo()
        elif editor is not None:
            try:
                editor.code.text.edit_redo() if redo else editor.code.text.edit_undo()
            except tk.TclError:
                pass  # nothing to undo

    def _undo_key(self, redo):
        try:
            focus = self.root.focus_get()
        except KeyError:
            focus = None
        if isinstance(focus, tk.Text):
            return None  # typing in code: the editor's own Ctrl+Z handles it
        self.undo(redo)
        return "break"

    def edit(self, action):
        """Edit > Cut/Copy/Paste/Delete: controls while designing, otherwise text in the code editor."""
        form = self.form
        if form is not None and self._designing():
            if action in ("cut", "copy"):
                copied = form.copy_selection()
                if copied:
                    self.clipboard = copied
                    if action == "cut":
                        form.delete_selection()
            elif action == "paste" and self.clipboard:
                form.paste(self.clipboard)
            elif action == "delete":
                form.delete_selection()
            return
        editor = self._current_editor()
        if editor is not None:
            event = {"cut": "<<Cut>>", "copy": "<<Copy>>", "paste": "<<Paste>>", "delete": "<<Clear>>"}[action]
            editor.code.text.event_generate(event)

    def toggle_comment(self):
        """Edit > Toggle Comment, in the code that's showing."""
        editor = self._current_editor()
        if editor is not None and not self._designing():
            editor.code.toggle_comment()

    # ----- completion and Go to Definition (assist.py) -----

    def _assist_unavailable(self, manual):
        if self.assistant is None or self.project is None:
            if manual:
                self.immediate.write("(Completion and Go to Definition need Jedi: pip install -e \".[ide]\")\n")
            return True
        return False

    def complete(self, editor, manual=False):
        """Ask for completions at the cursor, in the background; they're shown if still wanted."""
        if self._assist_unavailable(manual):
            return
        code = editor.code
        line, column = map(int, code.text.index("insert").split("."))
        start, prepared = code.word_start(), editor.prepared_code()
        python, folder, path = self.project.python(), self.project.folder, editor.code_path
        code.completion_request = getattr(code, "completion_request", 0) + 1
        request = code.completion_request

        def work():
            items = []
            try:
                items = self.assistant.complete(prepared, line, column, path, folder, python)
            finally:  # always answer, so the IDE stops waiting
                self._completions.put((editor, request, start, items))

        threading.Thread(target=work, daemon=True).start()
        self.root.after(30, self._show_completions)

    def _show_completions(self):
        try:
            editor, request, start, items = self._completions.get_nowait()
        except queue.Empty:
            self.root.after(30, self._show_completions)
            return
        code = editor.code
        # Only the latest request, and only while the cursor is still on that name.
        if editor in self.editors and request == code.completion_request and items and code.word_start() == start:
            code.completions.open(items, start)

    def go_to_definition(self, editor=None, index="insert"):
        """Edit > Go to Definition (F12, or Ctrl+click): open the code where a name is defined.
        A form's control or menu item is shown in the designer."""
        editor = editor or self._current_editor()
        if editor is None or self._assist_unavailable(manual=True):
            return
        code = editor.code
        line, column = map(int, code.text.index(index).split("."))
        word = code.text.get(f"{index} wordstart", f"{index} wordend").strip()
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            found = self.assistant.definition(editor.prepared_code(), line, column, editor.code_path,
                                              self.project.folder, self.project.python())
        finally:
            self.root.configure(cursor="")
        if found is None:
            self.immediate.write(f"(No definition found for {word or 'that'}.)\n")
        elif found.kind in ("control", "menu") and isinstance(editor, FormEditor):
            editor.show_design()
            if found.kind == "control":
                editor.select(found.name)
            else:
                self._show_menu_item(editor, found.name)
        elif found.kind == "builtin":
            self.immediate.write(f"({found.name} is built into Python, so there's no source to show.)\n")
        else:
            target = self.open_code(found.path)
            if target is not None:
                target.code.show_location(found.line, found.column, len(found.name))

    def _show_menu_item(self, editor, name):
        dialog = self.menu_editor()
        if dialog is not None:
            item = next((i for i in menus.walk(dialog.items) if i.get("name") == name), None)
            if item is not None:
                dialog.tree.selection_set(str(id(item)))
                dialog.tree.see(str(id(item)))

    def open_code(self, path):
        """Open a .py file: a form's code or a module of the project, else read-only."""
        if self.project and path.parent.resolve() == self.project.folder.resolve() and path.suffix == ".py":
            if path.with_suffix(".form").exists():
                return self.open_form(path.stem, "code")
            return self.open_module(path.stem)
        viewer = next((e for e in self.editors if isinstance(e, ViewerEditor) and e.path == path), None)
        if viewer is None:
            try:
                viewer = ViewerEditor(self, path)
            except OSError as e:
                self.immediate.write(f"(Couldn't open {path}: {e})\n")
                return None
            self._add_tab(viewer)
        self.documents.select(viewer.frame)
        self._tab_changed()
        return viewer

    def show_options(self):
        """Tools > Options...: the code font, indent width and theme."""
        options.OptionsDialog(self).grab_set()

    # ----- problems -----

    def problems_changed(self):
        """The linter found something new: show every problem in the Problems tab."""
        problems = self.linter.all_problems()
        self.problems.show(problems, checking=self.linter.busy, linting=bool(self.linter.tools()))
        self.bottom.tab(self.problems, text=f"Problems ({len(problems)})" if problems else "Problems")

    def go_to_problem(self, path, line, column):
        """Open the code with a problem, at its place."""
        editor = self.open_code(Path(path))
        if editor is not None:
            editor.code.show_location(line, column)
            editor.code.text.focus_set()

    # ----- F1 help -----

    def show_topic(self, topic):
        self.help.show(topic)
        self.bottom.select(self.help)

    def show_help(self):
        """F1: help on whatever you're working on: a property in the Properties panel, the
        designer's selection, the name at the cursor in the code, or else an overview."""
        try:
            focus = self.root.focus_get()
        except KeyError:
            focus = None
        form = self.form
        prop = self.properties.prop_with_focus(focus)
        if prop and form is not None and self.properties.current:
            spec = form.design.control(form.selected)
            self.show_topic(helptext.prop(spec["type"] if spec else "Form", prop))
        elif form is not None and self._designing():
            spec = form.design.control(form.selected)
            topic = helptext.control(spec["type"], spec["name"]) if spec else helptext.form(form.design.name)
            self.show_topic(topic)
        elif self._current_editor() is not None:
            self.show_topic(self._code_help(self._current_editor()))
        else:
            self.show_topic(helptext.home())

    def _code_help(self, editor):
        code = editor.code
        word = code.text.get("insert wordstart", "insert wordend").strip()
        if self.assistant is None or self.project is None:
            return helptext.Topic(word or "Help", "", 'Help on code needs Jedi: pip install -e ".[ide]"')
        line, column = map(int, code.text.index("insert").split("."))
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            found = self.assistant.help(editor.prepared_code(), line, column, editor.code_path,
                                        self.project.folder, self.project.python())
        finally:
            self.root.configure(cursor="")
        if isinstance(found, tuple):  # one of the form's controls or menu items
            kind, name, type_name = found
            return helptext.control(type_name, name) if kind == "control" else helptext.menu_item(name)
        return found or helptext.Topic(word or "Help", "", f"No help found for {word or 'that'}.")

    def format_document(self):
        """Edit > Format Document: the code of the document that's showing."""
        editor = self._current_editor()
        if editor is not None and self.project is not None and not getattr(editor, "read_only", False):
            if not formatting.tools_for(self.project):
                self.immediate.write("(No formatter is chosen for this project: see Project > Formatting...)\n")
            else:
                self.format_code(editor)

    def format_code(self, editor):
        """Format an open document's code with the project's formatters (one undo step).
        Returns False, leaving the code as it was, if a formatter couldn't."""
        tools = formatting.tools_for(self.project)
        if not tools:
            return True
        source = editor.code.get_source()
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            formatted, trouble = formatting.format_source(
                tools, self.python()[0], self.project.folder, editor.code_path, source, self.environment())
        finally:
            self.root.configure(cursor="")
        if trouble:
            self.immediate.write(f"--- {trouble} ---\n")
            return False
        editor.code.replace_keeping_place(formatted)
        return True

    def _clipboard_key(self, action):
        """Ctrl+X/C/V act on controls only while the design surface has the keyboard;
        anywhere else (code, Properties, Immediate) they're the usual text keys."""
        try:
            focus = self.root.focus_get()
        except KeyError:
            focus = None
        if self.form is None or not self._designing() or focus is None or not str(focus).startswith(str(self.form.surface)):
            return None
        self.edit(action)
        return "break"

    def _update_edit_menu(self, menu):
        editor = self._current_editor()
        designing = isinstance(editor, FormEditor) and editor.frame.select() == str(editor.surface)
        selected = bool(designing and editor.selected_controls())
        for label, possible in (("Undo", editor.can_undo() if designing else editor is not None),
                                ("Redo", editor.can_redo() if designing else editor is not None),
                                ("Cut", selected or (editor is not None and not designing)),
                                ("Copy", selected or (editor is not None and not designing)),
                                ("Paste", bool(self.clipboard) if designing else editor is not None),
                                ("Delete", selected or (editor is not None and not designing)),
                                ("Toggle Comment", editor is not None and not designing)):
            menu.entryconfigure(label, state=tk.NORMAL if possible else tk.DISABLED)

    def menu_editor(self):
        """Open the Menu Editor for the form that's showing."""
        return MenuEditor(self.root, self.form) if self.form else None

    # ----- documents -----

    def _editor(self, kind, name):
        return next((e for e in self.editors if isinstance(e, kind) and e.name == name), None)

    def open_form(self, name, view="design"):
        editor = self._editor(FormEditor, name)
        if editor is None:
            if self.project is None:
                return None
            try:
                editor = FormEditor(self, self.project.folder / f"{name}.form")
            except (OSError, ValueError, FormFileError) as e:
                messagebox.showerror("Open Form", str(e), parent=self.root)
                return None
            self._add_tab(editor)
        if view == "code":
            editor.show_code()
        else:
            editor.show_design()
        self._tab_changed()  # don't wait for <<NotebookTabChanged>>, which may arrive later
        return editor

    def open_module(self, name):
        editor = self._editor(ModuleEditor, name)
        if editor is None:
            if self.project is None:
                return None
            try:
                editor = ModuleEditor(self, self.project.folder / f"{name}.py")
            except OSError as e:
                messagebox.showerror("Open Module", str(e), parent=self.root)
                return None
            self._add_tab(editor)
        self.documents.select(editor.frame)
        self._tab_changed()
        return editor

    def _add_tab(self, editor):
        self.editors.append(editor)
        self.documents.add(editor.frame, text=editor.title())
        editor.code.on_complete = lambda code, manual: self.complete(editor, manual)
        editor.code.on_goto = lambda code, index: self.go_to_definition(editor, index)
        if not getattr(editor, "read_only", False):
            editor.code.on_change = lambda: self.linter.check(editor)  # soon after typing stops
            self.linter.check(editor, saved=True)
            editor.code.on_breakpoints = self.breakpoints_changed
            editor.code.on_gutter_menu = lambda line, e, editor=editor: self._gutter_menu(editor, line, e)
            editor.code.set_breakpoints(self._saved_breakpoints().get(self._relative(editor.code_path), []))

    def _current_editor(self):
        try:
            frame = self.documents.nametowidget(self.documents.select())
        except (KeyError, tk.TclError):  # no tabs
            return None
        return next((e for e in self.editors if e.frame is frame), None)

    def _tab_changed(self, _=None):
        editor = self._current_editor()
        self.form = editor if isinstance(editor, FormEditor) else None
        self.properties.attach(self.form)
        self.update_title()

    def close_document(self, editor=None, ask=True):
        """Close a document (default: the current one), asking to save changes."""
        editor = editor or self._current_editor()
        if editor is None:
            return True
        if ask and editor.is_dirty():
            answer = messagebox.askyesnocancel("readymade", f"Save changes to {editor.name}?", parent=self.root)
            if answer is None or (answer and not editor.save()):
                return False
        if self.properties.app is editor:
            self.properties.attach(None)
        self._store_breakpoints()
        self.editors.remove(editor)
        self.documents.forget(editor.frame)
        editor.frame.destroy()
        self._tab_changed()
        if self.project is not None:
            self.linter.check_project()  # its problems are now the saved file's
        return True

    def _close_all(self):
        if any(e.is_dirty() for e in self.editors):
            answer = messagebox.askyesnocancel("readymade", "Save changes to the project?", parent=self.root)
            if answer is None or (answer and not self.save()):
                return False
        for editor in list(self.editors):
            self.close_document(editor, ask=False)  # already saved or discarded
        return True

    def is_dirty(self):
        return any(e.is_dirty() for e in self.editors)

    def save(self):
        """Save every changed document. Returns False if any failed."""
        changed = [e for e in list(self.editors) if e.is_dirty()]
        if self.project and changed and formatting.format_on_save(self.project):
            for editor in changed:
                self.format_code(editor)  # if it can't, the save still goes ahead
        ok = all([e.save() for e in changed])
        self._store_breakpoints()  # where they are now that lines have moved
        for editor in changed:
            self.linter.check(editor, saved=True)
        if changed:
            self.linter.check_project()  # a change in one file can cause problems in another
        self.update_title()
        return ok

    def update_title(self):
        for editor in self.editors:
            self.documents.tab(editor.frame, text=editor.title())
        name = self.project.name if self.project else "No project"
        state = " [break]" if self.in_break_mode else " [run]" if self.session is not None else ""  # as VB showed
        self.root.title(f"{name}{'*' if self.is_dirty() else ''} - readymade{state}")

    def exit(self):
        if self._close_all():
            self.stop()
            self.root.destroy()

    # ----- running -----

    def run(self, step=False):
        """F5: run the program (with step, pausing as its first event starts), or continue it."""
        if self.in_break_mode:
            self.debug_go("continue")  # F5 continues a paused program
            return
        if self.project is None or not self._idle():
            return
        if not self.save():
            return
        folder = self.project.folder
        startup = self.project.startup
        if startup is None:
            self.immediate.write("(The project has no forms to run.)\n")
            return
        python, where = self.python()
        if not self._python_exists(python):
            return
        for editor in self.editors:
            editor.code.clear_error()
        self.immediate.write(f"--- Running {self.project.name} ({startup}, Python: {where}). Type Python below to inspect it. ---\n")
        self.session = DebugSession(self)  # Immediate lines, input() and the debugger go through it
        self.session.send(cmd="start", breakpoints=self._breakpoint_files(), watches=self.watches(),
                          break_on_errors=options.break_on_errors(), step=step)
        if step:
            self.immediate.write("--- Stepping: the program pauses as its first event (like Form_load) starts. ---\n")
        self._start([str(python), "-m", "readymade.run", "--debug", str(self.session.port), "--startup", startup,
                     str(folder)], interactive=True)
        self._watcher = TracebackWatcher(folder, self.show_error)
        self.update_title()

    def show_error(self, path, line, message):
        """Point out a run-time error: open the code where it happened and highlight the line."""
        self.immediate.write(f"--- {message}  ({path.name}, line {line}) ---\n")
        if path.with_suffix(".form").exists():
            editor = self.open_form(path.stem, "code")
        else:
            editor = self.open_module(path.stem)
        if editor is not None:
            editor.code.show_error(line, message)

    def environment(self):
        """Environment variables for programs and tools run for the project: they can import readymade."""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [_PACKAGE_ROOT, env.get("PYTHONPATH")]))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # Plain text only: the Immediate window can't show colors, and the IDE reads the
        # tracebacks and tool output, which color codes (e.g. from FORCE_COLOR) would garble.
        for name in ("FORCE_COLOR", "CLICOLOR_FORCE"):
            env.pop(name, None)
        env["PYTHON_COLORS"] = "0"
        env["NO_COLOR"] = "1"
        return env

    def _idle(self):
        if self.process is None:
            return True
        self.immediate.write("(Busy: wait for the program or install to finish, or use Run > End.)\n")
        return False

    def _start(self, args, interactive=False, on_exit=None):
        """Run a program or tool in the project folder, showing its output in the Immediate
        window. on_exit(exit code) runs when it ends; by default the code is reported."""
        env = self.environment()
        try:
            process = subprocess.Popen(
                args, stdin=subprocess.PIPE if interactive else subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", cwd=self.project.folder if self.project else None, env=env,
            )
        except OSError as e:
            self.immediate.write(f"--- Couldn't start {Path(args[0]).name}: {e} ---\n")
            if on_exit:
                on_exit(-1)
            return
        self.process = process
        self.bottom.select(self.immediate)  # its output appears there
        self._on_exit = on_exit
        self._watcher = None
        threading.Thread(target=_pump, args=(process.stdout, self._output), daemon=True).start()
        self.root.after(50, self._poll_output)

    def stop(self):
        if self.process is not None:
            self.process.terminate()

    def _poll_output(self):
        while True:
            try:
                item = self._output.get_nowait()
            except queue.Empty:
                break
            if item is None:
                code = self.process.wait() if self.process else None
                self.process = None
                self._watcher = None
                self._end_session()
                if self._on_exit:
                    self._on_exit(code)
                else:
                    self.immediate.write(f"--- Ended (exit code {code}) ---\n")
                return
            item = _ANSI.sub("", item)  # in case a program prints colors itself
            self.immediate.write(item)
            if self._watcher:
                self._watcher.feed(item)
        if self.session is not None:
            self.session.poll()  # (after the output, so a prompt comes after what was printed before it)
        self.root.after(50, self._poll_output)

    def _end_session(self):
        if self.session is not None:
            self.session.handle({"event": "running"})  # out of break mode, if it was paused
            self.session.close()
            self.session = None
        self.immediate.input_done()
        self.update_title()

    # ----- debugging -----

    def show_break_mode(self, on):
        """Break mode: the bottom area splits, with Locals, Watches and Call Stack beside the Immediate window."""
        if on and not self.in_break_mode:
            self.bottom.select(self.immediate)
        self.in_break_mode = on
        self._update_debug_windows()
        self.update_title()

    def show_debug_window(self, panel):
        """View > Locals, Watches or Call Stack: show the debug windows, with that one in front."""
        if not self.keep_debug_windows.get():
            self.keep_debug_windows.set(True)
            self._debug_windows_toggled()
        self.debug_tabs.select(panel)

    def _debug_windows_toggled(self):
        usersettings.set("debug-windows", self.keep_debug_windows.get())
        self._update_debug_windows()

    def _update_debug_windows(self):
        """The debug windows show in break mode, and whenever View > Debug Windows is ticked."""
        show = self.in_break_mode or self.keep_debug_windows.get()
        if show and not self._debug_windows_shown:
            self.bottom_area.add(self.debug_tabs, weight=1)
            self._place_split()
        elif not show and self._debug_windows_shown:
            width = self.bottom_area.winfo_width()
            if width > 1:
                self._break_split = min(0.85, max(0.15, self.bottom_area.sashpos(0) / width))  # as it was dragged
            self.bottom_area.forget(self.debug_tabs)
        self._debug_windows_shown = show

    def _place_split(self, tries=25):
        self.bottom_area.update_idletasks()  # (laid out first, or the new pane stays squeezed shut)
        width = self.bottom_area.winfo_width()
        if width < 50:  # the window isn't showing yet
            if tries:
                self.root.after(200, lambda: self._place_split(tries - 1))
            return
        if self._debug_windows_shown:
            self.bottom_area.sashpos(0, int(width * self._break_split))

    def debug_go(self, how, **extra):
        """Continue (F5), Step Into (F11), Step Over (F10) or Step Out (Shift+F11) while paused."""
        session = self.session
        if session is None and how in ("step", "next") and self.project is not None:
            self.run(step=True)  # F10 or F11 starts the program, stepping (as VB's F8 did)
            return
        if session is None or session.paused is None:
            return
        if how in STEPS and not session.can_step():
            self.immediate.write("(After an error the program can't step on: Continue skips the rest of the event.)\n")
            return
        session.go(how, **extra)

    def run_to_cursor(self):
        """Ctrl+F10: go on until the line with the cursor."""
        editor = self._code_editor()
        if editor is not None:
            self.debug_go("until", file=str(editor.code_path), line=int(editor.code.text.index("insert").split(".")[0]))

    def pause(self):
        """F6: break into the running program. It's idle between events, so it breaks as the next one starts."""
        if self.session is None or self.in_break_mode:
            return
        self.session.send(cmd="pause")
        self.immediate.write("--- Pausing: the program breaks when its next event starts (a click, a key, a timer). ---\n")

    def _update_debug_menu(self, menu):
        paused = self.in_break_mode and self.session is not None and self.session.paused is not None
        stepping = paused and self.session.can_step()
        stopped = self.session is None and self.process is None and self.project is not None
        for label, on in (("Continue", paused), ("Step Into", stepping or stopped), ("Step Over", stepping or stopped),
                          ("Step Out", stepping), ("Run to Cursor", stepping), ("Set Next Statement", stepping),
                          ("Quick Watch...", paused),
                          ("Pause", self.session is not None and not self.in_break_mode)):
            menu.entryconfigure(label, state=tk.NORMAL if on else tk.DISABLED)

    def _code_editor(self):
        """The editor whose code is showing, or None (a form's design, or nothing)."""
        editor = self._current_editor()
        if isinstance(editor, FormEditor) and editor.frame.select() != str(editor.code):
            return None
        return editor

    def toggle_breakpoint(self):
        """F9: set or clear a breakpoint on the cursor's line."""
        editor = self._code_editor()
        if editor is not None:
            editor.code.toggle_breakpoint()

    def breakpoint_condition(self, editor=None, line=None):
        """Debug > Breakpoint Condition: a condition and hit count for the breakpoint on a line
        (the cursor's), which gets one if it hasn't."""
        editor = editor or self._code_editor()
        if editor is None or editor.code.on_breakpoints is None:
            return None
        if line is None:
            line = int(editor.code.text.index("insert").split(".")[0])
        if not editor.code.can_break_at(line):
            self.root.bell()
            return None
        return BreakpointDialog(self, line, editor.code.breakpoint_settings(line) or {},
                                lambda settings: editor.code.set_breakpoint_settings(line, settings))

    def set_next_statement(self, editor=None, line=None):
        """Ctrl+Shift+F10, while paused: go on from another line (the cursor's) of the paused function."""
        editor = editor or self._code_editor()
        if editor is None or self.session is None or self.session.paused is None:
            return
        if line is None:
            line = int(editor.code.text.index("insert").split(".")[0])
        self.session.send(cmd="jump", file=str(editor.code_path), line=line)

    def _gutter_menu(self, editor, line, e):
        """A right-click in the line numbers."""
        menu = getattr(self, "_gutter_popup", None)
        if menu is None:
            menu = self._gutter_popup = tk.Menu(self.root, tearoff=False)
        menu.delete(0, tk.END)
        has = editor.code.breakpoint_settings(line) is not None
        menu.add_command(label="Remove Breakpoint" if has else "Add Breakpoint",
                         command=lambda: editor.code.toggle_breakpoint(line))
        menu.add_command(label="Breakpoint Condition...", command=lambda: self.breakpoint_condition(editor, line))
        if self.session is not None and self.session.paused is not None and self.session.can_step():
            menu.add_separator()
            menu.add_command(label="Run to Here",
                             command=lambda: self.debug_go("until", file=str(editor.code_path), line=line))
            menu.add_command(label="Set Next Statement", command=lambda: self.set_next_statement(editor, line))
        options.color_menus(menu, options.theme().chrome)
        menu.tk_popup(e.x_root, e.y_root)
        return menu

    def clear_breakpoints(self):
        for editor in self.editors:
            editor.code.set_breakpoints([])
        if self.project is not None:
            self.project.set_local_setting("breakpoints", None)
        self.breakpoints_changed()

    def breakpoints_changed(self):
        """A breakpoint was set or cleared: remember it, and tell the running program."""
        self._store_breakpoints()
        if self.session is not None:
            self.session.send(cmd="breakpoints", breakpoints=self._breakpoint_files())

    def breakpoints(self):
        """Every breakpoint in the project: {file name (relative to the project): [line, ...]}."""
        if self.project is None:
            return {}
        found = dict(self._saved_breakpoints())
        for editor in self.editors:
            if editor.code.on_breakpoints is not None:
                found[self._relative(editor.code_path)] = editor.code.breakpoints()
        return {name: lines for name, lines in found.items() if lines and (self.project.folder / name).exists()}

    def _saved_breakpoints(self):
        return self.project.local_settings().get("breakpoints", {}) if self.project else {}

    def _store_breakpoints(self):
        """Remember the breakpoints, on this machine (in the project's .readymade/local.json)."""
        if self.project is not None:
            found = self.breakpoints()
            if found != self._saved_breakpoints():
                self.project.set_local_setting("breakpoints", found or None)

    def _breakpoint_files(self):
        """The breakpoints as the program wants them: {full path: [line, ...]}."""
        return {str(self.project.folder / name): lines for name, lines in self.breakpoints().items()}

    def watches(self):
        """The project's watches (remembered on this machine): [{expression, function, file, kind}]."""
        return self.project.local_settings().get("watches", []) if self.project else []

    def set_watches(self, watches):
        if self.project is None:
            return
        self.project.set_local_setting("watches", watches or None)
        if self.session is not None:
            self.session.send(cmd="watches", watches=watches)  # paused, it answers with their values
        if not self.in_break_mode:
            self.watches_panel.show(watches)

    def add_watch(self, expression=None):
        """Debug > Add Watch: for the selected text (or the name at the cursor), in the function there."""
        if self.project is None:
            return
        watch = {"expression": expression or ""}
        editor = self._code_editor()
        if editor is not None and editor.code.on_breakpoints is not None:
            text = editor.code.text
            line = int(text.index("insert").split(".")[0])
            if not expression:
                watch["expression"] = (text.get("sel.first", "sel.last") if text.tag_ranges("sel")
                                       else text.get("insert wordstart", "insert wordend")).strip()
            watch["file"] = self._relative(editor.code_path)
            watch["function"] = function_at(editor.code.get_source(), line)

        def added(new):
            self.set_watches([*self.watches(), new])
            self.show_debug_window(self.watches_panel)
        return WatchDialog(self, watch, added)

    def edit_watch(self, index):
        if index is None:
            return self.add_watch()
        watches = self.watches()

        def edited(new):
            self.set_watches([new if i == index else w for i, w in enumerate(watches)])
        return WatchDialog(self, watches[index], edited, title="Edit Watch")

    def delete_watch(self, index):
        self.set_watches([w for i, w in enumerate(self.watches()) if i != index])

    def quick_watch(self):
        """Shift+F9, while paused: the value of the selected text (or the name at the cursor)."""
        editor = self._code_editor()
        if self.session is None or self.session.paused is None or editor is None:
            return
        text = editor.code.text
        expression = (text.get("sel.first", "sel.last") if text.tag_ranges("sel")
                      else text.get("insert wordstart", "insert wordend")).strip()
        if expression:
            self.session.send(cmd="quick", expression=expression)

    def code_files(self):
        """The project's code: {file name relative to the project: source}, open files as edited."""
        if self.project is None:
            return {}
        files = {path.name: path.read_text(encoding="utf-8", errors="replace")
                 for path in sorted(self.project.folder.glob("*.py"))}
        for editor in self.editors:
            if editor.code.on_breakpoints is not None:
                files[self._relative(editor.code_path)] = editor.code.get_source()
        return files

    def _relative(self, path):
        try:
            return Path(path).resolve().relative_to(self.project.folder.resolve()).as_posix()
        except ValueError:
            return str(path)

    # ----- environments and libraries -----

    def ask_create_environment(self):
        """Choose a Python to base the project's .venv on, then create it."""
        if self.project is None or not self._idle():
            return
        pythons = [(f"Python {describe_python(p)}   {p}", p) for p in find_pythons()]
        dialog = tk.Toplevel(self.root)
        dialog.title("Create Environment")
        dialog.transient(self.root)
        ttk.Label(dialog, text="Make a .venv for this project from:").pack(anchor="w", padx=8, pady=(8, 2))
        row = ttk.Frame(dialog)
        row.pack(fill=tk.X, padx=8)
        choice = ttk.Combobox(row, values=[label for label, _ in pythons], state="readonly", width=60)
        choice.current(0)
        choice.pack(side=tk.LEFT, fill=tk.X, expand=True)

        def browse():
            filename = filedialog.askopenfilename(parent=dialog, title="Choose a Python interpreter")
            if filename:
                pythons.append((f"Python {describe_python(filename)}   {filename}", Path(filename)))
                choice["values"] = [label for label, _ in pythons]
                choice.current(len(pythons) - 1)

        def create():
            base = pythons[choice.current()][1]
            if self.project.venv_python().parent.parent.exists() and not messagebox.askyesno(
                "Create Environment", "The project already has a .venv. Replace it?", parent=dialog
            ):
                return
            dialog.destroy()
            self.create_environment(base)

        ttk.Button(row, text="Browse...", command=browse).pack(side=tk.LEFT, padx=(4, 0))
        buttons = ttk.Frame(dialog, padding=8)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="Create", command=create).pack(side=tk.RIGHT, padx=(0, 4))
        dialog.grab_set()

    def create_environment(self, base, then=None):
        """Make the project's .venv from the base interpreter with venv (or uv if venv
        fails and uv is installed), install the project's libraries, and use it."""
        project = self.project
        if project is None or not self._idle():
            return
        venv = project.folder / ".venv"

        def created(code):
            if code == 0:
                return ready()
            uv = shutil.which("uv")
            if uv is None:
                self.immediate.write(
                    "--- Couldn't create the environment. On Linux the system Python may need its venv "
                    "package (e.g. python3-venv), or choose another Python. ---\n"
                )
                return
            self.immediate.write("--- venv didn't work; trying uv instead ---\n")
            shutil.rmtree(venv, ignore_errors=True)  # whatever venv left half-made
            self._start([uv, "venv", "--seed", "--python", str(base), str(venv)],
                        on_exit=lambda c: ready() if c == 0 else self.immediate.write("--- Couldn't create the environment. ---\n"))

        def ready():
            project.set_python(None)  # the new .venv is used from now on
            self._python_info.clear()
            self.explorer_refresh()

            def done():
                self.immediate.write("--- The environment is ready. ---\n")
                if then:
                    then()

            if project.dependencies:
                self._pip_install(project.dependencies, done)
            else:
                done()

        self.immediate.write(f"--- Creating .venv from Python {describe_python(base)} ---\n")
        self._start([str(base), "-m", "venv", "--clear", str(venv)], on_exit=created)

    def add_library(self, requirement=None):
        """pip install a library into the project's environment, and list it in pyproject.toml."""
        if self.project is None or not self._idle():
            return
        if requirement is None:
            requirement = simpledialog.askstring(
                "Add Library", "Library to install from PyPI (for example: requests):", parent=self.root
            )
        requirement = (requirement or "").strip()
        if not requirement:
            return
        if requirement.startswith("-"):
            messagebox.showerror("Add Library", "Enter a library name, not a pip option.", parent=self.root)
            return

        def install():
            self._pip_install([requirement], lambda: self._library_added(requirement))

        if self.project.python() is not None:
            install()
        elif messagebox.askyesno(
            "Add Library",
            "This project doesn't have its own environment yet, so the library would go into the "
            "IDE's Python. Create one (.venv) first?",
            parent=self.root,
        ):
            self.create_environment(find_pythons()[0], then=install)

    def make_exe(self):
        """Package the project as a program that runs without Python, using PyInstaller
        in the project's own environment (creating one, and installing PyInstaller, if needed)."""
        project = self.project
        if project is None or not self._idle() or not self.save():
            return
        startup = project.startup
        if startup is None:
            self.immediate.write("(The project has no forms to make a program from.)\n")
            return

        def build():
            python = project.python()
            launcher = package.write_launcher(project, startup)
            target = package.exe_path(project)
            self.immediate.write(f"--- Making {target.name} with PyInstaller. This takes a minute or so. ---\n")
            for entry in package.bundled_files(project)[1]:
                self.immediate.write(f"(Not found, so not included: {entry})\n")

            def built(code):
                if code == 0:
                    self.immediate.write(f"--- Done: {target} ---\n")
                else:
                    self.immediate.write("--- PyInstaller couldn't make the program; its messages are above. ---\n")

            try:
                args = package.pyinstaller_args(project, launcher, _PACKAGE_ROOT)
            except OSError as e:  # the icon couldn't be converted
                self.immediate.write(f"--- Couldn't make the program's icon from {project.setting('icon')}: {e} ---\n")
                return
            self._start([str(python), *args], on_exit=built)

        def with_pyinstaller():
            # Quietly check whether the environment has PyInstaller (and Pillow, if the icon
            # needs converting to the system's own format); install them if not.
            needs = {"PyInstaller": "pyinstaller", **({"PIL": "pillow"} if package.icon_needs_pillow(project) else {})}
            check = f"import importlib.util, sys; sys.exit(any(importlib.util.find_spec(m) is None for m in {list(needs)!r}))"
            self._start([str(project.python()), "-c", check], on_exit=lambda code: build() if code == 0 else self._pip_install(
                list(needs.values()), build, failed="pip couldn't install what Make EXE needs, so the program wasn't made."))

        python = project.python()
        if python is not None:
            if self._python_exists(python):
                with_pyinstaller()
        elif messagebox.askyesno(
            "Make EXE",
            "A program is made from the project's own environment, and this project doesn't "
            "have one yet. Create it (.venv) now?",
            parent=self.root,
        ):
            self.create_environment(find_pythons()[0], then=with_pyinstaller)

    def _python_exists(self, python):
        if python.exists():
            return True
        self.immediate.write(f"(The project's Python, {python}, doesn't exist. Choose another in the Project menu.)\n")
        return False

    def _pip_install(self, requirements, on_success, failed="pip couldn't install it, so nothing was added."):
        python = self.project.python() if self.project else None
        if python is None or not self._python_exists(python):
            return
        self.immediate.write(f"--- Installing {', '.join(requirements)} ---\n")
        self._start(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off", *requirements],
            on_exit=lambda code: on_success() if code == 0 else self.immediate.write(f"--- {failed} ---\n"),
        )

    ICON_TYPES = {"Icons and pictures": "*.png *.gif *.ico *.icns", "All files": "*"}

    def choose_icon(self):
        """Project > Program Icon: choose the picture the program's windows, and the program
        Make EXE makes, show as their icon. One from outside the project is copied into images/."""
        if self.project is None:
            return
        chosen = filedialog.askopenfilename(parent=self.root, title="Program Icon", initialdir=self.project.folder,
                                            filetypes=list(self.ICON_TYPES.items()))
        if chosen:
            try:
                self.set_icon(bring_in(self.project.folder, Path(chosen)))
            except OSError as e:
                messagebox.showerror("Program Icon", f"Couldn't copy {chosen}: {e}", parent=self.root)

    def set_icon(self, path):
        """Set (or with None, remove) the project's icon: a path relative to the project folder."""
        if self.project is None:
            return
        self.project.set_setting("icon", path)
        if path is None:
            self.immediate.write("--- The program no longer has an icon of its own. ---\n")
            return
        self.immediate.write(f"--- The program's icon is now {path}. ---\n")
        if Path(path).suffix.lower() not in (".png", ".gif"):
            self.immediate.write("(A .png works everywhere; other formats need the Pillow library in the project "
                                 "for the windows' icon.)\n")

    def remove_from_project(self, kind, name):
        """Delete a form's or module's files ("form", "module"), or take a library out of the
        project ("library"), after asking. Returns whether it was removed."""
        if self.project is None or not self._idle():
            return False
        if kind == "library":
            return self._remove_library(name)
        files = " and ".join([f"{name}.form", f"{name}.py"] if kind == "form" else [f"{name}.py"])
        uses = f"forms.{name}" if kind == "form" else f"import {name}"
        if not messagebox.askyesno(
            f"Remove {kind.capitalize()}",
            f"Delete {name} from the project? This deletes {files} and can't be undone.\n\n"
            f"Code that uses it (like {uses}) will need changing.",
            icon="warning", default="no", parent=self.root,
        ):
            return False
        editor = self._editor(FormEditor if kind == "form" else ModuleEditor, name)
        if editor is not None:
            self.close_document(editor, ask=False)  # its unsaved changes go with it
        (self.project.remove_form if kind == "form" else self.project.remove_module)(name)
        self.explorer_refresh()
        self.linter.check_project()  # forgets its problems
        self.immediate.write(f"--- Deleted {files}. ---\n")
        return True

    def _remove_library(self, requirement):
        python = self.project.python()
        library = requirement_name(requirement)
        where = ("It will also be uninstalled from the project's environment (libraries it brought with it stay)."
                 if python is not None else "The project uses the IDE's Python, so it stays installed there.")
        if not messagebox.askyesno("Remove Library", f"Remove {requirement} from the project's libraries? {where}",
                                   icon="warning", default="no", parent=self.root):
            return False
        self.project.remove_dependency(requirement)
        self.explorer_refresh()
        if python is None or not self._python_exists(python):
            self.immediate.write(f"--- Removed {requirement} from the project. ---\n")
            return True

        def uninstalled(code):
            if code == 0:
                self.immediate.write(f"--- Removed {requirement} from the project. ---\n")
            else:
                self.immediate.write(f"--- pip couldn't uninstall {library}, but it's no longer one of the project's libraries. ---\n")

        self.immediate.write(f"--- Uninstalling {library} ---\n")
        self._start([str(python), "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", library],
                    on_exit=uninstalled)
        return True

    def _library_added(self, requirement):
        self.project.add_dependency(requirement)
        self.explorer_refresh()
        self.immediate.write(f"--- Added {requirement} to the project. ---\n")

    def immediate_line(self, line):
        if self.session is not None and self.session.prompt is not None:
            self.immediate.write(line + "\n")  # the answer to the program's input()
            self.session.answer(line)
            return
        self.immediate.write(f">>> {line}\n")
        if line.lstrip().startswith("?"):  # VB's `? expr` prints the expression
            line = f"print({line.lstrip()[1:].strip()})"
        if self.process is None or self.process.stdin is None:
            self._console.push(line)
            return
        if self.session is not None:
            self.session.send(cmd="eval", line=line)
            return
        try:
            self.process.stdin.write(line + "\n")
            self.process.stdin.flush()
        except OSError:
            pass  # the program is exiting; _poll_output will report it


class _ImmediateStream:
    """A file-like object that writes to the Immediate window."""

    def __init__(self, app):
        self.app = app

    def write(self, data):
        self.app.immediate.write(data)
        return len(data)

    def flush(self):
        pass


class _DesignTimeConsole(code.InteractiveConsole):
    """Runs Immediate window lines inside the IDE when no program is running. input() asks
    in a small dialog (the IDE has no console to read), and help() writes its text."""

    def __init__(self, app):
        super().__init__({"__name__": "__immediate__", "input": self._input, "help": remote.Help()})
        self.app = app
        self.stream = _ImmediateStream(app)

    def _input(self, prompt=""):
        answer = simpledialog.askstring("input()", str(prompt) or "Input:", parent=self.app.root)
        if answer is None:
            raise EOFError
        self.stream.write(f"{prompt}{answer}\n")
        return answer

    def write(self, data):
        self.stream.write(data)

    def push(self, *args, **kwargs):
        with contextlib.redirect_stdout(self.stream), contextlib.redirect_stderr(self.stream):
            return super().push(*args, **kwargs)


def _pump(stream, output):
    for line in stream:
        output.put(line)
    output.put(None)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="readymade", description="A Visual Basic style IDE for Python.")
    parser.add_argument(
        "project", nargs="?", type=Path,
        help="a project folder (created if it doesn't exist), its pyproject.toml, or a .form file in it",
    )
    args = parser.parse_args(argv)
    root = tk.Tk()
    App(root, args.project)
    root.mainloop()
