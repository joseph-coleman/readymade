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
        self._on_double_click = on_double_click
        self._pending_drop = ""
        # The release that ends a double-click selects the button again, so the drop
        # waits for it: the ToolboxDrop tag runs after the Radiobutton class bindings.
        self.bind_class("ToolboxDrop", "<ButtonRelease-1>", self._drop)
        for label, value in [("Pointer", "")] + [(name, name) for name in REGISTRY]:
            button = tk.Radiobutton(
                self, text=label, value=value, variable=self._var,
                indicatoron=False, width=13, anchor="w", padx=6, pady=3,
            )
            button.pack(fill=tk.X, pady=1)
            if value:
                tags = button.bindtags()
                button.bindtags((tags[0], tags[1], "ToolboxDrop", *tags[2:]))
                button.bind("<Double-Button-1>", lambda e, v=value: setattr(self, "_pending_drop", v))

    def _drop(self, _):
        value, self._pending_drop = self._pending_drop, ""
        if value:
            self._on_double_click(value)

    @property
    def tool(self):
        """The control type being drawn, or "" for the pointer."""
        return self._var.get()

    def reset(self):
        self._var.set("")


class ProjectExplorer(ttk.Frame):
    """The project's forms and modules. Double-click to open; right-click for more."""

    def __init__(self, master, app):
        super().__init__(master, padding=4)
        self.app = app
        ttk.Label(self, text="Project").pack(anchor="w")
        self.tree = ttk.Treeview(self, show="tree", selectmode="browse", height=8)
        self.tree.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.tree.bind("<Double-Button-1>", lambda e: self._open("design"))
        self.tree.bind("<Return>", lambda e: self._open("design"))
        self.tree.bind("<Button-3>", self._popup)
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="View Object", command=lambda: self._open("design"))
        self.menu.add_command(label="View Code", command=lambda: self._open("code"))
        self.menu.add_command(label="Set as Startup", command=self._set_startup)

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        project = self.app.project
        if project is None:
            return
        top = self.tree.insert("", tk.END, text=project.name, open=True)
        startup = project.startup
        forms = self.tree.insert(top, tk.END, text="Forms", open=True)
        for name in project.forms():
            label = f"{name}  (startup)" if name == startup else name
            self.tree.insert(forms, tk.END, iid=f"form:{name}", text=label)
        modules = self.tree.insert(top, tk.END, text="Modules", open=True)
        for name in project.modules():
            self.tree.insert(modules, tk.END, iid=f"module:{name}", text=f"{name}.py")

    def _selected(self):
        kind, _, name = self.tree.focus().partition(":")
        return (kind, name) if name else (None, None)

    def _open(self, view):
        kind, name = self._selected()
        if kind == "form":
            self.app.open_form(name, view)
        elif kind == "module":
            self.app.open_module(name)
        return "break"

    def _popup(self, e):
        row = self.tree.identify_row(e.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        is_form = row.startswith("form:")
        for item in ("View Object", "Set as Startup"):
            self.menu.entryconfigure(item, state=tk.NORMAL if is_form else tk.DISABLED)
        self.menu.tk_popup(e.x_root, e.y_root)

    def _set_startup(self):
        kind, name = self._selected()
        if kind == "form":
            self.app.set_startup(name)


class PropertiesPanel(ttk.Frame):
    """Edit the selected object's properties. Edits commit on Enter or when focus leaves.

    app is the FormEditor whose form is showing, or None; see attach().
    """

    def __init__(self, master, app=None):
        super().__init__(master, padding=4)
        self.app = app
        self.current = None
        self._rows: dict[str, tuple[tk.StringVar, bool]] = {}  # prop -> (shown value, edited in a dialog)
        ttk.Label(self, text="Properties").pack(anchor="w")
        self.objects = ttk.Combobox(self, state="readonly", width=24)
        self.objects.pack(fill=tk.X, pady=(2, 6))
        self.objects.bind("<<ComboboxSelected>>", lambda e: self.app and self.app.select(self.objects.get()))
        self.grid_frame = ttk.Frame(self)
        self.grid_frame.pack(fill=tk.X)
        self.grid_frame.columnconfigure(1, weight=1)

    def attach(self, editor):
        """Show the properties of another form's objects (None: nothing)."""
        if editor is self.app:
            return
        self.commit_all()
        self.clear()
        self.app = editor
        self.refresh_objects()
        if editor is not None:
            self.show(editor.selected)

    def refresh_objects(self):
        self.objects["values"] = self.app.object_names() if self.app else []
        self.objects.set(self.current or "")

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
        props = self.app.props_for(obj)
        multiline = dict(props).get("multiline", False)
        for row, (prop, value) in enumerate(props):
            ttk.Label(self.grid_frame, text=prop).grid(row=row, column=0, sticky="w", padx=(0, 6), pady=1)
            var = tk.StringVar(value=_display(value))
            in_dialog = isinstance(value, list) or (prop == "text" and multiline)
            choices = ("True", "False") if isinstance(value, bool) else self.app.choices_for(obj, prop)
            if choices:
                editor = ttk.Combobox(self.grid_frame, textvariable=var, values=choices, state="readonly", width=16)
                editor.bind("<<ComboboxSelected>>", lambda e, p=prop: self.commit(p))
            elif in_dialog:
                editor = ttk.Frame(self.grid_frame)
                ttk.Entry(editor, textvariable=var, width=8, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
                ttk.Button(editor, text="\u2026", width=2, command=lambda p=prop: self._edit_lines(p)).pack(side=tk.LEFT)
            else:
                editor = ttk.Entry(self.grid_frame, textvariable=var, width=18)
                editor.bind("<Return>", lambda e, p=prop: self.commit(p))
                editor.bind("<FocusOut>", lambda e, p=prop: self.commit(p))
            editor.grid(row=row, column=1, sticky="ew", pady=1)
            self._rows[prop] = (var, in_dialog)

    def commit(self, prop):
        if self.app is None or self.current is None or prop not in self._rows:
            return
        var, in_dialog = self._rows[prop]
        if in_dialog:  # committed by the dialog's OK button
            return
        raw = var.get()
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
        if self.app is None or self.current is None:
            return
        for prop, value in self.app.props_for(self.current):
            if prop in self._rows:
                self._rows[prop][0].set(_display(value))

    def _edit_lines(self, prop):
        """Edit a list (one item per line, like VB's List property) or multi-line text."""
        obj = self.current
        if self.app is None or obj is None:
            return
        value = dict(self.app.props_for(obj))[prop]
        dialog = tk.Toplevel(self)
        dialog.title(f"{obj}.{prop}")
        dialog.transient(self.winfo_toplevel())
        hint = "One item per line:" if isinstance(value, list) else "Text:"
        ttk.Label(dialog, text=hint).pack(anchor="w", padx=8, pady=(8, 2))
        text = tk.Text(dialog, width=32, height=10, font=MONO, undo=True)
        text.pack(fill=tk.BOTH, expand=True, padx=8)
        text.insert("1.0", "\n".join(value) if isinstance(value, list) else value)

        def ok():
            self.app.set_property(obj, prop, text.get("1.0", "end-1c"))
            dialog.destroy()
            self.update_values()

        buttons = ttk.Frame(dialog, padding=8)
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", command=ok).pack(side=tk.RIGHT, padx=(0, 4))
        dialog.bind("<Escape>", lambda e: dialog.destroy())
        text.focus_set()
        dialog.grab_set()


def _display(value):
    if isinstance(value, list):
        return "; ".join(value)
    return str(value).replace("\n", " \u23ce ")  # show line breaks in multi-line text as ⏎


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
