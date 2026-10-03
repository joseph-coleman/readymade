"""The pybasic IDE: toolbox, form designer, code window, properties panel and
Immediate window in one Tk application.

App owns the document (a FormDesign and its source code) and the running
program. The panels call back into it, and it keeps them in sync.
"""

from __future__ import annotations

import argparse
import code
import contextlib
import keyword
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from pybasic import codegen, formfile
from pybasic.controls import REGISTRY
from pybasic.form import FORM, FORM_EVENTS, check_name
from pybasic.ide.codeview import CodeView
from pybasic.ide.designer import GRID, DesignSurface, snap
from pybasic.ide.panels import ImmediateWindow, PropertiesPanel, Toolbox

_PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])  # the folder containing pybasic/


class App:
    def __init__(self, root: tk.Tk, path: Path | None = None):
        self.root = root
        self.path: Path | None = None
        self.design = formfile.FormDesign()
        self.selected = FORM
        self.process: subprocess.Popen | None = None
        self._output: queue.Queue = queue.Queue()
        self._saved: tuple[str, str | None] = ("", None)
        self._console = _DesignTimeConsole(self)
        self._build_ui()
        if path is None or not path.exists() or not self._open_path(path):
            self._start_new(path)

    def _build_ui(self):
        root = self.root
        root.geometry("1100x720")
        if "clam" in ttk.Style().theme_names():
            ttk.Style().theme_use("clam")
        self._build_menu()

        outer = ttk.PanedWindow(root, orient=tk.VERTICAL)
        outer.pack(fill=tk.BOTH, expand=True)
        top = ttk.PanedWindow(outer, orient=tk.HORIZONTAL)
        self.toolbox = Toolbox(top, on_double_click=self.add_control_centered)
        self.notebook = ttk.Notebook(top)
        self.surface = DesignSurface(self.notebook, self)
        self.code = CodeView(self.notebook, self)
        self.notebook.add(self.surface, text="Design")
        self.notebook.add(self.code, text="Code")
        self.properties = PropertiesPanel(top, self)
        top.add(self.toolbox, weight=0)
        top.add(self.notebook, weight=1)
        top.add(self.properties, weight=0)
        self.immediate = ImmediateWindow(outer, on_line=self.immediate_line)
        outer.add(top, weight=1)
        outer.add(self.immediate, weight=0)

        for sequence, command in (
            ("<Control-n>", self.new),
            ("<Control-o>", self.open),
            ("<Control-s>", self.save),
            ("<F5>", self.run),
            ("<F7>", self.show_code),
            ("<Shift-F7>", self.show_design),
        ):
            root.bind(sequence, lambda e, c=command: (c(), "break")[1])
        root.protocol("WM_DELETE_WINDOW", self.exit)

    def _build_menu(self):
        menubar = tk.Menu(self.root)
        file = tk.Menu(menubar, tearoff=False)
        file.add_command(label="New", accelerator="Ctrl+N", command=self.new)
        file.add_command(label="Open...", accelerator="Ctrl+O", command=self.open)
        file.add_command(label="Save", accelerator="Ctrl+S", command=self.save)
        file.add_command(label="Save As...", command=self.save_as)
        file.add_separator()
        file.add_command(label="Exit", command=self.exit)
        view = tk.Menu(menubar, tearoff=False)
        view.add_command(label="Code", accelerator="F7", command=self.show_code)
        view.add_command(label="Object", accelerator="Shift+F7", command=self.show_design)
        run = tk.Menu(menubar, tearoff=False)
        run.add_command(label="Start", accelerator="F5", command=self.run)
        run.add_command(label="End", command=self.stop)
        menubar.add_cascade(label="File", menu=file)
        menubar.add_cascade(label="View", menu=view)
        menubar.add_cascade(label="Run", menu=run)
        self.root.configure(menu=menubar)

    # ----- the document -----

    def object_names(self):
        return [FORM] + [c["name"] for c in self.design.controls]

    def events_for(self, obj):
        if obj == FORM:
            return FORM_EVENTS
        spec = self.design.control(obj)
        return REGISTRY[spec["type"]].events if spec else ()

    def props_for(self, obj):
        if obj == FORM:
            d = self.design
            return [("name", d.name), ("text", d.text), ("width", d.width), ("height", d.height)]
        spec = self.design.control(obj)
        if spec is None:
            return []
        defaults = REGISTRY[spec["type"]].prop_defaults()
        return [("name", obj)] + [(prop, spec.get(prop, default)) for prop, default in defaults.items()]

    def select(self, obj):
        self.selected = obj
        self.surface.show_selection(obj)
        self.properties.show(obj)

    def set_property(self, obj, prop, raw):
        """Apply an edit from the Properties panel. Returns the object's (possibly new) name, or None if invalid."""
        current = dict(self.props_for(obj))[prop]
        try:
            value = _convert(raw, type(current))
            if prop in ("width", "height") and value < GRID:
                raise ValueError(f"{prop} must be at least {GRID}")
            if prop == "name":
                obj = self._rename(obj, value)
            elif obj == FORM:
                setattr(self.design, prop, value)
                self.surface.refresh_form()
            else:
                self.design.control(obj)[prop] = value
                self.surface.refresh_control(obj)
        except ValueError as e:
            messagebox.showerror("Invalid property value", str(e), parent=self.root)
            return None
        self.update_title()
        return obj

    def _rename(self, obj, new):
        if new == obj:
            return obj
        source = self.code.get_source()
        if obj == FORM:
            if not new.isidentifier() or keyword.iskeyword(new):
                raise ValueError(f"{new!r} is not a valid Python name")
            self.code.replace_source(codegen.rename_class(source, self.design.name, new))
            self.design.name = new
            return FORM
        check_name(new, [n for n in self.object_names() if n != obj])
        spec = self.design.control(obj)
        spec["name"] = new
        events = [e.name for e in REGISTRY[spec["type"]].events]
        self.code.replace_source(codegen.rename_control(source, obj, new, events))
        self.surface.rename(obj, new)
        self.selected = new
        self.properties.refresh_objects()
        self.code.refresh_objects()
        return new

    def geometry_changed(self, name, geometry):
        self.design.control(name).update(zip(("left", "top", "width", "height"), geometry))
        self.properties.update_values()
        self.update_title()

    def set_form_size(self, width, height):
        self.design.width, self.design.height = width, height
        self.surface.refresh_form()
        self.properties.update_values()
        self.update_title()

    def add_control(self, type_name, left, top, width=None, height=None):
        names = set(self.object_names())
        n = 1
        while f"{type_name}{n}" in names:
            n += 1
        spec = REGISTRY[type_name].new_spec(f"{type_name}{n}", left, top, width, height)
        self.design.controls.append(spec)
        self.surface.add(spec)
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(spec["name"])
        self.update_title()

    def add_control_centered(self, type_name):
        width, height = REGISTRY[type_name].default_size
        self.toolbox.reset()
        self.add_control(type_name, snap((self.design.width - width) / 2), snap((self.design.height - height) / 2))

    def delete_control(self, name):
        # Like VB, the control's handlers stay in the code.
        self.design.controls.remove(self.design.control(name))
        self.surface.remove(name)
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(FORM)
        self.update_title()

    def goto_handler(self, obj, event_name):
        """Show the handler for obj's event in the code window, creating it if needed."""
        event = next(e for e in self.events_for(obj) if e.name == event_name)
        method = f"{obj}_{event.name}"
        line = codegen.find_method(self.code.get_source(), method)
        if line is None:
            try:
                edit = codegen.add_method(self.code.get_source(), self.design.name, method, event.params)
            except codegen.CodeGenError as e:
                messagebox.showerror("Code", str(e), parent=self.root)
                return
            self.code.apply_edit(edit)
            line = edit.method_line
        self.show_code()
        self.code.show_method(obj, event.name, line)

    def show_code(self):
        self.code.refresh_objects()
        self.notebook.select(self.code)

    def show_design(self):
        self.notebook.select(self.surface)

    # ----- files -----

    def is_dirty(self):
        return (formfile.dumps(self.design), self.code.get_source()) != self._saved

    def update_title(self):
        name = self.path.name if self.path else "(untitled)"
        self.root.title(f"{name}{'*' if self.is_dirty() else ''} - pybasic")

    def _set_document(self, path, design, source, saved_source):
        self.properties.clear()
        # Absolute, so the path still works when the program runs in the form's own folder.
        self.path, self.design = (path.resolve() if path else None), design
        self.surface.rebuild()
        self.code.set_source(source)
        self._saved = (formfile.dumps(design), saved_source)
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(FORM)
        self.show_design()
        self.update_title()

    def _start_new(self, path=None):
        design = formfile.FormDesign()
        if path is not None and path.stem.isidentifier() and not keyword.iskeyword(path.stem):
            design.name = design.text = path.stem
        source = codegen.new_module(design.name)
        self._set_document(path, design, source, source)

    def _open_path(self, path):
        try:
            design = formfile.load(path)
            code_path = path.with_suffix(".py")
            saved = code_path.read_text(encoding="utf-8") if code_path.exists() else None
        except (OSError, formfile.FormFileError) as e:
            messagebox.showerror("Open", str(e), parent=self.root)
            return False
        self._set_document(path, design, saved if saved is not None else codegen.new_module(design.name), saved)
        return True

    def _confirm_discard(self):
        """True if it's OK to throw away the current document."""
        if not self.is_dirty():
            return True
        name = self.path.name if self.path else "this form"
        answer = messagebox.askyesnocancel("pybasic", f"Save changes to {name}?", parent=self.root)
        return self.save() if answer else answer is False

    def new(self):
        if self._confirm_discard():
            self._start_new()

    def open(self):
        if not self._confirm_discard():
            return
        filename = filedialog.askopenfilename(
            parent=self.root, filetypes=[("pybasic forms", "*.form"), ("All files", "*")]
        )
        if filename:
            self._open_path(Path(filename))

    def save(self):
        if self.path is None:
            return self.save_as()
        self.properties.commit_all()
        source = self.code.get_source()
        try:
            formfile.save(self.design, self.path)
            self.path.with_suffix(".py").write_text(source, encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Save", str(e), parent=self.root)
            return False
        self._saved = (formfile.dumps(self.design), source)
        self.update_title()
        return True

    def save_as(self):
        filename = filedialog.asksaveasfilename(
            parent=self.root, defaultextension=".form", initialfile=f"{self.design.name}.form",
            filetypes=[("pybasic forms", "*.form")],
        )
        if not filename:
            return False
        self.path = Path(filename).with_suffix(".form").resolve()
        return self.save()

    def exit(self):
        if self._confirm_discard():
            self.stop()
            self.root.destroy()

    # ----- running -----

    def run(self):
        if self.process is not None:
            self.immediate.write("(The program is already running.)\n")
            return
        if not self.save():
            return
        assert self.path is not None  # save() succeeded, so there is a path
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [_PACKAGE_ROOT, env.get("PYTHONPATH")]))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        self.process = subprocess.Popen(
            [sys.executable, "-m", "pybasic.run", "--immediate", str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", cwd=self.path.parent, env=env,
        )
        threading.Thread(target=_pump, args=(self.process.stdout, self._output), daemon=True).start()
        self.immediate.write(f"--- Running {self.path.name}. Type Python below to inspect it. ---\n")
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
                code = self.process.wait()
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


def _convert(raw, kind):
    if kind is bool:
        if raw not in ("True", "False"):
            raise ValueError("Choose True or False")
        return raw == "True"
    if kind is int:
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{raw!r} is not a whole number") from None
    return raw


def main(argv=None):
    parser = argparse.ArgumentParser(prog="pybasic", description="A Visual Basic style form designer for Python.")
    parser.add_argument("form", nargs="?", type=Path, help="the .form file to open (created on save if new)")
    args = parser.parse_args(argv)
    root = tk.Tk()
    App(root, args.form)
    root.mainloop()
