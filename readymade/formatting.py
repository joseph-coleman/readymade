"""Formatting: rewriting code in a consistent style with tools like Black or Ruff.

Formatting changes the code itself, so everyone working on a project should
use the same formatters: the project's choice (pyproject.toml) wins, and your
own default (your settings, see readymade.usersettings) is used for projects
that haven't chosen. Several can run in turn, import sorting first:

    [tool.readymade]
    format = ["isort", "black"]
    format-on-save = true

Each runs in the project's environment, with its own settings ([tool.black],
[tool.ruff.format], ...). A tool readymade doesn't know can be added with its
command; it must read the code on stdin and write the result on stdout:

    [tool.readymade.format-tools.mytool]
    command = ["{python}", "-m", "mytool", "-"]
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass

from readymade import usersettings
from readymade.lint import command_for


@dataclass(frozen=True)
class Formatter:
    name: str
    command: tuple[str, ...]  # {python} and {file} are filled in; the code goes in on stdin
    module: str = ""  # the module that must be importable, to tell whether it's installed
    package: str = ""  # what to pip install
    about: str = ""


# In the order they run: imports first, then the code's layout.
BUILT_IN = {tool.name: tool for tool in (
    Formatter("isort", ("{python}", "-m", "isort", "--filename", "{file}", "-"), "isort", "isort",
              "Sorts imports (pairs with any of the others)"),
    Formatter("autopep8", ("{python}", "-m", "autopep8", "-"), "autopep8", "autopep8",
              "Fixes PEP 8 problems, changing little else"),
    Formatter("yapf", ("{python}", "-m", "yapf"), "yapf", "yapf", "Google's formatter; very configurable"),
    Formatter("black", ("{python}", "-m", "black", "--quiet", "--stdin-filename", "{file}", "-"), "black", "black",
              "The uncompromising formatter"),
    Formatter("ruff", ("{python}", "-m", "ruff", "format", "--stdin-filename", "{file}", "-"), "ruff", "ruff",
              "Black's style; very fast"),
)}


def choices(project):
    """(the project's formatters, your default ones), as names."""
    return list(project.setting("format") or []), list(usersettings.get("format", []))


def set_choices(project, shared, mine):
    project.set_setting("format", list(shared) or None)
    usersettings.set("format", list(mine) or None)


def on_save_choices(project):
    """(the project's format-on-save, or None if it hasn't said; your default)."""
    return project.setting("format-on-save"), bool(usersettings.get("format-on-save", False))


def set_on_save(project, shared, mine):
    project.set_setting("format-on-save", True if shared else None)
    usersettings.set("format-on-save", True if mine else None)


def format_on_save(project):
    shared, mine = on_save_choices(project)
    return bool(shared) if shared is not None else mine


def definitions(project):
    """Every formatter the project can use, in the order they run: built-in, then defined ones."""
    tools = dict(BUILT_IN)
    for source in (project.settings().get("tool", {}).get("readymade", {}).get("format-tools", {}),
                   usersettings.get("format-tools", {})):
        for name, spec in source.items():
            tools[name] = Formatter(name, tuple(spec["command"]), spec.get("module", ""), spec.get("package", ""),
                                    spec.get("about", "Your own tool"))
    return tools


def tools_for(project):
    """The formatters to run for the project: its own choice, else your default, in running order."""
    shared, mine = choices(project)
    chosen = set(shared or mine)
    return [tool for name, tool in definitions(project).items() if name in chosen]


def run(tool, python, folder, path, source, env):
    """Format source with tool. Returns (the result, None) or (None, why it couldn't)."""
    try:
        result = subprocess.run(
            command_for(tool, python, path), input=source, capture_output=True, text=True,
            encoding="utf-8", errors="replace", cwd=folder, env=env, timeout=60,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        return None, f"{tool.name} couldn't run ({e.__class__.__name__})"
    if tool.module and f"No module named {tool.module}" in result.stderr:
        return None, f"{tool.name} isn't installed in this project's environment"
    if result.returncode != 0:  # e.g. a syntax error; some tools still print the code unchanged
        reason = next((line.strip() for line in result.stderr.splitlines() if line.strip()), f"exit code {result.returncode}")
        return None, f"{tool.name} couldn't format {path.name}: {reason}"
    return result.stdout, None


def format_source(tools, python, folder, path, source, env):
    """Run each formatter in turn. Returns (the formatted code, None), or (the code unchanged, why)."""
    formatted = source
    for tool in tools:
        result, trouble = run(tool, python, folder, path, formatted, env)
        if trouble:
            return source, trouble
        formatted = result
    return formatted, None
