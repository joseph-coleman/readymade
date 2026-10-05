"""Completion and Go to Definition, using Jedi (part of `pip install pybasic[ide]`).

A form's controls and menu items aren't in its code (they come from the .form
file), so before Jedi reads a form's code, a few lines declaring them are
added to the class, in Jedi's copy only:

    class Form1(Form):
        from pybasic import controls as _pybasic_controls, menus as _pybasic_menus
        Label1: _pybasic_controls.Label
        mnuOpen: _pybasic_menus.MenuItem

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
_HIDDEN = "_pybasic_"  # names of the added lines, never shown


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
    added_lines = [f"{indent}from pybasic import controls as {_HIDDEN}controls, menus as {_HIDDEN}menus"]
    added = {header + 1: ("import", "")}
    for type_name, name in controls:
        added[header + 1 + len(added_lines)] = ("control", name)
        added_lines.append(f"{indent}{name}: {_HIDDEN}controls.{type_name}")
    for name in menu_items:
        added[header + 1 + len(added_lines)] = ("menu", name)
        added_lines.append(f"{indent}{name}: {_HIDDEN}menus.MenuItem")
    return Prepared("\n".join(lines[:header] + added_lines + lines[header:]), header, added)


class Assistant:
    """Answers completion and definition questions about a project's code. Jedi isn't
    thread-safe, so questions are answered one at a time."""

    def __init__(self, pybasic_root):
        self.pybasic_root = str(pybasic_root)
        self._lock = threading.Lock()
        self._projects = {}

    def _project(self, folder, python):
        key = (str(folder), str(python) if python else None)
        if key not in self._projects:
            try:
                self._projects[key] = jedi.Project(folder, environment_path=key[1], added_sys_path=[self.pybasic_root])
            except Exception:  # an environment Jedi can't use: fall back to its own Python
                self._projects[key] = jedi.Project(folder, added_sys_path=[self.pybasic_root])
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
            kind, name = prepared.added[target.line]
            return Definition(kind, name)
        if not target.module_path or target.line is None:
            return Definition("builtin", target.name)
        line = prepared.from_jedi(target.line) if Path(target.module_path) == Path(path) else target.line
        return Definition("file", target.name, Path(target.module_path), line, target.column)
