"""Make EXE: package a project as a program that runs without Python installed.

PyInstaller does the work, in the project's own environment, so the program
gets exactly the project's Python and libraries. A small launcher imports
every form and module (forms load each other by name, which PyInstaller can't
follow) and shows the startup form. The .form files go in as data; at run time
each form finds its .form beside its module, as it does unpackaged.

Other files go in at the same place relative to the program's folder, so
app_path() finds them as it does unpackaged: pictures the forms show, and
whatever [tool.pybasic] include lists (files, folders or patterns, like
include = ["data", "sounds/*.wav"]).

The program is one file on Windows and Linux. On macOS it's an .app folder,
as PyInstaller recommends.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePath

from pybasic import formfile
from pybasic.controls import REGISTRY

LAUNCHER = "_pybasic_launcher.py"


def build_folder(project):
    return project.folder / "build"


def exe_path(project, platform=sys.platform):
    """Where the finished program will be."""
    dist = project.folder / "dist"
    if platform == "darwin":
        return dist / f"{project.name}.app"
    return dist / (f"{project.name}.exe" if platform == "win32" else project.name)


def launcher_source(project, startup):
    names = [*project.forms(), *project.modules()]
    return (
        "# Made by pybasic's Make EXE: starts the program. Changes here are overwritten.\n"
        f"import {', '.join(names)}  # noqa: F401  (so PyInstaller bundles every form and module)\n"
        "from pybasic import forms\n"
        "from pybasic.form import main_loop\n"
        "\n"
        f"forms.{startup}.show()\n"
        "main_loop()\n"
    )


def write_launcher(project, startup):
    folder = build_folder(project) / "pybasic"
    folder.mkdir(parents=True, exist_ok=True)
    launcher = folder / LAUNCHER
    launcher.write_text(launcher_source(project, startup), encoding="utf-8")
    return launcher


def bundled_files(project):
    """(files, missing): the (path, folder in the bundle) pairs to add as data, and the
    pictures and include entries that weren't found."""
    files, missing = [], []

    def add(path):
        path = Path(path)
        try:
            place = path.parent.relative_to(project.folder)
        except ValueError:  # outside the project: put it in the program's folder
            place = PurePath()
        if path.is_dir():
            place = place / path.name
        pair = (path, place.as_posix() if place.parts else ".")
        if pair not in files:
            files.append(pair)

    for form in project.forms():
        add(project.folder / f"{form}.form")
        try:
            design = formfile.load(project.folder / f"{form}.form")
        except (OSError, formfile.FormFileError):
            continue  # the build reports it, when the form fails to load
        for spec in design.controls:
            for prop in getattr(REGISTRY.get(spec["type"]), "file_props", {}):
                if spec.get(prop):
                    path = project.folder / spec[prop]
                    add(path) if path.is_file() else missing.append(f"{form}.{spec['name']}.{prop}: {spec[prop]}")
    include = project.setting("include") or []
    for entry in [include] if isinstance(include, str) else include:
        if any(c in entry for c in "*?["):
            found = sorted(p for p in project.folder.glob(entry) if p.is_file())
        else:
            found = [project.folder / entry] if (project.folder / entry).exists() else []
        for path in found:
            add(path)
        if not found:
            missing.append(f"include: {entry}")
    return files, missing


def pyinstaller_args(project, launcher, pybasic_root, platform=sys.platform):
    """The arguments after `python`, to run PyInstaller on the launcher."""
    work = build_folder(project) / "pyinstaller"
    args = [
        "-m", "PyInstaller", "--noconfirm", "--windowed",
        "--onedir" if platform == "darwin" else "--onefile",
        "--name", project.name,
        "--distpath", str(project.folder / "dist"),
        "--workpath", str(work), "--specpath", str(work),
        "--paths", str(project.folder), "--paths", str(pybasic_root),
    ]
    for path, place in bundled_files(project)[0]:
        # Paths are absolute, as the spec lives in build/.
        args += ["--add-data", f"{path}{os.pathsep}{place}"]
    args.append(str(launcher))
    return args
