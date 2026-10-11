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

    def center_on(self, widget):
        """Place the dialog over the middle of widget (the IDE's window, say)."""
        self.update_idletasks()
        x = widget.winfo_rootx() + (widget.winfo_width() - self.winfo_reqwidth()) // 2
        y = widget.winfo_rooty() + (widget.winfo_height() - self.winfo_reqheight()) // 3
        self.geometry(f"+{max(x, 0)}+{max(y, 0)}")


class AskString(Dialog):
    """A line of text to type, like tkinter's simpledialog.askstring but in the IDE's look."""

    def __init__(self, app, title, prompt, initial=""):
        super().__init__(app, title)
        self.answer = None
        ttk.Label(self.body, text=prompt).pack(anchor="w", pady=(0, 4))
        self.entry = ttk.Entry(self.body, width=40)
        self.entry.pack(fill=tk.X)
        self.entry.insert(0, initial)
        self.entry.select_range(0, tk.END)
        self.entry.icursor(tk.END)
        self.add_buttons()
        self.entry.focus_set()

    def ok(self):
        self.answer = self.entry.get()
        self.destroy()


def ask_string(app, title, prompt, initial=""):
    """Ask for a line of text and wait: what was typed, or None if canceled."""
    asker = AskString(app, title, prompt, initial)
    asker.center_on(app.root)
    asker.grab_set()
    asker.wait_window()
    return asker.answer
