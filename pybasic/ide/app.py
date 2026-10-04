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
import shutil
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog, ttk

from pybasic.formfile import FormFileError
from pybasic.ide.editors import FormEditor, ModuleEditor
from pybasic.ide.menueditor import MenuEditor
from pybasic.ide.panels import ImmediateWindow, ProjectExplorer, PropertiesPanel, Toolbox
from pybasic.ide.tracebacks import TracebackWatcher
from pybasic.project import Project, ProjectError, describe_python, find_pythons

_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])  # the folder containing pybasic/


class App:
    def __init__(self, root: tk.Tk, path: Path | None = None):
        self.root = root
        self.project: Project | None = None
        self.editors: list[FormEditor | ModuleEditor] = []
        self.form: FormEditor | None = None  # the form whose tab is showing
        self.process: subprocess.Popen | None = None  # the running program, or venv/pip
        self._on_exit = None
        self._watcher: TracebackWatcher | None = None  # finds errors in the running program's output
        self._output: queue.Queue = queue.Queue()
        self._console = _DesignTimeConsole(self)
        self._python_info: dict[str, str] = {}  # interpreter path -> describe_python(), which is slow
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
            ("<Control-e>", self.menu_editor),
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
        project.add_separator()
        project.add_command(label="Create Environment...", command=self.ask_create_environment)
        project.add_command(label="Add Library...", command=self.add_library)
        project.add_separator()
        project.add_command(label="Choose Python Interpreter...", command=self.choose_python)
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
        menubar.add_cascade(label="Project", menu=project)
        menubar.add_cascade(label="View", menu=view)
        menubar.add_cascade(label="Tools", menu=tools)
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

    def python(self):
        """The project's interpreter and where it came from, for running and for display."""
        path = self.project.python() if self.project else None
        if path is None:
            return Path(sys.executable), "IDE"
        configured = self.project.setting("python") if self.project else None
        return path, configured or ".venv"

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
        if self.project and self.project.settings().get("tool", {}).get("pybasic", {}).get("startup") == old:
            self.project.set_startup(new)
        self.explorer_refresh()
        self.update_title()

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
        if not python.exists():
            self.immediate.write(f"(The project's Python, {python}, doesn't exist. Choose another in the Project menu.)\n")
            return
        for editor in self.editors:
            editor.code.clear_error()
        self.immediate.write(f"--- Running {self.project.name} ({startup}, Python: {where}). Type Python below to inspect it. ---\n")
        self._start([str(python), "-m", "pybasic.run", "--immediate", "--startup", startup, str(folder)], interactive=True)
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

    def _idle(self):
        if self.process is None:
            return True
        self.immediate.write("(Busy: wait for the program or install to finish, or use Run > End.)\n")
        return False

    def _start(self, args, interactive=False, on_exit=None):
        """Run a program or tool in the project folder, showing its output in the Immediate
        window. on_exit(exit code) runs when it ends; by default the code is reported."""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [_PACKAGE_ROOT, env.get("PYTHONPATH")]))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
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

    def _pip_install(self, requirements, on_success):
        python = self.project.python() if self.project else None
        if python is None:
            return
        self.immediate.write(f"--- Installing {', '.join(requirements)} ---\n")
        self._start(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off", *requirements],
            on_exit=lambda code: on_success() if code == 0 else self.immediate.write("--- pip couldn't install it, so nothing was added. ---\n"),
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
    parser = argparse.ArgumentParser(prog="pybasic", description="A Visual Basic style IDE for Python.")
    parser.add_argument(
        "project", nargs="?", type=Path,
        help="a project folder (created if it doesn't exist), its pyproject.toml, or a .form file in it",
    )
    args = parser.parse_args(argv)
    root = tk.Tk()
    App(root, args.project)
    root.mainloop()
