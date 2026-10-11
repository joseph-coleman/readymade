"""Running the project's lint tools in the background, for the open code and for every
other file of the project.

Tools that read stdin check an open document's unsaved text shortly after typing
stops; the others check the saved file when it's opened or saved. Files that aren't
open are checked from disk: when the project opens, after saving (a change in one
file can cause problems in another), and when the tools change. Each tool's latest
results for a file replace its earlier ones; results that arrive after newer ones
were asked for are dropped. The Problems tab shows them all.
"""

from __future__ import annotations

import queue
import threading
from pathlib import Path

from readymade import lint
from readymade.project import ProjectError


class Linter:
    def __init__(self, app):
        self.app = app
        self._results: queue.Queue = queue.Queue()
        self._waiting = 0  # checks asked for whose results haven't arrived
        self._latest = {}  # (file, tool name) -> the latest check asked for
        self._told = set()  # tools whose trouble has been reported in the Immediate window
        self.problems: dict[Path, dict[str, list[lint.Problem]]] = {}  # file -> tool name -> its problems

    def tools(self):
        try:
            return lint.tools_for(self.app.project) if self.app.project else []
        except ProjectError:
            return []

    @property
    def busy(self):
        """Whether checks are still running."""
        return self._waiting > 0

    def all_problems(self):
        """Every problem found in the project, as (file, problem), by file name, line and column."""
        found = [(path, problem) for path, by_tool in self.problems.items() for problems in by_tool.values()
                 for problem in problems]
        return sorted(found, key=lambda item: (item[0].name.lower(), item[1].line, item[1].column, item[1].tool))

    def check(self, editor, saved=False):
        """Check an open document: everything after it's opened or saved; while typing, the stdin tools."""
        if editor.plain:
            return  # (a README or such: not Python)
        tools = self.tools()
        editor.code.keep_problems_of({tool.name for tool in tools})
        self._keep_tools(tools)
        if not saved:
            tools = [tool for tool in tools if tool.stdin]
        if not tools:
            self._changed()
            return
        self._start([(_file(editor.code_path), editor.code.get_source(), editor)], tools)

    def check_project(self):
        """Check the project's files that aren't open, as saved (open ones are checked as they're edited)."""
        project = self.app.project
        files = self.project_files()
        self.problems = {path: found for path, found in self.problems.items() if path in files}
        tools = self.tools()
        self._keep_tools(tools)
        opened = self._open_files()
        jobs = []
        for path in sorted(files - opened):
            try:
                jobs.append((path, path.read_text(encoding="utf-8"), None))
            except OSError:
                continue
        if project is None or not tools or not jobs:
            self._changed()
            return
        self._start(jobs, tools)

    def check_all(self):
        """After the tools change: check every open document again, and the rest of the project."""
        for editor in list(self.app.editors):
            if not editor.read_only:
                self.check(editor, saved=True)
        self.check_project()

    def project_files(self):
        """The project's code files: its forms' code and its modules."""
        project = self.app.project
        if project is None:
            return set()
        return {_file(project.folder / f"{name}.py") for name in [*project.forms(), *project.modules()]}

    def _open_files(self):
        return {_file(e.code_path) for e in self.app.editors if not e.read_only}

    def _keep_tools(self, tools):
        """Forget the problems of tools that are no longer chosen."""
        names = {tool.name for tool in tools}
        for found in self.problems.values():
            for name in set(found) - names:
                del found[name]

    def _start(self, jobs, tools):
        """Run each tool on each (file, source, editor or None), in a background thread."""
        project = self.app.project
        python = self.app.envs.python()[0]
        env, folder = self.app.runner.environment(), project.folder
        work_list = []
        for path, source, editor in jobs:
            for tool in tools:
                key = (path, tool.name)
                self._latest[key] = self._latest.get(key, 0) + 1
                work_list.append((path, source, editor, tool, self._latest[key]))
        self._waiting += len(work_list)

        def work():
            for path, source, editor, tool, version in work_list:
                problems, trouble = lint.run(tool, python, folder, path, source, env)
                self._results.put((path, editor, tool, version, problems, trouble))

        threading.Thread(target=work, daemon=True).start()
        if self._waiting == len(work_list):  # nothing was being collected
            self.app.root.after(100, self._collect)
        self._changed()  # "checking"

    def _collect(self):
        files, opened = self.project_files(), self._open_files()
        while True:
            try:
                path, editor, tool, version, problems, trouble = self._results.get_nowait()
            except queue.Empty:
                break
            self._waiting -= 1
            if self._latest.get((path, tool.name)) != version:
                continue  # a newer check is on its way
            if editor is not None and editor not in self.app.editors:
                continue  # closed: the saved file is checked instead
            if editor is None and path in opened:
                continue  # opened since: its editor's checks count
            if trouble and tool.name not in self._told:
                self._told.add(tool.name)
                self.app.immediate.write(f"--- Linting: {trouble}. Project > Linting... can install it. ---\n")
            if editor is not None:
                editor.code.set_problems(tool.name, problems)
            if path in files:
                self.problems.setdefault(path, {})[tool.name] = problems
        self._changed()
        if self._waiting > 0:
            self.app.root.after(100, self._collect)

    def _changed(self):
        changed = getattr(self.app, "problems_changed", None)
        if changed is not None:
            changed()


def _file(path):
    return Path(path).resolve()
