"""Run a project: python -m readymade.run path/to/project [--startup Form1]

The target can be a project folder, its pyproject.toml, or one of its .form
files (which then becomes the startup form). The project folder is put on
sys.path, so forms and modules import each other by name. With --immediate,
lines read from stdin are executed inside the running program (the IDE's
Immediate window uses this), with `forms`, the startup form as `form`, its
controls by name, and every default form instance by name.
"""

from __future__ import annotations

import argparse
import code
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path

from readymade import forms
from readymade.form import app_root, main_loop, set_app_path
from readymade.project import Project


def attach_immediate(form):
    """Execute lines from stdin on the Tk thread while the program runs."""
    namespace = {"forms": forms, "form": form, "self": form}
    console = code.InteractiveConsole(namespace)
    lines = queue.Queue()

    def read_stdin():
        for line in sys.stdin:
            lines.put(line.rstrip("\n"))

    def poll():
        while not lines.empty():
            namespace.update(forms.loaded())
            if form.loaded:
                namespace.update(form.controls)
            console.push(lines.get())
        try:
            app_root().after(50, poll)
        except tk.TclError:
            pass  # the program has ended

    threading.Thread(target=read_stdin, daemon=True).start()
    app_root().after(50, poll)  # start once the main loop runs, after the startup form is shown


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m readymade.run", description="Run a readymade project.")
    parser.add_argument("target", type=Path, help="a project folder, its pyproject.toml, or a .form file")
    parser.add_argument("--startup", help="the form to show first (default: the project's startup form)")
    parser.add_argument("--immediate", action="store_true", help="execute Python lines from stdin while running")
    args = parser.parse_args(argv)

    project = Project.find(args.target)
    startup = args.startup or (args.target.stem if args.target.suffix == ".form" else project.startup)
    if startup is None:
        raise SystemExit(f"{project.folder} has no forms to run")
    sys.path.insert(0, str(project.folder))
    set_app_path(project.folder)
    form = getattr(forms, startup)
    if args.immediate:
        attach_immediate(form)
    form.show()
    main_loop()


if __name__ == "__main__":
    main()
