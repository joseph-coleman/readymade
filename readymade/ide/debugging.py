"""The IDE's side of its link with a program it runs (see readymade.remote).

The IDE listens on a localhost port and starts the program with --debug PORT. Lines typed
in the Immediate window go to the program; when the program asks for input(), the next
line typed answers it. The debugger's messages travel the same way (see
readymade.debugger): the program says when it pauses, with where and its variables, and
the IDE says how to go on.
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

STEPS = ("step", "next", "return", "until")  # Step Into, Step Over, Step Out, Run to Cursor


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
        if event == "input":
            self.prompt = message.get("prompt", "")
            self.app.immediate.write(self.prompt)
            self.app.immediate.ask_for_input()
        elif event == "paused":
            self._paused(message)
        elif event == "running":
            self._running()
        elif event == "frame" and self.paused is not None:
            self.selected = message.get("selected", self.selected)
            self.app.locals.show(message.get("locals", []))
            self.app.watches_panel.show(self.app.watches(), message.get("watches"))
            self.app.call_stack.select(self.selected)
        elif event == "children":
            path = message.get("path") or [""]
            panel = self.app.watches_panel if path[0] == "#watch" else self.app.locals
            panel.add_children(path, message.get("items", []))
        elif event == "watch_values" and self.paused is None and not self.app.in_break_mode:
            watches = self.app.watches()
            values = message.get("watches", [])
            if [v["name"] for v in values] == [w["expression"] for w in watches]:  # (not from before a change)
                self.app.watches_panel.show(watches, values)
        elif event == "quick":
            QuickWatch(self.app, message.get("info", {}))

    # ----- break mode -----

    def _paused(self, message):
        app = self.app
        self.paused = message
        self.selected = message.get("selected", 0)
        app.show_break_mode(True)
        app.locals.show(message.get("locals", []))
        app.watches_panel.show(app.watches(), message.get("watches"))
        app.call_stack.show(message.get("stack", []), self.selected)
        if message.get("reason") == "watch":
            app.immediate.write(f"--- Watch: {message.get('message', '')} ---\n")
        editor = self.show_place()
        if editor is not None and message.get("reason") == "error":
            editor.code.show_error(self.where()["line"], message.get("message", ""))
        if editor is not None and message.get("changed_line"):
            editor.code.show_changed(message["changed_line"])
        app.root.deiconify()
        app.root.lift()  # (the program's window was in front)

    def _running(self):
        self.paused = None
        for editor in self.app.editors:
            editor.code.clear_paused()
        self.app.locals.clear()
        self.app.watches_panel.show(self.app.watches())
        self.app.call_stack.clear()
        self.app.show_break_mode(False)

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
        self.send(cmd="frame", index=index)

    def expand(self, path):
        if self.paused is not None or path[:1] == ["#watch"]:  # (watches have values while running too)
            self.send(cmd="expand", path=path)

    def can_step(self):
        """Stepping is possible when paused, except at an error (the failed line can't go on)."""
        return self.paused is not None and self.paused.get("stepping", False)

    def go(self, how, **extra):
        """Continue, or one of STEPS. Returns whether the program was told to."""
        if self.paused is None or (how in STEPS and not self.can_step()):
            return False
        self.paused = None  # (until it says it's paused again)
        self.send(cmd=how, **extra)
        return True

    def answer(self, text, eof=False):
        """Answer the program's input() with a line typed in the Immediate window."""
        self.prompt = None
        self.app.immediate.input_done()
        self.send(cmd="answer", text=text, eof=eof)

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
        self.files = app.code_files()  # {relative name: source}
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
        files.bind("<<ComboboxSelected>>", lambda e: self._file_chosen())
        ttk.Label(context, text="Function:").grid(row=1, column=0, sticky="w", pady=2)
        self.functions = ttk.Combobox(context, textvariable=self.function, state="readonly", width=30)
        self.functions.grid(row=1, column=1, sticky="w", padx=(8, 0))
        self._file_chosen(keep=True)
        kinds = ttk.LabelFrame(body, text="Watch type", padding=8)
        kinds.grid(row=2, column=0, columnspan=2, sticky="we", pady=(8, 0))
        for value, label in KINDS:
            ttk.Radiobutton(kinds, text=label, value=value, variable=self.kind).pack(anchor="w")
        self.note = ttk.Label(body, style="Note.TLabel", wraplength=380)
        self.note.grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))
        for variable in (self.kind, self.function):
            variable.trace_add("write", lambda *_: self._update_note())
        self._update_note()
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=2, sticky="e", pady=(12, 0))
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
        ttk.Button(buttons, text="Add Watch", command=lambda: (self.destroy(), app.add_watch(expression))).pack(
            side=tk.LEFT)
        ttk.Button(buttons, text="Close", command=self.destroy).pack(side=tk.LEFT, padx=(4, 0))
        self.bind("<Escape>", lambda e: self.destroy())
        self.focus_set()
