"""The project's breakpoints and watches: where they're kept, and how they're read, changed
and renamed, in one place (the debug controller shows them and tells the running program).

They're remembered on this machine, in the project's .readymade/local.json:

    "breakpoints": {"Form1.py": [12, {"line": 20, "condition": "total > 100"}]}
    "watches": [{"expression": "total", "function": "add_tax", "file": "Form1.py", "kind": "watch"}]

A breakpoint is a line number, or with settings {line, condition, hit_mode, hits, log,
disabled} (see readymade.debugger.BreakCondition). Open code holds its breakpoints as marks
in its CodeView, which move with edits; this reads them from there, and a closed file's
from what's remembered.
"""

from __future__ import annotations


def breakpoint_item(item):
    """A remembered breakpoint (a line, or {line, ...settings}) as (line, settings)."""
    if isinstance(item, dict):
        return item["line"], {k: v for k, v in item.items() if k != "line"}
    return item, {}


class Breakpoints:
    def __init__(self, app):
        self.app = app

    @property
    def project(self):
        return self.app.project

    # ----- breakpoints -----

    def saved(self):
        """The breakpoints as remembered: {file (relative to the project): [line or {line, ...}]}."""
        return self.project.local_settings().get("breakpoints", {}) if self.project else {}

    def all(self):
        """Every breakpoint in the project, open files' as they are now: {file: [line or {line, ...}]}."""
        if self.project is None:
            return {}
        found = dict(self.saved())
        for editor in self.app.editors:
            if editor.is_project_code:
                found[self.project.relative(editor.code_path)] = editor.code.breakpoints()
        return {name: items for name, items in found.items() if items and (self.project.folder / name).exists()}

    def in_file(self, file):
        """A file's remembered breakpoints, for its code as it opens."""
        return self.saved().get(file, [])

    def rows(self):
        """For the Breakpoints tab: [(file, line, the line's code, settings)]."""
        rows = []
        for file, items in sorted(self.all().items()):
            editor = self.editor_for(file)
            if editor is not None:
                lines = editor.code.get_source().splitlines()
            else:
                lines = (self.project.folder / file).read_text(encoding="utf-8", errors="replace").splitlines()
            for item in items:
                line, settings = breakpoint_item(item)
                rows.append((file, line, lines[line - 1].strip() if 0 < line <= len(lines) else "", settings))
        return rows

    def for_program(self):
        """The breakpoints switched on, as the running program wants them: {full path: [line or {line, ...}]}."""
        found = {}
        for name, items in self.all().items():
            on = [item for item in items if not (isinstance(item, dict) and item.get("disabled"))]
            if on:
                found[str(self.project.folder / name)] = on
        return found

    def store(self):
        """Remember them as they are now (open files' marks move with edits)."""
        if self.project is not None:
            found = self.all()
            if found != self.saved():
                self.project.set_local_setting("breakpoints", found or None)

    def editor_for(self, file):
        """The open editor of a project file (relative name), or None."""
        return next((e for e in self.app.editors if e.is_project_code
                     and self.project.relative(e.code_path) == file), None)

    def change(self, file, line, change):
        """Change a breakpoint: change(settings) -> its new settings, or with change None,
        remove it. An open file's is changed in its code (which says so, as its marks change);
        a closed file's where it's remembered. Returns True for a closed file's (the caller
        then says so), False otherwise."""
        editor = self.editor_for(file)
        if editor is not None:
            settings = editor.code.breakpoint_settings(line)
            if settings is not None:
                if change is None:
                    editor.code.toggle_breakpoint(line)
                else:
                    editor.code.set_breakpoint_settings(line, change(settings))
            return False
        saved = {name: list(items) for name, items in self.saved().items()}
        items = saved.get(file, [])
        for index, item in enumerate(items):
            at, settings = breakpoint_item(item)
            if at == line:
                new = None if change is None else {k: v for k, v in change(settings).items() if v}
                if new is None:
                    del items[index]
                else:
                    items[index] = {"line": line, **new} if new else line
                break
        saved[file] = items
        self.project.set_local_setting("breakpoints", {k: v for k, v in saved.items() if v} or None)
        return True

    def clear(self):
        """No breakpoints, anywhere."""
        for editor in self.app.editors:
            editor.code.set_breakpoints([])
        if self.project is not None:
            self.project.set_local_setting("breakpoints", None)

    # ----- watches -----

    def watches(self):
        """The project's watches: [{expression, function, file, kind}]."""
        return self.project.local_settings().get("watches", []) if self.project else []

    def save_watches(self, watches):
        self.project.set_local_setting("watches", watches or None)

    def breaking_watches(self):
        """The watches that pause the program, which act like breakpoints: [(index, watch)]."""
        return [(i, w) for i, w in enumerate(self.watches()) if w.get("kind") in ("true", "changes")]

    # ----- files -----

    def file_renamed(self, old, new):
        """A file was renamed (relative names): its breakpoints and watches go with it. Returns
        whether any watches changed (for the running program to hear)."""
        saved = self.saved()
        if old in saved:
            self.project.set_local_setting("breakpoints", {new if k == old else k: v for k, v in saved.items()})
        watches = self.watches()
        if not any(w.get("file") == old for w in watches):
            return False
        self.save_watches([{**w, "file": new} if w.get("file") == old else w for w in watches])
        return True
