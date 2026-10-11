"""License notices for a program made with Make EXE: LICENSES.txt beside it.

A program made with Make EXE carries Python, Tcl/Tk, readymade and the libraries it uses
inside it, and most of their licenses (MIT, BSD, the PSF's) ask for their notices to
come along when it's given to others. This gathers them, from the environment the
program was made from:

    python -m readymade.notices OUTPUT PROGRAM [LIBRARY ...]

LIBRARY: the project's dependencies; the libraries they need come too. Runs in the
project's environment (the IDE runs it there), so it reads what's actually bundled.
"""

from __future__ import annotations

import re
import sys
from importlib import metadata
from pathlib import Path

_LICENSE_FILE = re.compile(r"(?i)^(licen[cs]e|copying|notice|authors)([._-].*)?$")
_RULE = "=" * 72


def collect(libraries=()):
    """[(title, license text)]: readymade, Python, Tcl/Tk, then each library and what it needs."""
    found = [("readymade", _readymade()), (f"Python {sys.version.split()[0]}", _python())]
    tcl, tk = _tcl_tk()
    found += [("Tcl", tcl), ("Tk", tk)]
    for name in _with_requirements(libraries):
        found.append(_library(name))
    return [(title, text) for title, text in found if text]


def write(path, program, libraries=()):
    sections = [f"{title}\n{_RULE}\n\n{text.strip()}\n" for title, text in collect(libraries)]
    Path(path).write_text(
        f"{program} is made with readymade, and carries these inside it. Their licenses ask for\n"
        "these notices to come along with it.\n\n" + "\n\n".join(sections), encoding="utf-8")


def _readymade():
    here = Path(__file__).resolve().parent
    for candidate in (here.parent / "LICENSE", here / "LICENSE"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    try:
        return _distribution_license(metadata.distribution("readymade"))
    except metadata.PackageNotFoundError:
        return "MIT License (https://opensource.org/licenses/MIT)"


def _python():
    base = Path(sys.base_prefix)
    version = f"python{sys.version_info.major}.{sys.version_info.minor}"
    for candidate in (base / "LICENSE.txt", base / "LICENSE", base / "lib" / version / "LICENSE.txt",
                      base / "Lib" / "LICENSE.txt", base / "share" / "doc" / version / "LICENSE"):
        if candidate.is_file():
            return candidate.read_text(encoding="utf-8", errors="replace")
    return ("Python Software Foundation License Version 2 (https://docs.python.org/3/license.html)\n"
            "Copyright (c) 2001 Python Software Foundation. All rights reserved.")


def _tcl_tk():
    """The license terms of Tcl and Tk, from their library folders (Tk's is beside Tcl's)."""
    try:
        import tkinter

        tcl = Path(tkinter.Tcl().eval("set tcl_library"))
    except Exception:  # noqa: BLE001 - no Tcl here to ask: the usual terms
        return _TCL_TK, _TCL_TK
    tk = tcl.parent / f"tk{tkinter.TkVersion}"

    def terms(folder):
        found = next((f for f in (folder / "license.terms", folder.parent / "license.terms",
                                   folder / "demos" / "license.terms") if f.is_file()), None)
        return found.read_text(encoding="utf-8", errors="replace") if found else _TCL_TK

    return terms(tcl), terms(tk)


_TCL_TK = ("Tcl/Tk license (BSD-style): https://www.tcl.tk/software/tcltk/license.html\n"
           "Copyright (c) the Regents of the University of California, Sun Microsystems, Inc., Scriptics\n"
           "Corporation, ActiveState Corporation and other parties.")


def _with_requirements(libraries):
    """The libraries and those they need, by their distribution names, in order, each once."""
    seen, order, waiting = set(), [], list(libraries)
    while waiting:
        requirement = waiting.pop(0)
        name = re.split(r"[\s<>=!~;\[(]", requirement.strip(), maxsplit=1)[0]
        key = re.sub(r"[-_.]+", "-", name).lower()
        if not name or key in seen or key == "readymade":
            continue
        seen.add(key)
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        order.append(distribution.metadata["Name"] or name)
        for needed in distribution.requires or []:
            if ";" in needed and "extra ==" in needed:
                continue  # an optional extra
            waiting.append(needed)
    return order


def _library(name):
    distribution = metadata.distribution(name)
    version = distribution.version
    return f"{distribution.metadata['Name']} {version}", _distribution_license(distribution)


def _distribution_license(distribution):
    texts = []
    for file in distribution.files or []:
        if _LICENSE_FILE.match(file.name) and (".dist-info" in str(file) or "licenses" in file.parts):
            try:
                texts.append(file.read_text(encoding="utf-8"))
            except (OSError, UnicodeDecodeError):
                continue
    if texts:
        return "\n\n".join(texts)
    meta = distribution.metadata
    said = meta.get("License-Expression") or meta.get("License") or ", ".join(
        c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::"))
    home = meta.get("Home-page") or next((url.split(",", 1)[-1].strip() for url in meta.get_all("Project-URL") or []), "")
    return f"License: {said or 'see the project'}" + (f"\n{home}" if home else "")


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) < 2:
        raise SystemExit(__doc__)
    write(argv[0], argv[1], argv[2:])


if __name__ == "__main__":
    main()
