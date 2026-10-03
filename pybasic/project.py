"""pybasic projects: a folder that is also a standard Python project.

The project file is the folder's pyproject.toml, so uv, pip and PyInstaller
understand it too. pybasic's own settings live in its [tool.pybasic] table:

    [tool.pybasic]
    startup = "MainForm"
    python = ".venv/bin/python"   # optional; see Project.python()

Forms (Name.form + Name.py) and modules (any other .py file) are found by
looking in the folder, so there's no file list to keep in sync.
"""

from __future__ import annotations

import json
import keyword
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from pybasic import codegen, formfile

PYPROJECT = "pyproject.toml"


class ProjectError(Exception):
    pass


@dataclass
class Project:
    folder: Path

    @classmethod
    def find(cls, path):
        """The project for a project folder, its pyproject.toml, or a .form file in it."""
        path = Path(path).resolve()
        return cls(path if path.is_dir() else path.parent)

    @classmethod
    def create(cls, folder, first_form="Form1"):
        """Make a new project in an empty or new folder, with one form."""
        folder = Path(folder).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        if any(folder.iterdir()):
            raise ProjectError(f"{folder} isn't empty. Choose a new or empty folder for the project.")
        (folder / PYPROJECT).write_text(new_pyproject(folder.name), encoding="utf-8")
        project = cls(folder)
        project.add_form(first_form)
        project.set_startup(first_form)
        return project

    @property
    def pyproject(self):
        return self.folder / PYPROJECT

    def settings(self):
        if not self.pyproject.exists():
            return {}
        try:
            return tomllib.loads(self.pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ProjectError(f"{self.pyproject}: {e}") from None

    @property
    def name(self):
        return self.settings().get("project", {}).get("name") or self.folder.name

    def setting(self, key):
        return self.settings().get("tool", {}).get("pybasic", {}).get(key)

    def set_setting(self, key, value):
        """Set (or with None, remove) a [tool.pybasic] setting in pyproject.toml."""
        text = self.pyproject.read_text(encoding="utf-8") if self.pyproject.exists() else new_pyproject(self.folder.name)
        self.pyproject.write_text(set_setting(text, key, value), encoding="utf-8")

    @property
    def startup(self):
        """The form shown first: [tool.pybasic] startup, or else the first form."""
        startup = self.setting("startup")
        if startup:
            return startup
        forms = self.forms()
        return forms[0] if forms else None

    def set_startup(self, form):
        if not form.isidentifier():
            raise ProjectError(f"{form!r} isn't a valid form name.")
        self.set_setting("startup", form)

    def python(self):
        """The interpreter that runs the project: [tool.pybasic] python, else the
        folder's .venv, else None (meaning the IDE's own Python)."""
        configured = self.setting("python")
        if configured:
            return self.folder / configured  # an absolute path replaces the folder
        for candidate in (".venv/Scripts/python.exe", ".venv/bin/python"):
            if (self.folder / candidate).exists():
                return self.folder / candidate
        return None

    def set_python(self, path):
        """Use the interpreter at path (None: back to .venv or the IDE's Python).
        Paths inside the project are stored relative to it, so the project can move."""
        if path is not None:
            path = Path(os.path.abspath(path))  # not resolve(): a venv's python is a symlink that must stay one
            if path.is_relative_to(self.folder):
                path = path.relative_to(self.folder)
            path = path.as_posix()
        self.set_setting("python", path)

    def forms(self):
        return sorted(p.stem for p in self.folder.glob("*.form"))

    def modules(self):
        forms = set(self.forms())
        return sorted(p.stem for p in self.folder.glob("*.py") if p.stem not in forms)

    def add_form(self, name):
        self._check_new_name(name)
        design = formfile.FormDesign(name=name, text=name)
        formfile.save(design, self.folder / f"{name}.form")
        (self.folder / f"{name}.py").write_text(codegen.new_module(name), encoding="utf-8")

    def add_module(self, name):
        self._check_new_name(name)
        (self.folder / f"{name}.py").write_text(f'"""{name}: code shared by the project\'s forms."""\n', encoding="utf-8")

    def _check_new_name(self, name):
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ProjectError(f"{name!r} isn't a valid Python name.")
        if name in sys.stdlib_module_names or name == "pybasic":
            raise ProjectError(f"{name!r} would hide Python's own {name} module. Choose another name.")
        if any(p.stem.lower() == name.lower() for p in self.folder.glob("*.py")) or name in self.forms():
            raise ProjectError(f"The project already has a form or module named {name!r}.")


def new_pyproject(name):
    dist = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._").lower() or "project"
    return (
        "[project]\n"
        f'name = "{dist}"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.11"\n'
        "dependencies = []\n"
        "\n"
        "[tool.pybasic]\n"
    )


def set_setting(text, key, value):
    """Set (or with None, remove) key in pyproject.toml's [tool.pybasic] table,
    leaving everything else in the text as it was."""
    line = f"{key} = {json.dumps(value)}"  # a JSON string is also a valid TOML string
    existing = rf"(?m)^{re.escape(key)}[ \t]*=.*$"
    header = re.search(r"(?m)^\[tool\.pybasic\][ \t]*$", text)
    if header is None:
        return text if value is None else text.rstrip("\n") + f"\n\n[tool.pybasic]\n{line}\n"
    start = header.end()
    following = re.search(r"(?m)^\[", text[start:])  # the next table ends this one
    end = start + following.start() if following else len(text)
    body = text[start:end]
    if value is None:
        body = re.sub(existing + r"\n?", "", body, count=1)
    elif re.search(existing, body):
        body = re.sub(existing, lambda m: line, body, count=1)
    else:
        body = "\n" + line + body
    return text[:start] + body + text[end:]


def describe_python(path):
    """The interpreter's version, plus any problem running pybasic with it."""
    probe = "import sys; print('%d.%d.%d' % sys.version_info[:3]); import tkinter"
    try:
        result = subprocess.run([str(path), "-c", probe], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"can't run it ({e.__class__.__name__})"
    version = result.stdout.strip() or "?"
    problems = []
    if tuple(int(n) for n in version.split(".")[:2] if n.isdigit()) < (3, 11):
        problems.append("pybasic needs 3.11+")
    if result.returncode != 0:
        problems.append("no tkinter")
    return ", ".join([version, *problems])
