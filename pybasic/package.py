"""Make EXE: package a project as a program that runs without Python installed.

PyInstaller does the work, in the project's own environment, so the program
gets exactly the project's Python and libraries. A small launcher imports
every form and module (forms load each other by name, which PyInstaller can't
follow) and shows the startup form. The .form files go in as data; at run time
each form finds its .form beside its module, as it does unpackaged.

The program is one file on Windows and Linux. On macOS it's an .app folder,
as PyInstaller recommends.
"""

from __future__ import annotations

import os
import sys

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
    for form in project.forms():
        # Each .form goes beside its module in the bundle; paths are absolute, as the spec lives in build/.
        args += ["--add-data", f"{project.folder / (form + '.form')}{os.pathsep}."]
    args.append(str(launcher))
    return args
