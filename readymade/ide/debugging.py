"""The IDE's side of its link with a program it runs (see readymade.remote).

The IDE listens on a localhost port and starts the program with --debug PORT; they
exchange the messages readymade.protocol lists. Lines typed in the Immediate window go to
the program; when the program asks for input(), the next line typed answers it. The
debugger's messages travel the same way (see readymade.debugger): the program says when it
pauses, with where and its variables, and the IDE says how to go on.
"""

from __future__ import annotations

import ast
import json
import queue
import socket
import threading
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from readymade import protocol
from readymade.ide import helptext
from readymade.ide.tooltips import help_button, tip
from readymade.protocol import STEPPING, Cmd, Event, Reason



class DebugSession:
    def __init__(self, app):
        self.app = app
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.bind(("127.0.0.1", 0))
        self._server.listen(1)
        self.port = self._server.getsockname()[1]
        self._messages: queue.Queue = queue.Queue()
        self._lock = threading.Lock()
        self._file = None
        self._unsent = []  # sent before the program connected
        self.prompt = None  # while the program waits for input(): its prompt
        self.paused = None  # while the program is paused: what it said ({reason, message, stack, stepping, ...})
        self.selected = 0  # the call stack frame chosen (0 is the outermost)
        self._said_ends = False
        self._tip = None  # (id, code view, expression, x, y): the value tip asked for last
        self._tips = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        self._server.settimeout(60)
        try:
            connection, _ = self._server.accept()
        except OSError:
            return  # closed, or the program never connected
        finally:
            self._server.close()
        stream = connection.makefile("rw", encoding="utf-8", newline="\n")
        with self._lock:
            self._file = stream
            for message in self._unsent:
                self._write(message)
            self._unsent = []
        try:
            for line in stream:
                self._messages.put(json.loads(line))
        except (OSError, ValueError):
            pass

    def _write(self, message):
        if self._file is None:
            return
        try:
            self._file.write(json.dumps(message) + "\n")
            self._file.flush()
        except (OSError, ValueError):
            pass  # the program has ended

    def send(self, **message):
        protocol.check(message)
        with self._lock:
            if self._file is None:
                self._unsent.append(message)
            else:
                self._write(message)

    def poll(self):
        """Handle what the program has sent (the IDE calls this as it reads the program's output)."""
        while True:
            try:
                message = self._messages.get_nowait()
            except queue.Empty:
                return
            self.handle(message)

    def handle(self, message):
        event = message.get("event")
        if event == Event.INPUT:
            self.prompt = message.get("prompt", "")
            self.app.immediate.write(self.prompt)
            self.app.immediate.ask_for_input()
        elif event == Event.PAUSED:
            self._paused(message)
        elif event == Event.RUNNING:
            self._running()
        elif event == Event.FRAME and self.paused is not None:
            self.selected = message.get("selected", self.selected)
            self.app.locals.show(message.get("locals", []))
            self.app.watches_panel.show(self.app.debug.breakpoints.watches(), message.get("watches"))
            self.app.call_stack.select(self.selected)
        elif event == Event.CHILDREN:
            path = message.get("path") or [""]
            panel = self.app.watches_panel if path[0] == "#watch" else self.app.locals
            panel.add_children(path, message.get("items", []))
        elif event == Event.WATCH_VALUES and self.paused is None and not self.app.in_break_mode:
            watches = self.app.debug.breakpoints.watches()
            values = message.get("watches", [])
            if [v["name"] for v in values] == [w["expression"] for w in watches]:  # (not from before a change)
                self.app.watches_panel.show(watches, values)
        elif event == Event.NOTE:  # e.g. why Set Next Statement couldn't
            self.app.immediate.write(f"--- {message.get('text', '')} ---\n")
        elif event == Event.LOG:  # a logpoint's message
            self.app.immediate.write(f"\u00bb {message.get('text', '')}\n")
        elif event == Event.TIP:
            self._tip_answered(message)
        elif event == Event.QUICK:
            QuickWatch(self.app, message.get("info", {}))

    # ----- break mode -----

    def _paused(self, message):
        app = self.app
        self.paused = message
        self.selected = message.get("selected", 0)
        app.debug.show_break_mode(True)
        app.locals.show(message.get("locals", []))
        app.watches_panel.show(app.debug.breakpoints.watches(), message.get("watches"))
        app.call_stack.show(message.get("stack", []), self.selected)
        if message.get("reason") == Reason.WATCH:
            app.immediate.write(f"--- Watch: {message.get('message', '')} ---\n")
            app.debug_tabs.select(app.watches_panel)  # the watch that paused it, in front
            for index in message.get("watches_fired", [])[:1]:
                app.watches_panel.choose(index)
        editor = self.show_place()
        if editor is not None and message.get("reason") in (Reason.ERROR, Reason.RAISED):
            editor.code.show_error(self.where()["line"], message.get("message", ""))
        if message.get("reason") == Reason.RAISED:
            app.immediate.write(f"--- {message.get('message', '')} was raised here. If a try catches it, the program "
                                "carries on there: step (F10) to see where. ---\n")
        if editor is not None and message.get("changed_line"):
            editor.code.show_changed(message["changed_line"])
        if message.get("ends") and not self._said_ends:
            self._said_ends = True
            app.immediate.write("--- The program failed as it started, so it can't go on: Continue or End ends it. ---\n")
        app.root.deiconify()
        app.root.lift()  # (the program's window was in front)

    def _running(self):
        self.paused = None
        self._tip = None
        for editor in self.app.editors:
            editor.code.hide_tip()
        for editor in self.app.editors:
            editor.code.clear_paused()
        self.app.locals.clear()
        self.app.watches_panel.show(self.app.debug.breakpoints.watches())
        self.app.call_stack.clear()
        self.app.debug.show_break_mode(False)

    def where(self):
        """The chosen frame while paused: {file, line, function}."""
        return self.paused["stack"][self.selected]

    def show_place(self):
        """Open the chosen frame's code with its line marked. Returns the editor."""
        frame = self.where()
        for editor in self.app.editors:
            editor.code.clear_paused()
        editor = self.app.open_code(Path(frame["file"]))
        if editor is not None:
            editor.code.show_paused(frame["line"])
        return editor

    def choose_frame(self, index):
        """The Call Stack's choice: its variables, its place, and Immediate lines run there."""
        if self.paused is None:
            return
        self.selected = index
        self.app.call_stack.select(index)
        self.show_place()
        self.send(cmd=Cmd.FRAME, index=index)

    def expand(self, path):
        if self.paused is not None or path[:1] == ["#watch"]:  # (watches have values while running too)
            self.send(cmd=Cmd.EXPAND, path=path)

    def ask_tip(self, code, expression, x, y):
        """The mouse rests on a name in some code: ask the paused program for its value."""
        if self.paused is None:
            return
        self._tips += 1
        self._tip = (self._tips, code, expression, x, y)
        self.send(cmd=Cmd.TIP, id=self._tips, expression=expression)

    def _tip_answered(self, message):
        if self._tip is None or message.get("id") != self._tip[0] or self.paused is None:
            return  # the mouse moved on, or the program went on
        _, code, expression, x, y = self._tip
        self._tip = None
        info = message.get("info", {})
        if not info.get("failed"):  # (a name the paused function doesn't have shows nothing)
            code.show_tip(expression, f"{expression} = {info.get('value', '')}", x, y)

    def assign(self, path, text):
        """Locals: give a variable (or a part of one) the value of a Python expression."""
        if self.paused is not None:
            self.send(cmd=Cmd.ASSIGN, path=path, value=text)

    def can_step(self):
        """Stepping is possible when paused, except at an error (the failed line can't go on)."""
        return self.paused is not None and self.paused.get("stepping", False)

    def go(self, how, **extra):
        """Continue, or one of STEPPING. Returns whether the program was told to."""
        if self.paused is None or (how in STEPPING and not self.can_step()):
            return False
        self.paused = None  # (until it says it's paused again)
        self.send(cmd=how, **extra)
        return True

    def answer(self, text, eof=False):
        """Answer the program's input() with a line typed in the Immediate window."""
        self.prompt = None
        self.app.immediate.input_done()
        self.send(cmd=Cmd.ANSWER, text=text, eof=eof)

    def close(self):
        self.prompt = None
        try:
            self._server.close()
        except OSError:
            pass
        with self._lock:
            if self._file is not None:
                try:
                    self._file.close()
                except OSError:
                    pass
                self._file = None


# ----- watches -----

KINDS = (("watch", "Watch the expression"), ("true", "Break when the value is true"),
         ("changes", "Break when the value changes"))
KIND_TIPS = {"watch": "Shows its value when the program is paused (and as it runs, if it's not a function's)",
             "true": "Pauses the program as soon as it becomes true (a \u25cf in the Watches window)",
             "changes": "Pauses the program on the line after its value changes, naming the line that changed it "
                        "(a \u0394 in the Watches window)"}
ALL_FILES = "(All files)"
ALL_FUNCTIONS = "(All functions)"


def functions_in(source):
    """The names of the functions (and methods) defined in some code, in order."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    names = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    return list(dict.fromkeys(sorted(names, key=str.lower)))


def function_at(source, line):
    """The name of the innermost function around a line, or ""."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return ""
    found, size = "", None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.lineno <= line <= (node.end_lineno or 0):
            if size is None or node.end_lineno - node.lineno < size:
                found, size = node.name, node.end_lineno - node.lineno
    return found


class WatchDialog(tk.Toplevel):
    """Debug > Add Watch (and Edit Watch): an expression, the context it's watched in (a
    function, a file, or anywhere), and whether it only shows or breaks. on_ok(watch)."""

    def __init__(self, app, watch, on_ok, title="Add Watch"):
        super().__init__(app.root)
        self.app = app
        self.on_ok = on_ok
        self.title(title)
        self.transient(app.root)
        self.resizable(False, False)
        self.files = app.files.code_files()  # {relative name: source}
        self.expression = tk.StringVar(self, watch.get("expression", ""))
        self.file = tk.StringVar(self, watch.get("file") or ALL_FILES)
        self.function = tk.StringVar(self, watch.get("function") or ALL_FUNCTIONS)
        self.kind = tk.StringVar(self, watch.get("kind", "watch"))

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Expression:").grid(row=0, column=0, sticky="w", pady=4)
        entry = ttk.Entry(body, textvariable=self.expression, width=44)
        entry.grid(row=0, column=1, sticky="we", padx=(8, 0))
        context = ttk.LabelFrame(body, text="Context", padding=8)
        context.grid(row=1, column=0, columnspan=2, sticky="we", pady=(8, 0))
        ttk.Label(context, text="File:").grid(row=0, column=0, sticky="w", pady=2)
        files = ttk.Combobox(context, textvariable=self.file, state="readonly", width=30,
                             values=[ALL_FILES, *self.files])
        files.grid(row=0, column=1, sticky="w", padx=(8, 0))
        tip(files, "Only in this file's code, or (All files) anywhere in the project")
        files.bind("<<ComboboxSelected>>", lambda e: self._file_chosen())
        ttk.Label(context, text="Function:").grid(row=1, column=0, sticky="w", pady=2)
        self.functions = ttk.Combobox(context, textvariable=self.function, state="readonly", width=30)
        self.functions.grid(row=1, column=1, sticky="w", padx=(8, 0))
        tip(self.functions, "Only while this function runs, with its variables; (All functions): its file's "
                            "names, or anywhere the program is")
        self._file_chosen(keep=True)
        kinds = ttk.LabelFrame(body, text="Watch type", padding=8)
        kinds.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 0))
        for value, label in KINDS:
            choice = ttk.Radiobutton(kinds, text=label, value=value, variable=self.kind)
            choice.pack(anchor="w")
            tip(choice, KIND_TIPS[value])
        self.note = ttk.Label(body, style="Note.TLabel", wraplength=380)
        self.note.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        for variable in (self.kind, self.function):
            variable.trace_add("write", lambda *_: self._update_note())
        self._update_note()
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
        help_button(self, buttons, app, lambda: helptext.dialog("watch"))
        ttk.Button(buttons, text="OK", command=self.ok).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=(4, 0))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        entry.focus_set()
        entry.select_range(0, tk.END)

    def _file_chosen(self, keep=False):
        source = self.files.get(self.file.get())
        names = functions_in(source) if source is not None else sorted(
            {name for code in self.files.values() for name in functions_in(code)}, key=str.lower)
        self.functions.configure(values=[ALL_FUNCTIONS, *names])
        if not keep and self.function.get() not in names:
            self.function.set(ALL_FUNCTIONS)

    def _update_note(self):
        breaks = self.kind.get() != "watch"
        anywhere = self.function.get() == ALL_FUNCTIONS
        self.note.configure(text="Checking after every line of the program slows it down: "
                                 "choose a function if you can." if breaks and anywhere else "")

    def watch(self):
        return {"expression": self.expression.get().strip(), "kind": self.kind.get(),
                "file": "" if self.file.get() == ALL_FILES else self.file.get(),
                "function": "" if self.function.get() == ALL_FUNCTIONS else self.function.get()}

    def ok(self):
        watch = self.watch()
        if not watch["expression"]:
            self.bell()
            return
        try:
            compile(watch["expression"], "<watch>", "eval")
        except SyntaxError:
            self.note.configure(text=f"{watch['expression']} isn't an expression Python can read.")
            self.bell()
            return
        self.destroy()
        self.on_ok(watch)


class QuickWatch(tk.Toplevel):
    """Debug > Quick Watch (Shift+F9): an expression's value now, with Add Watch to keep watching it."""

    def __init__(self, app, info):
        super().__init__(app.root)
        self.title("Quick Watch")
        self.transient(app.root)
        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        expression = info.get("name", "")
        ttk.Label(body, text=expression, font=("TkDefaultFont", 10, "bold")).pack(anchor="w")
        self.value = tk.Text(body, height=4, width=60, wrap="word", font=app.immediate.output.cget("font"),
                             highlightthickness=0)
        self.value.insert("1.0", info.get("value", ""))
        self.value.configure(state=tk.DISABLED)
        self.value.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        if info.get("type"):
            ttk.Label(body, text=f"Type: {info['type']}", style="Note.TLabel").pack(anchor="w", pady=(4, 0))
        buttons = ttk.Frame(body)
        buttons.pack(anchor="e", pady=(12, 0))
        ttk.Button(buttons, text="Add Watch", command=lambda: (self.destroy(), app.debug.add_watch(expression))).pack(
            side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.LEFT, padx=(4, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()


# ----- breakpoint conditions -----

HIT_MODES = (("", "Always"), ("=", "When the hit count is"), (">=", "When the hit count is at least"),
             ("%", "When the hit count is a multiple of"))


class BreakpointDialog(tk.Toplevel):
    """Breakpoint Condition: stop at a breakpoint only when an expression is true, and/or on
    some of the times it's reached (counted when the condition is true); or instead of
    stopping, write a message in the Immediate window (a logpoint). on_ok(settings)."""

    def __init__(self, app, line, settings, on_ok):
        super().__init__(app.root)
        self.on_ok = on_ok
        self.title("Breakpoint Condition")
        self.transient(app.root)
        self.resizable(False, False)
        self.condition = tk.StringVar(self, settings.get("condition", ""))
        labels = dict(HIT_MODES)
        self.mode = tk.StringVar(self, labels.get(settings.get("hit_mode", ""), labels[""]))
        self.hits = tk.StringVar(self, str(settings.get("hits") or 1))
        self.logs = tk.BooleanVar(self, bool(settings.get("log")))
        self.log = tk.StringVar(self, settings.get("log", ""))

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text=f"Stop at line {line}...").grid(row=0, column=0, columnspan=3, sticky="w")
        ttk.Label(body, text="When this is true:").grid(row=1, column=0, sticky="w", pady=(8, 4))
        entry = ttk.Entry(body, textvariable=self.condition, width=40)
        entry.grid(row=1, column=1, columnspan=2, sticky="we", padx=(8, 0), pady=(8, 4))
        ttk.Label(body, text="An expression, like total > 100. Empty: whenever it's reached.",
                  style="Note.TLabel").grid(row=2, column=1, columnspan=2, sticky="w", padx=(8, 0))
        ttk.Label(body, text="Hit count:").grid(row=3, column=0, sticky="w", pady=(8, 4))
        modes = ttk.Combobox(body, textvariable=self.mode, values=[label for _, label in HIT_MODES],
                             state="readonly", width=32)
        modes.grid(row=3, column=1, sticky="w", padx=(8, 0), pady=(8, 4))
        tip(modes, "Pause only on some of the times the line is reached (counted from the start of each run, "
                   "when the condition is true): the nth, from the nth on, or every nth")
        self.count = ttk.Spinbox(body, from_=1, to=1_000_000, textvariable=self.hits, width=7)
        self.count.grid(row=3, column=2, sticky="w", padx=(4, 0), pady=(8, 4))
        self.mode.trace_add("write", lambda *_: self._mode_chosen())
        self._mode_chosen()
        logs = ttk.Checkbutton(body, text="Instead of stopping, write this in the Immediate window:",
                               variable=self.logs, command=self._logs_chosen)
        logs.grid(row=4, column=0, columnspan=3, sticky="w", pady=(12, 4))
        tip(logs, "A logpoint: the program carries on, writing the message each time (the print() you'd add "
                  "and later remove). It's a diamond in the line numbers.")
        self.log_entry = ttk.Entry(body, textvariable=self.log, width=40)
        self.log_entry.grid(row=5, column=1, columnspan=2, sticky="we", padx=(8, 0))
        ttk.Label(body, text="Names in {braces} show their values: total is {subtotal}",
                  style="Note.TLabel").grid(row=6, column=1, columnspan=2, sticky="w", padx=(8, 0))
        self._logs_chosen()
        self.note = ttk.Label(body, style="Note.TLabel", wraplength=420)
        self.note.grid(row=7, column=0, columnspan=3, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=8, column=0, columnspan=3, sticky="e", pady=(12, 0))
        help_button(self, buttons, app, lambda: helptext.dialog("breakpoint"))
        ttk.Button(buttons, text="OK", command=self.ok).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=(4, 0))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())
        entry.focus_set()

    def _logs_chosen(self):
        self.log_entry.configure(state="normal" if self.logs.get() else "disabled")
        if self.logs.get():
            self.log_entry.focus_set()

    def _mode_chosen(self):
        self.count.configure(state="disabled" if self.hit_mode() == "" else "normal")

    def hit_mode(self):
        return next(mode for mode, label in HIT_MODES if label == self.mode.get())

    def settings(self):
        mode = self.hit_mode()
        try:
            hits = max(1, int(self.hits.get()))
        except ValueError:
            hits = 1
        return {"condition": self.condition.get().strip(), "hit_mode": mode, "hits": hits if mode else 0,
                "log": self.log.get().strip() if self.logs.get() else ""}

    def ok(self):
        settings = self.settings()
        if settings["condition"]:
            try:
                compile(settings["condition"], "<condition>", "eval")
            except SyntaxError:
                self.note.configure(text=f"{settings['condition']} isn't an expression Python can read.")
                self.bell()
                return
        if self.logs.get():
            try:
                compile("f" + repr(settings["log"]), "<message>", "eval")
            except SyntaxError:
                self.note.configure(text="Python can't read the {names} in the message.")
                self.bell()
                return
            if not settings["log"]:
                self.note.configure(text="Type the message to write.")
                self.bell()
                return
        self.destroy()
        self.on_ok(settings)
