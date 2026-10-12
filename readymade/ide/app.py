"""The readymade IDE: Toolbox, documents, Project Explorer, Properties and the
Immediate window in one Tk application.

App builds the window and owns what the IDE's parts share: the open project, the open
documents (editors.py), the running program and its link (process, session), and the
windows. Its jobs are each in their own module, with a reference back to it:

    app.runner  running.py       running the program, its output, Immediate lines
    app.debug   debugcontrol.py  break mode, breakpoints and watches (kept by breakpoints.py)
    app.files   projectfiles.py  renaming, removing, new files, bundling, outside changes
    app.envs    environments.py  interpreters, environments, libraries, Make EXE

What's left here: the window and its menus, documents, Edit, Find, F1 help and completion.
The Toolbox and Properties panel work on the form whose tab is showing.
"""

from __future__ import annotations

import argparse
import queue
import subprocess
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from readymade import events, formatting, menus
from readymade.formfile import FormFileError
from readymade.ide import PACKAGE_ROOT, assist, helptext, menubar, options
from readymade.ide.debugcontrol import DebugControl
from readymade.ide.dialog import ask_string
from readymade.ide.debugging import DebugSession
from readymade.ide.editors import FormEditor, ModuleEditor, ViewerEditor
from readymade.ide.environments import Environments
from readymade.ide.find import FindBar, FindInFilesPanel
from readymade.ide.linting import Linter
from readymade.ide.menueditor import MenuEditor
from readymade.ide.panels import (BreakpointsPanel, CallStackPanel, HelpPanel, ImmediateWindow, LocalsPanel,
                                  ProblemsPanel, ProjectExplorer, PropertiesPanel, Toolbox, WatchesPanel)
from readymade.ide.projectfiles import ProjectFiles
from readymade.ide.running import Runner
from readymade.project import Project, ProjectError


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
        # The IDE's jobs, each in its own module, sharing the state above and the windows below:
        self.runner = Runner(self)  # running the program (running.py)
        self.debug = DebugControl(self)  # break mode, breakpoints and watches (debugcontrol.py)
        self.files = ProjectFiles(self)  # the project's files: renaming, removing, bundling (projectfiles.py)
        self.envs = Environments(self)  # interpreters, environments, libraries, Make EXE (environments.py)
        self.linter = Linter(self)
        self.assistant = assist.Assistant(PACKAGE_ROOT) if assist.AVAILABLE else None
        self._completions: queue.Queue = queue.Queue()  # answers from the assistant's thread
        self.clipboard: list[dict] = []  # copied controls, for pasting into any form
        self.clipboard_handlers: list = []  # their event handlers, for Edit > Paste with Code
        self._build_ui()
        if path is not None:
            self.open_path(path)
        self.update_title()

    def _build_ui(self):
        root = self.root
        root.geometry("1180x740")
        if "clam" in ttk.Style(root).theme_names():
            ttk.Style(root).theme_use("clam")
        self.light_theme = ttk.Style(root).theme_use()  # the Light option's look; Dark is its own theme (options.py)
        menubar.build(self)  # the menus and their shortcuts (menubar.py)

        outer = ttk.PanedWindow(root, orient=tk.VERTICAL)
        outer.pack(fill=tk.BOTH, expand=True)
        top = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        self.toolbox = Toolbox(top, on_double_click=lambda t: self.form and self.form.add_control_centered(t))
        self.documents = ttk.Notebook(top)
        self.documents.bind("<<NotebookTabChanged>>", self.tab_changed)
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
        self.locals = LocalsPanel(self.debug_tabs, on_expand=lambda path: self.session and self.session.expand(path),
                                  on_assign=lambda path, text: self.session and self.session.assign(path, text))
        self.call_stack = CallStackPanel(self.debug_tabs, on_select=lambda i: self.session and self.session.choose_frame(i))
        self.watches_panel = WatchesPanel(self.debug_tabs, on_expand=lambda path: self.session and self.session.expand(path),
                                          on_edit=self.debug.edit_watch, on_delete=self.debug.delete_watch)
        self.debug_tabs.add(self.locals, text="Locals")
        self.debug_tabs.add(self.watches_panel, text="Watches")
        self.debug_tabs.add(self.call_stack, text="Call Stack")
        self.breakpoints_panel = BreakpointsPanel(
            self.debug_tabs, on_go=self.debug.go_to_breakpoint, on_switch=self.debug.switch_breakpoint,
            on_condition=lambda file, line: self.debug.breakpoint_condition(self.debug.open_breakpoint(file, line), line),
            on_remove=lambda file, line: self.debug.change_breakpoint(file, line, None),
            on_remove_all=self.debug.clear_breakpoints, on_watch=self.debug.breakpoints_tab_watch)
        self.debug_tabs.add(self.breakpoints_panel, text="Breakpoints")
        self.immediate = ImmediateWindow(self.bottom, on_line=self.runner.immediate_line)
        self.problems = ProblemsPanel(self.bottom, on_open=self.go_to_problem)
        self.help = HelpPanel(self.bottom)
        self.find_panel = FindInFilesPanel(self.bottom, search_files=self.files.search_files, on_open=self.go_to_found)
        self.bottom.add(self.immediate, text="Immediate")
        self.bottom.add(self.problems, text="Problems")
        self.bottom.add(self.help, text="Help")
        self.bottom.add(self.find_panel, text="Find")
        self.problems_changed()
        options.apply(self)  # the font, indent and colors chosen in Tools > Options
        if root.tk.call("tk", "windowingsystem") == "aqua":  # a Mac's app menu has Preferences... (⌘,)
            root.createcommand("::tk::mac::ShowPreferences", self.show_options)
        outer.add(top, weight=1)
        outer.add(self.bottom_area, weight=0)
        self.debug.update_debug_windows()

        root.protocol("WM_DELETE_WINDOW", self.exit)
        # Back from another program: look for files changed outside the IDE.
        root.bind("<FocusOut>", lambda e: root.after_idle(self.files.window_left), add="+")
        root.bind("<FocusIn>", lambda e: self.files.window_back(), add="+")

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
        self.watches_panel.show(self.debug.breakpoints.watches())
        self.debug.show_breakpoints()
        self.files.project_opened()
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
        name = ask_string(self, f"Add {kind}", f"{kind} name:", suggestion)
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

    def toggle_tab_order(self):
        """Format > Tab Order: click the form's controls in the order Tab should visit them
        (Esc, or the menu again, to finish)."""
        if not self.designing():
            return
        surface = self.form.surface
        if surface.tab_order_next is None:
            surface.start_tab_order()
            self.immediate.write("(Tab Order: click the controls in the order Tab should visit them; Esc when done.)\n")
        else:
            surface.stop_tab_order()

    def designing(self):
        """True while a form's Design tab is showing."""
        return self.form is not None and self.form.frame.select() == str(self.form.surface)

    def undo(self, redo=False):
        """Edit > Undo/Redo: the designer's when a form's design is showing, otherwise the code editor's."""
        editor = self.current_editor()
        if editor is not None and editor.showing_design():
            editor.redo() if redo else editor.undo()
        elif editor is not None:
            try:
                editor.code.text.edit_redo() if redo else editor.code.text.edit_undo()
            except tk.TclError:
                pass  # nothing to undo

    def undo_key(self, redo):
        """Ctrl+Z, Ctrl+Y: the designer's undo, unless typing in text, which has its own."""
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
        if form is not None and self.designing():
            if action in ("cut", "copy"):
                copied = form.copy_selection()
                if copied:
                    self.clipboard = copied
                    self.clipboard_handlers = form.copy_handlers(copied)  # for Paste with Code
                    if action == "cut":
                        form.delete_selection()
            elif action == "paste" and self.clipboard:
                form.paste(self.clipboard)
            elif action == "paste_code" and self.clipboard:
                form.paste(self.clipboard, self.clipboard_handlers)
                if form.handlers_left_out:
                    self.immediate.write(f"--- Not pasted, as the code already has them: "
                                         f"{', '.join(form.handlers_left_out)}. ---\n")
            elif action == "delete":
                form.delete_selection()
            return
        editor = self.current_editor()
        if editor is not None:
            event = {"cut": "<<Cut>>", "copy": "<<Copy>>", "paste": "<<Paste>>", "paste_code": "<<Paste>>",
                     "delete": "<<Clear>>"}[action]
            editor.code.text.event_generate(event)

    # ----- finding -----

    def _code_for_finding(self):
        """The code to find in: the code that's showing (a form's, switched to from its design)."""
        editor = self.current_editor()
        if editor is not None and editor.showing_design():
            editor.show_code()
        return editor

    def find(self, replace=False):
        """Edit > Find (Ctrl+F) and Replace (Ctrl+H; on a Mac Option+Command+F)."""
        editor = self._code_for_finding()
        if editor is not None:
            editor.code.show_find(replace=replace and not editor.read_only)

    def find_next(self, direction):
        editor = self._code_for_finding()
        if editor is not None:
            editor.code.find_next(direction)

    def find_in_files(self):
        """Edit > Find in Files (Ctrl+Shift+F): the Find tab, looking for the selected text."""
        text = ""
        editor = self.current_editor()
        if editor is not None and editor.code.text.tag_ranges("sel"):
            chosen = editor.code.text.get("sel.first", "sel.last")
            text = chosen if "\n" not in chosen else ""
        self.bottom.select(self.find_panel)
        self.find_panel.open(text)

    def go_to_found(self, path, line, column, length):
        """A Find in Files result: open its file there, with what was found selected."""
        relative = Path(path).relative_to(self.project.folder).as_posix()
        editor = self.files.open_file(relative)
        if editor is not None:
            editor.code.show_location(line, column, length)

    def toggle_comment(self):
        """Edit > Toggle Comment, in the code that's showing."""
        editor = self.current_editor()
        if editor is not None and not self.designing():
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
        editor = editor or self.current_editor()
        if editor is None or editor.plain or self._assist_unavailable(manual=True):
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
        elif found.kind in ("control", "menu") and editor.has_design:
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
        viewer = next((e for e in self.editors if e.read_only and e.path == path), None)
        if viewer is None:
            try:
                viewer = ViewerEditor(self, path)
            except OSError as e:
                self.immediate.write(f"(Couldn't open {path}: {e})\n")
                return None
            self.add_tab(viewer)
        self.documents.select(viewer.frame)
        self.tab_changed()
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
        """F1: help on whatever you're working on: the window with the keyboard (a bottom tab,
        the Project Explorer, the Toolbox), a property in the Properties panel, the designer's
        selection, the name at the cursor in the code, or else an overview."""
        try:
            focus = self.root.focus_get()
        except KeyError:
            focus = None
        form = self.form
        prop = self.properties.prop_with_focus(focus)
        place = self._panel_with(focus)
        if _inside(focus, (FindBar, FindInFilesPanel)) or place is self.find_panel:
            self.show_topic(helptext.finding())
        elif place is self.toolbox:
            tool = self.toolbox.tool
            self.show_topic(helptext.control(tool) if tool else helptext.panel("toolbox"))
        elif place is not None and place is not self.help:
            self.show_topic(helptext.panel(self._PANEL_TOPICS[type(place).__name__]))
        elif prop and form is not None and self.properties.current:
            spec = form.design.control(form.selected)
            self.show_topic(helptext.prop(spec["type"] if spec else "Form", prop))
        elif form is not None and self.designing():
            spec = form.design.control(form.selected)
            topic = helptext.control(spec["type"], spec["name"]) if spec else helptext.form(form.design.name)
            self.show_topic(topic)
        elif self.current_editor() is not None and not self.current_editor().plain:
            self.show_topic(self._code_help(self.current_editor()))
        else:
            self.show_topic(helptext.home())

    _PANEL_TOPICS = {"ImmediateWindow": "immediate", "ProblemsPanel": "problems", "ProjectExplorer": "explorer",
                     "LocalsPanel": "locals", "WatchesPanel": "watches", "CallStackPanel": "call stack",
                     "BreakpointsPanel": "breakpoints"}

    def _panel_with(self, widget):
        """The IDE window (a bottom tab, the Project Explorer, the Toolbox) a widget is in, or
        None. A tab strip with the keyboard counts as the tab it's showing."""
        for notebook in (self.bottom, self.debug_tabs):
            if widget is notebook:
                return notebook.nametowidget(notebook.select()) if notebook.select() else None
        panels = (self.immediate, self.problems, self.help, self.find_panel, self.watches_panel, self.locals,
                  self.call_stack, self.breakpoints_panel, self.explorer, self.toolbox)
        while widget is not None:
            if any(widget is panel for panel in panels):
                return widget
            widget = getattr(widget, "master", None)
        return None

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
        editor = self.current_editor()
        if editor is not None and self.project is not None and not editor.read_only:
            if not formatting.tools_for(self.project):
                self.immediate.write("(No formatter is chosen for this project: see Project > Formatting...)\n")
            else:
                self.format_code(editor)

    def format_code(self, editor):
        """Format an open document's code with the project's formatters (one undo step).
        Returns False, leaving the code as it was, if a formatter couldn't."""
        tools = formatting.tools_for(self.project)
        if not tools or editor.plain:
            return True
        source = editor.code.get_source()
        self.root.configure(cursor="watch")
        self.root.update_idletasks()
        try:
            formatted, trouble = formatting.format_source(
                tools, self.envs.python()[0], self.project.folder, editor.code_path, source, self.runner.environment())
        finally:
            self.root.configure(cursor="")
        if trouble:
            self.immediate.write(f"--- {trouble} ---\n")
            return False
        editor.code.replace_keeping_place(formatted)
        return True

    def clipboard_key(self, action):
        """Ctrl+X/C/V act on controls only while the design surface has the keyboard;
        anywhere else (code, Properties, Immediate) they're the usual text keys."""
        try:
            focus = self.root.focus_get()
        except KeyError:
            focus = None
        if self.form is None or not self.designing() or focus is None or not str(focus).startswith(str(self.form.surface)):
            return None
        self.edit(action)
        return "break"

    def menu_editor(self):
        """Open the Menu Editor for the form that's showing."""
        return MenuEditor(self, self.form) if self.form else None

    # ----- documents -----

    def editor_of(self, kind, name):
        return next((e for e in self.editors if isinstance(e, kind) and e.name == name), None)

    def open_form(self, name, view="design"):
        editor = self.editor_of(FormEditor, name)
        if editor is None:
            if self.project is None:
                return None
            try:
                editor = FormEditor(self, self.project.folder / f"{name}.form")
            except (OSError, ValueError, FormFileError) as e:
                messagebox.showerror("Open Form", str(e), parent=self.root)
                return None
            self.add_tab(editor)
        if view == "code":
            editor.show_code()
        else:
            editor.show_design()
        self.tab_changed()  # don't wait for <<NotebookTabChanged>>, which may arrive later
        return editor

    def open_module(self, name):
        editor = self.editor_of(ModuleEditor, name)
        if editor is None:
            if self.project is None:
                return None
            try:
                editor = ModuleEditor(self, self.project.folder / f"{name}.py")
            except OSError as e:
                messagebox.showerror("Open Module", str(e), parent=self.root)
                return None
            self.add_tab(editor)
        self.documents.select(editor.frame)
        self.tab_changed()
        return editor

    def add_tab(self, editor):
        self.editors.append(editor)
        self.documents.add(editor.frame, text=editor.title())
        if editor.plain:
            return  # another file, like a README: plain text
        editor.code.on_complete = lambda code, manual: self.complete(editor, manual)
        editor.code.on_goto = lambda code, index: self.go_to_definition(editor, index)
        if not editor.read_only:
            # Soon after typing stops: check the code, and show the Breakpoints tab where they've moved to.
            editor.code.on_change = lambda: (self.linter.check(editor), self.debug.show_breakpoints())
            editor.code.on_edited = lambda code=editor.code: self.debug.code_edited(code)
            editor.code.on_hover = lambda expression, x, y, code=editor.code: self.debug.hovered(code, expression, x, y)
            editor.code.on_set_next = lambda line, editor=editor: self.debug.set_next_statement(editor, line)
            self.linter.check(editor, saved=True)
            editor.code.on_breakpoints = self.debug.breakpoints_changed
            editor.code.on_gutter_menu = lambda line, e, editor=editor: self.debug.gutter_menu(editor, line, e)
            editor.code.set_breakpoints(self.debug.breakpoints.in_file(self.project.relative(editor.code_path)))

    def code_editor(self):
        """The editor whose code is showing, or None (a form's design, or nothing)."""
        editor = self.current_editor()
        if editor is not None and editor.showing_design():
            return None
        return editor

    def current_editor(self):
        try:
            frame = self.documents.nametowidget(self.documents.select())
        except (KeyError, tk.TclError):  # no tabs
            return None
        return next((e for e in self.editors if e.frame is frame), None)

    def tab_changed(self, _=None):
        editor = self.current_editor()
        self.form = editor if editor is not None and editor.has_design else None
        self.properties.attach(self.form)
        self.update_title()

    def close_document(self, editor=None, ask=True):
        """Close a document (default: the current one), asking to save changes."""
        editor = editor or self.current_editor()
        if editor is None:
            return True
        if ask and editor.is_dirty():
            answer = messagebox.askyesnocancel("readymade", f"Save changes to {editor.name}?", parent=self.root)
            if answer is None or (answer and not editor.save()):
                return False
        if self.properties.app is editor:
            self.properties.attach(None)
        if not editor.is_dirty():  # (changes thrown away: its breakpoints stay where the saved code has them)
            self.debug.breakpoints.store()
        self.editors.remove(editor)
        self.documents.forget(editor.frame)
        editor.frame.destroy()
        self.tab_changed()
        self.debug.show_breakpoints()
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
        self.debug.breakpoints.store()  # where they are now that lines have moved
        if any(e.has_design for e in changed):
            self.explorer_refresh()  # (the pictures forms show are bundled: the Files list marks them)
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
            self.runner.stop()
            self.root.destroy()


def _inside(widget, kinds):
    """Whether a widget is one of kinds, or inside one."""
    while widget is not None:
        if isinstance(widget, kinds):
            return True
        widget = getattr(widget, "master", None)
    return False


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
