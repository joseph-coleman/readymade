"""The debugger, in the program the IDE runs (python -m readymade.run --debug PORT).

Break mode, as in VB: the program pauses at a breakpoint, after a step, at an error in an
event handler, or when a watch says so. While it's paused its windows wait (the program's
own thread is here), and the IDE shows where it stopped, the call stack and the local
variables; the Immediate window runs lines in the paused function. It goes on when the IDE
says continue, step over, step into, step out or run to the cursor.

Only the project's own files are stopped in, so stepping never wanders into readymade,
tkinter or Python's library. Tracing (which slows a program) is on only while there are
breakpoints or watches that break, or while stepping.

Watches, as in VB: an expression with a context (a function, a file, or anywhere in the
project) and a kind: "watch" shows its value whenever the program is paused; "true" breaks
when it becomes true; "changes" breaks on the line after its value changes. Those two are
checked after every line run in their context, so a narrow context keeps the program fast.
A watch of a function is noted after each of its lines too, as its variables only exist
while it runs: between events the IDE shows it as the function left it. While the program
runs, the IDE is told the watches' values twice a second, when they change (see tick).

Python tells a debugger about a line just before it runs, so a change is noticed as the
next line starts (where the program pauses); the line that made it is named and marked.
A change made by a function's last line is noticed as the function returns.
"""

from __future__ import annotations

import bdb
import code
import itertools
import os
import reprlib
import sys
import traceback
from collections import ChainMap
from collections.abc import MutableMapping
from pathlib import Path

class _Repr(reprlib.Repr):
    def repr_dict(self, x, level):
        """In the dict's own order (reprlib sorts the keys)."""
        if not x:
            return "{}"
        if level <= 0:
            return "{" + self.fillvalue + "}"
        pieces = [f"{self.repr1(key, level - 1)}: {self.repr1(x[key], level - 1)}"
                  for key in itertools.islice(x, self.maxdict)]
        if len(x) > self.maxdict:
            pieces.append(self.fillvalue)
        return "{" + ", ".join(pieces) + "}"


_repr = _Repr()
_repr.maxstring = _repr.maxother = 120
_repr.maxlist = _repr.maxtuple = _repr.maxdict = _repr.maxset = 12
MAX_CHILDREN = 300


def value_info(name, value, path):
    """A variable for the Locals window: its name, value, type and whether it has parts to show."""
    return {"name": str(name), "value": _repr.repr(value), "type": type(value).__name__,
            "path": path, "expandable": bool(_children(value))}


def _children(value):
    """(name, child) pairs for a value's parts: items of lists, tuples, sets and dicts, and an
    object's attributes (not its methods, nor names starting with _)."""
    if isinstance(value, (str, bytes, int, float, complex, bool, type(None))):
        return []
    if isinstance(value, dict):
        return [(_repr.repr(key), item) for key, item in list(value.items())[:MAX_CHILDREN]]
    if isinstance(value, (list, tuple)):
        return [(f"[{i}]", item) for i, item in enumerate(value[:MAX_CHILDREN])]
    if isinstance(value, (set, frozenset)):
        return [(f"{{{i}}}", item) for i, item in enumerate(list(value)[:MAX_CHILDREN])]
    if isinstance(value, type) or callable(value) and not hasattr(value, "__dict__"):
        return []
    try:
        attributes = vars(value)
    except TypeError:
        return []
    return [(name, item) for name, item in list(attributes.items())[:MAX_CHILDREN]
            if not name.startswith("_") and not callable(item)]


class FrameScope(MutableMapping):
    """The names an Immediate line sees while paused: the paused function's local variables,
    its module's globals, then extra names (the forms, as when running) that nothing else has.
    Assigning sets a local variable (which sticks from Python 3.13 on)."""

    def __init__(self, frame, extra):
        self.frame = frame
        self.extra = extra

    def __getitem__(self, name):
        try:
            return self.frame.f_locals[name]
        except KeyError:
            if name in self.extra and name not in self.frame.f_globals:
                return self.extra[name]
            raise

    def __setitem__(self, name, value):
        self.frame.f_locals[name] = value

    def __delitem__(self, name):
        del self.frame.f_locals[name]

    def __iter__(self):
        return iter(self.frame.f_locals)

    def __len__(self):
        return len(self.frame.f_locals)


class FrameConsole(code.InteractiveConsole):
    """The Immediate window while paused: lines run in the paused function (see FrameScope)."""

    def __init__(self, frame, extra=None):
        self.scope = FrameScope(frame, extra or {})
        super().__init__(self.scope)
        self.frame = frame

    def runcode(self, code):
        try:
            exec(code, self.frame.f_globals, self.scope)
        except SystemExit:
            raise
        except BaseException:
            self.showtraceback()


class Debugger(bdb.Bdb):
    def __init__(self, channel, folder):
        super().__init__()
        self.channel = channel
        self.folder = os.path.normcase(str(Path(folder).resolve()))
        self.break_on_errors = True
        self.pause_requested = False
        self._in_project = {}  # file name -> whether it's one of the project's
        self._tracing = False
        self.frames = []  # while paused: [(frame, line)], outermost first
        self.selected = 0
        self.consoles = {}
        self.post_mortem_mode = False
        self.extra_names = dict  # extra_names() -> names Immediate lines see while paused, if nothing else has them
        self.watches = []  # [Watch]
        self._why = None  # (reason, message) for the stop being made
        self.last_running = None  # the watches' values the IDE was last told while running
        self._ran = {}  # frame -> the line it last started, while watches are traced

    # ----- which frames count -----

    def in_project(self, frame):
        name = frame.f_code.co_filename
        found = self._in_project.get(name)
        if found is None:
            try:
                # (not "<frozen runpy>" and the like, which would resolve inside the folder the program runs in)
                path = "" if name.startswith("<") else os.path.normcase(str(Path(name).resolve()))
            except (OSError, ValueError):
                path = ""
            found = self._in_project[name] = path.startswith(self.folder + os.sep)
        return found

    def stop_here(self, frame):
        return self.in_project(frame) and super().stop_here(frame)

    # ----- starting and stopping tracing -----

    def _must_trace(self):
        return bool(self.breaks) or any(w.traced for w in self.watches)

    def trace_if_needed(self):
        """Trace (on this thread) only while something could make it stop."""
        if self._must_trace():
            if not self._tracing:
                self.reset()
                self._set_stopinfo(sys._getframe(), None, -1)  # (bdb's own) no stepping: just watch for breakpoints
                sys.settrace(self.trace_dispatch)
                self._tracing = True
        elif self._tracing:
            sys.settrace(None)
            self._tracing = False

    def do_clear(self, arg):
        self.clear_bpbynumber(arg)  # bdb removing a temporary breakpoint (Run to Cursor) once hit

    def set_continue(self):
        if self._must_trace():
            self._set_stopinfo(self.botframe, None, -1)  # (bdb would stop tracing, with no breakpoints)
        else:
            super().set_continue()
            self._tracing = False  # (bdb has turned tracing off)
            self._ran.clear()

    def set_breakpoints(self, breakpoints):
        """{file: [line, ...]}: the IDE's breakpoints, all of them."""
        self.clear_all_breaks()
        for file, lines in breakpoints.items():
            for line in lines:
                self.set_break(self.canonic(file), int(line))
        self.trace_if_needed()

    # ----- where it stops -----

    def set_watches(self, watches):
        """The IDE's watches, all of them: [{expression, function, file, kind}]. Those that were
        already there keep what they've seen (a value that changes is compared with the last)."""
        old = {id(w): w for w in self.watches}
        kept = []
        for spec in watches:
            same = next((w for w in old.values() if w.spec == spec), None)
            if same is not None:
                del old[id(same)]
            kept.append(same or Watch(spec, self.folder))
        self.watches = kept
        self.last_running = None  # (tell the IDE their values again)
        self.trace_if_needed()

    def break_anywhere(self, frame):
        return super().break_anywhere(frame) or any(w.traced and w.in_context(frame, self) for w in self.watches)

    def break_here(self, frame):
        fired = self._check_watches(frame)  # (first, so they always see each line)
        if super().break_here(frame):
            self._why = ("breakpoint", "", None)
        elif fired[0]:
            self._why = ("watch", *fired)
        return self._why is not None

    def _check_watches(self, frame, returning=False):
        """Check the traced watches in context, after a line ran (or as frame returns):
        (what made those that break fire, or "", the line that ran)."""
        if not self.in_project(frame):
            return "", None
        if returning:
            ran = frame.f_lineno  # (still the last line it ran)
            self._ran.pop(frame, None)
        else:
            ran = self._ran.get(frame)
            self._ran[frame] = frame.f_lineno
        fired = "; ".join(filter(None, (w.check(frame, self.extra_names) for w in self.watches
                                         if w.traced and w.in_context(frame, self))))
        if returning:
            for watch in self.watches:
                watch.left(frame)
        if fired and ran is not None:
            fired += f" on line {ran}"
        return fired, ran

    def user_line(self, frame):
        if self.post_mortem_mode:
            return
        if self._why is None:  # stepping (bdb didn't ask break_here)
            fired = self._check_watches(frame)
            self._why = ("watch", *fired) if fired[0] else ("step", "", None)
        reason, message, changed = self._why
        self._why = None
        self.interaction([(f, f.f_lineno) for f in self._stack(frame)], reason, message, changed)

    def dispatch_return(self, frame, arg):
        if not self.post_mortem_mode and any(w.traced for w in self.watches):
            fired, ran = self._check_watches(frame, returning=True)  # (a change on its last line)
            if fired:
                self.interaction([(f, f.f_lineno) for f in self._stack(frame)], "watch", fired, ran)
        return super().dispatch_return(frame, arg)

    def user_call(self, frame, argument_list):
        pass  # it stops at the first line instead

    def user_return(self, frame, return_value):
        pass

    def user_exception(self, frame, exc_info):
        pass  # errors are handled where events run (see post_mortem)

    def _stack(self, frame):
        frames = []
        while frame is not None:
            if self.in_project(frame):
                frames.append(frame)
            frame = frame.f_back
        return list(reversed(frames))

    def pause_at_next_event(self):
        """Break at the start of the next event handler (an idle program runs no Python)."""
        self.pause_requested = True

    def break_into_event(self):
        """Called as an event handler starts: stop at its first line if a pause was asked for."""
        if self.pause_requested:
            self.pause_requested = False
            if not self._tracing:
                self.reset()
            self.set_step()
            sys.settrace(self.trace_dispatch)
            self._tracing = True

    def post_mortem(self, error):
        """Break where an error happened in an event handler. The error's traceback has been printed."""
        tb = error.__traceback__
        frames = []
        while tb is not None:
            if self.in_project(tb.tb_frame):
                frames.append((tb.tb_frame, tb.tb_lineno))
            tb = tb.tb_next
        if not frames:
            return
        self.post_mortem_mode = True
        try:
            self.interaction(frames, "error", f"{type(error).__name__}: {error}")
        finally:
            self.post_mortem_mode = False

    # ----- paused: the IDE's commands -----

    def interaction(self, frames, reason, message="", changed_line=None):
        """Paused: tell the IDE, and do what it says until it says go on. changed_line: for a
        watch that broke, the line that made the change (in the innermost frame)."""
        self.frames = frames
        self.selected = len(frames) - 1
        self.consoles = {}
        self.channel.send(event="paused", reason=reason, message=message, stack=self._stack_info(),
                          selected=self.selected, locals=self._locals(), watches=self._watch_values(),
                          stepping=not self.post_mortem_mode, changed_line=changed_line)
        while True:
            command = self.channel.receive()
            kind = command.get("cmd")
            if kind == "eval":
                self._run_line(command.get("line", ""))
            elif kind == "frame":
                self.selected = max(0, min(len(self.frames) - 1, int(command.get("index", 0))))
                self._send_frame()
            elif kind == "watches":
                self.set_watches(command.get("watches", []))
                self._send_frame()
            elif kind == "quick":
                self.channel.send(event="quick", info=self._quick(command.get("expression", "")))
            elif kind == "expand":
                self.channel.send(event="children", path=command.get("path"), items=self._expand(command.get("path")))
            elif kind == "breakpoints":
                self.clear_all_breaks()
                for file, lines in command.get("breakpoints", {}).items():
                    for line in lines:
                        self.set_break(self.canonic(file), int(line))
            elif kind == "closed":
                os._exit(0)  # the IDE has gone
            elif kind in ("continue", "step", "next", "return", "until"):
                if self.post_mortem_mode:
                    break  # after an error the event can only end
                frame = self.frames[-1][0]
                if kind == "continue":
                    self.set_continue()
                elif kind == "step":
                    self.set_step()
                elif kind == "next":
                    self.set_next(frame)
                elif kind == "return":
                    self.set_return(frame)
                elif kind == "until":
                    self.set_break(self.canonic(command["file"]), int(command["line"]), temporary=True)
                    self.set_continue()
                break
        self.frames = []
        self.consoles = {}
        self.last_running = None
        self.channel.send(event="running")

    def _stack_info(self):
        return [{"file": frame.f_code.co_filename, "line": line, "function": frame.f_code.co_name}
                for frame, line in self.frames]

    def _frame(self):
        return self.frames[self.selected][0]

    def _locals(self):
        frame = self._frame()
        return [value_info(name, value, [name]) for name, value in frame.f_locals.items()
                if not (name.startswith("__") and name.endswith("__"))]

    def _expand(self, path):
        try:
            if path[0] == WATCH:
                value, steps = self._watch_value(self.watches[int(path[1])])[0], path[2:]
            else:
                value, steps = self._frame().f_locals[path[0]], path[1:]
            for step in steps:
                value = dict(_children(value))[step]
        except Exception:  # noqa: BLE001 - gone, or a watch that now fails: nothing to show
            return []
        return [value_info(name, child, [*path, name]) for name, child in _children(value)]

    def _run_line(self, line):
        console = self.consoles.get(self.selected)
        if console is None:
            console = self.consoles[self.selected] = FrameConsole(self._frame(), self.extra_names())
        try:
            console.push(line)
        except SystemExit:
            os._exit(0)
        sys.stdout.flush()
        sys.stderr.flush()
        self._send_frame()  # values may have changed

    def _send_frame(self):
        self.channel.send(event="frame", selected=self.selected, locals=self._locals(), watches=self._watch_values())

    def _watch_values(self):
        """Each watch's value, for the Watches window: in the chosen frame while paused, else as
        the program runs, between events (see Watch.running_scope)."""
        return [self._watch_info(index, watch) for index, watch in enumerate(self.watches)]

    def _watch_info(self, index, watch):
        path = [WATCH, index]
        try:
            value, note = self._watch_value(watch)
        except OutOfContext:
            return {"name": watch.expression, "value": "<out of context>", "type": "", "path": path,
                    "expandable": False}
        except Exception as error:  # noqa: BLE001 - whatever the expression raises is its value here
            return {"name": watch.expression, "value": f"<{type(error).__name__}: {error}>", "type": "",
                    "path": path, "expandable": False}
        info = value_info(watch.expression, value, path)
        if note:
            info["note"] = note
        return info

    def _watch_value(self, watch):
        """(A watch's value, a note on it): in the chosen frame while paused (or another on the
        call stack, the innermost, if that one's out of context), else as the program runs; a
        function's watch elsewhere, as the function left it. Raises OutOfContext, or whatever
        the expression raises."""
        if self.frames and watch.in_context(self._frame(), self):
            return watch.evaluate(self._frame(), self.extra_names), ""
        if self.frames and watch.function:
            frame = next((f for f, _ in reversed(self.frames) if watch.in_context(f, self)), None)
            if frame is not None:
                return watch.evaluate(frame, self.extra_names), f"in {watch.function}"
        if watch.function:
            if watch.seen is None:
                raise OutOfContext
            return watch.seen[0], f"as {watch.function} left it"
        if self.frames:
            raise OutOfContext
        scope = watch.running_scope(self)
        if scope is None:
            raise OutOfContext
        return eval(watch.code, scope.maps[0], scope), ""

    def _quick(self, expression):
        """Quick Watch: an expression's value in the chosen frame."""
        try:
            value = eval(compile(expression, "<quick watch>", "eval"), self._frame().f_globals,
                         FrameScope(self._frame(), self.extra_names()))
        except Exception as error:  # noqa: BLE001
            return {"name": expression, "value": f"<{type(error).__name__}: {error}>", "type": "", "expandable": False}
        return value_info(expression, value, [])


WATCH = "#watch"  # a path starting [WATCH, index] is a watch's value, or its parts


class OutOfContext(Exception):
    """A watch asked for where it doesn't apply."""


class Watch:
    """A watch from the IDE: {expression, function ("" for any), file (relative to the
    project, "" for any), kind ("watch", "true" or "changes")}."""

    def __init__(self, spec, folder):
        self.spec = spec
        self.expression = spec.get("expression", "")
        self.function = spec.get("function", "")
        self.file = os.path.normcase(os.path.join(folder, spec["file"])) if spec.get("file") else ""
        self.kind = spec.get("kind", "watch")
        self.breaks = self.kind in ("true", "changes")
        try:
            self.code = compile(self.expression, "<watch>", "eval")
        except SyntaxError:
            self.code = compile(repr(f"<can't read: {self.expression}>"), "<watch>", "eval")
            self.breaks = False
        # Checked after each line in its context: those that break, and those of a function.
        self.traced = self.breaks or bool(self.function)
        self.last = None  # "changes": the value's repr when last checked (None: not yet)
        self.undefined_in = None  # the frame where it last couldn't be worked out (a variable not set yet)
        self.was_true = False
        self.seen = None  # (value,): a function's watch, as the function last had it

    def in_context(self, frame, debugger):
        if self.function and frame.f_code.co_name != self.function:
            return False
        if self.file:
            return debugger.canonic(frame.f_code.co_filename) == debugger.canonic(self.file)
        return debugger.in_project(frame)

    def evaluate(self, frame, extra_names):
        return eval(self.code, frame.f_globals, FrameScope(frame, extra_names()))

    def running_scope(self, debugger):
        """Where the watch is worked out while the program runs, or None if it can't be: no
        function is running between events, so a watch for one is out of context. Others see
        their file's module (or the startup form's), then the forms and controls, as Immediate
        lines do."""
        if self.function:
            return None
        names = debugger.extra_names()
        if self.file:
            module = next((m for m in list(sys.modules.values()) if getattr(m, "__file__", None)
                           and debugger.canonic(m.__file__) == debugger.canonic(self.file)), None)
            if module is None:
                return None  # (not loaded yet)
        else:
            form = names.get("form")
            module = sys.modules.get(type(form).__module__) if form is not None else None
        return ChainMap(vars(module) if module is not None else {"__builtins__": __builtins__}, names)

    def check(self, frame, extra_names):
        """After a line in its context: note the value, and say what happened if this watch
        breaks now (else "")."""
        try:
            value = self.evaluate(frame, extra_names)
        except Exception:  # noqa: BLE001 - not there (yet): no break
            self.was_true = False
            self.undefined_in = frame
            return ""
        if self.function:
            self.seen = (value,)
        if self.kind == "true":
            true = bool(value)
            fired, self.was_true = true and not self.was_true, true
            return f"{self.expression} became true" if fired else ""
        if self.kind != "changes":
            return ""
        shown = repr(value)
        before, self.last = self.last, shown
        set_here, self.undefined_in = self.undefined_in is frame, None
        if set_here:  # it didn't exist a line ago, in this same function: a variable was set
            return f"{self.expression} was set to {_short(shown)}"
        if before is None or before == shown:
            return ""
        return f"{self.expression} changed from {_short(before)} to {_short(shown)}"

    def left(self, frame):
        """frame is returning (no frame is kept)."""
        if self.undefined_in is frame:
            self.undefined_in = None


def _short(text, most=60):
    return text if len(text) <= most else text[:most - 3] + "..."


_debugger: Debugger | None = None


def current():
    """The program's debugger when the IDE is debugging it, else None."""
    return _debugger


def start(channel, folder, settings):
    """Debug this program: settings is the IDE's {"breakpoints", "watches", "break_on_errors"}."""
    global _debugger
    _debugger = Debugger(channel, folder)
    _debugger.break_on_errors = settings.get("break_on_errors", True)
    _debugger.watches = [Watch(w, _debugger.folder) for w in settings.get("watches", [])]
    _debugger.set_breakpoints(settings.get("breakpoints", {}))
    return _debugger


def handle(message):
    """A command from the IDE while the program runs (not paused)."""
    if _debugger is None:
        return
    kind = message.get("cmd")
    if kind == "breakpoints":
        _debugger.set_breakpoints(message.get("breakpoints", {}))
    elif kind == "watches":
        _debugger.set_watches(message.get("watches", []))
    elif kind == "pause":
        _debugger.pause_at_next_event()
    elif kind == "expand":  # a watch's parts
        _debugger.channel.send(event="children", path=message.get("path"), items=_debugger._expand(message.get("path")))
    elif kind == "break_on_errors":
        _debugger.break_on_errors = bool(message.get("on"))


def tick():
    """Called twice a second while the program runs: tell the IDE the watches' values, when they change."""
    if _debugger is None or not _debugger.watches:
        return
    values = _debugger._watch_values()
    if values != _debugger.last_running:
        _debugger.last_running = values
        _debugger.channel.send(event="watch_values", watches=values)


def event_failed(error):
    """An event handler raised error: with the IDE debugging, break there. Returns whether it did."""
    if _debugger is None or not _debugger.break_on_errors:
        return False
    traceback.print_exception(error)
    sys.stderr.flush()
    _debugger.post_mortem(error)
    return True

