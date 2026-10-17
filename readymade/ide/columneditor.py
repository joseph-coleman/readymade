"""The DataTable's Columns dialog: each column's definition, chosen rather than typed.

The columns are listed on the left; the chosen one's settings are on the right, those that
fit its kind (decimals for a number, a format for a date, choices for a choice...). Each is
checked as it's typed, as a dict of settings is (ColumnKind.from_dict). OK gives the columns
back as the Properties panel's list does: a line for a simple one, else its dict as JSON.
"""

from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from readymade.controls.datatable import FORMATS, KINDS, ColumnKind
from readymade.ide import helptext
from readymade.ide.dialog import Dialog

# The settings shown for each kind (the others are hidden), beyond those every kind has.
FITS = {
    "text": ("max_length",),
    "number": ("decimals", "min", "max"),
    "money": ("decimals", "min", "max"),
    "date": ("format", "min", "max"),
    "time": ("format", "step", "min", "max"),
    "datetime": ("format", "min", "max"),
    "check": (),
    "choice": ("choices",),
}
FLAGS = ("required", "unique", "key", "readonly", "hidden", "temporary")
_FIELDS = ("name", "header", "kind", "decimals", "format", "step", "max_length", "min", "max", "default")


def _fields_of(kind):
    """A column's definition as the dialog's fields: text for each, a list's lines, flags (a
    setting at its usual value is left empty)."""
    usual_decimals = kind.decimals is None or (kind.kind == "money" and kind.decimals == 2)
    fields = {"name": kind.name, "header": kind.header, "kind": kind.kind,
              "decimals": "" if usual_decimals else str(kind.decimals),
              "format": "" if kind.format == FORMATS.get(kind.kind, kind.format) else kind.format,
              "step": "" if kind.step == 30 else str(kind.step),
              "max_length": "" if kind.max_length is None else str(kind.max_length),
              "choices": "\n".join(kind.choices)}
    for setting in ("min", "max", "default"):
        value = getattr(kind, setting)
        fields[setting] = "" if value is None else kind.text(value)
    for flag in FLAGS:
        fields[flag] = bool(getattr(kind, flag))
    if kind.key:  # (key says required and unique)
        fields["required"] = fields["unique"] = False
    return fields


def definition_of(fields):
    """The fields as a column's definition (a dict), for ColumnKind.from_dict to check."""
    kind = fields["kind"]
    definition = {"name": fields["name"].strip()}
    if fields["header"].strip():
        definition["header"] = fields["header"].strip()
    if kind != "text":
        definition["kind"] = kind
    for setting in ("decimals", "step", "max_length"):
        text = fields[setting].strip()
        if text and setting in FITS[kind]:
            try:
                definition[setting] = int(text)
            except ValueError:
                raise ValueError(f"{definition['name'] or 'the column'}: {setting.replace('_', ' ')} "
                                 f"must be a whole number, not {text!r}") from None
    if fields["format"].strip() and "format" in FITS[kind]:
        definition["format"] = fields["format"].strip()
    if kind == "choice":
        definition["choices"] = [line.strip() for line in fields["choices"].splitlines() if line.strip()]
    for setting in ("min", "max"):
        if fields[setting].strip() and setting in FITS[kind]:
            definition[setting] = fields[setting].strip()
    if fields["default"].strip():
        definition["default"] = fields["default"].strip()
    for flag in FLAGS:
        if fields[flag]:
            definition[flag] = True
    return definition


def line_of(kind):
    """A column as the Properties panel's list has it: a line, or its definition as JSON."""
    return kind.line() or json.dumps(kind.definition())


class ColumnsEditor(Dialog):
    """Edit a DataTable's columns: apply(text) is given them with OK, one per line."""

    def __init__(self, app, title, definitions, apply):
        super().__init__(app, title, resizable=True, padding=8)
        self.withdraw()  # (out of sight while it's made, measured and placed: shown once, not jumping about)
        self.apply = apply
        self.columns = [_fields_of(ColumnKind.of(d)) for d in definitions] or [_fields_of(ColumnKind("Column1"))]
        self._loading = False

        body = self.body
        self.list = ttk.Treeview(body, columns=("name", "kind"), show="headings", selectmode="browse", height=14)
        self.list.heading("name", text="Column")
        self.list.heading("kind", text="Kind")
        self.list.column("name", width=150)
        self.list.column("kind", width=80)
        self.list.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.list.bind("<<TreeviewSelect>>", lambda e: self._load())
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        fields = self.fields = ttk.Frame(body, padding=(8, 0, 0, 0))
        fields.grid(row=0, column=1, rowspan=2, sticky="new")
        self.vars, self.rows = {}, {}
        for row, (setting, label) in enumerate((("name", "Name"), ("header", "Header (shown)"), ("kind", "Kind"),
                                                ("decimals", "Decimal places"), ("format", "Format (empty: usual)"),
                                                ("step", "Minutes between"), ("choices", "Choices (one a line)"),
                                                ("max_length", "Most characters"), ("min", "Least"),
                                                ("max", "Most"), ("default", "Default (new rows)"))):
            text = ttk.Label(fields, text=label)
            text.grid(row=row, column=0, sticky="nw", pady=2, padx=(0, 6))
            if setting == "choices":
                field = self.choices = tk.Text(fields, width=24, height=4, undo=True)
                field.bind("<<Modified>>", lambda e: self._choices_changed())
            else:
                var = self.vars[setting] = tk.StringVar(self)
                if setting == "kind":
                    field = ttk.Combobox(fields, textvariable=var, values=KINDS, state="readonly", width=12)
                elif setting in ("format", "default"):
                    field = ttk.Combobox(fields, textvariable=var, width=26)
                    if setting == "default":
                        self.default_field = field
                    else:
                        self.format_field = field
                else:
                    field = ttk.Entry(fields, textvariable=var, width=28)
                var.trace_add("write", lambda *_, s=setting: self._changed(s))
            field.grid(row=row, column=1, sticky="ew", pady=2)
            self.rows[setting] = (text, field)
        flags = ttk.Frame(fields)
        flags.grid(row=20, column=1, sticky="w", pady=(4, 0))
        for i, flag in enumerate(FLAGS):
            var = self.vars[flag] = tk.BooleanVar(self)
            ttk.Checkbutton(flags, text=flag.capitalize(), variable=var).grid(row=i // 3, column=i % 3, sticky="w",
                                                                              padx=(0, 8))
            var.trace_add("write", lambda *_, s=flag: self._changed(s))
        self.problem = ttk.Label(fields, foreground="#b00020", wraplength=300, justify="left")
        self.problem.grid(row=21, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.note = ttk.Label(fields, style="Note.TLabel", wraplength=300, justify="left",
                              text="A formula or validator (a function) is set in code, in Form_load: "
                                   "self.Items.columns[\"Total\"].formula = lambda row: ...")
        self.note.grid(row=22, column=0, columnspan=2, sticky="w", pady=(6, 0))

        buttons = ttk.Frame(body, padding=(8, 8, 0, 0))
        buttons.grid(row=2, column=0, sticky="w")
        for label, command in (("Add", self.add), ("Delete", self.delete), ("Move Up", lambda: self.move(-1)),
                               ("Move Down", lambda: self.move(1))):
            ttk.Button(buttons, text=label, command=command).pack(side=tk.LEFT, padx=(0, 4))
        self.add_buttons(enter=False, help=lambda: helptext.dialog("columns"))
        self._show_list(0)
        self._steady_size(over=app.root)
        self.deiconify()
        self._grab()

    def _grab(self):
        """The keyboard and mouse to the dialog alone, once it's on the screen (a grab needs it
        to be: on X11 that's a moment after deiconify())."""
        try:
            self.grab_set()
        except tk.TclError:
            if self.winfo_exists():
                self.after(10, self._grab)

    def _steady_size(self, over):
        """As big as the tallest and widest kind's settings need (time's, datetime's), so the
        dialog doesn't jump about as the kind changes (Tk sizes a window to what it holds);
        placed over the middle of over (the IDE's window). Measured while it's hidden."""
        at = self.chosen()
        kind = self.columns[at]["kind"] if at is not None else "text"
        width = height = 0
        said = self.problem.cget("text")
        self.problem.configure(text="A problem said here,\non two lines")  # (room for one)
        for each in KINDS:
            self._fit_to_kind(each)
            self.update_idletasks()
            width, height = max(width, self.winfo_reqwidth()), max(height, self.winfo_reqheight())
        self._fit_to_kind(kind)
        self.problem.configure(text=said)
        self.minsize(width, height)
        x = over.winfo_rootx() + (over.winfo_width() - width) // 2
        y = over.winfo_rooty() + (over.winfo_height() - height) // 3
        self.geometry(f"{width}x{height}+{max(x, 0)}+{max(y, 0)}")

    # ----- the list -----

    def _show_list(self, select=None):
        self.list.delete(*self.list.get_children())
        for i in range(len(self.columns)):
            self.list.insert("", tk.END, iid=str(i), values=self._row_text(i))
        if select is not None and self.columns:
            self.list.selection_set(str(select))
            self.list.see(str(select))
        self._load()

    def _row_text(self, i):
        fields = self.columns[i]
        return (fields["name"] or "(no name)", fields["kind"] + ("  (!)" if self._problem(i) else ""))

    def chosen(self):
        selection = self.list.selection()
        return int(selection[0]) if selection else None

    def add(self):
        """A new text column, after the one chosen."""
        names = {c["name"].lower() for c in self.columns}
        number = len(self.columns) + 1
        while f"column{number}" in names:
            number += 1
        at = (self.chosen() if self.chosen() is not None else len(self.columns) - 1) + 1
        self.columns.insert(at, _fields_of(ColumnKind(f"Column{number}")))
        self._show_list(at)
        self.rows["name"][1].focus_set()
        self.rows["name"][1].select_range(0, tk.END)

    def delete(self):
        at = self.chosen()
        if at is None or len(self.columns) == 1:
            self.bell()  # (a DataTable keeps at least one column)
            return
        del self.columns[at]
        self._show_list(min(at, len(self.columns) - 1))

    def move(self, step):
        at = self.chosen()
        if at is None or not 0 <= at + step < len(self.columns):
            self.bell()
            return
        self.columns[at], self.columns[at + step] = self.columns[at + step], self.columns[at]
        self._show_list(at + step)

    # ----- the chosen column's fields -----

    def _load(self):
        at = self.chosen()
        if at is None:
            return
        fields = self.columns[at]
        self._loading = True
        try:
            for setting in (*_FIELDS, *FLAGS):
                self.vars[setting].set(fields[setting])
            self.choices.delete("1.0", tk.END)
            self.choices.insert("1.0", fields["choices"])
            self.choices.edit_modified(False)
        finally:
            self._loading = False
        self._fit_to_kind()
        self._say_problem()

    def _changed(self, setting):
        at = self.chosen()
        if self._loading or at is None:
            return
        self.columns[at][setting] = self.vars[setting].get()
        if setting == "kind":
            self._fit_to_kind()
        self.list.item(str(at), values=self._row_text(at))
        self._say_problem()

    def _choices_changed(self):
        if not self.choices.edit_modified():
            return
        self.choices.edit_modified(False)
        at = self.chosen()
        if self._loading or at is None:
            return
        self.columns[at]["choices"] = self.choices.get("1.0", "end-1c")
        self._fit_to_kind()  # (the default's choices follow)
        self.list.item(str(at), values=self._row_text(at))
        self._say_problem()

    def _fit_to_kind(self, kind=None):
        """Show the settings that fit the column's kind (or kind), and hide the rest."""
        at = self.chosen()
        if kind is None:
            kind = self.columns[at]["kind"] if at is not None else "text"
        for setting in ("decimals", "format", "step", "choices", "max_length", "min", "max"):
            text, field = self.rows[setting]
            if setting in FITS[kind]:
                text.grid()
                field.grid()
            else:
                text.grid_remove()
                field.grid_remove()
        self.format_field.configure(values={"date": ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%-d %b %Y", "%a %-d %b %Y"),
                                            "time": ("%-I:%M %p", "%H:%M", "%-I:%M:%S %p"),
                                            "datetime": ("%Y-%m-%d %-I:%M %p", "%Y-%m-%d %H:%M",
                                                         "%m/%d/%Y %-I:%M %p")}.get(kind, ()))
        choices = [line.strip() for line in self.columns[at]["choices"].splitlines() if line.strip()] if at is not None else []
        self.default_field.configure(values={"check": ("", "True", "False"), "choice": ("", *choices)}.get(kind, ()))


    # ----- checking -----

    def _problem(self, i):
        """What's wrong with column i's definition, or ""."""
        try:
            ColumnKind.from_dict(definition_of(self.columns[i]))
        except ValueError as e:
            return str(e)
        def called(fields):  # (a column's name, and its header if it has one)
            return {fields["name"].strip().lower(), fields["header"].strip().lower()} - {""}

        mine = called(self.columns[i])
        if any(mine & called(other) for j, other in enumerate(self.columns) if j != i):
            return "Another column has the same name or header"
        return ""

    def _say_problem(self):
        at = self.chosen()
        self.problem.configure(text=self._problem(at) if at is not None else "")

    def ok(self):
        """Check every column, then give them to the DataTable."""
        for i in range(len(self.columns)):
            if self._problem(i):
                self.list.selection_set(str(i))
                self.list.see(str(i))
                self._load()
                self.bell()
                return
        if all(c["hidden"] for c in self.columns):
            self.problem.configure(text="At least one column has to be shown (not hidden)")
            self.bell()
            return
        self.apply("\n".join(line_of(ColumnKind.from_dict(definition_of(c))) for c in self.columns))
        self.destroy()
