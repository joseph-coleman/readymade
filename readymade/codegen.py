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
