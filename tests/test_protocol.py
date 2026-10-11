"""The messages between the IDE and the programs it runs (readymade.protocol)."""

import ast
from pathlib import Path

import pytest

from readymade import protocol
from readymade.protocol import COMMANDS, EVENTS, Cmd, Event, Reason

SOURCE = Path(__file__).resolve().parent.parent / "readymade"


def test_check():
    message = {"cmd": Cmd.JUMP, "file": "Form1.py", "line": 12}
    assert protocol.check(message) is message
    assert protocol.check({"event": Event.RUNNING})
    for bad, said in (({"cmd": "jmup", "file": "x", "line": 1}, "no such cmd: 'jmup'"),
                      ({"cmd": Cmd.JUMP, "file": "x"}, "missing line"),
                      ({"cmd": Cmd.JUMP, "file": "x", "line": 1, "column": 2}, "unknown column"),
                      ({"line": 1}, "a cmd or an event"),
                      ({"cmd": Cmd.EVAL, "event": Event.NOTE}, "a cmd or an event")):
        with pytest.raises(ValueError, match=said):
            protocol.check(bad)


def test_every_name_is_listed():
    names = {value for key, value in vars(Cmd).items() if not key.startswith("_")}
    assert names == set(COMMANDS)
    assert {value for key, value in vars(Event).items() if not key.startswith("_")} == set(EVENTS)
    assert set(protocol.STEPPING) < names


def _calls():
    """Every .send(cmd=..., ...) or .send(event=..., ...) in readymade's code."""
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "send"
                    and any(k.arg in ("cmd", "event") for k in node.keywords)):
                yield path, node


def test_every_message_sent_is_one_listed():
    """A static check: it covers messages no test happens to send."""
    checked = 0
    for path, call in _calls():
        where = f"{path.name}:{call.lineno}"
        kind = next(k for k in call.keywords if k.arg in ("cmd", "event"))
        given = {k.arg for k in call.keywords if k.arg is not None} - {kind.arg}
        if isinstance(kind.value, ast.Name) or any(k.arg is None for k in call.keywords):
            continue  # (a name chosen at run time, like Continue or a step, or fields passed on: check() sees those)
        assert isinstance(kind.value, ast.Attribute), f"{where}: send a name from readymade.protocol"
        table = COMMANDS if kind.arg == "cmd" else EVENTS
        name = getattr(Cmd if kind.arg == "cmd" else Event, kind.value.attr)
        assert given == set(table[name]), f"{where}: {kind.arg} {name!r} sends {sorted(given)}"
        checked += 1
    assert checked >= 20  # (so the scan is really finding them)


def test_every_name_used_exists():
    """Cmd.X, Event.X and Reason.X anywhere in readymade's code: a misspelled one would only fail when run."""
    owners = {"Cmd": Cmd, "Event": Event, "Reason": Reason}
    for path in SOURCE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in owners:
                if path.name == "protocol.py" or (node.value.id == "Event" and path.name in ("controls.py", "form.py",
                                                                                           "editors.py", "menus.py")):
                    continue  # (controls' own Event, a different thing)
                assert hasattr(owners[node.value.id], node.attr), f"{path.name}:{node.lineno}: no {node.value.id}.{node.attr}"
