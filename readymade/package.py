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

The program is one file on Windows and Linux, or with one-folder a folder holding it and
what it needs (it starts quicker). On macOS it's always an .app, as PyInstaller recommends.
Its details (File > Make EXE's dialog) are [project] version and these [tool.readymade]
settings: program-name, company, description, copyright, one-folder, and notices (whether
LICENSES.txt goes beside it: see readymade.notices). Windows shows them in the program
file's properties; on macOS the version and copyright go in the app's Info.plist (Get Info
has no place for a company or description).
"""

from __future__ import annotations

import os
import plistlib
import re
import sys
from pathlib import Path, PurePath

from readymade import formfile, pictures
from readymade.controls import REGISTRY

LAUNCHER = "_readymade_launcher.py"


def build_folder(project):
    return project.folder / "build"


def details(project):
    """The program's details, as File > Make EXE shows them: name, version, company,
    description, copyright, one_folder, notices."""
    def setting(key, default=""):
        value = project.setting(key)
        return default if value is None else value

    return {"name": setting("program-name") or project.name, "version": project.version,
            "company": setting("company"), "description": setting("description"),
            "copyright": setting("copyright"), "one_folder": setting("one-folder", False) is True,
            "notices": setting("notices", True) is not False}


def set_details(project, chosen):
    """Save details() as chosen in the dialog (what's as the defaults stays out of pyproject.toml)."""
    project.set_version(chosen["version"])
    for key, value, default in (("program-name", chosen["name"], project.name), ("company", chosen["company"], ""),
                                ("description", chosen["description"], ""), ("copyright", chosen["copyright"], ""),
                                ("one-folder", chosen["one_folder"], False), ("notices", chosen["notices"], True)):
        project.set_setting(key, None if value == default else value)


def check_name(name):
    """A program's name must be one a file can have. Raises ValueError if not."""
    if not name.strip() or name.strip() in (".", "..") or re.search(r'[/\\:*?"<>|]', name):
        raise ValueError(f"{name!r} can't be a program's name: it's made into a file name.")


def exe_path(project, platform=sys.platform):
    """Where the finished program will be."""
    dist = project.folder / "dist"
    name = details(project)["name"]
    if platform == "darwin":
        return dist / f"{name}.app"
    file = f"{name}.exe" if platform == "win32" else name
    return dist / name / file if details(project)["one_folder"] else dist / file


def notices_path(project, platform=sys.platform):
    """Where LICENSES.txt goes: beside the program (in its folder, with one-folder)."""
    return exe_path(project, platform).parent / "LICENSES.txt"


def version_numbers(version):
    """A version as Windows wants it, four numbers: "1.2" -> (1, 2, 0, 0), "2.0b1" -> (2, 0, 0, 0)."""
    numbers = []
    for part in str(version).split("."):
        digits = re.match(r"\d+", part)
        if digits is None:
            break
        numbers.append(int(digits.group()))
    return tuple((numbers + [0, 0, 0, 0])[:4])


def windows_version_file(project):
    """The program file's details for Windows (its Properties > Details), as PyInstaller's
    --version-file wants them. Returns its path."""
    d = details(project)
    numbers = version_numbers(d["version"] or "0")
    version = d["version"] or "0.0.0"
    strings = [("CompanyName", d["company"]), ("FileDescription", d["description"] or d["name"]),
               ("FileVersion", version), ("InternalName", d["name"]), ("LegalCopyright", d["copyright"]),
               ("OriginalFilename", f"{d['name']}.exe"), ("ProductName", d["name"]), ("ProductVersion", version)]
    text = (
        "VSVersionInfo(\n"
        f"  ffi=FixedFileInfo(filevers={numbers}, prodvers={numbers}, mask=0x3f, flags=0x0, OS=0x40004,\n"
        "                    fileType=0x1, subtype=0x0, date=(0, 0)),\n"
        "  kids=[\n"
        "    StringFileInfo([StringTable('040904B0', [\n"
        + "".join(f"      StringStruct({key!r}, {value!r}),\n" for key, value in strings if value)
        + "    ])]),\n"
        "    VarFileInfo([VarStruct('Translation', [1033, 1200])]),\n"
        "  ]\n"
        ")\n"
    )
    path = build_folder(project) / "readymade" / "version.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def set_mac_details(project, app=None):
    """Put the version and copyright in a made Mac app's Info.plist (PyInstaller leaves 0.0.0)."""
    d = details(project)
    plist = Path(app or exe_path(project, "darwin")) / "Contents" / "Info.plist"
    with open(plist, "rb") as file:
        info = plistlib.load(file)
    if d["version"]:
        info["CFBundleShortVersionString"] = info["CFBundleVersion"] = d["version"]
    if d["copyright"]:
        info["NSHumanReadableCopyright"] = d["copyright"]
    info["CFBundleDisplayName"] = d["name"]
    with open(plist, "wb") as file:
        plistlib.dump(info, file)


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
    d = details(project)
    args = [
        "-m", "PyInstaller", "--noconfirm", "--windowed",
        "--onedir" if platform == "darwin" or d["one_folder"] else "--onefile",
        "--name", d["name"],
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
    if platform == "win32":
        args += ["--version-file", str(windows_version_file(project))]
    args.append(str(launcher))
    return args
