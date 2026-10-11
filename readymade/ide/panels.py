"""The IDE's side panels: Toolbox, Properties, and the Immediate, Problems and Help tabs,
and while a program is paused, Locals, Watches, Call Stack and Breakpoints."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade import menus
from readymade.controls import REGISTRY
from readymade.ide import options

MONO = options.CODE_FONT  # code and output: Tools > Options chooses it


class Toolbox(ttk.Frame):
    """Pick a control type to draw. Double-click one to drop it on the form."""

    def __init__(self, master, on_double_click):
        super().__init__(master, padding=4)
        ttk.Label(self, text="Toolbox").pack(anchor="w", pady=(0, 4))
        self._var = tk.StringVar(value="")
        self._on_double_click = on_double_click
        self._pending_drop = ""
        self._usual = {}  # button -> its colors before a theme changed them
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

    def apply_chrome(self, chrome):
        """Color the tool buttons (plain Tk widgets) for a theme; None: their usual colors."""
        for button in self.winfo_children():
            if not isinstance(button, tk.Radiobutton):
                continue
            if button not in self._usual:
                self._usual[button] = {key: button.cget(key) for key in
                                       ("background", "foreground", "selectcolor", "activebackground",
                                        "activeforeground", "highlightbackground")}
            colors = self._usual[button] if chrome is None else {
                "background": chrome.button, "foreground": chrome.text, "selectcolor": chrome.field,
                "activebackground": chrome.button_active, "activeforeground": chrome.text,
                "highlightbackground": chrome.window}
            button.configure(**colors)

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

    def apply_chrome(self, chrome):
        """The rows' scrolling area is a plain Tk canvas: give it the panel's color."""
        self._scroller.configure(background=ttk.Style(self).lookup("TFrame", "background"))

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
        # A frame left with no rows keeps its old size rather than shrinking, so say how big it is now.
        self.grid_frame.configure(width=1, height=1)
        self._fit_rows()
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

    def renamed(self, old, new):
        """A control was renamed (by this panel or not): its rows now belong to the new name,
        or a new control given the old name would later get their values."""
        if self.current == old:
            self.current = new
            self.objects.set(new)

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
        text = tk.Text(dialog, width=32, height=10, font=options.ensure_code_font(dialog), undo=True)
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
        options.ensure_code_font(self)
        self.output = tk.Text(body, height=8, font=MONO, state=tk.DISABLED, wrap="word", highlightthickness=0)
        scroll = ttk.Scrollbar(body, command=self.output.yview)
        self.output.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.output.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        prompt = ttk.Frame(self)
        prompt.pack(fill=tk.X, pady=(2, 0))
        self.prompt = ttk.Label(prompt, text=">>>", font=MONO)  # "input:" while the program waits for input()
        self.prompt.pack(side=tk.LEFT)
        self.entry = ttk.Entry(prompt, font=MONO)
        self.entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(4, 0))
        self.entry.bind("<Return>", self._submit)
        self.entry.bind("<Up>", lambda e: self._recall(-1))
        self.entry.bind("<Down>", lambda e: self._recall(1))

    def apply_theme(self, theme):
        self.output.configure(background=theme.background, foreground=theme.foreground,
                              insertbackground=theme.cursor, selectbackground=theme.selection)

    def ask_for_input(self):
        """The program is waiting for input(): the next line answers it."""
        self.prompt.configure(text="input:")
        self.entry.focus_set()

    def input_done(self):
        self.prompt.configure(text=">>>")

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


class ProblemsPanel(ttk.Frame):
    """Every problem the lint tools find in the project, open files or not. Click one
    (or press Enter) to go to it; on_open(path, line, column) does the going."""

    def __init__(self, master, on_open):
        super().__init__(master, padding=(4, 2))
        self._on_open = on_open
        self.status = ttk.Label(self, style="Note.TLabel")
        self.status.pack(anchor="w")
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.tree = ttk.Treeview(body, columns=("file", "line", "problem"), show="headings", height=6,
                                 selectmode="browse", style="Problems.Treeview")
        for column, heading, width, stretch in (("file", "File", 140, False), ("line", "Line", 60, False),
                                                ("problem", "Problem", 600, True)):
            self.tree.heading(column, text=heading, anchor="w")
            self.tree.column(column, width=width, stretch=stretch, anchor="w")
        scroll = ttk.Scrollbar(body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._places = {}  # row -> (path, line, column)
        self.tree.bind("<ButtonRelease-1>", lambda e: self._open(self.tree.identify_row(e.y)))
        self.tree.bind("<Return>", lambda e: self._open(self.tree.focus()))

    def apply_theme(self, theme):
        style = ttk.Style(self)
        style.configure("Problems.Treeview", background=theme.background, fieldbackground=theme.background,
                        foreground=theme.foreground)
        style.map("Problems.Treeview", background=[("selected", theme.selection)],
                  foreground=[("selected", theme.foreground)])

    def show(self, problems, checking=False, linting=True):
        """Show [(path, lint.Problem)]. checking: more results are on their way; linting:
        whether any tools are chosen."""
        self.tree.delete(*self.tree.get_children())
        self._places = {}
        for path, problem in problems:
            row = self.tree.insert("", tk.END, values=(path.name, problem.line, f"{problem.message}  ({problem.tool})"))
            self._places[row] = (path, problem.line, problem.column)
        if not linting:
            status = "Linting is off: choose tools in Project > Linting..."
        elif checking:
            status = "Checking..."
        elif problems:
            files = len({path for path, _ in problems})
            status = f"{len(problems)} problem{'s' * (len(problems) != 1)} in {files} file{'s' * (files != 1)}"
        else:
            status = "No problems found."
        self.status.configure(text=status)

    def _open(self, row):
        if row in self._places:
            self._on_open(*self._places[row])
        return "break"


class HelpPanel(ttk.Frame):
    """F1's help: a topic's title, what it is, and its text, with a link to the Python
    documentation when there's a page about it."""

    def __init__(self, master):
        super().__init__(master, padding=(4, 2))
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.title = ttk.Label(top, font=("TkDefaultFont", 11, "bold"))
        self.title.pack(side=tk.LEFT)
        self.subtitle = ttk.Label(top, style="Note.TLabel")
        self.subtitle.pack(side=tk.LEFT, padx=8)
        self.docs = ttk.Button(top, text="Python documentation")
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        options.ensure_code_font(self)
        self.text = tk.Text(body, height=8, font=MONO, wrap="word", state=tk.DISABLED, padx=4, highlightthickness=0)
        scroll = ttk.Scrollbar(body, command=self.text.yview)
        self.text.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self.url = ""

    def apply_theme(self, theme):
        self.text.configure(background=theme.background, foreground=theme.foreground,
                            selectbackground=theme.selection)

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


def _style_tree(widget, style_name, theme):
    style = ttk.Style(widget)
    style.configure(style_name, background=theme.background, fieldbackground=theme.background,
                    foreground=theme.foreground)
    style.map(style_name, background=[("selected", theme.selection)], foreground=[("selected", theme.foreground)])


def _tree(master, columns, style_name, show="headings"):
    body = ttk.Frame(master)
    body.pack(fill=tk.BOTH, expand=True)
    tree = ttk.Treeview(body, columns=[name for name, *_ in columns if name != "#0"], show=show, height=6,
                        selectmode="browse", style=style_name)
    for column, heading, width, stretch in columns:
        tree.heading(column, text=heading, anchor="w")
        tree.column(column, width=width, stretch=stretch, anchor="w")
    scroll = ttk.Scrollbar(body, command=tree.yview)
    tree.configure(yscrollcommand=scroll.set)
    scroll.pack(side=tk.RIGHT, fill=tk.Y)
    tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
    return tree


class LocalsPanel(ttk.Frame):
    """While the program is paused: the variables of the function it's in, with their values
    and types. Objects, lists and dicts open to show their parts; on_expand(path) asks the
    program for them, which answer with add_children(path, items). With on_assign, double-
    click a value (or press F2) to change it: on_assign(path, Python expression)."""

    COLUMNS = (("#0", "Name", 160, False), ("value", "Value", 360, True), ("type", "Type", 100, False))

    def __init__(self, master, on_expand, on_assign=None):
        super().__init__(master, padding=(4, 2))
        self._on_expand = on_expand
        self._on_assign = on_assign
        self.tree = _tree(self, self.COLUMNS, "Debug.Treeview", show="tree headings")
        self._rows = {}  # path (a tuple of names) -> row
        self._paths = {}  # row -> path
        self._opened = set()  # the paths opened, opened again after the next step
        self.value_editor = None  # the box a value is being changed in
        self.tree.bind("<<TreeviewOpen>>", self._open)
        self.tree.bind("<<TreeviewClose>>", lambda e: self._opened.discard(self._paths.get(self.tree.focus())))
        if on_assign is not None:
            self.tree.bind("<Double-Button-1>", self._double_click)
            self.tree.bind("<F2>", lambda e: self.edit_value(self.tree.focus()))

    def apply_theme(self, theme):
        _style_tree(self, "Debug.Treeview", theme)

    def clear(self):
        self._close_editor()
        self.tree.delete(*self.tree.get_children())
        self._rows = {}
        self._paths = {}

    def _double_click(self, e):
        if self.tree.identify_column(e.x) != "#1":
            return None  # (on a name, it opens or closes as usual)
        return self.edit_value(self.tree.identify_row(e.y))

    def edit_value(self, row):
        """Change a value: a box over it takes a Python expression; Enter sets it, Escape doesn't."""
        path = self._paths.get(row)
        box = self.tree.bbox(row, "value") if path else None
        if not box:
            return "break"
        self._close_editor()
        x, y, width, height = box
        old = self.tree.set(row, "value")
        entry = self.value_editor = ttk.Entry(self.tree)
        entry.insert(0, old)
        entry.select_range(0, tk.END)
        entry.place(x=x, y=y, width=width, height=height)
        entry.focus_set()

        def done(commit):
            text = entry.get().strip()
            self._close_editor()
            self.tree.focus_set()
            if commit and text and text != old:
                self._on_assign(list(path), text)
            return "break"

        entry.bind("<Return>", lambda e: done(True))
        entry.bind("<KP_Enter>", lambda e: done(True))
        entry.bind("<Escape>", lambda e: done(False))
        entry.bind("<FocusOut>", lambda e: self._close_editor())
        return "break"

    def _close_editor(self):
        if self.value_editor is not None:
            self.value_editor.destroy()
            self.value_editor = None

    def show(self, variables):
        """Show [{name, value, type, path, expandable}] (see readymade.debugger.value_info)."""
        chosen = self._paths.get(self.tree.focus())
        self.clear()
        for info in variables:
            self._insert("", info)
        if chosen in self._rows:  # the same one stays chosen as values change
            self.tree.focus(self._rows[chosen])
            self.tree.selection_set(self._rows[chosen])

    def add_children(self, path, items):
        row = self._rows.get(tuple(path))
        if row is None:
            return
        self.tree.delete(*self.tree.get_children(row))
        for info in items:
            self._insert(row, info)

    def _insert(self, parent, info):
        path = tuple(info["path"])
        row = self.tree.insert(parent, tk.END, text=info["name"], values=self._values(info))
        self._rows[path] = row
        self._paths[row] = path
        if info["expandable"]:
            self.tree.insert(row, tk.END, text="...", tags=("waiting",))  # so it has an opener
            if path in self._opened:
                self.tree.item(row, open=True)
                self._on_expand(list(path))

    def _values(self, info):
        return info["value"], info["type"]

    def _open(self, _):
        row = self.tree.focus()
        path = self._paths.get(row)
        if path is None:
            return
        self._opened.add(path)
        children = self.tree.get_children(row)
        if len(children) == 1 and "waiting" in self.tree.item(children[0], "tags"):
            self._on_expand(list(path))

    def value_of(self, *path):
        """(value, type) shown for a variable, or one of its parts: for tests."""
        return tuple(self.tree.item(self._rows[path], "values"))


def describe_watch(watch):
    """Where a watch applies and what it does, for the Watches window."""
    where = " in ".join(filter(None, (watch.get("function"), watch.get("file")))) or "anywhere"
    does = {"true": ", breaks when true", "changes": ", breaks when it changes"}.get(watch.get("kind"), "")
    return where + does


class WatchesPanel(LocalsPanel):
    """The watches (see readymade.debugger.Watch), with their values while the program is
    paused. Right-click, Enter or Delete to change them: on_edit(index, or None to add one),
    on_delete(index)."""

    COLUMNS = (("#0", "Expression", 120, False), ("value", "Value", 180, True), ("type", "Type", 70, False),
               ("context", "Context", 150, True))

    def __init__(self, master, on_expand, on_edit, on_delete):
        super().__init__(master, on_expand)
        self._on_edit = on_edit
        self._on_delete = on_delete
        self._watches = []
        self.menu = tk.Menu(self, tearoff=False)
        self.menu.add_command(label="Add Watch...", command=lambda: self._on_edit(None))
        self.menu.add_command(label="Edit Watch...", command=lambda: self._edit(self.index()))
        self.menu.add_command(label="Delete Watch", command=lambda: self._delete(self.index()))
        for sequence in menus.context_clicks(self.tree):
            self.tree.bind(sequence, self._popup)
        self.tree.bind("<Double-Button-1>", lambda e: self._edit(self.index(self.tree.identify_row(e.y))))
        self.tree.bind("<Return>", lambda e: self._edit(self.index()))
        self.tree.bind("<Delete>", lambda e: self._delete(self.index()))

    def show(self, watches, values=None):
        """watches: [{expression, function, file, kind}]; values: what the paused program said
        about them (None while it isn't paused)."""
        self._watches = watches
        if values is None:
            values = [{"name": w["expression"], "value": "", "type": "", "path": ["#watch", i], "expandable": False}
                      for i, w in enumerate(watches)]
        super().show(values)

    def _values(self, info):
        path = info["path"]
        value = f"{info['value']}  ({info['note']})" if info.get("note") else info["value"]  # e.g. as total left it
        if len(path) == 2 and path[0] == "#watch" and path[1] < len(self._watches):
            return value, info["type"], describe_watch(self._watches[path[1]])
        return value, info["type"], ""

    def index(self, row=None):
        """The watch at a row (default: the chosen one), or None."""
        path = self._paths.get(row if row is not None else self.tree.focus())
        return path[1] if path and len(path) >= 2 else None

    def _popup(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self.tree.selection_set(row)
            self.tree.focus(row)
        on = tk.NORMAL if self.index(row) is not None else tk.DISABLED
        self.menu.entryconfigure("Edit Watch...", state=on)
        self.menu.entryconfigure("Delete Watch", state=on)
        self.menu.tk_popup(e.x_root, e.y_root)

    def _edit(self, index):
        if index is not None:
            self._on_edit(index)
        return "break"

    def _delete(self, index):
        if index is not None:
            self._on_delete(index)
        return "break"


class CallStackPanel(ttk.Frame):
    """While the program is paused: the functions it's in, the one it stopped in at the top.
    Choosing one (on_select(index)) shows its place, its variables, and runs Immediate lines there."""

    def __init__(self, master, on_select):
        super().__init__(master, padding=(4, 2))
        self._on_select = on_select
        self.tree = _tree(self, (("function", "Function", 200, False), ("place", "File and line", 400, True)),
                          "Debug.Treeview")
        self._indexes = {}  # row -> index in the stack (outermost first)
        self.tree.bind("<ButtonRelease-1>", lambda e: self._choose(self.tree.identify_row(e.y)))
        self.tree.bind("<Return>", lambda e: self._choose(self.tree.focus()))

    def apply_theme(self, theme):
        _style_tree(self, "Debug.Treeview", theme)

    def clear(self):
        self.tree.delete(*self.tree.get_children())
        self._indexes = {}

    def show(self, stack, selected):
        """stack: [{file, line, function}], outermost first, as the program sends it."""
        self.clear()
        for index in reversed(range(len(stack))):
            frame = stack[index]
            name = frame["file"].replace("\\", "/").rsplit("/", 1)[-1]
            row = self.tree.insert("", tk.END, values=(frame["function"], f"{name}, line {frame['line']}"))
            self._indexes[row] = index
        self.select(selected)

    def select(self, index):
        for row, i in self._indexes.items():
            if i == index:
                self.tree.selection_set(row)
                self.tree.focus(row)

    def _choose(self, row):
        if row in self._indexes:
            self._on_select(self._indexes[row])
        return "break"


def describe_breakpoint(settings):
    """A breakpoint's condition and hit count, for the Breakpoints window."""
    said = [f"when {settings['condition']}"] if settings.get("condition") else []
    hits = settings.get("hits") or 1
    said += {"=": [f"on hit {hits}"], ">=": [f"from hit {hits} on"], "%": [f"every {hits} hits"]}.get(
        settings.get("hit_mode", ""), [])
    if settings.get("log"):
        said.append(f"writes: {settings['log']}")
    return ", ".join(said)


class BreakpointsPanel(ttk.Frame):
    """Every breakpoint in the project. Clicking its dot switches one off and on (it stays,
    hollow and grayed, to switch back on); clicking elsewhere in a row goes to it; Enter or a double-click edits its condition;
    Delete removes it. The callbacks each get (file, line), file relative to the project."""

    ON, OFF = "\u25cf", "\u25cb"  # ● ○, as the line numbers show them

    def __init__(self, master, on_go, on_switch, on_condition, on_remove, on_remove_all):
        super().__init__(master, padding=(4, 2))
        self._on = {"go": on_go, "switch": on_switch, "condition": on_condition, "remove": on_remove}
        self.tree = _tree(self, (("on", "", 30, False), ("file", "File", 110, False), ("line", "Line", 50, False),
                                 ("code", "Code", 240, True), ("when", "Condition", 180, True)), "Debug.Treeview")
        self.tree.column("on", anchor="center")
        self._places = {}  # row -> (file, line)
        self.tree.bind("<ButtonRelease-1>", self._clicked)
        self.tree.bind("<Double-Button-1>", lambda e: self._do("condition", self.tree.identify_row(e.y)))
        self.tree.bind("<Return>", lambda e: self._do("condition", self.tree.focus()))
        self.tree.bind("<Delete>", lambda e: self._do("remove", self.tree.focus()))
        self.tree.bind("<space>", lambda e: self._do("switch", self.tree.focus()))
        self.menu = tk.Menu(self, tearoff=False)
        for label, action in (("Go to Breakpoint", "go"), ("Switch Off or On", "switch"),
                              ("Breakpoint Condition...", "condition"), ("Remove Breakpoint", "remove")):
            self.menu.add_command(label=label, command=lambda a=action: self._do(a, self.tree.focus()))
        self.menu.add_separator()
        self.menu.add_command(label="Remove All Breakpoints", command=on_remove_all)
        for sequence in menus.context_clicks(self.tree):
            self.tree.bind(sequence, self._popup)

    def apply_theme(self, theme):
        _style_tree(self, "Debug.Treeview", theme)
        self.tree.tag_configure("off", foreground=theme.number)

    def show(self, rows):
        """rows: [(file, line, the line's code, settings)], settings as CodeView.breakpoints gives them."""
        chosen = self._places.get(self.tree.focus())
        self.tree.delete(*self.tree.get_children())
        self._places = {}
        for file, line, code, settings in rows:
            off = bool(settings.get("disabled"))
            row = self.tree.insert("", tk.END, values=(self.OFF if off else self.ON, file, line, code,
                                                        describe_breakpoint(settings)), tags=("off",) if off else ())
            self._places[row] = (file, line)
            if (file, line) == chosen:
                self.tree.focus(row)
                self.tree.selection_set(row)

    def _clicked(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self._do("switch" if self.tree.identify_column(e.x) == "#1" else "go", row)

    def _do(self, action, row):
        if row in self._places:
            self._on[action](*self._places[row])
        return "break"

    def _popup(self, e):
        row = self.tree.identify_row(e.y)
        if row:
            self.tree.focus(row)
            self.tree.selection_set(row)
        on = tk.NORMAL if row in self._places else tk.DISABLED
        for index in range(4):
            self.menu.entryconfigure(index, state=on)
        self.menu.tk_popup(e.x_root, e.y_root)
