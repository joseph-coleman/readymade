"""The IDE's dialogs, built the same way: a title over the IDE's window, a body to fill, and
a row of buttons at the bottom right (Help, the main button, Cancel). Enter presses the main
button, Esc is Cancel, F1 is Help.

    class Thing(Dialog):
        def __init__(self, app):
            super().__init__(app, "Thing")
            ttk.Entry(self.body).grid(row=0, column=0)   # the body is a padded ttk.Frame
            self.add_buttons(help=lambda: helptext.dialog("thing"))

        def ok(self):   # the main button (and Enter)
            ...
            self.destroy()
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade.ide.tooltips import tip


class Dialog(tk.Toplevel):
    def __init__(self, app, title, resizable=False, padding=12):
        super().__init__(app.root)
        self.app = app
        self.title(title)
        self.transient(app.root)
        self.resizable(resizable, resizable)
        self.padding = padding
        self.body = ttk.Frame(self, padding=padding)
        self.body.pack(fill=tk.BOTH, expand=True)

    def add_buttons(self, ok="OK", cancel="Cancel", help=None, enter=True, tips=None):
        """The row of buttons, under the body: Help (when help gives a topic: a function, as
        F1 asks for it when pressed), the main one (labeled ok; None for none) and Cancel.
        enter=False when Enter means something in the body (a new line, say). tips: {label:
        a tip for that button}. Returns the row, to add more buttons to (they pack left)."""
        row = ttk.Frame(self, padding=(self.padding, 0, self.padding, self.padding))
        row.pack(fill=tk.X)
        buttons = ttk.Frame(row)
        buttons.pack(side=tk.RIGHT)
        if help is not None:
            def show_help(_=None):
                self.app.show_topic(help())
                return "break"

            ttk.Button(buttons, text="Help", command=show_help).pack(side=tk.LEFT, padx=(0, 12))
            self.bind("<F1>", show_help)
        made = {}
        if ok is not None:
            made[ok] = ttk.Button(buttons, text=ok, command=self.ok, default="active")
            made[ok].pack(side=tk.LEFT)
            if enter:
                self.bind("<Return>", lambda e: self.ok())
        made[cancel] = ttk.Button(buttons, text=cancel, command=self.cancel)
        made[cancel].pack(side=tk.LEFT, padx=(4, 0))
        self.bind("<Escape>", lambda e: self.cancel())
        for label, said in (tips or {}).items():
            tip(made[label], said)
        return buttons

    def ok(self):
        """The main button: subclasses do their work, then close."""
        self.destroy()

    def cancel(self):
        self.destroy()
