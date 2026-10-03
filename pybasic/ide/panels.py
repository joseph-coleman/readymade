"""The IDE's side panels: Toolbox, Properties and the Immediate window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pybasic.controls import REGISTRY

MONO = "TkFixedFont"


class Toolbox(ttk.Frame):
    """Pick a control type to draw. Double-click one to drop it on the form."""

    def __init__(self, master, on_double_click):
        super().__init__(master, padding=4)
        ttk.Label(self, text="Toolbox").pack(anchor="w", pady=(0, 4))
        self._var = tk.StringVar(value="")
        for label, value in [("Pointer", "")] + [(name, name) for name in REGISTRY]:
            button = tk.Radiobutton(
                self, text=label, value=value, variable=self._var,
                indicatoron=False, width=10, anchor="w", padx=6, pady=3,
            )
            button.pack(fill=tk.X, pady=1)
            if value:
                button.bind("<Double-Button-1>", lambda e, v=value: on_double_click(v))

    @property
    def tool(self):
        """The control type being drawn, or "" for the pointer."""
        return self._var.get()

    def reset(self):
        self._var.set("")


class PropertiesPanel(ttk.Frame):
    """Edit the selected object's properties. Edits commit on Enter or when focus leaves."""

    def __init__(self, master, app):
        super().__init__(master, padding=4)
        self.app = app
        self.current = None
        self._rows: dict[str, tk.StringVar] = {}
        ttk.Label(self, text="Properties").pack(anchor="w")
        self.objects = ttk.Combobox(self, state="readonly", width=24)
        self.objects.pack(fill=tk.X, pady=(2, 6))
        self.objects.bind("<<ComboboxSelected>>", lambda e: app.select(self.objects.get()))
        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(fill=tk.X)
        self.grid_frame.columnconfigure(1, weight=1)

    def refresh_objects(self):
        self.objects["values"] = self.app.object_names()
        if self.current:
            self.objects.set(self.current)

    def clear(self):
        """Drop the rows without committing them, e.g. when another file is opened."""
        for child in self.grid_frame.winfo_children():
            child.destroy()
        self._rows = {}
        self.current = None

    def show(self, obj):
        self.commit_all()
        self.clear()
        self.current = obj
        self.objects.set(obj)
        for row, (prop, value) in enumerate(self.app.props_for(obj)):
            ttk.Label(self.grid_frame, text=prop).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=1)
            var = tk.StringVar(value=str(value))
            if isinstance(value, bool):
                editor = ttk.Combobox(self.grid_frame, textvariable=var, values=("True", "False"), state="readonly", width=16)
                editor.bind("<<ComboboxSelected>>", lambda e, p=prop: self.commit(p))
            else:
                editor = ttk.Entry(self.grid_frame, textvariable=var, width=18)
                editor.bind("<Return>", lambda e, p=prop: self.commit(p))
                editor.bind("<FocusOut>", lambda e, p=prop: self.commit(p))
            editor.grid(row=row, column=1, sticky="ew", pady=1)
            self._rows[prop] = var

    def commit(self, prop):
        if self.current is None or prop not in self._rows:
            return
        raw = self._rows[prop].get()
        current = dict(self.app.props_for(self.current)).get(prop)
        if current is None or raw == str(current):
            return
        renamed = self.app.set_property(self.current, prop, raw)
        if renamed is not None:
            self.current = renamed
            self.objects.set(renamed)
        self.update_values()

    def commit_all(self):
        for prop in list(self._rows):
            self.commit(prop)

    def update_values(self):
        """Show the current values, e.g. after a control is dragged."""
        if self.current is None:
            return
        for prop, value in self.app.props_for(self.current):
            if prop in self._rows:
                self._rows[prop].set(str(value))


class ImmediateWindow(ttk.Frame):
    """Program output, plus a Python prompt into the running program (or the IDE when stopped)."""

    def __init__(self, master, on_line):
        super().__init__(master, padding=(4, 2))
        self._on_line = on_line
        self._history: list[str] = []
        self._history_pos = 0
        ttk.Label(self, text="Immediate").pack(anchor="w")
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)
        self.output = tk.Text(body, height=8, font=MONO, state=tk.DISABLED, wrap="word")
        scroll = ttk.Scrollbar(body, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prompt = ttk.Frame(self)
        prompt.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(prompt, text=">>>", font=MONO).pack(side=tk.LEFT)
        self.entry = ttk.Entry(prompt, font=MONO)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self.entry.bind("<Return>", self._submit)
        self.entry.bind("<Up>", lambda e: self._recall(-1))
        self.entry.bind("<Down>", lambda e: self._recall(1))

    def write(self, text):
        self.output.configure(state=tk.NORMAL)
        self.output.insert(tk.END, text)
        self.output.see(tk.END)
        self.output.configure(state=tk.DISABLED)

    def _submit(self, _):
        line = self.entry.get()
        self.entry.delete(0, tk.END)
        if line.strip():
            self._history.append(line)
        self._history_pos = len(self._history)
        self._on_line(line)

    def _recall(self, step):
        if not self._history:
            return
        self._history_pos = max(0, min(len(self._history), self._history_pos + step))
        self.entry.delete(0, tk.END)
        if self._history_pos < len(self._history):
            self.entry.insert(0, self._history[self._history_pos])
