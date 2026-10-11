"""The Python that runs the project: choosing an interpreter, creating an environment (.venv),
adding and removing libraries with pip, and Make EXE (PyInstaller, in that environment)."""

from __future__ import annotations

import shutil
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from readymade import package
from readymade.ide import PACKAGE_ROOT
from readymade.ide.dialog import Dialog, ask_string
from readymade.ide.makeexe import MakeExeDialog
from readymade.project import ProjectError, describe_python, find_pythons, requirement_name
from readymade.ide.part import Part


class Environments(Part):
    def __init__(self, app):
        super().__init__(app)
        self._python_info: dict[str, str] = {}  # interpreter path -> describe_python(), which is slow

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
        self.app.explorer_refresh()

    def ask_create_environment(self):
        """Choose a Python to base the project's .venv on, then create it."""
        if self.project is None or not self.app.runner.idle():
            return
        pythons = [(f"Python {describe_python(p)}   {p}", p) for p in find_pythons()]
        dialog = Dialog(self.app, "Create Environment", padding=8)
        ttk.Label(dialog.body, text="Make a .venv for this project from:").pack(anchor="w", pady=(0, 2))
        row = ttk.Frame(dialog.body)
        row.pack(fill=tk.X)
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
        dialog.ok = create
        dialog.add_buttons(ok="Create")
        dialog.grab_set()

    def create_environment(self, base, then=None):
        """Make the project's .venv from the base interpreter with venv (or uv if venv
        fails and uv is installed), install the project's libraries, and use it."""
        project = self.project
        if project is None or not self.app.runner.idle():
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
            self.app.runner.start_process(
                [uv, "venv", "--seed", "--python", str(base), str(venv)],
                on_exit=lambda c: ready() if c == 0 else self.immediate.write("--- Couldn't create the environment. ---\n"))

        def ready():
            project.set_python(None)  # the new .venv is used from now on
            self._python_info.clear()
            self.app.explorer_refresh()

            def done():
                self.immediate.write("--- The environment is ready. ---\n")
                if then:
                    then()

            if project.dependencies:
                self.pip_install(project.dependencies, done)
            else:
                done()

        self.immediate.write(f"--- Creating .venv from Python {describe_python(base)} ---\n")
        self.app.runner.start_process([str(base), "-m", "venv", "--clear", str(venv)], on_exit=created)

    def add_library(self, requirement=None):
        """pip install a library into the project's environment, and list it in pyproject.toml."""
        if self.project is None or not self.app.runner.idle():
            return
        if requirement is None:
            requirement = ask_string(self.app, "Add Library", "Library to install from PyPI (for example: requests):")
        requirement = (requirement or "").strip()
        if not requirement:
            return
        if requirement.startswith("-"):
            messagebox.showerror("Add Library", "Enter a library name, not a pip option.", parent=self.root)
            return

        def install():
            self.pip_install([requirement], lambda: self._library_added(requirement))

        if self.project.python() is not None:
            install()
        elif messagebox.askyesno(
            "Add Library",
            "This project doesn't have its own environment yet, so the library would go into the "
            "IDE's Python. Create one (.venv) first?",
            parent=self.root,
        ):
            self.create_environment(find_pythons()[0], then=install)

    def remove_library(self, requirement):
        python = self.project.python()
        library = requirement_name(requirement)
        where = ("It will also be uninstalled from the project's environment (libraries it brought with it stay)."
                 if python is not None else "The project uses the IDE's Python, so it stays installed there.")
        if not messagebox.askyesno("Remove Library", f"Remove {requirement} from the project's libraries? {where}",
                                   icon="warning", default="no", parent=self.root):
            return False
        self.project.remove_dependency(requirement)
        self.app.explorer_refresh()
        if python is None or not self.python_exists(python):
            self.immediate.write(f"--- Removed {requirement} from the project. ---\n")
            return True

        def uninstalled(code):
            if code == 0:
                self.immediate.write(f"--- Removed {requirement} from the project. ---\n")
            else:
                self.immediate.write(f"--- pip couldn't uninstall {library}, but it's no longer one of the project's libraries. ---\n")

        self.immediate.write(f"--- Uninstalling {library} ---\n")
        self.app.runner.start_process(
            [str(python), "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", library], on_exit=uninstalled)
        return True

    def _library_added(self, requirement):
        self.project.add_dependency(requirement)
        self.app.explorer_refresh()
        self.immediate.write(f"--- Added {requirement} to the project. ---\n")

    def pip_install(self, requirements, on_success, failed="pip couldn't install it, so nothing was added."):
        python = self.project.python() if self.project else None
        if python is None or not self.python_exists(python):
            return
        self.immediate.write(f"--- Installing {', '.join(requirements)} ---\n")
        self.app.runner.start_process(
            [str(python), "-m", "pip", "install", "--disable-pip-version-check", "--progress-bar", "off", *requirements],
            on_exit=lambda code: on_success() if code == 0 else self.immediate.write(f"--- {failed} ---\n"),
        )

    def python_exists(self, python):
        if python.exists():
            return True
        self.immediate.write(f"(The project's Python, {python}, doesn't exist. Choose another in the Project menu.)\n")
        return False

    def make_exe(self, ask=True):
        """File > Make EXE...: the program's details (a dialog, unless ask is False), then
        package the project as a program that runs without Python, using PyInstaller in the
        project's own environment (creating one, and installing PyInstaller, if needed)."""
        project = self.project
        if project is None or not self.app.runner.idle() or not self.app.save():
            return None
        if ask:
            return MakeExeDialog(self.app, on_make=lambda: self.make_exe(ask=False))
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
                if code != 0:
                    self.immediate.write("--- PyInstaller couldn't make the program; its messages are above. ---\n")
                    return
                if sys.platform == "darwin":
                    try:
                        package.set_mac_details(project)
                    except (OSError, ValueError) as e:
                        self.immediate.write(f"(Couldn't put the version in the app's Info.plist: {e})\n")
                if not package.details(project)["notices"]:
                    self.immediate.write(f"--- Done: {target} ---\n")
                    return
                notices = package.notices_path(project)
                self.app.runner.start_process(
                    [str(python), "-m", "readymade.notices", str(notices), package.details(project)["name"],
                     *project.dependencies], on_exit=lambda code: self.immediate.write(
                    f"--- Done: {target}, with its license notices in {notices.name} ---\n" if code == 0 else
                    f"--- Done: {target} (but its license notices couldn't be written: see above) ---\n"))

            try:
                args = package.pyinstaller_args(project, launcher, PACKAGE_ROOT)
            except OSError as e:  # the icon couldn't be converted
                self.immediate.write(f"--- Couldn't make the program's icon from {project.setting('icon')}: {e} ---\n")
                return
            self.app.runner.start_process([str(python), *args], on_exit=built)

        def with_pyinstaller():
            # Quietly check whether the environment has PyInstaller (and Pillow, if the icon
            # needs converting to the system's own format); install them if not.
            needs = {"PyInstaller": "pyinstaller", **({"PIL": "pillow"} if package.icon_needs_pillow(project) else {})}
            check = f"import importlib.util, sys; sys.exit(any(importlib.util.find_spec(m) is None for m in {list(needs)!r}))"
            self.app.runner.start_process(
                [str(project.python()), "-c", check], on_exit=lambda code: build() if code == 0 else self.pip_install(
                    list(needs.values()), build, failed="pip couldn't install what Make EXE needs, so the program wasn't made."))

        python = project.python()
        if python is not None:
            if self.python_exists(python):
                with_pyinstaller()
        elif messagebox.askyesno(
            "Make EXE",
            "A program is made from the project's own environment, and this project doesn't "
            "have one yet. Create it (.venv) now?",
            parent=self.root,
        ):
            self.create_environment(find_pythons()[0], then=with_pyinstaller)
