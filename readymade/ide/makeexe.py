"""File > Make EXE...: the program's details, then Make (see readymade.package)."""

from __future__ import annotations

import sys
import tkinter as tk
from tkinter import ttk

from readymade import package
from readymade.ide import helptext
from readymade.ide.dialog import Dialog
from readymade.ide.tooltips import tip


class MakeExeDialog(Dialog):
    """The name, version and details of the program to make, one file or one folder, and
    license notices. Make saves them (in pyproject.toml, for next time) and calls on_make()."""

    def __init__(self, app, on_make):
        super().__init__(app, "Make EXE")
        self.on_make = on_make
        d = package.details(app.project)
        self.fields = {key: tk.StringVar(self, d[key]) for key in ("name", "version", "company", "description",
                                                                   "copyright")}
        self.one_folder = tk.BooleanVar(self, d["one_folder"])
        self.notices = tk.BooleanVar(self, d["notices"])

        body = self.body
        first = None
        for row, (key, label) in enumerate((("name", "Program name:"), ("version", "Version:"),
                                            ("company", "Company:"), ("description", "Description:"),
                                            ("copyright", "Copyright:"))):
            ttk.Label(body, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(body, textvariable=self.fields[key], width=40)
            entry.grid(row=row, column=1, sticky="we", padx=(8, 0), pady=2)
            first = first or entry
        where = ("A Mac's Get Info shows the version and copyright; the company and description\n"
                 "are for Windows, which shows them all in the program's Properties."
                 if sys.platform == "darwin" else "Windows shows these in the program's Properties.")
        ttk.Label(body, text=where, style="Note.TLabel").grid(row=5, column=1, sticky="w", padx=(8, 0))
        kind = ttk.LabelFrame(body, text="Make it as", padding=8)
        kind.grid(row=6, column=0, columnspan=2, sticky="we", pady=(10, 0))
        if sys.platform == "darwin":
            ttk.Label(kind, text="An .app (on a Mac, a program is always one).").pack(anchor="w")
        else:
            for text, value, said in (
                    ("One file, easy to hand to people", False,
                     "A single program file. It starts a little slower, as it unpacks itself each time."),
                    ("One folder with the program and what it needs (it starts quicker)", True,
                     "The program with its parts beside it, in a folder: hand people the whole folder.")):
                choice = ttk.Radiobutton(kind, text=text, value=value, variable=self.one_folder)
                choice.pack(anchor="w")
                tip(choice, said)
        notices = ttk.Checkbutton(body, text="Put LICENSES.txt beside it: the notices of Python, readymade and the\n"
                                             "libraries it carries, which their licenses ask to come along",
                                  variable=self.notices)
        notices.grid(row=7, column=0, columnspan=2, sticky="w", pady=(10, 0))
        tip(notices, "Their licenses (MIT, BSD, the PSF's) ask for their notices to come along when you give the "
                     "program to others: this gathers them in one file")
        self.note = ttk.Label(body, style="Note.TLabel", wraplength=440)
        self.note.grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 0))
        self.add_buttons(ok="Make", help=lambda: helptext.dialog("make exe"))
        first.focus_set()

    def chosen(self):
        return {**{key: var.get().strip() for key, var in self.fields.items()},
                "one_folder": self.one_folder.get(), "notices": self.notices.get()}

    def ok(self):
        self.make()

    def make(self):
        chosen = self.chosen()
        try:
            package.check_name(chosen["name"])
        except ValueError as e:
            self.note.configure(text=str(e))
            self.bell()
            return
        package.set_details(self.app.project, chosen)
        self.destroy()
        self.on_make()
