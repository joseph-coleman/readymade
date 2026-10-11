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

    @property
    def version(self):
        """[project] version: the program's version, like "1.2.0"."""
        return str(self.settings().get("project", {}).get("version", "") or "")

    def set_version(self, version):
        text = self.pyproject.read_text(encoding="utf-8") if self.pyproject.exists() else new_pyproject(self.folder.name)
        self.pyproject.write_text(set_setting(text, "version", version or None, table="project"), encoding="utf-8")

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

    def other_files(self, folder=""):
        """The project's other files and folders, in one of its folders ("" for the top):
        [(path relative to the project, whether it's a folder)], folders first. Not its forms
        and modules (shown on their own), nor hidden folders (.venv, .readymade, .git), caches,
        what builds leave, or the system's own clutter (.DS_Store). Files like .gitignore show."""
        base = self.folder / folder
        try:
            entries = list(base.iterdir())
        except OSError:
            return []
        found = []
        for path in entries:
            name = path.name
            is_folder = path.is_dir()
            if (name in _NOT_SHOWN or name.endswith(".egg-info") or (is_folder and name.startswith("."))
                    or (not folder and path.suffix in (".form", ".py") and not is_folder)):
                continue
            found.append((path.relative_to(self.folder).as_posix(), is_folder))
        return sorted(found, key=lambda entry: (not entry[1], entry[0].lower()))

    def snapshot(self, most=5000):
        """The project's files and folders as the Project Explorer would show them (forms and
        modules included), to notice changes made outside the IDE: a frozenset of paths."""
        found, waiting = {p.name for p in self.folder.glob("*.form")} | {p.name for p in self.folder.glob("*.py")}, [""]
        while waiting and len(found) < most:
            folder = waiting.pop()
            for relative, is_folder in self.other_files(folder):
                found.add(relative + "/" * is_folder)
                if is_folder:
                    waiting.append(relative)
        return frozenset(found)

    def rename_file(self, relative, new_name):
        """Rename one of the project's other files or folders (relative, like "data/old.csv") to
        new_name in the same folder. Returns the new relative path. Make EXE's include list
        follows it."""
        if not new_name or new_name in (".", "..") or any(c in new_name for c in "/\\:*?\"<>|"):
            raise ProjectError(f"{new_name!r} isn't a name for a file or folder.")
        old = self.folder / relative
        new = old.with_name(new_name)
        if new.exists() and new.resolve() != old.resolve():
            raise ProjectError(f"There's already a {new_name} there.")
        old.rename(new)
        renamed = new.relative_to(self.folder).as_posix()
        include = [renamed + entry[len(relative):] if entry == relative or entry.startswith(relative + "/") else entry
                   for entry in self.include()]
        if include != self.include():
            self.set_setting("include", include)
        return renamed

    def include(self):
        """[tool.readymade] include: what Make EXE bundles besides the forms and their pictures."""
        include = self.setting("include") or []
        return [include] if isinstance(include, str) else list(include)

    def set_bundled(self, relative, bundled):
        """Add a file or folder (relative, like "data/prices.csv") to include, or take it out."""
        include = [entry for entry in self.include() if entry != relative]
        if bundled:
            include.append(relative)
        self.set_setting("include", include or None)

    def add_form(self, name):
        self.check_new_name(name)
        design = formfile.FormDesign(name=name, text=name)
        formfile.save(design, self.folder / f"{name}.form")
        (self.folder / f"{name}.py").write_text(codegen.new_module(name), encoding="utf-8")

    def add_module(self, name):
        self.check_new_name(name)
        (self.folder / f"{name}.py").write_text(f'"""{name}: code shared by the project\'s forms."""\n', encoding="utf-8")

    def remove_form(self, name, discard=None):
        """Remove a form's .form and .py files: discard(path) each (default: delete it). If it
        was the startup form, the first remaining form becomes the startup form."""
        for path in (self.folder / f"{name}.form", self.folder / f"{name}.py"):
            if path.exists():
                (discard or Path.unlink)(path)
        if self.setting("startup") == name:
            self.set_setting("startup", None)

    def remove_module(self, name, discard=None):
        """Remove a module's .py file: discard(path) (default: delete it)."""
        path = self.folder / f"{name}.py"
        if path.exists():
            (discard or Path.unlink)(path)

    def rename_module(self, old, new):
        """Rename a module's file, and the imports of it in the project's other code:
        `import old` (and old.name after it) and `from old import ...`. Returns the files
        changed, as {path: new source} for the caller to write (or show, if they're open)."""
        self.check_new_name(new)
        (self.folder / f"{old}.py").rename(self.folder / f"{new}.py")
        changed = {}
        for path in sorted(self.folder.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            renamed = rename_imports(source, old, new)
            if renamed != source:
                changed[path] = renamed
        return changed

    def check_new_name(self, name):
        if not name.isidentifier() or keyword.iskeyword(name):
            raise ProjectError(f"{name!r} isn't a valid Python name.")
        if name in sys.stdlib_module_names or name == "readymade":
            raise ProjectError(f"{name!r} would hide Python's own {name} module. Choose another name.")
        if any(p.stem.lower() == name.lower() for p in self.folder.glob("*.py")) or name in self.forms():
            raise ProjectError(f"The project already has a form or module named {name!r}.")


def rename_imports(source, old, new):
    """Python code with a module's imports renamed: `import old` (and old.name where it's
    used), `import old as x`, `from old import ...`."""
    imported_plainly = re.search(rf"^[ \t]*import[ \t]+(?:[\w.]+[ \t]*,[ \t]*)*{re.escape(old)}\b(?![ \t]+as\b)",
                                 source, re.M)
    source = re.sub(rf"^([ \t]*import[ \t]+(?:[\w.]+[ \t]*,[ \t]*)*){re.escape(old)}\b(?!\.)", rf"\g<1>{new}",
                    source, flags=re.M)
    source = re.sub(rf"^([ \t]*from[ \t]+){re.escape(old)}\b(?=[ \t]+import\b)", rf"\g<1>{new}", source, flags=re.M)
    if imported_plainly:
        source = re.sub(rf"(?<![\w.]){re.escape(old)}\.(?=\w)", f"{new}.", source)
    return source


# (Besides hidden folders, like .venv.)
_NOT_SHOWN = {"__pycache__", "build", "dist", "venv", "node_modules", ".DS_Store", "Thumbs.db", "desktop.ini"}


def rename_form_references(source, old, new):
    """Python code with a form's name changed where it's used: forms.Old, and imports of it.
    Where the code does `from Old import Old`, Old there is the form's class, so each Old in
    that code changes; otherwise it's the module (see rename_imports)."""
    source = re.sub(rf"\bforms\.{re.escape(old)}\b", f"forms.{new}", source)
    if re.search(rf"^[ \t]*from[ \t]+{re.escape(old)}[ \t]+import\b", source, re.M):
        return re.sub(rf"(?<![\w.]){re.escape(old)}\b", new, source)
    return rename_imports(source, old, new)


def uses_of(source, name, form=False):
    """The lines of some code that use a module (or with form, a form) by name: imports of it,
    and for a form, forms.Name. [(line number, the line)]."""
    pattern = re.compile(rf"^[ \t]*(from[ \t]+{re.escape(name)}[ \t]+import\b|import[ \t]+(.*,[ \t]*)?"
                         rf"{re.escape(name)}\b(?!\.))" + (rf"|\bforms\.{re.escape(name)}\b" if form else ""))
    return [(n, line.strip()) for n, line in enumerate(source.splitlines(), 1) if pattern.search(line)]


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


def set_setting(text, key, value, table="tool.readymade"):
    """Set (or with None, remove) key in pyproject.toml's [tool.readymade] table (or another),
    leaving everything else in the text as it was."""
    line = f"{key} = {json.dumps(value)}"  # JSON strings, lists, true and false are also valid TOML
    header = re.search(rf"(?m)^\[{re.escape(table)}\][ \t]*$", text)
    if header is None:
        return text if value is None else text.rstrip("\n") + f"\n\n[{table}]\n{line}\n"
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
    """Add requirement to [project] dependencies in pyproject.toml text, replacing any entry
    for the same package where it is, and leaving the rest of the text (comments in the list
    too) as it was."""
    return _edit_dependencies(text, requirement.strip(), adding=True)


def remove_dependency(text, requirement):
    """Remove requirement's package from [project] dependencies in pyproject.toml text (with
    its line, and any comment on it, when it has a line of its own)."""
    return _edit_dependencies(text, requirement, adding=False)


def _edit_dependencies(text, requirement, adding):
    """Change the dependencies list in place, as someone editing it by hand would."""
    header = re.search(r"(?m)^\[project\][ \t]*$", text)
    literal = json.dumps(requirement)
    if header is None:
        return text.rstrip("\n") + f"\n\n[project]\ndependencies = [{literal}]\n" if adding else text
    start = header.end()
    following = re.search(r"(?m)^\[", text[start:])
    end = start + following.start() if following else len(text)
    key = re.search(r"(?m)^dependencies[ \t]*=[ \t]*\[", text[start:end])
    if key is None:
        return text[:start] + f"\ndependencies = [{literal}]" + text[start:] if adding else text
    open_at = start + key.end() - 1
    close_at = _closing_bracket(text, open_at)
    items = _list_items(text, open_at, close_at)
    same = [item for item in items if requirement_name(item[2]) == requirement_name(requirement)]
    if not adding:
        for item in reversed(same):
            text = _remove_item(text, item, multi_line="\n" in text[open_at:close_at])
        return text
    if same:  # this package is there already: changed where it stands
        first, *others = same
        for item in reversed(others):
            text = _remove_item(text, item, multi_line="\n" in text[open_at:close_at])
        return text if first[2] == requirement else text[:first[0]] + literal + text[first[1]:]
    return _append_item(text, open_at, close_at, items, literal)


def _list_items(text, open_at, close_at):
    """The strings in a TOML list: [(start, end, value)], skipping comments."""
    import tomllib

    items, i = [], open_at + 1
    while i < close_at:
        char = text[i]
        if char == "#":
            newline = text.find("\n", i)
            i = close_at if newline < 0 else newline
            continue
        if char in "\"'":
            j = i + 1
            while j < close_at and text[j] != char:
                j += 2 if char == '"' and text[j] == "\\" else 1
            items.append((i, j + 1, tomllib.loads("v = " + text[i:j + 1])["v"]))
            i = j + 1
            continue
        i += 1
    return items


def _append_item(text, open_at, close_at, items, literal):
    inside = text[open_at + 1:close_at]
    if not items and not inside.strip():
        return text[:open_at] + f"[\n    {literal},\n]" + text[close_at + 1:]
    if "\n" not in inside:  # all on one line: ["a", "b"]
        last = items[-1][1]
        return text[:last] + f", {literal}" + text[last:]
    # One per line: after the last, indented the same, with a comma after the one before.
    indent = "    "
    if items:
        last_start, last_end, _ = items[-1]
        line_start = text.rfind("\n", 0, last_start) + 1
        indent = text[line_start:last_start]
        after = re.match(r"[ \t]*,", text[last_end:])
        if after is None:
            text = text[:last_end] + "," + text[last_end:]
            close_at += 1
    close_line = text.rfind("\n", 0, close_at) + 1
    if not text[close_line:close_at].strip():  # ] on its own line
        return text[:close_line] + f"{indent}{literal},\n" + text[close_line:]
    return text[:close_at] + f"\n{indent}{literal},\n" + text[close_at:]


def _remove_item(text, item, multi_line):
    start, end, _ = item
    line_start = text.rfind("\n", 0, start) + 1
    line_end = text.find("\n", end)
    line_end = len(text) if line_end < 0 else line_end
    rest = text[end:line_end].lstrip(" \t")
    rest = rest[1:].lstrip(" \t") if rest.startswith(",") else rest
    if multi_line and not text[line_start:start].strip() and (not rest or rest.startswith("#")):
        return text[:line_start] + text[line_end + 1:]  # its whole line, with any comment on it
    following = re.match(r"[ \t]*,[ \t]*", text[end:])
    if following:
        return text[:start] + text[end + following.end():]
    before = re.search(r",[ \t]*$", text[:start])
    return text[:before.start()] + text[end:] if before else text[:start] + text[end:]


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
