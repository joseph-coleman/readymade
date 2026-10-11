"""Running the project's program from the IDE: F5 and Shift+F5, its output in the Immediate
window, Immediate lines (in the program, or in the IDE when nothing runs), and the link with
it that input(), help() and the debugger use (see debugging.py)."""

from __future__ import annotations

import code
import contextlib
import os
import queue
import re
import subprocess
import threading
from pathlib import Path
from tkinter import simpledialog

from readymade import remote
from readymade.ide import PACKAGE_ROOT, options
from readymade.ide.debugging import DebugSession
from readymade.ide.tracebacks import TracebackWatcher
from readymade.ide.part import Part


_ANSI = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")  # terminal color and cursor codes


class Runner(Part):
    def __init__(self, app):
        super().__init__(app)
        self._on_exit = None
        self._watcher = None  # finds errors in the running program's output (TracebackWatcher)
        self._output: queue.Queue = queue.Queue()
        self._console = _DesignTimeConsole(app)

    def run(self, step=False):
        """F5: run the program (with step, pausing as its first event starts), or continue it."""
        if self.app.in_break_mode:
            self.app.debug.debug_go("continue")  # F5 continues a paused program
            return
        if self.project is None or not self.idle():
            return
        if not self.app.save():
            return
        folder = self.project.folder
        startup = self.project.startup
        if startup is None:
            self.immediate.write("(The project has no forms to run.)\n")
            return
        python, where = self.app.envs.python()
        if not self.app.envs.python_exists(python):
            return
        for editor in self.editors:
            editor.code.clear_error()
        self.immediate.write(f"--- Running {self.project.name} ({startup}, Python: {where}). Type Python below to inspect it. ---\n")
        self.app.session = DebugSession(self.app)  # Immediate lines, input() and the debugger go through it
        breakpoints = self.app.debug.breakpoints
        self.app.session.send(cmd="start", breakpoints=breakpoints.for_program(), watches=breakpoints.watches(),
                              break_on_errors=options.break_on_errors(), break_on_all=options.break_on_all_errors(),
                              step=step)
        if step:
            self.immediate.write("--- Stepping: the program pauses as its first event (like Form_load) starts. ---\n")
        self.start_process([str(python), "-m", "readymade.run", "--debug", str(self.app.session.port), "--startup",
                            startup, str(folder)], interactive=True)
        self._watcher = TracebackWatcher(folder, self.show_error)
        self.app.update_title()

    def show_error(self, path, line, message):
        """Point out a run-time error: open the code where it happened and highlight the line."""
        self.immediate.write(f"--- {message}  ({path.name}, line {line}) ---\n")
        if path.with_suffix(".form").exists():
            editor = self.app.open_form(path.stem, "code")
        else:
            editor = self.app.open_module(path.stem)
        if editor is not None:
            editor.code.show_error(line, message)

    def environment(self):
        """Environment variables for programs and tools run for the project: they can import readymade."""
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [PACKAGE_ROOT, env.get("PYTHONPATH")]))
        env["PYTHONUNBUFFERED"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        # Plain text only: the Immediate window can't show colors, and the IDE reads the
        # tracebacks and tool output, which color codes (e.g. from FORCE_COLOR) would garble.
        for name in ("FORCE_COLOR", "CLICOLOR_FORCE"):
            env.pop(name, None)
        env["PYTHON_COLORS"] = "0"
        env["NO_COLOR"] = "1"
        return env

    def idle(self):
        if self.app.process is None:
            return True
        self.immediate.write("(Busy: wait for the program or install to finish, or use Run > End.)\n")
        return False

    def start_process(self, args, interactive=False, on_exit=None):
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
        self.app.process = process
        self.app.bottom.select(self.immediate)  # its output appears there
        self._on_exit = on_exit
        self._watcher = None
        threading.Thread(target=_pump, args=(process.stdout, self._output), daemon=True).start()
        self.root.after(50, self._poll_output)

    def stop(self):
        if self.app.process is not None:
            self.app.process.terminate()

    def _poll_output(self):
        while True:
            try:
                item = self._output.get_nowait()
            except queue.Empty:
                break
            if item is None:
                code = self.app.process.wait() if self.app.process else None
                self.app.process = None
                self._watcher = None
                self.end_session()
                if self._on_exit:
                    self._on_exit(code)
                else:
                    self.immediate.write(f"--- Ended (exit code {code}) ---\n")
                return
            item = _ANSI.sub("", item)  # in case a program prints colors itself
            self.immediate.write(item)
            if self._watcher:
                self._watcher.feed(item)
        if self.app.session is not None:
            self.app.session.poll()  # (after the output, so a prompt comes after what was printed before it)
        self.root.after(50, self._poll_output)

    def end_session(self):
        if self.app.session is not None:
            self.app.session.handle({"event": "running"})  # out of break mode, if it was paused
            self.app.session.close()
            self.app.session = None
        self.immediate.input_done()
        for editor in self.editors:
            editor.code.clear_note()  # (edits made during the run now count)
        self.app.update_title()

    def immediate_line(self, line):
        if self.app.session is not None and self.app.session.prompt is not None:
            self.immediate.write(line + "\n")  # the answer to the program's input()
            self.app.session.answer(line)
            return
        self.immediate.write(f">>> {line}\n")
        if line.lstrip().startswith("?"):  # VB's `? expr` prints the expression
            line = f"print({line.lstrip()[1:].strip()})"
        if self.app.process is None or self.app.process.stdin is None:
            self._console.push(line)
            return
        if self.app.session is not None:
            self.app.session.send(cmd="eval", line=line)
            return
        try:
            self.app.process.stdin.write(line + "\n")
            self.app.process.stdin.flush()
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
