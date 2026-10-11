"""Moving files to the Recycle Bin (Windows) or the Trash (macOS, Linux), where they can be
put back from, instead of deleting them. Each system's own way, without extra libraries:

    Windows  the shell's file operation with undo allowed (what Explorer does)
    macOS    NSFileManager's trashItemAtURL (through ctypes), else asking the Finder
    Linux    the freedesktop.org trash: ~/.local/share/Trash, or .Trash-UID at the top of
             another drive, with a .trashinfo file saying where it came from
"""

from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


class TrashError(OSError):
    pass


def name():
    """What the system calls it."""
    return "Recycle Bin" if sys.platform == "win32" else "Trash"


def move_to_trash(path):
    """Move a file or folder to the Recycle Bin / Trash. Raises TrashError if it couldn't."""
    path = Path(path).absolute()
    if not path.exists() and not path.is_symlink():
        raise TrashError(f"{path} isn't there")
    if sys.platform == "win32":
        _windows(path)
    elif sys.platform == "darwin":
        _mac(path)
    else:
        _freedesktop(path)


def _windows(path):
    import ctypes
    from ctypes import wintypes

    class SHFILEOPSTRUCTW(ctypes.Structure):
        _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR),
                    ("pTo", wintypes.LPCWSTR), ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL),
                    ("hNameMappings", ctypes.c_void_p), ("lpszProgressTitle", wintypes.LPCWSTR)]

    FO_DELETE = 3
    FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI = 0x4, 0x10, 0x40, 0x400
    operation = SHFILEOPSTRUCTW(wFunc=FO_DELETE, pFrom=str(path) + "\0",  # (the list ends with two NULs)
                                fFlags=FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI)
    result = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(operation))
    if result or operation.fAnyOperationsAborted:
        raise TrashError(f"Windows couldn't move {path.name} to the Recycle Bin (error {result})")


def _mac(path):
    try:
        if _mac_file_manager(path):
            return
    except (OSError, AttributeError):
        pass
    script = f'tell application "Finder" to delete (POSIX file "{_applescript(str(path))}" as alias)'
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode != 0:
        raise TrashError(f"The Finder couldn't move {path.name} to the Trash: {result.stderr.strip()}")


def _applescript(text):
    return text.replace("\\", "\\\\").replace('"', '\\"')


def _mac_file_manager(path):
    """[[NSFileManager defaultManager] trashItemAtURL:url resultingItemURL:nil error:nil]."""
    import ctypes
    import ctypes.util

    objc = ctypes.cdll.LoadLibrary(ctypes.util.find_library("objc"))
    ctypes.cdll.LoadLibrary(ctypes.util.find_library("Foundation"))
    objc.objc_getClass.restype = objc.sel_registerName.restype = ctypes.c_void_p
    objc.objc_getClass.argtypes = objc.sel_registerName.argtypes = [ctypes.c_char_p]
    send = objc.objc_msgSend

    def message(receiver, selector, *args, returns=ctypes.c_void_p):
        send.restype = returns
        send.argtypes = [ctypes.c_void_p, ctypes.c_void_p] + [type(a) if isinstance(a, ctypes._SimpleCData)
                                                                else ctypes.c_void_p for a in args]
        return send(receiver, objc.sel_registerName(selector), *args)

    text = message(objc.objc_getClass(b"NSString"), b"stringWithUTF8String:", ctypes.c_char_p(os.fsencode(path)))
    url = message(objc.objc_getClass(b"NSURL"), b"fileURLWithPath:", ctypes.c_void_p(text))
    manager = message(objc.objc_getClass(b"NSFileManager"), b"defaultManager")
    return bool(message(manager, b"trashItemAtURL:resultingItemURL:error:", ctypes.c_void_p(url),
                        ctypes.c_void_p(None), ctypes.c_void_p(None), returns=ctypes.c_bool))


def _freedesktop(path):
    trash = _trash_folder(path)
    files, info = trash / "files", trash / "info"
    for folder in (files, info):
        folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    # A name not used in the trash yet: "notes.txt", "notes.txt.2", ...
    stem, n = path.name, 1
    while (files / (stem if n == 1 else f"{stem}.{n}")).exists() or (
            info / f"{stem if n == 1 else f'{stem}.{n}'}.trashinfo").exists():
        n += 1
    trashed = stem if n == 1 else f"{stem}.{n}"
    # The home trash keeps where it came from in full; a drive's own trash, from the drive's top.
    where = str(path) if trash == _home_trash() else os.path.relpath(path, trash.parent)
    (info / f"{trashed}.trashinfo").write_text(
        f"[Trash Info]\nPath={quote(where)}\nDeletionDate={datetime.datetime.now():%Y-%m-%dT%H:%M:%S}\n",
        encoding="utf-8")
    try:
        os.rename(path, files / trashed)
    except OSError as e:
        (info / f"{trashed}.trashinfo").unlink(missing_ok=True)
        raise TrashError(f"Couldn't move {path.name} to the Trash: {e}") from None


def _home_trash():
    data = os.environ.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    return Path(data) / "Trash"


def _trash_folder(path):
    """The home trash for files on its drive, else .Trash-UID at the top of the file's drive."""
    home = _home_trash()
    home.mkdir(parents=True, exist_ok=True, mode=0o700)
    device = path.lstat().st_dev
    if home.stat().st_dev == device:
        return home
    top = path.parent
    while top.parent != top and top.parent.stat().st_dev == device:
        top = top.parent
    return top / f".Trash-{os.getuid()}"
