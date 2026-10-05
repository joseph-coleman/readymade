"""Running the project's lint tools for the open code, in the background.

Tools that read stdin check the unsaved text shortly after typing stops; the
others check the saved file when it's opened or saved. Each tool's latest
results replace its earlier ones; results that arrive after newer ones were
asked for are dropped.
"""

from __future__ import annotations

import queue
import threading

from pybasic import lint
from pybasic.project import ProjectError


class Linter:
    def __init__(self, app):
        self.app = app
        self._results: queue.Queue = queue.Queue()
        self._waiting = 0  # checks asked for whose results haven't arrived
        self._latest = {}  # (editor, tool name) -> the latest check asked for
        self._told = set()  # tools whose trouble has been reported in the Immediate window

    def tools(self):
        try:
            return lint.tools_for(self.app.project) if self.app.project else []
        except ProjectError:
            return []

    def check(self, editor, saved=False):
        """Check an open document: everything after it's opened or saved; while typing, the stdin tools."""
        tools = self.tools()
        editor.code.keep_problems_of({tool.name for tool in tools})
        if not saved:
            tools = [tool for tool in tools if tool.stdin]
        if not tools:
            return
        project = self.app.project
        python = self.app.python()[0]
        env, folder, path, source = self.app.environment(), project.folder, editor.code_path, editor.code.get_source()
        jobs = []
        for tool in tools:
            key = (editor, tool.name)
            self._latest[key] = self._latest.get(key, 0) + 1
            jobs.append((tool, self._latest[key]))
        self._waiting += len(jobs)

        def work():
            for tool, version in jobs:
                problems, trouble = lint.run(tool, python, folder, path, source, env)
                self._results.put((editor, tool, version, problems, trouble))

        threading.Thread(target=work, daemon=True).start()
        if self._waiting == len(jobs):  # nothing was being collected
            self.app.root.after(100, self._collect)

    def check_all(self):
        """After the tools change: check every open document again."""
        for editor in list(self.app.editors):
            self.check(editor, saved=True)

    def _collect(self):
        while True:
            try:
                editor, tool, version, problems, trouble = self._results.get_nowait()
            except queue.Empty:
                break
            self._waiting -= 1
            if editor not in self.app.editors or self._latest.get((editor, tool.name)) != version:
                continue  # closed, or a newer check is on its way
            if trouble and tool.name not in self._told:
                self._told.add(tool.name)
                self.app.immediate.write(f"--- Linting: {trouble}. Project > Linting... can install it. ---\n")
            editor.code.set_problems(tool.name, problems)
        if self._waiting > 0:
            self.app.root.after(100, self._collect)
