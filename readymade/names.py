"""What a name can be, checked in one place. Each raises ValueError saying what's wrong.

    check_python_name   a name code uses: a control, a menu item, a form's class
    check_control_name  a control's: a Python name, or an element of a control array, "Digit[3]"
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

_ELEMENT = re.compile(r"^([A-Za-z_]\w*)\[(0|[1-9]\d*)\]$")  # (no [007]: one name for each index)
MAX_INDEX = 32767  # (VB's)

_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)),
                     *(f"LPT{n}" for n in range(1, 10))}


def check_python_name(name):
    if not isinstance(name, str) or not name.isidentifier() or keyword.iskeyword(name):
        raise ValueError(f"{name!r} isn't a valid Python name: letters, digits and _, not starting with a digit "
                         "(and not a word Python keeps, like for or class).")


def split_element(name):
    """A control's name as (array name, index): "Digit[3]" is ("Digit", 3), and a control
    that isn't in an array, "Label1", is ("Label1", None)."""
    match = _ELEMENT.match(name)
    return (match.group(1), int(match.group(2))) if match else (name, None)


def element_name(base, index):
    """The name of a control array's element: element_name("Digit", 3) is "Digit[3]"."""
    return base if index is None else f"{base}[{int(index)}]"


def check_control_name(name):
    base, index = split_element(name)
    check_python_name(base)
    if index is not None and index > MAX_INDEX:
        raise ValueError(f"{name!r}: an index can be 0 to {MAX_INDEX}.")


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
