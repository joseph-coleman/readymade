"""The messages between the IDE and a program it runs (python -m readymade.run --debug PORT).

The IDE listens on a localhost port and the program connects; they exchange JSON lines,
each a dict. A command (the IDE to the program) has "cmd" with its name; an event (the
program to the IDE) has "event". Their other keys are listed below, with what they mean.
Both sides send through check(), so a misspelled name or field fails at once (in the
tests) instead of being quietly ignored by the other side. The program's print() output
doesn't come this way: it goes to its stdout, which the IDE shows in the Immediate window.

Programs run without the IDE never use any of this.
"""

from __future__ import annotations


class Cmd:
    """The IDE's commands to the program, by name."""

    START = "start"
    EVAL = "eval"
    ANSWER = "answer"
    PAUSE = "pause"
    BREAKPOINTS = "breakpoints"
    WATCHES = "watches"
    BREAK_ON_ERRORS = "break_on_errors"
    FRAME = "frame"
    EXPAND = "expand"
    ASSIGN = "assign"
    QUICK = "quick"
    TIP = "tip"
    JUMP = "jump"
    CONTINUE = "continue"
    STEP = "step"
    NEXT = "next"
    RETURN = "return"
    UNTIL = "until"
    CLOSED = "closed"


class Event:
    """The program's events to the IDE, by name."""

    INPUT = "input"
    PAUSED = "paused"
    RUNNING = "running"
    FRAME = "frame"
    CHILDREN = "children"
    WATCH_VALUES = "watch_values"
    NOTE = "note"
    LOG = "log"
    TIP = "tip"
    QUICK = "quick"


class Reason:
    """Why the program paused (a paused event's reason)."""

    BREAKPOINT = "breakpoint"  # at a breakpoint
    STEP = "step"  # after a step, a Pause, or Run to Cursor
    WATCH = "watch"  # a watch that breaks fired
    ERROR = "error"  # an event handler failed: the program can't go on from that line
    RAISED = "raised"  # an error was raised here, maybe to be caught (Break on All Errors)


STEPPING = (Cmd.STEP, Cmd.NEXT, Cmd.RETURN, Cmd.UNTIL)  # the ways on from a pause that step (not CONTINUE)

# Value shapes used below:
#   breakpoints  {full path: [line, or {line, condition, hit_mode, hits, log}]} (see debugger.BreakCondition)
#   watches      [{expression, function, file, kind}] (see debugger.Watch)
#   variable     {name, value (its repr, shortened), type, path, expandable}, maybe with note
#                (see debugger.value_info); path names it from the frame: ["basket", "[0]"],
#                or a watch's: ["#watch", 0, ...]
#   frame        {file, line, function}

COMMANDS = {
    Cmd.START: {  # the first thing the program reads, before any form loads
        "breakpoints": "the breakpoints switched on",
        "watches": "the watches",
        "break_on_errors": "pause where an event handler fails",
        "break_on_all": "also where an error is raised, even if a try catches it",
        "step": "pause as the first event starts (F10 or F11 to start)",
    },
    Cmd.EVAL: {"line": "an Immediate line: run in the program, or while paused in the chosen frame"},
    Cmd.ANSWER: {"text": "the answer to input()", "eof": "no answer: input() raises EOFError"},
    Cmd.PAUSE: {},  # pause as the next event starts
    Cmd.BREAKPOINTS: {"breakpoints": "all of them, now"},
    Cmd.WATCHES: {"watches": "all of them, now"},
    Cmd.BREAK_ON_ERRORS: {"on": "pause where an event handler fails", "all": "also where an error is raised"},
    # While paused:
    Cmd.FRAME: {"index": "the call stack frame to look at (0: the outermost)"},
    Cmd.EXPAND: {"path": "a variable's path: its parts are wanted (a children event)"},
    Cmd.ASSIGN: {"path": "a variable's path", "value": "the new value, a Python expression"},
    Cmd.QUICK: {"expression": "Quick Watch: its value is wanted (a quick event)"},
    Cmd.TIP: {"id": "to match the answer", "expression": "the name under the mouse (a tip event answers)"},
    Cmd.JUMP: {"file": "the paused function's file", "line": "go on from this line (Set Next Statement)"},
    Cmd.CONTINUE: {},
    Cmd.STEP: {},  # into
    Cmd.NEXT: {},  # over
    Cmd.RETURN: {},  # out
    Cmd.UNTIL: {"file": "the file", "line": "run to this line (Run to Cursor)"},
    Cmd.CLOSED: {},  # never sent: the program's channel gives it when the IDE has gone
}

EVENTS = {
    Event.INPUT: {"prompt": "input() is waiting for an answer (an answer command)"},
    Event.PAUSED: {
        "reason": "a Reason",
        "message": "what to say about it: the error, the watch that fired, the condition",
        "stack": "[frame], outermost first",
        "selected": "the frame shown (the innermost)",
        "locals": "[variable] of the selected frame",
        "watches": "[variable] for each watch, in order",
        "stepping": "whether it can step on (not after an error)",
        "changed_line": "for a watch that fired, the line that changed its value, or None",
        "ends": "going on ends the program (it failed as it started)",
        "watches_fired": "the indexes of the watches that fired",
    },
    Event.RUNNING: {},  # it went on
    Event.FRAME: {"selected": "the frame shown", "locals": "[variable]", "watches": "[variable]"},
    Event.CHILDREN: {"path": "the variable opened", "items": "[variable], its parts"},
    Event.WATCH_VALUES: {"watches": "[variable]: their values as the program runs, when they change"},
    Event.NOTE: {"text": "something for the Immediate window, like why Set Next Statement couldn't"},
    Event.LOG: {"text": "a logpoint's message", "file": "where", "line": "its line"},
    Event.TIP: {"id": "the tip command's", "info": "a variable"},
    Event.QUICK: {"info": "a variable"},
}


def check(message):
    """Return message if it's one of the above, with just its fields; raise ValueError if not."""
    if ("cmd" in message) == ("event" in message):
        raise ValueError(f"a message has a cmd or an event, not {message!r}")
    kind, name = ("cmd", message["cmd"]) if "cmd" in message else ("event", message["event"])
    fields = (COMMANDS if kind == "cmd" else EVENTS).get(name)
    if fields is None:
        raise ValueError(f"no such {kind}: {name!r}")
    given = set(message) - {kind}
    if given != set(fields):
        missing, extra = sorted(set(fields) - given), sorted(given - set(fields))
        raise ValueError(f"{kind} {name!r}: " + "; ".join(filter(None, (
            f"missing {', '.join(missing)}" if missing else "", f"unknown {', '.join(extra)}" if extra else ""))))
    return message
