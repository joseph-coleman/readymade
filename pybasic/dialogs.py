"""VB-style dialog functions: msgbox, inputbox, and the common file dialogs.

Each shows a modal dialog over the form you're using and returns the answer:

    if msgbox("Save changes?", buttons="yesno", icon="question") == "yes":
        ...
    name = inputbox("What's your name?")          # like input(), but None if Cancel
    path = open_file_dialog(filetypes={"Text files": "*.txt"})  # a Path, or None
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from tkinter import filedialog, messagebox, simpledialog

from pybasic import form as _form

BUTTONS = {
    "ok": messagebox.OK,
    "okcancel": messagebox.OKCANCEL,
    "yesno": messagebox.YESNO,
    "yesnocancel": messagebox.YESNOCANCEL,
    "retrycancel": messagebox.RETRYCANCEL,
    "abortretryignore": messagebox.ABORTRETRYIGNORE,
}
ICONS = ("info", "warning", "error", "question")


def msgbox(message, title=None, buttons="ok", icon="info"):
    """Show a message. Returns the button clicked: "ok", "cancel", "yes", "no",
    "retry", "abort" or "ignore"."""
    if buttons not in BUTTONS:
        raise ValueError(f"buttons must be one of: {', '.join(BUTTONS)}")
    if icon not in ICONS:
        raise ValueError(f"icon must be one of: {', '.join(ICONS)}")
    parent = _parent()
    dialog = messagebox.Message(parent=parent, title=_title(title, parent), message=str(message), icon=icon, type=BUTTONS[buttons])
    return str(dialog.show())


def inputbox(prompt, title=None, default=""):
    """Ask for a line of text, like input(prompt) but in a dialog. Returns the
    text, or None if Cancel was clicked."""
    parent = _parent()
    return simpledialog.askstring(_title(title, parent), str(prompt), initialvalue=default, parent=parent)


def open_file_dialog(title=None, filetypes=None, folder=None, multiple=False):
    """Choose a file to open. Returns its Path, or None if cancelled. With
    multiple=True, returns a list of Paths (empty if cancelled).
    filetypes is like {"Text files": "*.txt", "Images": "*.png *.jpg"}."""
    options = _file_options(title, filetypes, folder)
    if multiple:
        return [Path(p) for p in filedialog.askopenfilenames(**options)]
    return _path(filedialog.askopenfilename(**options))


def save_file_dialog(title=None, filetypes=None, folder=None, filename=""):
    """Choose where to save a file. Returns its Path, or None if cancelled. The
    first filetype's extension is added if the name has none."""
    options = _file_options(title, filetypes, folder)
    options["initialfile"] = filename
    if filetypes:
        first = next(iter(dict(filetypes).values())).split()[0]  # e.g. "*.txt"
        if first.startswith("*.") and "*" not in first[2:]:
            options["defaultextension"] = first[1:]
    return _path(filedialog.asksaveasfilename(**options))


def folder_dialog(title=None, folder=None):
    """Choose a folder. Returns its Path, or None if cancelled."""
    options = _file_options(title, None, folder)
    return _path(filedialog.askdirectory(mustexist=True, **options))


def _parent():
    """The window the dialog belongs to: the focused form, else a showing one."""
    root = _form.app_root()
    try:
        focus = root.focus_get()
    except KeyError:  # focus is in a widget tkinter doesn't know, like a dialog's
        focus = None
    if focus is not None:
        return focus.winfo_toplevel()
    showing = [f.root for f in _form._loaded if f.root.winfo_viewable()]
    return showing[0] if showing else root


def _title(title, parent):
    if title is not None:
        return str(title)
    return parent.title() if parent is not _form.app_root() else ""


def _file_options(title, filetypes, folder):
    options: dict[str, Any] = {"parent": _parent()}
    if title is not None:
        options["title"] = str(title)
    if filetypes:
        options["filetypes"] = list(dict(filetypes).items())
    if folder is not None:
        options["initialdir"] = str(folder)
    return options


def _path(result):
    return Path(result) if result else None
