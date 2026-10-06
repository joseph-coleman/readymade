"""Syntax colouring for the code window, in the colours of VS Code's light theme.

Uses Pygments when it's installed (`pip install readymade[ide]`); without it,
a simpler built-in colouring of keywords, strings and comments.
"""

from __future__ import annotations

import bisect
import keyword
import re
from typing import Any

# Tag name -> colour. The code window gives each tag its colour.
COLORS = {
    "keyword": "#0000ff",
    "control": "#af00db",
    "string": "#a31515",
    "escape": "#ee0000",
    "comment": "#008000",
    "number": "#098658",
    "function": "#795e26",
    "class": "#267f99",
    "variable": "#001080",
}
# Shown like control flow, as VS Code does, including import, from and as.
_CONTROL = {"if", "elif", "else", "for", "while", "break", "continue", "return", "try", "except", "finally",
            "raise", "with", "yield", "await", "pass", "match", "case", "assert", "import", "from", "as"}

_token: Any = None
_LEXER: Any = None  # stays None without Pygments; the IDE works without it
try:
    from pygments import token as _token
    from pygments.lexers import PythonLexer

    # No stripping or added newline, so the tokens line up with the text exactly.
    _LEXER = PythonLexer(stripnl=False, ensurenl=False)
except ImportError:
    pass


def spans(source):
    """(tag, start, end) for the coloured parts of source, as Tk text indexes like "3.4"."""
    found = _pygments_spans(source) if _LEXER is not None else _simple_spans(source)
    merged = []
    for tag, start, end in found:
        if merged and merged[-1][0] == tag and merged[-1][2] == start:
            merged[-1] = (tag, merged[-1][1], end)  # fewer, longer tags are quicker for Tk
        else:
            merged.append((tag, start, end))
    return merged


def _tag_for(kind, value):
    t = _token
    if kind in t.Comment:
        return "comment"
    if kind in t.String.Escape:
        return "escape"
    if kind in t.String.Interpol:
        return "keyword"  # the braces of an f-string
    if kind in t.String:
        return "string"
    if kind in t.Number:
        return "number"
    if kind in t.Keyword:
        return "control" if value in _CONTROL else "keyword"
    if kind in t.Operator.Word:
        return "keyword"
    if kind in t.Name.Builtin.Pseudo:
        return "variable"  # self, cls
    if kind in t.Name.Class or kind in t.Name.Exception:
        return "class"
    if kind in t.Name.Function or kind in t.Name.Decorator or kind in t.Name.Builtin:
        return "function"
    return None


def _pygments_spans(source):
    line, column = 1, 0
    for kind, value in _LEXER.get_tokens(source):
        newlines = value.count("\n")
        end_line = line + newlines
        end_column = len(value) - value.rfind("\n") - 1 if newlines else column + len(value)
        tag = _tag_for(kind, value)
        if tag:
            yield tag, f"{line}.{column}", f"{end_line}.{end_column}"
        line, column = end_line, end_column


_STRING = r"'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\""
_SIMPLE = re.compile(rf"(?P<comment>#[^\n]*)|(?P<string>{_STRING})|(?P<keyword>\b(?:{'|'.join(keyword.kwlist)})\b)")


def _simple_spans(source):
    starts = [0] + [m.end() for m in re.finditer("\n", source)]  # where each line begins

    def index(offset):
        line = bisect.bisect_right(starts, offset)
        return f"{line}.{offset - starts[line - 1]}"

    for m in _SIMPLE.finditer(source):
        tag = m.lastgroup
        if tag == "keyword" and m.group() in _CONTROL:
            tag = "control"
        yield tag, index(m.start()), index(m.end())
