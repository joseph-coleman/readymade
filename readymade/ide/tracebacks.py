"""Spot Python tracebacks in a running program's output, so the IDE can show
where in the project an error happened."""

from __future__ import annotations

import os
import re
from pathlib import Path

# A traceback frame, e.g. `  File "/p/Form1.py", line 12, in Button1_click`. A
# SyntaxError's frame has no ", in ...".
_FRAME = re.compile(r'^  File "(?P<file>[^"]+)", line (?P<line>\d+)')


class TracebackWatcher:
    """Feed it output lines; on_error(path, line, message) is called for each
    traceback whose last frame in the project folder is known."""

    def __init__(self, folder, on_error):
        self.folder = os.path.normcase(os.path.abspath(folder))
        self.on_error = on_error
        self.frames = None  # while inside a traceback: [(file, line), ...]

    def feed(self, line):
        line = line.rstrip("\n")
        if line.startswith("Traceback (most recent call last):"):
            self.frames = []
            return
        if self.frames is None:
            return
        frame = _FRAME.match(line)
        if frame:
            self.frames.append((frame["file"], int(frame["line"])))
            return
        if not line.strip() or line[0] in " \t":
            return  # the frame's code, ^ markers, or a blank line
        # The first unindented line ends the traceback: it's the error itself.
        frames, self.frames = self.frames, None
        ours = [(f, n) for f, n in frames if self._in_project(f)]
        if ours:
            file, number = ours[-1]
            self.on_error(Path(file), number, line.strip())

    def _in_project(self, file):
        return os.path.normcase(os.path.dirname(os.path.abspath(file))) == self.folder
