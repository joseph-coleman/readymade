"""Linting: checking code with tools like Ruff, pyflakes, flake8, pylint and mypy.

Linting is off until tools are chosen (Project > Linting...). The project's
pyproject.toml lists the tools everyone uses; each person can add tools they
want in all their projects, in their own settings (see readymade.usersettings):

    [tool.readymade]
    lint = ["ruff", "mypy"]

Each tool runs as its own program in the project's environment, so the
project's versions of the tools and their own settings (ruff.toml,
[tool.mypy], .flake8, .pylintrc, ...) apply. A tool readymade doesn't know can
be added with its command, in the project or in your own settings (as
"lint-tools"); any tool that prints `file:line:column: message` lines works:

    [tool.readymade.lint-tools.mytool]
    command = ["{python}", "-m", "mytool", "{file}"]
    stdin = false   # true if it reads the code from stdin; then it checks as you type
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from readymade import usersettings


@dataclass(frozen=True)
class Tool:
    name: str
    command: tuple[str, ...]  # {python} and {file} are filled in
    stdin: bool = False  # reads the code from stdin, so it can check unsaved code as you type
    module: str = ""  # the module that must be importable, to tell whether it's installed
    package: str = ""  # what to pip install
    column_base: int = 1  # pylint counts columns from 0
    about: str = ""


BUILT_IN = {tool.name: tool for tool in (
    Tool("pyflakes", ("{python}", "-m", "pyflakes"), stdin=True, module="pyflakes", package="pyflakes",
         about="Errors only, like undefined names and unused imports"),
    Tool("ruff", ("{python}", "-m", "ruff", "check", "--output-format=concise", "--stdin-filename", "{file}", "-"),
         stdin=True, module="ruff", package="ruff", about="Errors and style; very fast"),
    Tool("flake8", ("{python}", "-m", "flake8", "--stdin-display-name", "{file}", "-"), stdin=True,
         module="flake8", package="flake8", about="Errors and PEP 8 style"),
    Tool("pylint", ("{python}", "-m", "pylint", "--score=n", "--msg-template={path}:{line}:{column}: {msg_id} {msg}", "{file}"),
         module="pylint", package="pylint", column_base=0, about="Thorough; checks when you save"),
    Tool("mypy", ("{python}", "-m", "mypy", "--show-column-numbers", "--no-error-summary", "--no-pretty", "{file}"),
         module="mypy", package="mypy", about="Type checking; checks when you save"),
)}


@dataclass(frozen=True)
class Problem:
    line: int
    column: int  # from 0, as Tk counts
    message: str
    tool: str


# `file:line:column: message`; the column is optional. Windows paths keep their "C:".
_LINE = re.compile(r"^(?P<file>.+?):(?P<line>\d+):(?:(?P<column>\d+):)?\s*(?P<message>.+)$")


def parse(output, tool, path):
    """The problems in path from a tool's output."""
    problems = []
    for text in output.splitlines():
        found = _LINE.match(text.strip())
        if not found or found["file"] not in ("<stdin>", "-") and _file_name(found["file"]) != Path(path).name:
            continue  # not a problem line, or about another file (mypy also reports imported ones)
        message = found["message"]
        if message.startswith("note:"):
            continue  # mypy's hints aren't problems
        message = message.removeprefix("error: ")
        column = int(found["column"]) - tool.column_base if found["column"] else 0
        problems.append(Problem(int(found["line"]), max(0, column), message, tool.name))
    return problems


def _file_name(reported):
    return re.split(r"[\\/]", reported)[-1]  # either kind of slash, whichever system the tool ran on


def command_for(tool, python, path):
    # Not str.format: pylint's message template has braces of its own.
    return [part.replace("{python}", str(python)).replace("{file}", str(path)) for part in tool.command]


def run(tool, python, folder, path, source, env):
    """Check source (saved at path) with tool. Returns (problems, None) or ([], why it didn't run)."""
    try:
        result = subprocess.run(
            command_for(tool, python, path), input=source if tool.stdin else None, capture_output=True,
            text=True, encoding="utf-8", errors="replace", cwd=folder, env=env, timeout=120,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return [], f"{tool.name} couldn't run ({e.__class__.__name__})"
    if tool.module and f"No module named {tool.module}" in result.stderr:
        return [], f"{tool.name} isn't installed in this project's environment"
    return parse(result.stdout + "\n" + result.stderr, tool, path), None


def choices(project):
    """(the tools the project uses, the tools you use in all your projects), as names."""
    return list(project.setting("lint") or []), list(usersettings.get("lint", []))


def set_choices(project, shared, mine):
    project.set_setting("lint", list(shared) or None)
    usersettings.set("lint", list(mine) or None)


def definitions(project):
    """Every tool the project can use: the built-in ones and any defined for it, by name."""
    tools = dict(BUILT_IN)
    for source in (project.settings().get("tool", {}).get("readymade", {}).get("lint-tools", {}),
                   usersettings.get("lint-tools", {})):
        for name, spec in source.items():
            tools[name] = Tool(name, tuple(spec["command"]), stdin=bool(spec.get("stdin", False)),
                               module=spec.get("module", ""), package=spec.get("package", ""),
                               column_base=int(spec.get("column-base", 1)), about=spec.get("about", "Your own tool"))
    return tools


def tools_for(project):
    """The tools to run for the project on this machine (unknown names are left out)."""
    shared, mine = choices(project)
    known = definitions(project)
    return [known[name] for name in dict.fromkeys(shared + mine) if name in known]


def installed(python, tools, env=None):
    """The names of the tools whose module the interpreter can import."""
    modules = {tool.module: tool.name for tool in tools if tool.module}
    check = "import importlib.util, sys; print(*[m for m in sys.argv[1:] if importlib.util.find_spec(m)])"
    try:
        result = subprocess.run([str(python), "-c", check, *modules], capture_output=True, text=True, env=env, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    return {modules[m] for m in result.stdout.split() if m in modules}
