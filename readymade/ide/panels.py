"""The IDE's side panels: Toolbox, Properties and the Immediate window."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade import menus
from readymade.controls import REGISTRY

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
        for sequence in menus.context_clicks(self.tree):
            self.tree.bind(sequence, self._popup)
        self.tree.bind("<Delete>", lambda e: self._remove())
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="View Object", command=lambda: self._open("design"))
        self.menu.add_command(label="View Code", command=lambda: self._open("code"))
        self.menu.add_command(label="Set as Startup", command=self._set_startup)
        self.menu.add_separator()
        self.menu.add_command(label="Remove...", command=self._remove)
        self.python_menu = tk.Menu(self, tearoff=False)
        self.python_menu.add_command(label="Create Environment...", command=app.ask_create_environment)
        self.python_menu.add_command(label="Choose Python Interpreter...", command=app.choose_python)
        self.python_menu.add_command(label="Use Default Python", command=lambda: app.set_python(None))
        self.libraries_menu = tk.Menu(self, tearoff=False)
        self.libraries_menu.add_command(label="Add Library...", command=app.add_library)
        self.libraries_menu.add_command(label="Remove Library...", command=self._remove)
        for menu in (self.menu, self.python_menu, self.libraries_menu):
            menus.defer_commands(menu)  # or dialogs opened from them freeze on macOS

    def refresh(self):
        self.tree.delete(*self.tree.get_children())
        project = self.app.project
        if project is None:
            return
        top = self.tree.insert("", tk.END, text=project.name, open=True)
        self.tree.insert(top, tk.END, iid="python", text=self.app.python_label())
        startup = project.startup
        forms = self.tree.insert(top, tk.END, text="Forms", open=True)
        for name in project.forms():
            label = f"{name}  (startup)" if name == startup else name
            self.tree.insert(forms, tk.END, iid=f"form:{name}", text=label)
        modules = self.tree.insert(top, tk.END, text="Modules", open=True)
        for name in project.modules():
            self.tree.insert(modules, tk.END, iid=f"module:{name}", text=f"{name}.py")
        libraries = self.tree.insert(top, tk.END, iid="libraries", text="Libraries", open=True)
        for requirement in project.dependencies:
            self.tree.insert(libraries, tk.END, iid=f"library:{requirement}", text=requirement)

    def _selected(self):
        kind, _, name = self.tree.focus().partition(":")
        return (kind, name) if name else (None, None)

    def _open(self, view):
        if self.tree.focus() == "python":
            self.app.choose_python()
            return "break"
        if self.tree.focus() == "libraries":
            self.app.add_library()
            return "break"
        kind, name = self._selected()
        if kind == "form":
            self.app.open_form(name, view)
        elif kind == "module":
            self.app.open_module(name)
        return "break"

    def _remove(self):
        """Remove the selected form, module or library (the app asks first)."""
        kind, name = self._selected()
        if kind in ("form", "module", "library"):
            self.app.remove_from_project(kind, name)
        return "break"

    def _popup(self, e):
        row = self.tree.identify_row(e.y)
        if not row:
            return
        self.tree.selection_set(row)
        self.tree.focus(row)
        self.menu_for(row).tk_popup(e.x_root, e.y_root)

    def menu_for(self, row):
        """The right-click menu for a row, with what doesn't apply to it disabled."""
        def enable(menu, label, on):
            menu.entryconfigure(label, state=tk.NORMAL if on else tk.DISABLED)

        if row == "python":
            return self.python_menu
        if row == "libraries" or self.tree.parent(row) == "libraries":
            enable(self.libraries_menu, "Remove Library...", row.startswith("library:"))
            return self.libraries_menu
        for label in ("View Object", "Set as Startup"):
            enable(self.menu, label, row.startswith("form:"))
        enable(self.menu, "Remove...", row.startswith(("form:", "module:")))
        return self.menu

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
        self._editors: dict[str, tk.Widget] = {}  # prop -> its editing widget
        self._swatches: dict[str, tk.Label] = {}  # color prop -> the patch showing its color
        ttk.Label(self, text="Properties").pack(anchor="w")
        self.objects = ttk.Combobox(self, state="readonly", width=24)
        self.objects.pack(fill=tk.X, pady=(2, 6))
        self.objects.bind("<<ComboboxSelected>>", lambda e: self.app and self.app.select(self.objects.get()))
        # The rows scroll when there are more than fit.
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True)
        style = ttk.Style(self)
        style.configure("Dots.TButton", padding=(2, 0))
        self._scroller = tk.Canvas(body, highlightthickness=0, bd=0, background=style.lookup("TFrame", "background"))
        self._bar = ttk.Scrollbar(body, command=self._scroller.yview)
        self._scroller.configure(yscrollcommand=self._bar.set)
        self._scroller.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.grid_frame = ttk.Frame(self._scroller)
        self.grid_frame.columnconfigure(1, weight=1)
        self._rows_window = self._scroller.create_window(0, 0, window=self.grid_frame, anchor="nw")
        self.grid_frame.bind("<Configure>", lambda e: self._fit_rows())
        self._scroller.bind("<Configure>", lambda e: self._fit_rows())

    def _fit_rows(self):
        """Make the rows as wide as the panel, and show the scrollbar only when they don't all fit."""
        self._scroller.itemconfigure(self._rows_window, width=self._scroller.winfo_width())
        if int(self._scroller["width"]) != self.grid_frame.winfo_reqwidth():
            self._scroller["width"] = self.grid_frame.winfo_reqwidth()  # the panel's natural width, not a canvas's
        height = self.grid_frame.winfo_reqheight()
        self._scroller.configure(scrollregion=(0, 0, 0, height))
        if height > self._scroller.winfo_height() > 1:
            if not self._bar.winfo_ismapped():
                self._bar.pack(side=tk.RIGHT, fill=tk.Y, before=self._scroller)
        else:
            self._bar.pack_forget()
            self._scroller.yview_moveto(0)

    def _wheel(self, e):
        if self._bar.winfo_ismapped():
            step = -1 if (e.num == 4 or e.delta > 0) else 1
            self._scroller.yview_scroll(step * 2, "units")
        return "break"  # and a dropdown under the mouse keeps its value

    def _see(self, widget):
        """Scroll so a row being edited (say, reached with Tab) is in view."""
        total = self.grid_frame.winfo_reqheight()
        if total <= self._scroller.winfo_height():
            return
        top = widget.winfo_rooty() - self.grid_frame.winfo_rooty()
        bottom = top + widget.winfo_height()
        shown_top = self._scroller.canvasy(0)
        shown_bottom = shown_top + self._scroller.winfo_height()
        if top < shown_top:
            self._scroller.yview_moveto(top / total)
        elif bottom > shown_bottom:
            self._scroller.yview_moveto((bottom - self._scroller.winfo_height()) / total)

    def _connect_row(self, widget):
        for w in (widget, *widget.winfo_children()):
            for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                w.bind(sequence, self._wheel)
            w.bind("<FocusIn>", lambda e, row=widget: self._see(row), add="+")

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
        self._editors = {}
        self._swatches = {}
        self.current = None

    def show(self, obj):
        self.commit_all()
        self.clear()
        self.current = obj
        self.objects.set(obj)
        props = self.app.props_for(obj)
        multiline = dict(props).get("multiline", False)
        for row, (prop, value) in enumerate(props):
            label = ttk.Label(self.grid_frame, text=prop)
            label.grid(row=row, column=0, sticky="w", padx=(0, 6), pady=1)
            self._connect_row(label)
            var = tk.StringVar(value=_display(value))
            in_dialog = isinstance(value, list) or (prop == "text" and multiline)
            choices = ("True", "False") if isinstance(value, bool) else self.app.choices_for(obj, prop)
            chooser = self.app.chooser_for(obj, prop)
            if chooser:  # typed, or chosen in a dialog with the "..." button
                editor = ttk.Frame(self.grid_frame)
                entry = ttk.Entry(editor, textvariable=var, width=8)
                entry.pack(side=tk.LEFT, fill=tk.X, expand=True)
                entry.bind("<Return>", lambda e, p=prop: self.commit(p))
                entry.bind("<FocusOut>", lambda e, p=prop: self.commit(p))
                if chooser == "color":
                    swatch = self._swatches[prop] = tk.Label(editor, width=2, relief="solid", bd=1)
                    swatch.pack(side=tk.LEFT, padx=(2, 0), fill=tk.Y)
                    self._swatch_usual = swatch.cget("background")  # shown for "", the usual color
                    self._show_swatch(prop, value)
                ttk.Button(editor, text="\u2026", width=2, style="Dots.TButton",
                           command=lambda p=prop: self._choose(p)).pack(side=tk.LEFT)
            elif choices:
                editor = ttk.Combobox(self.grid_frame, textvariable=var, values=choices, state="readonly", width=16)
                editor.bind("<<ComboboxSelected>>", lambda e, p=prop: self.commit(p))
            elif in_dialog:
                editor = ttk.Frame(self.grid_frame)
                ttk.Entry(editor, textvariable=var, width=8, state="readonly").pack(side=tk.LEFT, fill=tk.X, expand=True)
                ttk.Button(editor, text="\u2026", width=2, style="Dots.TButton",
                           command=lambda p=prop: self._edit_lines(p)).pack(side=tk.LEFT)
            else:
                editor = ttk.Entry(self.grid_frame, textvariable=var, width=18)
                editor.bind("<Return>", lambda e, p=prop: self.commit(p))
                editor.bind("<FocusOut>", lambda e, p=prop: self.commit(p))
            editor.grid(row=row, column=1, sticky="ew", pady=1)
            self._connect_row(editor)
            self._rows[prop] = (var, in_dialog)
            self._editors[prop] = editor
        self._scroller.yview_moveto(0)

    def prop_with_focus(self, widget):
        """The property whose row has the keyboard focus (for F1), or None."""
        if widget is None:
            return None
        return next((prop for prop, editor in self._editors.items() if str(widget).startswith(str(editor))), None)

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
            if prop in self._swatches:
                self._show_swatch(prop, value)

    def _show_swatch(self, prop, color):
        self._swatches[prop]["background"] = color or self._swatch_usual

    def _choose(self, prop):
        """Choose a property's value in a dialog: a file (one from elsewhere is copied into
        the project), a color or a font."""
        if self.app is None or self.current is None:
            return
        self.commit(prop)
        renamed = self.app.choose(self.current, prop)
        if renamed is not None:
            self.current = renamed

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


class HelpPanel(ttk.Frame):
    """F1's help: a topic's title, what it is, and its text, with a link to the Python
    documentation when there's a page about it."""

    def __init__(self, master):
        super().__init__(master, padding=(4, 2))
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.title = ttk.Label(top, font=("TkDefaultFont", 11, "bold"))
        self.title.pack(side=tk.LEFT)
        self.subtitle = ttk.Label(top, foreground="gray40")
        self.subtitle.pack(side=tk.LEFT, padx=8)
        self.docs = ttk.Button(top, text="Python documentation")
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.text = tk.Text(body, height=8, font=MONO, wrap="word", state=tk.DISABLED, padx=4)
        scroll = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.url = ""

    def show(self, topic):
        self.title.configure(text=topic.title)
        self.subtitle.configure(text=topic.subtitle)
        self.text.configure(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", topic.text)
        self.text.configure(state=tk.DISABLED)
        self.url = topic.docs_url
        if self.url:
            self.docs.configure(command=lambda url=self.url: __import__("webbrowser").open(url))
            self.docs.pack(side=tk.RIGHT)
        else:
            self.docs.pack_forget()
