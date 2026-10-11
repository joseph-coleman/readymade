"""VB-style dialog functions: msgbox, inputbox, the common file dialogs, and color and font pickers.

Each shows a modal dialog over the form you're using and returns the answer:

    if msgbox("Save changes?", buttons="yesno", icon="question") == "yes":
        ...
    name = inputbox("What's your name?")          # like input(), but None if Cancel
    path = open_file_dialog(filetypes={"Text files": "*.txt"})  # a Path, or None
    color = color_dialog("#336699")               # "#rrggbb", or None
    font = font_dialog("Arial, 12")               # like "Arial, 14, bold", or None

Python's own input() still reads from the console, which a window program
doesn't have (from the IDE it competes with the Immediate window), so forms
should use inputbox() instead.
"""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, simpledialog, ttk
from tkinter import font as tkfont
from typing import Any

from readymade import appearance
from readymade import form as _form

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
    "retry", "abort" or "ignore".
    
    buttons:  ok,  okcancel, yesno, yesnocancel, retrycancel, abortretryignore
    icons: info, warning, question, error
    """
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
    """Choose a file to open. Returns its Path, or None if canceled. With
    multiple=True, returns a list of Paths (empty if canceled).
    filetypes is like {"Text files": "*.txt", "Images": "*.png *.jpg"}."""
    options = _file_options(title, filetypes, folder)
    if multiple:
        return [Path(p) for p in filedialog.askopenfilenames(**options)]
    return _path(filedialog.askopenfilename(**options))


def save_file_dialog(title=None, filetypes=None, folder=None, filename=""):
    """Choose where to save a file. Returns its Path, or None if canceled. The
    first filetype's extension is added if the name has none."""
    options = _file_options(title, filetypes, folder)
    options["initialfile"] = filename
    if filetypes:
        first = next(iter(dict(filetypes).values())).split()[0]  # e.g. "*.txt"
        if first.startswith("*.") and "*" not in first[2:]:
            options["defaultextension"] = first[1:]
    return _path(filedialog.asksaveasfilename(**options))


def folder_dialog(title=None, folder=None):
    """Choose a folder. Returns its Path, or None if canceled."""
    options = _file_options(title, None, folder)
    return _path(filedialog.askdirectory(mustexist=True, **options))


def color_dialog(color=None, title=None):
    """Choose a color, starting from color (like "#336699" or "red"). Returns
    "#rrggbb", or None if canceled."""
    options: dict[str, Any] = {"parent": _parent()}
    if color is not None:
        options["color"] = color
    if title is not None:
        options["title"] = str(title)
    return colorchooser.askcolor(**options)[1]


def font_dialog(font="", title=None):
    """Choose a font, starting from font (like "Arial, 12, bold"). Returns the font in the
    same form, ready for a control's font property, or None if canceled. "" is the usual font."""
    parent = _parent()
    return FontChooser.ask(parent, font, title=str(title) if title is not None else "Font")


class FontChooser(tk.Toplevel):
    """The font dialog: a family, a size and styles, with a sample. Tk has no standard font
    dialog on every system, so this is readymade's own."""

    SIZES = (8, 9, 10, 11, 12, 14, 16, 18, 20, 24, 28, 32, 36, 48, 72)
    USUAL = "(usual font)"

    @classmethod
    def ask(cls, parent, font="", title="Font"):
        """Show the dialog over parent until it's closed; the chosen font, or None."""
        dialog = cls(parent, font, title)
        dialog.grab_set()
        dialog.wait_window()
        return dialog.result

    def __init__(self, parent, font="", title="Font"):
        super().__init__(parent)
        self.title(title)
        self.transient(parent.winfo_toplevel())
        self.resizable(False, False)
        self.result = None
        family, size, styles = appearance.parse_font(font)
        self.family = tk.StringVar(self, family or self.USUAL)
        self.size = tk.StringVar(self, str(size) if size else "")
        self.styles = {s: tk.BooleanVar(self, s in styles) for s in appearance.FONT_STYLES}

        body = ttk.Frame(self, padding=8)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Font:").grid(row=0, column=0, sticky="w")
        ttk.Label(body, text="Size:").grid(row=0, column=2, sticky="w", padx=(8, 0))
        entry = ttk.Entry(body, textvariable=self.family, width=28)
        entry.grid(row=1, column=0, columnspan=2, sticky="ew")
        self.families = tk.Listbox(body, height=10, exportselection=False)
        names = sorted({f for f in tkfont.families(self) if not f.startswith("@")}, key=str.lower)
        self.families.insert(tk.END, self.USUAL, *names)
        self.families.grid(row=2, column=0, sticky="nsew")
        bar = ttk.Scrollbar(body, command=self.families.yview)
        self.families["yscrollcommand"] = bar.set
        bar.grid(row=2, column=1, sticky="ns")
        self.families.bind("<<ListboxSelect>>", self._picked)
        sizes = ttk.Combobox(body, textvariable=self.size, values=self.SIZES, width=6)
        sizes.grid(row=1, column=2, sticky="nw", padx=(8, 0))
        checks = ttk.Frame(body)
        checks.grid(row=2, column=2, sticky="nw", padx=(8, 0), pady=(6, 0))
        for style, var in self.styles.items():
            ttk.Checkbutton(checks, text=style.capitalize(), variable=var).pack(anchor="w")
        self.sample = tk.Label(body, text="AaBbYyZz 123", height=2, relief="sunken", bd=1)
        self.sample.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=4, column=0, columnspan=3, sticky="e", pady=(8, 0))
        ttk.Button(buttons, text="OK", command=self.ok).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.cancel).pack(side=tk.LEFT, padx=(4, 0))
        self._usual = tkfont.nametofont("TkDefaultFont", root=self).actual()
        for var in (self.family, self.size, *self.styles.values()):
            var.trace_add("write", lambda *_: self._show_sample())
        self.family.trace_add("write", lambda *_: self._select(self.family.get()))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.cancel())
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        self._select(self.family.get())
        self._show_sample()
        entry.focus_set()
        entry.select_range(0, tk.END)  # typing replaces it

    def value(self):
        """The font chosen so far, like "Arial, 12, bold"; ValueError if the size isn't a number."""
        family = self.family.get().strip()
        styles = [s for s, var in self.styles.items() if var.get()]
        return appearance.format_font((family if family != self.USUAL else "", self.size.get(), *styles))

    def ok(self):
        try:
            self.result = self.value()
        except ValueError:
            self.bell()
            return
        self.destroy()

    def cancel(self):
        self.result = None
        self.destroy()

    def _picked(self, _):
        chosen = self.families.curselection()
        if chosen:
            self.family.set(self.families.get(chosen[0]))

    def _select(self, family):
        names = self.families.get(0, tk.END)
        if family in names:
            index = names.index(family)
            self.families.selection_clear(0, tk.END)
            self.families.selection_set(index)
            self.families.see(index)

    def _show_sample(self):
        try:
            self.sample["font"] = appearance.tk_font(self.value(), self._usual)
        except ValueError:
            pass  # a size that's still being typed


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
