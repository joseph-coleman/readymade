"""Run a project: python -m readymade.run path/to/project [--startup Form1]

The target can be a project folder, its pyproject.toml, or one of its .form
files (which then becomes the startup form). The project folder is put on
sys.path, so forms and modules import each other by name. With --immediate,
lines read from stdin are executed inside the running program (the IDE's
Immediate window uses this), with `forms`, the startup form as `form`, its
controls by name, and every default form instance by name. The IDE uses --debug PORT
instead: the same, over a link to the IDE that also carries input() and the debugger
(see readymade.remote).
"""

from __future__ import annotations

import argparse
import code
import queue
import sys
import threading
import tkinter as tk
from pathlib import Path

from readymade import debugger, forms, remote
from readymade.form import app_root, main_loop, set_app_icon, set_app_path
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
    parser.add_argument("--debug", type=int, metavar="PORT", help="connect to the IDE listening on this port")
    args = parser.parse_args(argv)

    project = Project.find(args.target)
    startup = args.startup or (args.target.stem if args.target.suffix == ".form" else project.startup)
    if startup is None:
        raise SystemExit(f"{project.folder} has no forms to run")
    sys.path.insert(0, str(project.folder))
    set_app_path(project.folder)
    icon = project.setting("icon")
    if icon:
        set_app_icon(project.folder / icon)
    channel = None
    if args.debug:
        channel = remote.Channel(args.debug)
        remote.install(channel)  # input() and help() go through the IDE
        # The IDE starts with its breakpoints, before any form loads (Form_load can have them too).
        settings = channel.receive(timeout=30) or {}
        debugger.start(channel, project.folder, settings if settings.get("cmd") == "start" else {})
    form = getattr(forms, startup)
    if channel is not None:
        immediate = remote.Immediate(form, channel, handle=debugger.handle, tick=debugger.tick)
        debugger.current().extra_names = immediate.names  # paused, Immediate lines can use the forms too
        immediate.start(app_root())
    elif args.immediate:
        attach_immediate(form)
    form.show()
    main_loop()


if __name__ == "__main__":
    main()
