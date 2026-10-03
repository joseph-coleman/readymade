"""Run a form: python -m pybasic.run path/to/Form1.form

The form's code is loaded from the .py file beside it. With --immediate, lines
read from stdin are executed inside the running program (the IDE's Immediate
window uses this), with the form available as `form` and each control by name.
"""

from __future__ import annotations

import argparse
import code
import importlib.util
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path

from pybasic import formfile
from pybasic.form import Form


def load_form_class(form_path):
    """The Form subclass in the .py beside form_path, or Form itself if there is no code."""
    form_path = Path(form_path)
    code_path = form_path.with_suffix(".py")
    if not code_path.exists():
        return Form
    name = formfile.load(form_path).name
    sys.path.insert(0, str(code_path.parent.resolve()))
    spec = importlib.util.spec_from_file_location(code_path.stem, code_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cls = getattr(module, name, None)
    if not (isinstance(cls, type) and issubclass(cls, Form)):
        raise SystemExit(f"{code_path.name}: expected a class {name}(Form)")
    return cls


def attach_immediate(form):
    """Execute lines from stdin on the Tk thread while the form runs."""
    console = code.InteractiveConsole({"form": form, "self": form, **form.controls})
    lines = queue.Queue()

    def read_stdin():
        for line in sys.stdin:
            lines.put(line.rstrip("\n"))

    def poll():
        while not lines.empty():
            console.push(lines.get())
        try:
            form.root.after(50, poll)
        except tk.TclError:
            pass  # the form was closed from the Immediate window

    threading.Thread(target=read_stdin, daemon=True).start()
    poll()


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m pybasic.run", description="Run a pybasic form.")
    parser.add_argument("form", type=Path, help="the .form file to run")
    parser.add_argument("--immediate", action="store_true", help="execute Python lines from stdin while running")
    args = parser.parse_args(argv)
    form = load_form_class(args.form)(args.form)
    if args.immediate:
        attach_immediate(form)
    form.root.mainloop()


if __name__ == "__main__":
    main()
