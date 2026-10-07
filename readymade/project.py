"""readymade projects: a folder that is also a standard Python project.

The project file is the folder's pyproject.toml, so uv, pip and PyInstaller
understand it too. readymade's own settings live in its [tool.readymade] table:

    [tool.readymade]
    startup = "MainForm"

Settings that only make sense on one machine, like which Python interpreter to
use, live in .readymade/local.json instead, kept per machine and out of git; see
Project.python().

Forms (Name.form + Name.py) and modules (any other .py file) are found by
looking in the folder, so there's no file list to keep in sync.
"""

from __future__ import annotations

import json
import keyword
import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from readymade import codegen, formfile

PYPROJECT = "pyproject.toml"
LOCAL = Path(".readymade") / "local.json"  # this machine's settings, kept out of git
RUNTIME_PYTHON = (3, 10)  # the oldest Python that can run a project; tested with 3.10.19 and Tk 9.0


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
            import tomllib  # here, not at the top: running a program mustn't need Python 3.11
        except ModuleNotFoundError:
            raise ProjectError("Reading pyproject.toml needs Python 3.11 or later") from None
        try:
            return tomllib.loads(self.pyproject.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ProjectError(f"{self.pyproject}: {e}") from None

    @property
    def name(self):
        return self.settings().get("project", {}).get("name") or self.folder.name

    def setting(self, key):
        return self.settings().get("tool", {}).get("readymade", {}).get(key)

    def set_setting(self, key, value):
        """Set (or with None, remove) a [tool.readymade] setting in pyproject.toml."""
        text = self.pyproject.read_text(encoding="utf-8") if self.pyproject.exists() else new_pyproject(self.folder.name)
        self.pyproject.write_text(set_setting(text, key, value), encoding="utf-8")

    @property
    def startup(self):
        """The form shown first: [tool.readymade] startup, or else the first form."""
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
        """The interpreter that runs the project, or None for the IDE's own Python."""
        return self.python_choice()[0]

    def python_choice(self):
        """(interpreter, where it was chosen): this machine's choice, else this platform's
        .venv, else (None, None), meaning the IDE's own Python."""
        chosen = self.local_settings().get("python")
        if chosen:
            return self.folder / chosen, chosen  # an absolute path replaces the folder
        # Only this platform's layout: a folder shared between Windows and WSL may hold the other's .venv.
        if self.venv_python().exists():
            return self.venv_python(), ".venv"
        return None, None

    def local_settings(self):
        """This machine's settings for the project, from .readymade/local.json."""
        return self._local_file().get("machines", {}).get(_machine(), {})

    def set_local_setting(self, key, value):
        """Set (or with None, remove) one of this machine's settings."""
        data = self._local_file()
        machine = data.setdefault("machines", {}).setdefault(_machine(), {})
        if value is None:
            machine.pop(key, None)
        else:
            machine[key] = value
        path = self.folder / LOCAL
        path.parent.mkdir(exist_ok=True)
        ignore = path.parent / ".gitignore"
        if not ignore.exists():
            ignore.write_text("# Machine-specific readymade settings: not for sharing.\n*\n", encoding="utf-8")
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    def _local_file(self):
        path = self.folder / LOCAL
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (OSError, ValueError) as e:
            raise ProjectError(f"{path}: {e}") from None

    def venv_python(self):
        """Where the project's .venv puts its interpreter on this platform."""
        return self.folder / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    @property
    def dependencies(self):
        return list(self.settings().get("project", {}).get("dependencies", []))

    def add_dependency(self, requirement):
        text = self.pyproject.read_text(encoding="utf-8") if self.pyproject.exists() else new_pyproject(self.folder.name)
        self.pyproject.write_text(add_dependency(text, requirement), encoding="utf-8")

    def remove_dependency(self, requirement):
        """Take a library out of the project's dependencies (it stays installed; see the IDE)."""
        if self.pyproject.exists():
            text = self.pyproject.read_text(encoding="utf-8")
            self.pyproject.write_text(remove_dependency(text, requirement), encoding="utf-8")

    def set_python(self, path):
        """Use the interpreter at path on this machine (None: back to .venv or the IDE's Python).
        Paths inside the project are stored relative to it, so the project can move."""
        if path is not None:
            path = Path(os.path.abspath(path))  # not resolve(): a venv's python is a symlink that must stay one
            if path.is_relative_to(self.folder):
                path = path.relative_to(self.folder)
            path = path.as_posix()
        self.set_local_setting("python", path)

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

    def remove_form(self, name):
        """Delete a form's .form and .py files. If it was the startup form, the first
        remaining form becomes the startup form."""
        if self.setting("startup") == name:
            self.set_setting("startup", None)
        for path in (self.folder / f"{name}.form", self.folder / f"{name}.py"):
            path.unlink(missing_ok=True)

    def remove_module(self, name):
        """Delete a module's .py file."""
        (self.folder / f"{name}.py").unlink(missing_ok=True)

    def _check_new_name(self, name):
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ProjectError(f"{name!r} isn't a valid Python name.")
        if name in sys.stdlib_module_names or name == "readymade":
            raise ProjectError(f"{name!r} would hide Python's own {name} module. Choose another name.")
        if any(p.stem.lower() == name.lower() for p in self.folder.glob("*.py")) or name in self.forms():
            raise ProjectError(f"The project already has a form or module named {name!r}.")


def _machine():
    """This machine and platform, e.g. "MYPC win32": WSL and Windows on one PC count as two."""
    return f"{platform.node()} {sys.platform}"


def new_pyproject(name):
    dist = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-._").lower() or "project"
    return (
        "[project]\n"
        f'name = "{dist}"\n'
        'version = "0.1.0"\n'
        'requires-python = ">=3.10"\n'  # what readymade's runtime needs; the IDE itself needs 3.11
        "dependencies = []\n"
        "\n"
        "[tool.readymade]\n"
    )


def set_setting(text, key, value):
    """Set (or with None, remove) key in pyproject.toml's [tool.readymade] table,
    leaving everything else in the text as it was."""
    line = f"{key} = {json.dumps(value)}"  # JSON strings and lists are also valid TOML
    header = re.search(r"(?m)^\[tool\.readymade\][ \t]*$", text)
    if header is None:
        return text if value is None else text.rstrip("\n") + f"\n\n[tool.readymade]\n{line}\n"
    start = header.end()
    following = re.search(r"(?m)^\[", text[start:])  # the next table ends this one
    end = start + following.start() if following else len(text)
    body = text[start:end]
    existing = re.search(rf"(?m)^{re.escape(key)}[ \t]*=[ \t]*", body)
    if existing is None:
        body = body if value is None else "\n" + line + body
    else:
        # The old value ends with its line, or for a list, with the line of its closing ].
        value_end = existing.end()
        if body[value_end:value_end + 1] == "[":
            value_end = _closing_bracket(body, value_end)
        line_end = body.find("\n", value_end)
        line_end = len(body) if line_end < 0 else line_end + (1 if value is None else 0)
        body = body[:existing.start()] + ("" if value is None else line) + body[line_end:]
    return text[:start] + body + text[end:]


def requirement_name(requirement):
    """The package a requirement like "Requests[socks]>=2" is for, normalized: "requests"."""
    name = re.split(r"[\s<>=!~;\[(@]", requirement.strip(), maxsplit=1)[0]
    return re.sub(r"[-_.]+", "-", name).lower()


def add_dependency(text, requirement):
    """Add requirement to [project] dependencies in pyproject.toml text, replacing
    any entry for the same package and leaving the rest of the text as it was."""
    requirement = requirement.strip()
    return _change_dependencies(text, lambda current: [*_without(current, requirement), requirement])


def remove_dependency(text, requirement):
    """Remove requirement's package from [project] dependencies in pyproject.toml text."""
    return _change_dependencies(text, lambda current: _without(current, requirement))


def _without(requirements, requirement):
    return [r for r in requirements if requirement_name(r) != requirement_name(requirement)]


def _change_dependencies(text, change):
    """Replace [project] dependencies with change(the current list), leaving the rest of the text as it was."""
    header = re.search(r"(?m)^\[project\][ \t]*$", text)
    if header is None:
        wanted = change([])
        return text.rstrip("\n") + f"\n\n[project]\ndependencies = {_inline(wanted)}\n" if wanted else text
    start = header.end()
    following = re.search(r"(?m)^\[", text[start:])
    end = start + following.start() if following else len(text)
    key = re.search(r"(?m)^dependencies[ \t]*=[ \t]*\[", text[start:end])
    if key is None:
        wanted = change([])
        return text[:start] + f"\ndependencies = {_inline(wanted)}" + text[start:] if wanted else text
    open_at = start + key.end() - 1
    close_at = _closing_bracket(text, open_at)
    import tomllib

    current = tomllib.loads("d = " + text[open_at : close_at + 1])["d"]
    wanted = change(current)
    if wanted == current:
        return text  # nothing to change, so not even the list's layout
    return text[:open_at] + _toml_list(wanted) + text[close_at + 1 :]


def _inline(requirements):
    return "[" + ", ".join(json.dumps(r) for r in requirements) + "]"


def _toml_list(requirements):
    """A rewritten list: one requirement per line, so changes diff cleanly."""
    if not requirements:
        return "[]"
    return "[" + "".join(f"\n    {json.dumps(r)}," for r in requirements) + "\n]"


def _closing_bracket(text, open_at):
    """The index of the ] matching the [ at open_at, skipping strings and comments."""
    depth, i = 0, open_at
    while i < len(text):
        c = text[i]
        if c in "\"'":
            quote = c
            i += 1
            while i < len(text) and text[i] != quote:
                i += 2 if text[i] == "\\" and quote == '"' else 1
        elif c == "#":
            i = text.find("\n", i) if "\n" in text[i:] else len(text)
            continue
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    raise ProjectError("pyproject.toml has a dependencies list with no closing ]")


def find_pythons():
    """Python interpreters on this machine that a project environment could be based on:
    the IDE's own, every python on the PATH, conda/mamba environments, and (on
    Windows) those the py launcher knows about."""
    candidates = [Path(getattr(sys, "_base_executable", None) or sys.executable)]
    names = ["python.exe"] if os.name == "nt" else ["python3", *(f"python3.{n}" for n in range(10, 16))]
    candidates += _on_path(names)
    candidates += _conda_pythons()
    if os.name == "nt":
        candidates += _py_launcher_pythons()
    found, seen = [], set()
    for candidate in candidates:
        real = os.path.realpath(candidate)
        # Skip the Microsoft Store's placeholders: running one opens the Store.
        if real not in seen and candidate.is_file() and "WindowsApps" not in candidate.parts:
            seen.add(real)
            found.append(candidate)
    return found


def _on_path(names):
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        for name in names:
            if folder and (Path(folder) / name).is_file():
                yield Path(folder) / name


def _conda_pythons():
    """The interpreters of conda (or mamba) environments, when conda is in use."""
    tool = os.environ.get("CONDA_EXE") or os.environ.get("MAMBA_EXE")
    if not tool:
        return []
    try:
        listing = subprocess.run([tool, "env", "list", "--json"], capture_output=True, text=True, timeout=30)
        envs = json.loads(listing.stdout)["envs"]
    except (OSError, subprocess.TimeoutExpired, ValueError, KeyError):
        return []
    return [Path(env) / ("python.exe" if os.name == "nt" else "bin/python") for env in envs]


def _py_launcher_pythons():
    try:
        listing = subprocess.run(["py", "-0p"], capture_output=True, text=True, timeout=15).stdout
    except (OSError, subprocess.TimeoutExpired):
        return []
    return [Path(p) for p in re.findall(r"(?m)([A-Za-z]:\\.*?\.exe)\s*$", listing)]


def describe_python(path):
    """The interpreter's version, plus any problem running readymade with it."""
    probe = "import sys; print('%d.%d.%d' % sys.version_info[:3]); import tkinter"
    try:
        result = subprocess.run([str(path), "-c", probe], capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"can't run it ({e.__class__.__name__})"
    version = result.stdout.strip() or "?"
    problems = []
    if tuple(int(n) for n in version.split(".")[:2] if n.isdigit()) < RUNTIME_PYTHON:
        problems.append("readymade needs %d.%d+" % RUNTIME_PYTHON)
    if result.returncode != 0:
        problems.append("no tkinter")
    return ", ".join([version, *problems])
