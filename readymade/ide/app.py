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

from readymade import events, formatting, menus, package
from readymade.formfile import FormFileError
from readymade.ide import assist
from readymade.ide.editors import FormEditor, ModuleEditor, ViewerEditor
from readymade.ide.linting import Linter
from readymade.ide.menueditor import MenuEditor
from readymade.ide import helptext
from readymade.ide.panels import HelpPanel, ImmediateWindow, ProjectExplorer, PropertiesPanel, Toolbox
from readymade.ide.tooldialog import formatting_dialog, linting_dialog
from readymade.ide.tracebacks import TracebackWatcher
from readymade.project import Project, ProjectError, describe_python, find_pythons

_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])  # the folder containing readymade/
_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")  # terminal colour and cursor codes


class App:
    def __init__(self, root: tk.Tk, path: Path | None = None):
        self.root = root
        events.collect_garbage_on(root)  # the IDE's threads mustn't free Tk objects (see events.py)
        self.project: Project | None = None
        self.editors: list[FormEditor | ModuleEditor] = []
        self.form: FormEditor | None = None  # the form whose tab is showing
        self.process: subprocess.Popen | None = None  # the running program, or venv/pip
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
        # Below: the Immediate window, and F1's help.
        self.bottom = ttk.Notebook(outer)
        self.immediate = ImmediateWindow(self.bottom, on_line=self.immediate_line)
        self.help = HelpPanel(self.bottom)
        self.bottom.add(self.immediate, text="Immediate")
        self.bottom.add(self.help, text="Help")
        outer.add(top, weight=1)
        outer.add(self.bottom, weight=0)

        for sequence, command in (
            ("<Control-n>", self.new_project),
            ("<Control-o>", self.open_project),
            ("<Control-s>", self.save),
            ("<Control-w>", self.close_document),
            ("<Control-e>", self.menu_editor),
            ("<F5>", self.run),
            ("<F7>", lambda: self.form and self.form.show_code()),
            ("<Shift-F7>", lambda: self.form and self.form.show_design()),
        ):
            root.bind(sequence, lambda e, c=command: (c(), "break")[1])
        root.bind(menus.shortcut_sequence("Alt+Shift+F"), lambda e: (self.format_document(), "break")[1])
        root.bind("<F12>", lambda e: (self.go_to_definition(), "break")[1])
        root.bind("<F1>", lambda e: (self.show_help(), "break")[1])
        for sequence, redo in (("<Control-z>", False), ("<Control-y>", True), ("<Control-Z>", True)):
            root.bind(sequence, lambda e, r=redo: self._undo_key(r))
        for sequence, action in (("<Control-x>", "cut"), ("<Control-c>", "copy"), ("<Control-v>", "paste")):
            root.bind(sequence, lambda e, a=action: self._clipboard_key(a))
        root.protocol("WM_DELETE_WINDOW", self.exit)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file = tk.Menu(menubar, tearoff=False)
        file.add_command(label="New Project...", accelerator="Ctrl+N", command=self.new_project)
        file.add_command(label="Open Project...", accelerator="Ctrl+O", command=self.open_project)
        file.add_command(label="Save All", accelerator="Ctrl+S", command=self.save)
        file.add_command(label="Close", accelerator="Ctrl+W", command=self.close_document)
        file.add_separator()
        file.add_command(label="Make EXE...", command=self.make_exe)
        file.add_separator()
        file.add_command(label="Exit", command=self.exit)
        edit = tk.Menu(menubar, tearoff=False, postcommand=lambda: self._update_edit_menu(edit))
        edit.add_command(label="Undo", accelerator="Ctrl+Z", command=self.undo)
        edit.add_command(label="Redo", accelerator="Ctrl+Y", command=lambda: self.undo(redo=True))
        edit.add_separator()
        for label, action, key in (("Cut", "cut", "Ctrl+X"), ("Copy", "copy", "Ctrl+C"),
                                   ("Paste", "paste", "Ctrl+V"), ("Delete", "delete", "Del")):
            edit.add_command(label=label, accelerator=key, command=lambda a=action: self.edit(a))
        edit.add_separator()
        edit.add_command(label="Toggle Comment", accelerator="Ctrl+/", command=self.toggle_comment)
        edit.add_command(label="Format Document", accelerator="Shift+Alt+F", command=self.format_document)
        edit.add_command(label="Go to Definition", accelerator="F12", command=self.go_to_definition)
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
        view = tk.Menu(menubar, tearoff=False)
        view.add_command(label="Code", accelerator="F7", command=lambda: self.form and self.form.show_code())
        view.add_command(label="Object", accelerator="Shift+F7", command=lambda: self.form and self.form.show_design())
        tools = tk.Menu(menubar, tearoff=False)
        tools.add_command(label="Menu Editor...", accelerator="Ctrl+E", command=self.menu_editor)
        run = tk.Menu(menubar, tearoff=False)
        run.add_command(label="Start", accelerator="F5", command=self.run)
        run.add_command(label="End", command=self.stop)
        menubar.add_cascade(label="File", menu=file)
        menubar.add_cascade(label="Edit", menu=edit)
        menubar.add_cascade(label="Format", menu=format_menu)
        menubar.add_cascade(label="Project", menu=project)
        menubar.add_cascade(label="View", menu=view)
        menubar.add_cascade(label="Tools", menu=tools)
        menubar.add_cascade(label="Run", menu=run)
        help_menu = tk.Menu(menubar, tearoff=False)
        help_menu.add_command(label="Help on This", accelerator="F1", command=self.show_help)
        help_menu.add_command(label="readymade Overview", command=lambda: self.show_topic(helptext.home()))
        menubar.add_cascade(label="Help", menu=help_menu)
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
            target = self._open_code(found.path)
            if target is not None:
                target.code.show_location(found.line, found.column, len(found.name))

    def _show_menu_item(self, editor, name):
        dialog = self.menu_editor()
        if dialog is not None:
            item = next((i for i in menus.walk(dialog.items) if i.get("name") == name), None)
            if item is not None:
                dialog.tree.selection_set(str(id(item)))
                dialog.tree.see(str(id(item)))

    def _open_code(self, path):
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
        self.editors.remove(editor)
        self.documents.forget(editor.frame)
        editor.frame.destroy()
        self._tab_changed()
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
        for editor in changed:
            self.linter.check(editor, saved=True)
        self.update_title()
        return ok

    def update_title(self):
        for editor in self.editors:
            self.documents.tab(editor.frame, text=editor.title())
        name = self.project.name if self.project else "No project"
        self.root.title(f"{name}{'*' if self.is_dirty() else ''} - readymade")

    def exit(self):
        if self._close_all():
            self.stop()
            self.root.destroy()

    # ----- running -----

    def run(self):
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
        self._start([str(python), "-m", "readymade.run", "--immediate", "--startup", startup, str(folder)], interactive=True)
        self._watcher = TracebackWatcher(folder, self.show_error)

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
        # Plain text only: the Immediate window can't show colours, and the IDE reads the
        # tracebacks and tool output, which colour codes (e.g. from FORCE_COLOR) would garble.
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
                if self._on_exit:
                    self._on_exit(code)
                else:
                    self.immediate.write(f"--- Ended (exit code {code}) ---\n")
                return
            item = _ANSI.sub("", item)  # in case a program prints colours itself
            self.immediate.write(item)
            if self._watcher:
                self._watcher.feed(item)
        self.root.after(50, self._poll_output)

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

            self._start([str(python), *package.pyinstaller_args(project, launcher, _PACKAGE_ROOT)], on_exit=built)

        def with_pyinstaller():
            # Quietly check whether the environment has PyInstaller; install it if not.
            check = "import importlib.util, sys; sys.exit(importlib.util.find_spec('PyInstaller') is None)"
            self._start([str(project.python()), "-c", check], on_exit=lambda code: build() if code == 0 else self._pip_install(
                ["pyinstaller"], build, failed="pip couldn't install PyInstaller, so the program wasn't made."))

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

    def _library_added(self, requirement):
        self.project.add_dependency(requirement)
        self.explorer_refresh()
        self.immediate.write(f"--- Added {requirement} to the project. ---\n")

    def immediate_line(self, line):
        self.immediate.write(f">>> {line}\n")
        if line.lstrip().startswith("?"):  # VB's `? expr` prints the expression
            line = f"print({line.lstrip()[1:].strip()})"
        if self.process is None or self.process.stdin is None:
            self._console.push(line)
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
    """Runs Immediate window lines inside the IDE when no program is running."""

    def __init__(self, app):
        super().__init__({"__name__": "__immediate__"})
        self.stream = _ImmediateStream(app)

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
