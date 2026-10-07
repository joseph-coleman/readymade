"""Make EXE: package a project as a program that runs without Python installed.

PyInstaller does the work, in the project's own environment, so the program
gets exactly the project's Python and libraries. A small launcher imports
every form and module (forms load each other by name, which PyInstaller can't
follow) and shows the startup form. The .form files go in as data; at run time
each form finds its .form beside its module, as it does unpackaged.

Other files go in at the same place relative to the program's folder, so
app_path() finds them as it does unpackaged: pictures the forms show, and
whatever [tool.readymade] include lists (files, folders or patterns, like
include = ["data", "sounds/*.wav"]).

The program is one file on Windows and Linux. On macOS it's an .app folder,
as PyInstaller recommends.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path, PurePath

from readymade import formfile, pictures
from readymade.controls import REGISTRY

LAUNCHER = "_readymade_launcher.py"


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
    icon = project.setting("icon")
    return (
        "# Made by readymade's Make EXE: starts the program. Changes here are overwritten.\n"
        f"import {', '.join(names)}  # noqa: F401  (so PyInstaller bundles every form and module)\n"
        "from readymade import forms\n"
        "from readymade.form import app_path, main_loop, set_app_icon\n"
        "\n"
        + (f"set_app_icon(app_path({icon!r}))\n" if icon else "")
        + f"forms.{startup}.show()\n"
        "main_loop()\n"
    )


# The format of a program file's own icon on each system (Linux programs have none).
_ICON_FORMATS = {"win32": ".ico", "darwin": ".icns"}


def icon_needs_pillow(project, platform=sys.platform):
    """Whether the project's environment needs Pillow, for PyInstaller to turn the project's
    icon into the system's own format. Not when the IDE has Pillow: program_icon() does it here."""
    icon = project.setting("icon")
    native = _ICON_FORMATS.get(platform)
    return bool(icon and native and Path(icon).suffix.lower() != native and not pictures.have_pillow())


def program_icon(project, platform=sys.platform):
    """The icon for the program file (PyInstaller's --icon), or None: the project's icon in
    the system's own format. When the IDE has Pillow, a PNG or other picture is converted
    here, into the build folder; otherwise PyInstaller converts it, with Pillow in the
    project's environment. Raises OSError if the picture can't be read."""
    icon = project.setting("icon")
    native = _ICON_FORMATS.get(platform)
    source = project.folder / icon if icon else None
    if source is None or native is None or not source.is_file():
        return None
    if source.suffix.lower() == native or not pictures.have_pillow():
        return source
    target = build_folder(project) / "readymade" / f"icon{native}"
    target.parent.mkdir(parents=True, exist_ok=True)
    pictures.make_icon(source, target)
    return target


def write_launcher(project, startup):
    folder = build_folder(project) / "readymade"
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
    icon = project.setting("icon")
    if icon:  # for the windows' icon (the program file's own is built in)
        path = project.folder / icon
        add(path) if path.is_file() else missing.append(f"icon: {icon}")
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


def pyinstaller_args(project, launcher, readymade_root, platform=sys.platform):
    """The arguments after `python`, to run PyInstaller on the launcher."""
    work = build_folder(project) / "pyinstaller"
    args = [
        "-m", "PyInstaller", "--noconfirm", "--windowed",
        "--onedir" if platform == "darwin" else "--onefile",
        "--name", project.name,
        "--distpath", str(project.folder / "dist"),
        "--workpath", str(work), "--specpath", str(work),
        "--paths", str(project.folder), "--paths", str(readymade_root),
    ]
    for path, place in bundled_files(project)[0]:
        # Paths are absolute, as the spec lives in build/.
        args += ["--add-data", f"{path}{os.pathsep}{place}"]
    icon = program_icon(project, platform)
    if icon is not None:
        args += ["--icon", str(icon)]  # the program file's own icon
    args.append(str(launcher))
    return args
