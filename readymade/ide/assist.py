"""Completion and Go to Definition, using Jedi (part of `pip install readymade[ide]`).

A form's controls and menu items aren't in its code (they come from the .form
file), so before Jedi reads a form's code, a few lines declaring them are
added to the class, in Jedi's copy only:

    class Form1(Form):
        from readymade import controls as _readymade_controls, menus as _readymade_menus
        Label1: _readymade_controls.Label
        mnuOpen: _readymade_menus.MenuItem

Then `self.` completes to the controls and `self.Label1.` to a Label's
properties. Line numbers are shifted back for the editor, and a definition
found in the added lines is reported as that control or menu item.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

jedi: Any = None
try:
    import jedi
except ImportError:  # the IDE works without it, minus these features
    pass

AVAILABLE = jedi is not None
_HIDDEN = "_readymade_"  # names of the added lines, never shown


@dataclass(frozen=True)
class Completion:
    name: str
    kind: str  # function, class, module, property, statement, ...


@dataclass(frozen=True)
class Definition:
    kind: str  # "control", "menu", "file", or "builtin" (no source to show)
    name: str
    path: Path | None = None
    line: int = 0
    column: int = 0


@dataclass(frozen=True)
class Prepared:
    """A form's code as Jedi sees it: added declarations after the class line."""
    source: str
    after: int  # the class line; lines below it are shifted down
    added: dict  # added line number -> (kind, name)

    def to_jedi(self, line):
        return line + len(self.added) if line > self.after else line

    def from_jedi(self, line):
        if line in self.added:
            return None
        return line - len(self.added) if line > self.after + len(self.added) else line


def prepare(source, class_name="", controls=(), menu_items=()):
    """Add declarations for a form's controls (type, name) and menu items (names) to its class."""
    lines = source.split("\n")
    header = next((i for i, line in enumerate(lines, 1) if re.match(rf"class\s+{re.escape(class_name)}\b.*:\s*$", line)), None)
    if not class_name or header is None:
        return Prepared(source, 0, {})
    body = next((line for line in lines[header:] if line.strip()), "    ")
    indent = body[: len(body) - len(body.lstrip())] or "    "
    added_lines = [f"{indent}from readymade import controls as {_HIDDEN}controls, menus as {_HIDDEN}menus"]
    added = {header + 1: ("import", "", "")}
    for type_name, name in controls:
        added[header + 1 + len(added_lines)] = ("control", name, type_name)
        added_lines.append(f"{indent}{name}: {_HIDDEN}controls.{type_name}")
    for name in menu_items:
        added[header + 1 + len(added_lines)] = ("menu", name, "MenuItem")
        added_lines.append(f"{indent}{name}: {_HIDDEN}menus.MenuItem")
    return Prepared("\n".join(lines[:header] + added_lines + lines[header:]), header, added)


class Assistant:
    """Answers completion and definition questions about a project's code. Jedi isn't
    thread-safe, so questions are answered one at a time."""

    def __init__(self, readymade_root):
        self.readymade_root = str(readymade_root)
        self._lock = threading.Lock()
        self._projects = {}

    def _project(self, folder, python):
        key = (str(folder), str(python) if python else None)
        if key not in self._projects:
            try:
                self._projects[key] = jedi.Project(folder, environment_path=key[1], added_sys_path=[self.readymade_root])
            except Exception:  # an environment Jedi can't use: fall back to its own Python
                self._projects[key] = jedi.Project(folder, added_sys_path=[self.readymade_root])
        return self._projects[key]

    def _script(self, prepared, path, folder, python):
        return jedi.Script(prepared.source, path=str(path), project=self._project(folder, python))

    def complete(self, prepared, line, column, path, folder, python):
        """Completions at (line, column) of the editor's code (lines from 1, columns from 0)."""
        with self._lock:
            try:
                found = self._script(prepared, path, folder, python).complete(prepared.to_jedi(line), column)
            except Exception:  # Jedi can fail on unusual code; then there's simply nothing to offer
                return []
        return [Completion(c.name, c.type) for c in found if not c.name.startswith(_HIDDEN)]

    def help(self, prepared, line, column, path, folder, python):
        """Help on the name at (line, column): a Topic, ("control", name, type) or ("menu", name, ...)
        for a form's own, or None."""
        from readymade.ide.helptext import Topic

        with self._lock:
            try:
                found = self._script(prepared, path, folder, python).help(prepared.to_jedi(line), column)
                if not found:
                    return None
                name = found[0]
                if name.module_path and Path(name.module_path) == Path(path) and name.line in prepared.added:
                    return prepared.added[name.line]
                text = name.docstring()
                if not text.strip() and name.type in ("statement", "instance", "param"):
                    inferred = name.infer()  # a variable: help on what it holds
                    if inferred:
                        name, text = inferred[0], inferred[0].docstring()
                full = name.full_name or name.name
                kind = name.type
            except Exception:  # Jedi can fail on unusual code
                return None
        if not text.strip() and full.startswith("readymade."):
            text = _readymade_doc(full)  # e.g. properties, whose docstrings Jedi doesn't read
        where = full.rsplit(".", 1)[0] if "." in full and kind != "module" else ""
        subtitle = kind + (f" in {where}" if where and where != "builtins" else "")
        return Topic(full, subtitle, text.strip() or "(No documentation.)", _docs_url(kind, full))

    def definition(self, prepared, line, column, path, folder, python):
        """Where the name at (line, column) is defined, or None."""
        with self._lock:
            try:
                found = self._script(prepared, path, folder, python).goto(prepared.to_jedi(line), column, follow_imports=True)
            except Exception:
                return None
        if not found:
            return None
        target = found[0]
        if target.module_path and Path(target.module_path) == Path(path) and target.line in prepared.added:
            kind, name, _ = prepared.added[target.line]
            return Definition(kind, name)
        if not target.module_path or target.line is None:
            return Definition("builtin", target.name)
        line = prepared.from_jedi(target.line) if Path(target.module_path) == Path(path) else target.line
        return Definition("file", target.name, Path(target.module_path), line, target.column)


def _docs_url(kind, full):
    """The Python documentation's page about a standard-library name, or ""."""
    import sys

    top = full.split(".")[0]
    if kind == "keyword" or top.startswith("_"):
        return ""
    if top == "builtins":
        rest = full[len("builtins."):]
        # Functions and types like len and int are on the built-in functions page; methods like str.upper on stdtypes.
        return f"https://docs.python.org/3/library/{'stdtypes' if '.' in rest else 'functions'}.html#{rest}"
    if top in sys.stdlib_module_names:
        if kind == "module":
            return f"https://docs.python.org/3/library/{full}.html"
        module = full.rsplit(".", 1)[0]
        return f"https://docs.python.org/3/library/{module if module.count('.') <= 1 else top}.html#{full}"
    return ""


def _readymade_doc(full):
    """The docstring of something in readymade, read from readymade itself (it's loaded in the IDE)."""
    import importlib
    import inspect

    parts = full.split(".")
    for split in range(len(parts) - 1, 0, -1):
        try:
            thing = importlib.import_module(".".join(parts[:split]))
        except ImportError:
            continue
        for part in parts[split:]:
            thing = inspect.getattr_static(thing, part, None)
            if thing is None:
                return ""
        return inspect.getdoc(thing) or ""
    return ""
