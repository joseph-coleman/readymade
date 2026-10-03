"""The pybasic IDE: Toolbox, documents, Project Explorer, Properties and the
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
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from pybasic.formfile import FormFileError
from pybasic.ide.editors import FormEditor, ModuleEditor
from pybasic.ide.panels import ImmediateWindow, ProjectExplorer, PropertiesPanel, Toolbox
from pybasic.project import Project, ProjectError

_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])  # the folder containing pybasic/


class App:
    def __init__(self, root: tk.Tk, path: Path | None = None):
        self.root = root
        self.project: Project | None = None
        self.editors: list[FormEditor | ModuleEditor] = []
        self.form: FormEditor | None = None  # the form whose tab is showing
        self.process: subprocess.Popen | None = None
        self._output: queue.Queue = queue.Queue()
        self._console = _DesignTimeConsole(self)
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
        self.immediate = ImmediateWindow(outer, on_line=self.immediate_line)
        outer.add(top, weight=1)
        outer.add(self.immediate, weight=0)

        for sequence, command in (
            ("<Control-n>", self.new_project),
            ("<Control-o>", self.open_project),
            ("<Control-s>", self.save),
            ("<Control-w>", self.close_document),
            ("<F5>", self.run),
            ("<F7>", lambda: self.form and self.form.show_code()),
            ("<Shift-F7>", lambda: self.form and self.form.show_design()),
        ):
            root.bind(sequence, lambda e, c=command: (c(), "break")[1])
        root.protocol("WM_DELETE_WINDOW", self.exit)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file = tk.Menu(menubar, tearoff=False)
        file.add_command(label="New Project...", accelerator="Ctrl+N", command=self.new_project)
        file.add_command(label="Open Project...", accelerator="Ctrl+O", command=self.open_project)
        file.add_command(label="Save All", accelerator="Ctrl+S", command=self.save)
        file.add_command(label="Close", accelerator="Ctrl+W", command=self.close_document)
        file.add_separator()
        file.add_command(label="Exit", command=self.exit)
        project = tk.Menu(menubar, tearoff=False)
        project.add_command(label="Add Form...", command=self.add_form)
        project.add_command(label="Add Module...", command=self.add_module)
        project.add_command(label="Refresh", command=self.explorer_refresh)
        view = tk.Menu(menubar, tearoff=False)
        view.add_command(label="Code", accelerator="F7", command=lambda: self.form and self.form.show_code())
        view.add_command(label="Object", accelerator="Shift+F7", command=lambda: self.form and self.form.show_design())
        run = tk.Menu(menubar, tearoff=False)
        run.add_command(label="Start", accelerator="F5", command=self.run)
        run.add_command(label="End", command=self.stop)
        menubar.add_cascade(label="File", menu=file)
        menubar.add_cascade(label="Project", menu=project)
        menubar.add_cascade(label="View", menu=view)
        menubar.add_cascade(label="Run", menu=run)
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
        if self.project and self.project.settings().get("tool", {}).get("pybasic", {}).get("startup") == old:
            self.project.set_startup(new)
        self.explorer_refresh()
        self.update_title()

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
            answer = messagebox.askyesnocancel("pybasic", f"Save changes to {editor.name}?", parent=self.root)
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
            answer = messagebox.askyesnocancel("pybasic", "Save changes to the project?", parent=self.root)
            if answer is None or (answer and not self.save()):
                return False
        for editor in list(self.editors):
            self.close_document(editor, ask=False)  # already saved or discarded
        return True

    def is_dirty(self):
        return any(e.is_dirty() for e in self.editors)

    def save(self):
        """Save every changed document. Returns False if any failed."""
        ok = all([e.save() for e in list(self.editors) if e.is_dirty()])
        self.update_title()
        return ok

    def update_title(self):
        for editor in self.editors:
            self.documents.tab(editor.frame, text=editor.title())
        name = self.project.name if self.project else "No project"
        self.root.title(f"{name}{'*' if self.is_dirty() else ''} - pybasic")

    def exit(self):
        if self._close_all():
            self.stop()
            self.root.destroy()

    # ----- running -----

    def run(self):
        if self.project is None:
            return
        if self.process is not None:
            self.immediate.write("(The program is already running.)\n")
            return
        if not self.save():
            return
        folder = self.project.folder
        startup = self.project.startup
        if startup is None:
            self.immediate.write("(The project has no forms to run.)\n")
            return
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [_PACKAGE_ROOT, env.get("PYTHONPATH")]))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        process = subprocess.Popen(
            [sys.executable, "-m", "pybasic.run", "--immediate", "--startup", startup, str(folder)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", cwd=folder, env=env,
        )
        self.process = process
        threading.Thread(target=_pump, args=(process.stdout, self._output), daemon=True).start()
        self.immediate.write(f"--- Running {self.project.name} ({startup}). Type Python below to inspect it. ---\n")
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
                self.immediate.write(f"--- Ended (exit code {code}) ---\n")
                return
            self.immediate.write(item)
        self.root.after(50, self._poll_output)

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
    parser = argparse.ArgumentParser(prog="pybasic", description="A Visual Basic style IDE for Python.")
    parser.add_argument(
        "project", nargs="?", type=Path,
        help="a project folder (created if it doesn't exist), its pyproject.toml, or a .form file in it",
    )
    args = parser.parse_args(argv)
    root = tk.Tk()
    App(root, args.project)
    root.mainloop()
