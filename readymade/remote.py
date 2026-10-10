"""The running program's side of its link with the IDE (python -m readymade.run --debug PORT).

The IDE listens on a localhost port; the program connects and they exchange JSON lines.
The program's prints still go to its stdout, which the IDE shows in the Immediate window.

From the IDE: {"cmd": "eval", "line": ...} runs a line typed in the Immediate window;
{"cmd": "answer", "text": ...} answers an input() (see ide_input); the debugger adds more.
To the IDE: {"event": "input", "prompt": ...} asks for a line of input; the debugger adds more.

Run from the IDE, the program's input() asks in the Immediate window (a window program has
no console of its own), and help() writes its text instead of starting pydoc's own prompt.
"""

from __future__ import annotations

import builtins
import code
import json
import pydoc
import queue
import socket
import sys
import threading
import tkinter as tk

CLOSED = {"cmd": "closed"}  # what receive() gives once the IDE has gone


class Channel:
    """JSON lines to and from the IDE. A thread reads them; answers to input() are kept apart."""

    def __init__(self, port):
        self._socket = socket.create_connection(("127.0.0.1", port))
        self._file = self._socket.makefile("rw", encoding="utf-8", newline="\n")
        self._lock = threading.Lock()
        self.inbox: queue.Queue = queue.Queue()
        self.answers: queue.Queue = queue.Queue()
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            for line in self._file:
                message = json.loads(line)
                (self.answers if message.get("cmd") == "answer" else self.inbox).put(message)
        except (OSError, ValueError):
            pass
        self.inbox.put(CLOSED)
        self.answers.put(CLOSED)

    def send(self, **message):
        try:
            with self._lock:
                self._file.write(json.dumps(message) + "\n")
                self._file.flush()
        except OSError:
            pass  # the IDE has gone

    def receive(self, timeout=None):
        """The next message from the IDE (waiting up to timeout seconds; None if none came)."""
        try:
            return self.inbox.get(timeout=timeout)
        except queue.Empty:
            return None


def ide_input(channel):
    """An input() that asks in the IDE's Immediate window."""
    def ask(prompt=""):
        sys.stdout.flush()  # what the program printed first appears first
        channel.send(event="input", prompt=str(prompt))
        answer = channel.answers.get()
        if answer is CLOSED or answer.get("eof"):
            raise EOFError
        return answer.get("text", "")
    return ask


class Help:
    """help() for the Immediate window: help(thing) shows its documentation; plain help()
    says how, as there's no interactive help prompt in a window program."""

    def __repr__(self):
        return "Type help(something) to read about it, like help(str) or help(\"for\"). In the code window, F1 helps with the name under the cursor."

    def __call__(self, *things):
        if not things:
            print(repr(self))
            return
        pydoc.Helper(output=sys.stdout).help(things[0])


def install(channel):
    """Make the program's input() and help() work with the IDE."""
    builtins.input = ide_input(channel)
    builtins.help = Help()


class Immediate:
    """Runs lines typed in the Immediate window inside the program, on its Tk thread, with
    forms, the startup form as form (and self), its controls and every loaded form by name."""

    def __init__(self, form, channel, handle=None, tick=None):
        from readymade import forms

        self.forms = forms
        self.form = form
        self.channel = channel
        self.handle = handle  # handle(message) for the debugger's commands
        self.tick = tick  # called twice a second (the debugger tells the IDE what its watches show)
        self._polls = 0
        self.namespace = {"forms": forms, "form": form, "self": form}
        self.console = code.InteractiveConsole(self.namespace)

    def start(self, root):
        root.after(50, lambda: self._poll(root))  # once the main loop runs, after the form shows

    def names(self):
        """The names Immediate lines see: forms, form, self, the form's controls and every loaded form."""
        self.namespace.update(self.forms.loaded())
        if self.form.loaded:
            self.namespace.update(self.form.controls)
        return self.namespace

    def run_line(self, line):
        self.names()
        self.console.push(line)

    def _poll(self, root):
        while (message := self.channel.receive(timeout=0)) is not None:
            if message.get("cmd") == "eval":
                self.run_line(message.get("line", ""))
            elif self.handle is not None:
                self.handle(message)
        self._polls += 1
        if self.tick is not None and self._polls % 10 == 0:
            self.tick()
        try:
            root.after(50, lambda: self._poll(root))
        except tk.TclError:
            pass  # the program has ended
