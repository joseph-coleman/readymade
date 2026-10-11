"""Small source edits on a form's .py module: adding, finding and renaming handlers.

These work on lines and regular expressions rather than the ast, so they keep
working while the code has a syntax error in it, which is most of the time
during editing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

INDENT = "    "


class CodeGenError(Exception):
    pass


@dataclass(frozen=True)
class Edit:
    """Replace lines [start, end) (0-based) with text."""

    start: int
    end: int
    text: str
    method_line: int  # 1-based line of the new def once the edit is applied

    def apply(self, source):
        lines = source.splitlines(keepends=True)
        return "".join(lines[: self.start]) + self.text + "".join(lines[self.end :])


def new_module(class_name):
    return (
        "from readymade import Form\n"
        "\n"
        "\n"
        f"class {class_name}(Form):\n"
        f"{INDENT}pass\n"
        "\n"
        "\n"
        'if __name__ == "__main__":\n'
        f"{INDENT}{class_name}.run()\n"
    )


def defined_methods(source):
    return set(re.findall(r"^[ \t]+(?:async[ \t]+)?def[ \t]+(\w+)[ \t]*\(", source, re.M))


def find_method(source, name):
    """The 1-based line of `def name(`, or None."""
    m = re.search(rf"^[ \t]+(?:async[ \t]+)?def[ \t]+{re.escape(name)}[ \t]*\(", source, re.M)
    return source.count("\n", 0, m.start()) + 1 if m else None


def method_at(source, line):
    """The name of the method (or function) a line (1-based) is in, or None. By the
    indentation of the lines that start statements (not those inside brackets or strings),
    so it works while the code has errors."""
    lines = source.splitlines()
    if not 1 <= line <= len(lines):
        return None
    starts = _statement_lines(source)
    defs = []  # [(indent, name)] around the line being read
    for number, text in enumerate(lines[:line], 1):
        stripped = text.strip()
        if number not in starts or not stripped or stripped.startswith("#"):
            continue
        indent = len(text) - len(text.lstrip())
        while defs and indent <= defs[-1][0]:
            defs.pop()
        found = re.match(r"[ \t]*(?:async[ \t]+)?def[ \t]+(\w+)", text)
        if found:
            defs.append((indent, found.group(1)))
    return defs[-1][1] if defs else None


def _statement_lines(source):
    """The line numbers where statements start (lines of their own, not continued ones);
    after a tokenizing error, every later line counts."""
    import io
    import tokenize

    starts, expecting = set(), True
    try:
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type in (tokenize.NEWLINE, tokenize.NL):
                expecting = expecting or token.type == tokenize.NEWLINE
            elif token.type not in (tokenize.COMMENT, tokenize.INDENT, tokenize.DEDENT) and expecting:
                starts.add(token.start[0])
                expecting = False
    except (tokenize.TokenError, IndentationError, SyntaxError) as error:
        broke_at = error.args[1][0] if len(error.args) > 1 and isinstance(error.args[1], tuple) else 1
        starts.update(range(broke_at, source.count("\n") + 2))
    return starts


def add_method(source, class_name, name, params=()):
    """An Edit that adds an empty method at the end of the class."""
    lines = source.splitlines(keepends=True)
    class_re = re.compile(rf"class[ \t]+{re.escape(class_name)}\b")
    start = next((i for i, line in enumerate(lines) if class_re.match(line)), None)
    if start is None:
        raise CodeGenError(f"Couldn't find 'class {class_name}' in the code.")

    # The class body runs until the first non-blank, non-comment line at column 0.
    last = start
    for i in range(start + 1, len(lines)):
        line = lines[i]
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line[0] not in " \t":
            break
        last = i

    body = [i for i in range(start + 1, last + 1) if lines[i].strip() and not lines[i].lstrip().startswith("#")]
    indent = INDENT
    if body:
        first = lines[body[0]]
        indent = first[: len(first) - len(first.lstrip())]
    signature = ", ".join(("self", *params))
    method = f"{indent}def {name}({signature}):\n{indent}{indent}pass\n"

    # A new class holds only a placeholder `pass`; replace it.
    if len(body) == 1 and lines[body[0]].strip() == "pass":
        return Edit(body[0], body[0] + 1, method, method_line=body[0] + 1)

    insert_at = last + 1
    prefix = "" if lines[last].endswith("\n") else "\n"
    return Edit(insert_at, insert_at, prefix + "\n" + method, method_line=insert_at + 2)


def method_text(source, name):
    """A method's code: its def (and any decorators) through the end of its body, or None."""
    line = find_method(source, name)
    if line is None:
        return None
    lines = source.splitlines(keepends=True)
    start = line - 1
    indent = _indent(lines[start])
    while start > 0 and lines[start - 1].lstrip().startswith("@") and _indent(lines[start - 1]) == indent:
        start -= 1
    end = line
    while end < len(lines) and (not lines[end].strip() or len(_indent(lines[end])) > len(indent)):
        end += 1
    while end > line and not lines[end - 1].strip():
        end -= 1  # (not the blank lines after it)
    text = "".join(lines[start:end])
    return text if text.endswith("\n") else text + "\n"


def add_method_text(source, class_name, text):
    """The source with a method's code (from method_text) added at the end of the class,
    indented as the class's other methods are."""
    edit = add_method(source, class_name, "_new_method_")
    placeholder = next(line for line in edit.text.splitlines(keepends=True) if "def _new_method_" in line)
    indent, old = _indent(placeholder), _indent(text)
    moved = "".join(indent + line[len(old):] if line.startswith(old) else line
                    for line in text.splitlines(keepends=True))
    body = edit.text[: edit.text.index(placeholder)] + moved
    return Edit(edit.start, edit.end, body, edit.method_line).apply(source)


def _indent(line):
    return line[: len(line) - len(line.lstrip())]


def rename_control(source, old, new, events):
    """Rename a control's handlers and its `self.old` references."""
    if events:
        names = "|".join(re.escape(e) for e in events)
        pattern = rf"^([ \t]+(?:async[ \t]+)?def[ \t]+){re.escape(old)}_({names})(?=[ \t]*\()"
        source = re.sub(pattern, rf"\g<1>{new}_\g<2>", source, flags=re.M)
    return re.sub(rf"\bself\.{re.escape(old)}\b", f"self.{new}", source)


def rename_class(source, old, new):
    """Rename the form class everywhere it appears as a whole word."""
    return re.sub(rf"\b{re.escape(old)}\b", new, source)
