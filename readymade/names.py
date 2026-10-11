"""What a name can be, checked in one place. Each raises ValueError saying what's wrong.

    check_python_name   a name code uses: a control, a menu item, a form's class
    check_module_name   a form's or module's name: a Python name that doesn't hide one of
                        Python's own modules (json, os...) or readymade
    check_file_name     a file's or folder's name, on every system: Windows is the strictest
                        (no \\ / : * ? " < > |, no CON or NUL, no trailing dot or space)

Checks for names already taken stay with their callers, which know what's there.
"""

from __future__ import annotations

import keyword
import re
import sys

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                     *(f"LPT{n}" for n in range(1, 10))}


def check_python_name(name):
    if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"{name!r} isn't a valid Python name: letters, digits and _, not starting with a digit "
                         "(and not a word Python keeps, like for or class).")


def check_module_name(name):
    check_python_name(name)
    if name in sys.stdlib_module_names or name == "readymade":
        raise ValueError(f"{name!r} would hide Python's own {name} module. Choose another name.")


def check_file_name(name):
    if not name or name.strip() != name or name in (".", "..") or name.endswith("."):
        raise ValueError(f"{name!r} isn't a name for a file or folder (it can't be empty, or start or end with a "
                         "space, or end with a dot).")
    bad = re.findall(r'[\\/:*?"<>|\x00-\x1f]', name)
    if bad:
        raise ValueError(f"{name!r} isn't a name for a file or folder: it can't have {' '.join(sorted(set(bad)))} "
                         "in it.")
    if name.split(".")[0].upper() in _WINDOWS_RESERVED:
        raise ValueError(f"{name!r} isn't a name for a file or folder: Windows keeps {name.split('.')[0].upper()} "
                         "for itself.")
