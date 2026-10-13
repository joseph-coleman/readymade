"""The Table control: rows of values under typed columns, edited like a spreadsheet.

Its data is rows of Python values, each converted to its column's kind (text, number, check
or a choice). Code reaches it the Pythonic way:

    table.rows                     a list of rows: index, append, insert, del, len, loop
    table[2, "Price"]              a cell (a column by header or number)
    table["Price"]                 a Column: element-wise arithmetic, sum(), mean()...
    table["Total"] = table["Price"] * table["Qty"]

A ttk Treeview shows it, with an editor placed over the cell being edited.
"""

from __future__ import annotations

import csv
import operator
import re
import tkinter as tk
from collections.abc import MutableSequence, Sequence
from dataclasses import dataclass
from pathlib import Path
from tkinter import ttk

from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip
from readymade.controls.trees import _TreeLook

CHECK_MARK = "✓"
_TRUE = {"true", "yes", "y", "1", "x", "on", CHECK_MARK}
_FALSE = {"false", "no", "n", "0", "", "off"}
_WHOLE = re.compile(r"^[+-]?\d+$")


# ----- columns: what each holds -----

@dataclass(frozen=True)
class ColumnKind:
    """One column: its header, its kind of value, and whether the user can edit it. Written
    as a line of the Table's columns: "Price : number 2", "Size : S | M | L", "Total :
    number, readonly"."""

    name: str
    kind: str = "text"  # text, number, check or choice
    decimals: int | None = None  # for a number: the places it keeps (None: as it comes)
    choices: tuple = ()  # for a choice
    readonly: bool = False

    @classmethod
    def parse(cls, line):
        name, _, rest = str(line).partition(":")
        name = name.strip()
        if not name:
            raise ValueError(f"{line!r}: a column needs a header before any ':'")
        parts = [p.strip() for p in rest.split(",")] if rest.strip() else []
        readonly = "readonly" in parts
        kinds = [p for p in parts if p and p != "readonly"]
        if len(kinds) > 1:
            raise ValueError(f"{line!r}: one kind per column (a choice's are separated by |, not commas)")
        spec = kinds[0] if kinds else "text"
        if "|" in spec:
            choices = tuple(c.strip() for c in spec.split("|") if c.strip())
            return cls(name, "choice", choices=choices, readonly=readonly)
        words = spec.split()
        if words[0] == "number" and len(words) <= 2:
            if len(words) == 2 and not words[1].isdigit():
                raise ValueError(f"{line!r}: after number, how many decimal places (number 2)")
            return cls(name, "number", decimals=int(words[1]) if len(words) == 2 else None, readonly=readonly)
        if words in (["text"], ["check"]):
            return cls(name, words[0], readonly=readonly)
        raise ValueError(f"{line!r}: a column's kind is text, number (number 2: with 2 decimal places), check, "
                         "or choices like S | M | L; and maybe readonly")

    def line(self):
        """How it's written in the Table's columns."""
        kind = {"text": "", "check": "check", "choice": " | ".join(self.choices),
                "number": "number" + (f" {self.decimals}" if self.decimals is not None else "")}[self.kind]
        extras = ", ".join(p for p in (kind, "readonly" if self.readonly else "") if p)
        return f"{self.name} : {extras}" if extras else self.name

    def blank(self):
        """An empty cell's value."""
        return {"text": "", "number": 0, "check": False}.get(self.kind, self.choices[0] if self.choices else "")

    def convert(self, value):
        """value as this column holds it; ValueError if it can't be."""
        if self.kind == "text":
            return "" if value is None else str(value)
        if self.kind == "check":
            if isinstance(value, bool) or isinstance(value, (int, float)):
                return bool(value)
            word = "" if value is None else str(value).strip().lower()
            if word in _TRUE or word in _FALSE:
                return word in _TRUE
            raise ValueError(f"{self.name}: {value!r} isn't a tick (True or False)")
        if self.kind == "choice":
            if value is None or value == "":
                return self.blank()
            match = next((c for c in self.choices if c.lower() == str(value).strip().lower()), None)
            if match is None:
                raise ValueError(f"{self.name}: {value!r} isn't one of {', '.join(self.choices)}")
            return match
        return self._number(value)

    def _number(self, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return self.blank()
        if isinstance(value, bool):
            raise ValueError(f"{self.name}: {value!r} isn't a number")
        if isinstance(value, str):
            text = value.strip().replace(",", "")  # (1,234.5)
            try:
                value = int(text) if _WHOLE.match(text) else float(text)
            except ValueError:
                raise ValueError(f"{self.name}: {value!r} isn't a number") from None
        elif not isinstance(value, (int, float)):
            try:
                value = float(value)
            except (TypeError, ValueError):
                raise ValueError(f"{self.name}: {value!r} isn't a number") from None
        return round(float(value), self.decimals) if self.decimals is not None else value

    def show(self, value):
        """How a cell's value is shown."""
        if self.kind == "check":
            return CHECK_MARK if value else ""
        if self.kind == "number" and self.decimals is not None:
            return f"{value:.{self.decimals}f}"
        return str(value)

    def sort_key(self, value):
        if self.kind == "text":
            return str(value).casefold()
        if self.kind == "choice":
            return self.choices.index(value) if value in self.choices else len(self.choices)
        return value


# ----- a column's values, with element-wise arithmetic -----

class Column(Sequence):
    """A column's values (table["Price"]). It's like a list to read (index, len, loop, sum),
    but arithmetic is element-wise, as in numpy: table["Price"] * table["Qty"] multiplies
    each row's pair; table["Price"] * 1.2 each value. Assign one to a column to put it there:
    table["Total"] = table["Price"] * table["Qty"]. (Comparing with == is as lists.)"""

    def __init__(self, values, name=""):
        self._values = list(values)
        self.name = name

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return Column(self._values[index], self.name)
        return self._values[index]

    def __iter__(self):
        return iter(self._values)

    def __eq__(self, other):
        return isinstance(other, (Column, list, tuple)) and list(self) == list(other)

    __hash__ = None

    def __repr__(self):
        return f"Column({self.name!r}, {self._values!r})"

    def tolist(self):
        """Its values, as a list."""
        return list(self._values)

    def _each(self, other, op, reverse=False):
        if isinstance(other, (Column, list, tuple)):
            if len(other) != len(self):
                raise ValueError(f"columns of different lengths: {len(self)} and {len(other)}")
            pairs = zip(self._values, other)
        else:
            pairs = ((value, other) for value in self._values)
        return Column([op(b, a) if reverse else op(a, b) for a, b in pairs], self.name)

    def __add__(self, other):
        return self._each(other, operator.add)

    def __radd__(self, other):
        return self._each(other, operator.add, reverse=True)

    def __sub__(self, other):
        return self._each(other, operator.sub)

    def __rsub__(self, other):
        return self._each(other, operator.sub, reverse=True)

    def __mul__(self, other):
        return self._each(other, operator.mul)

    def __rmul__(self, other):
        return self._each(other, operator.mul, reverse=True)

    def __truediv__(self, other):
        return self._each(other, operator.truediv)

    def __rtruediv__(self, other):
        return self._each(other, operator.truediv, reverse=True)

    def __floordiv__(self, other):
        return self._each(other, operator.floordiv)

    def __mod__(self, other):
        return self._each(other, operator.mod)

    def __pow__(self, other):
        return self._each(other, operator.pow)

    def __neg__(self):
        return Column([-v for v in self._values], self.name)

    def __abs__(self):
        return Column([abs(v) for v in self._values], self.name)

    def __round__(self, places=None):
        return Column([round(v, places) for v in self._values], self.name)

    def sum(self):
        """The values added up."""
        return sum(self._values)

    def mean(self):
        """The average (ValueError for no values)."""
        if not self._values:
            raise ValueError(f"no values to average in {self.name or 'the column'}")
        return sum(self._values) / len(self._values)

    def min(self):
        """The smallest value."""
        return min(self._values)

    def max(self):
        """The largest value."""
        return max(self._values)


# ----- rows: the table's rows as a list -----

class Row(Sequence):
    """One row of a Table (table.rows[2]): its cells, by column number or header. Setting a
    cell changes the table. It's the row at that place: after rows are added or deleted
    above it, it's whichever row is there now."""

    def __init__(self, table, index):
        self._table, self._index = table, index

    def __len__(self):
        return len(self._table._kinds)

    def __getitem__(self, column):
        if isinstance(column, slice):
            return self.tolist()[column]
        return self._table[self._index, column]

    def __setitem__(self, column, value):
        self._table[self._index, column] = value

    def __eq__(self, other):
        return isinstance(other, (Row, list, tuple)) and self.tolist() == list(other)

    __hash__ = None

    def __repr__(self):
        return repr(self.tolist())

    def tolist(self):
        """Its values, as a list."""
        return list(self._table._data[self._index])

    def asdict(self):
        """Its values by header: {"Item": "Apples", "Price": 1.2}."""
        return {kind.name: value for kind, value in zip(self._table._kinds, self._table._data[self._index])}


class Rows(MutableSequence):
    """A Table's rows, as a list: table.rows[2], table.rows[-1], table.rows.append([...]),
    table.rows.insert(0, [...]), del table.rows[3], len(table.rows), for row in table.rows.
    A row given can be a list (in column order; missing cells are blank) or a dict by header."""

    def __init__(self, table):
        self._table = table

    def __len__(self):
        return len(self._table._data)

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [Row(self._table, i) for i in range(*index.indices(len(self)))]
        return Row(self._table, self._table._row_at(index))

    def __setitem__(self, index, values):
        table = self._table
        if isinstance(index, slice):
            table._data[index] = [table._convert_row(v) for v in values]
        else:
            table._data[table._row_at(index)] = table._convert_row(values)
        table._refresh()

    def __delitem__(self, index):
        table = self._table
        if isinstance(index, slice):
            del table._data[index]
        else:
            del table._data[table._row_at(index)]
        table._refresh()

    def insert(self, index, values):
        table = self._table
        table._data.insert(index, table._convert_row(values))
        table._refresh()

    def __eq__(self, other):
        return isinstance(other, (Rows, list, tuple)) and [list(r) for r in self] == [list(r) for r in other]

    __hash__ = None

    def __repr__(self):
        return repr([list(r) for r in self._table._data])


# ----- the control -----

@register
class Table(_TreeLook, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """Rows of values under column headers, edited like a spreadsheet. columns says what each
    column holds, one per line: "Item", "Price : number 2", "In stock : check", "Size : S |
    M | L", "Total : number 2, readonly". Code reaches the data Pythonically:

        self.Stock.rows = [["Apples", 1.2, True, "M"], ["Pears", 0.95, False, "L"]]
        self.Stock[0, "Price"] = 1.25
        self.Stock["Total"] = self.Stock["Price"] * self.Stock["Qty"]

    The user moves a cell cursor with the arrows, Tab and a click; typing replaces a cell,
    and Enter, F2 or a double-click edits it (Enter again saves and moves down; Esc cancels).
    A blank row at the bottom makes new ones (addable); Delete removes the chosen rows
    (deletable); a header click sorts (sortable). cellchange runs after the user changes a
    cell; rowadd when a new row is made (for defaults), rowdelete as one is deleted."""

    type_name = "Table"
    default_size = (320, 200)
    default_event = "cellchange"
    events = (Event("cellchange", ("row", "column")), Event("rowadd", ("row",)),
              Event("rowdelete", ("row", "values")), Event("rowclick", ("row",), policy="latest"),
              Event("dblclick"), *_FOCUS_EVENTS)
    extra_props = {"columns": ["Name", "Amount : number"], "editable": True, "addable": True, "deletable": True,
                   "sortable": True}

    def create_widget(self, parent):
        self._data, self._kinds = [], []
        self._cur = (0, 0)
        self._editor = None
        self._editing = None  # (row, column) being edited
        self._sorted = None  # (column, descending)
        self._raisers = {}  # event -> what on() (or a Name_event method) attached
        self._editable = self._addable = self._deletable = self._sortable = True
        self._enabled = True
        self._fitted = False  # whether the columns have been shared out over its width
        frame = tk.Frame(parent)
        self._tree = ttk.Treeview(frame, show="headings", selectmode="extended", takefocus=1)
        bar = ttk.Scrollbar(frame, command=self._tree.yview,
                            style="Preview.Vertical.TScrollbar" if self.design else "Vertical.TScrollbar")
        self._tree.configure(yscrollcommand=lambda first, last: (bar.set(first, last), self._follow()))
        self._tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._parts = [frame, self._tree, bar]
        # The cell cursor: four thin lines around the cell.
        self._lines = [tk.Frame(self._tree, background="#2f6fd0") for _ in range(4)]
        if not self.design:
            tree = self._tree
            tree.bind("<ButtonPress-1>", self._click, add="+")
            tree.bind("<Double-Button-1>", self._double, add="+")
            tree.bind("<KeyPress>", self._key)
        self._tree.bind("<Configure>", lambda e: (self._fit_columns(), self._follow()), add="+")
        return frame

    def widgets(self):
        return [self._tree]

    def design_widgets(self):
        return list(self._parts)

    def _look_tree(self):
        return self._tree

    def _focus_widget(self):
        return self._tree

    # ----- properties -----

    @property
    def columns(self):
        """The columns, one per line: a header, then maybe ':' and a kind: text (the usual),
        number (number 2: kept to 2 decimal places), check (a tick), or choices like
        S | M | L; and maybe readonly, for one the user can't edit (code still can)."""
        return [kind.line() for kind in self._kinds]

    @columns.setter
    def columns(self, lines):
        kinds = [ColumnKind.parse(line) for line in lines] or [ColumnKind("Column 1")]
        names = [k.name.lower() for k in kinds]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"two columns have the same header: {', '.join(repeated)}")
        old = self._kinds
        self._kinds = kinds
        self._data = [[self._keep(kinds[i], row[i]) if i < len(old) else kinds[i].blank() for i in range(len(kinds))]
                      for row in self._data]
        ids = [f"c{i}" for i in range(len(kinds))]
        self._tree.configure(columns=ids, displaycolumns=ids)
        for i, kind in enumerate(kinds):
            anchor = {"number": "e", "check": "center"}.get(kind.kind, "w")
            self._tree.column(ids[i], anchor=anchor, stretch=True, minwidth=30)
            self._tree.heading(ids[i], text=kind.name, anchor=anchor, command=lambda c=i: self._header_clicked(c))
        self._sorted = None
        self._fitted = False
        self._fit_columns()
        self._refresh()

    @property
    def headers(self):
        """The columns' headers, in order: what a column number names (table.headers[2])."""
        return [kind.name for kind in self._kinds]

    def _fit_columns(self):
        """Share its width out among the columns: when it's first shown, and when they change
        (after that, their widths are the user's, dragged at the headers' edges)."""
        width = self._tree.winfo_width()
        if self._fitted or width <= 1 or not self._kinds:
            return
        for i in range(len(self._kinds)):
            self._tree.column(f"c{i}", width=max(30, width // len(self._kinds)))
        self._fitted = True

    def _unsort(self):
        """New rows: no longer sorted (the headers lose their arrows)."""
        self._sorted = None
        for i, kind in enumerate(self._kinds):
            self._tree.heading(f"c{i}", text=kind.name)

    @staticmethod
    def _keep(kind, value):
        try:
            return kind.convert(value)
        except ValueError:
            return kind.blank()  # (a column that changed kind: what doesn't fit is blank)

    def _switch(name, doc):
        def get(self):
            return getattr(self, "_" + name)

        def set(self, value):
            setattr(self, "_" + name, bool(value))
            if self._ready:
                self._refresh()

        return property(get, set, doc=doc)

    editable = _switch("editable", "Whether the user can change its cells (code always can).")
    addable = _switch("addable", "Whether a blank row at the bottom lets the user make new rows.")
    deletable = _switch("deletable", "Whether the Delete key removes the chosen rows.")
    sortable = _switch("sortable", "Whether a click on a column's header sorts the rows by it (again: the other way).")
    del _switch

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self._tree.state(["!disabled"] if self._enabled else ["disabled"])

    # ----- the data -----

    @property
    def rows(self):
        """Its rows, as a list: rows[2] (a row: its cells by number or header), append,
        insert, del, len, a loop. Set a list of rows (lists, or dicts by header) to replace
        them all."""
        return Rows(self)

    @rows.setter
    def rows(self, rows):
        self._data = [self._convert_row(row) for row in rows]
        self._unsort()
        self._refresh()

    def __getitem__(self, key):
        if isinstance(key, tuple) and len(key) == 2:
            row, column = key
            return self._data[self._row_at(row)][self._column_at(column)]
        if isinstance(key, (str, int)) and not isinstance(key, bool):
            if isinstance(key, int):
                raise TypeError(f"{self.name}[{key}]: a row is {self.name}.rows[{key}]; a column, "
                                f"{self.name}[\"header\"] (or {self.name}[:, {key}] in a later version)")
            column = self._column_at(key)
            return Column([row[column] for row in self._data], self._kinds[column].name)
        raise TypeError(f"{self.name}[...] takes a column's header, or a row and a column: {self.name}[2, \"Price\"]")

    def __setitem__(self, key, value):
        if isinstance(key, tuple) and len(key) == 2:
            row, column = self._row_at(key[0]), self._column_at(key[1])
            self._data[row][column] = self._kinds[column].convert(value)
            self._show_row(row)
            return
        if isinstance(key, str):
            column = self._column_at(key)
            kind = self._kinds[column]
            if isinstance(value, (Column, list, tuple)):
                if len(value) != len(self._data):
                    raise ValueError(f"{len(value)} values for {len(self._data)} rows")
                values = [kind.convert(v) for v in value]
            else:
                values = [kind.convert(value)] * len(self._data)  # one value for every row
            for row, new in zip(self._data, values):
                row[column] = new
            self._refresh()
            return
        raise TypeError(f"{self.name}[...] = takes a column's header, or a row and a column: {self.name}[2, \"Price\"]")

    def _row_at(self, row):
        if isinstance(row, bool) or not isinstance(row, int):
            raise TypeError(f"a row is a number, not {row!r}")
        if not -len(self._data) <= row < len(self._data):
            raise IndexError(f"{self.name} has {len(self._data)} rows, so there's no row {row}")
        return row % len(self._data)

    def _column_at(self, column):
        if isinstance(column, int) and not isinstance(column, bool):
            if not -len(self._kinds) <= column < len(self._kinds):
                raise IndexError(f"{self.name} has {len(self._kinds)} columns, so there's no column {column}")
            return column % len(self._kinds)
        names = [k.name for k in self._kinds]
        if column in names:
            return names.index(column)
        lower = [n.lower() for n in names]
        if str(column).lower() in lower:
            return lower.index(str(column).lower())
        raise KeyError(f"{self.name} has no column {column!r}; its columns: {', '.join(names)}")

    def _convert_row(self, values):
        kinds = self._kinds
        if isinstance(values, Row):
            values = values.tolist()
        if isinstance(values, dict):
            by_name = {}
            for header, value in values.items():
                by_name[self._column_at(header)] = value
            return [kind.convert(by_name.get(i)) if i in by_name else kind.blank() for i, kind in enumerate(kinds)]
        values = list(values)
        if len(values) > len(kinds):
            raise ValueError(f"{len(values)} values for {len(kinds)} columns: {values!r}")
        return [kind.convert(values[i]) if i < len(values) else kind.blank() for i, kind in enumerate(kinds)]

    def load_csv(self, path):
        """Replace the rows with a CSV file's (its first line, the headers, says which column is
        which; columns it hasn't are blank). A path from the program's folder, or a full path."""
        path = self._path(path)
        with open(path, newline="", encoding="utf-8-sig") as file:
            lines = list(csv.reader(file))
        if not lines:
            self.rows = []
            return
        names = [k.name.lower() for k in self._kinds]
        places = {i: names.index(h.strip().lower()) for i, h in enumerate(lines[0]) if h.strip().lower() in names}
        if not places:
            raise ValueError(f"{path.name}: its first line names none of {self.name}'s columns "
                             f"({', '.join(k.name for k in self._kinds)})")
        rows = []
        for number, line in enumerate(lines[1:], start=2):
            row = [kind.blank() for kind in self._kinds]
            for i, text in enumerate(line):
                if i in places:
                    try:
                        row[places[i]] = self._kinds[places[i]].convert(text)
                    except ValueError as e:
                        raise ValueError(f"{path.name}, line {number}: {e}") from None
            rows.append(row)
        self._data = rows
        self._unsort()
        self._refresh()

    def save_csv(self, path):
        """Write the rows to a CSV file, headers first. A path from the program's folder, or a full path."""
        with open(self._path(path), "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([k.name for k in self._kinds])
            for row in self._data:
                writer.writerow([k.show(v) if k.kind == "number" else v for k, v in zip(self._kinds, row)])

    def _path(self, path):
        path = Path(path)
        return path if path.is_absolute() else self.folder / path

    @property
    def current(self):
        """The cell cursor, (row, column). Set it to move it: table.current = (2, "Price")."""
        return self._cur

    @current.setter
    def current(self, cell):
        row, column = cell
        self._move(self._row_at(row), self._column_at(column), by_user=False)

    # ----- showing it -----

    def _new_row(self):
        """Whether the blank row at the bottom is there."""
        return self._addable and self._editable and self._enabled and not self.design

    def _refresh(self):
        tree = self._tree
        tree.delete(*tree.get_children())
        for i, row in enumerate(self._data):
            tree.insert("", "end", iid=str(i), values=self._shown(row), tags=("odd",) if i % 2 else ())
        if self._new_row():
            tree.insert("", "end", iid="new", values=[""] * len(self._kinds), tags=("new",))
        last = len(self._data) if self._new_row() else len(self._data) - 1
        self._cur = (min(self._cur[0], max(last, 0)), min(self._cur[1], max(len(self._kinds) - 1, 0)))
        self._paint_rows()
        self._follow()

    def _shown(self, row):
        return [kind.show(value) for kind, value in zip(self._kinds, row)]

    def _show_row(self, row):
        if self._tree.exists(str(row)):
            self._tree.item(str(row), values=self._shown(self._data[row]))

    def _paint(self):
        super()._paint()
        self._paint_rows()

    def _paint_rows(self):
        if not self._ready:
            return
        bg = self._background() or "#ffffff"
        channels = [int(bg[i:i + 2], 16) for i in (1, 3, 5)] if bg.startswith("#") else [255, 255, 255]
        shade = "#" + "".join(f"{round(c * 0.95):02x}" for c in channels)  # every other row a little darker
        self._tree.tag_configure("odd", background=shade)
        self._tree.tag_configure("new", background=bg)

    def _iid(self, row):
        return "new" if row == len(self._data) else str(row)

    def _follow(self):
        """Put the cell cursor (and an editor) over its cell, wherever scrolling took it."""
        if not self._ready or not self._kinds:
            return
        row, column = self._editing or self._cur
        iid = self._iid(row)
        box = self._tree.bbox(iid, f"c{column}") if self._tree.exists(iid) else ""
        if not box or self.design:
            for line in self._lines:
                line.place_forget()
            if self._editor is not None:
                self._editor.place_forget()
            return
        x, y, w, h = box
        for line, (lx, ly, lw, lh) in zip(self._lines, ((x, y, w, 2), (x, y + h - 2, w, 2), (x, y, 2, h),
                                                         (x + w - 2, y, 2, h))):
            line.place(x=lx, y=ly, width=lw, height=lh)
            line.lift()
        if self._editor is not None:
            self._editor.place(x=x, y=y, width=w, height=h)
            self._editor.lift()

    # ----- moving the cell cursor -----

    def _last_row(self):
        return len(self._data) if self._new_row() else len(self._data) - 1

    def _move(self, row, column, by_user=True, extend=False, select=True):
        if not self._kinds or self._last_row() < 0:
            return
        row = max(0, min(row, self._last_row()))
        column = max(0, min(column, len(self._kinds) - 1))
        moved_row = row != self._cur[0]
        self._cur = (row, column)
        iid = self._iid(row)
        if self._tree.exists(iid):
            self._tree.see(iid)
            self._tree.focus(iid)
            if extend:
                self._tree.selection_add(iid)
            elif select:
                self._tree.selection_set(iid)
        self._tree.update_idletasks()
        self._follow()
        if by_user and moved_row and row < len(self._data):
            self._raise("rowclick", row)

    def _click(self, e):
        tree = self._tree
        if tree.identify_region(e.x, e.y) not in ("cell", "tree"):
            return None  # (a header: sorting or resizing)
        if self._editor is not None and not self._finish():
            return "break"
        tree.focus_set()
        iid, column = tree.identify_row(e.y), tree.identify_column(e.x)
        if not iid or not column:
            return None
        row = len(self._data) if iid == "new" else int(iid)
        more = bool(e.state & 0x5)  # (Shift or Ctrl: choosing more rows, which Tk's own click does)
        self._move(row, int(column[1:]) - 1, select=not more)
        return None if more else "break"

    def _double(self, e):
        if self._tree.identify_region(e.x, e.y) == "cell":
            self._edit()

    def _key(self, e):
        if self._editor is not None:
            return None
        key, row, column = e.keysym, *self._cur
        shift = bool(e.state & 0x1)
        ctrl = bool(e.state & 0x4)
        page = max(1, self._tree.winfo_height() // max(1, self._row_height()) - 1)
        moves = {"Up": (row - 1, column), "Down": (row + 1, column), "Left": (row, column - 1),
                 "Right": (row, column + 1), "Home": (0 if ctrl else row, 0),
                 "End": (self._last_row() if ctrl else row, len(self._kinds) - 1),
                 "Prior": (row - page, column), "Next": (row + page, column)}
        if key in moves:
            self._move(*moves[key], extend=shift and key in ("Up", "Down", "Prior", "Next"))
            return "break"
        if key in ("Tab", "ISO_Left_Tab"):
            return self._tab(-1 if shift or key == "ISO_Left_Tab" else 1)
        if key in ("Return", "KP_Enter", "F2"):
            self._edit()
            return "break"
        if key == "Delete":
            self._delete_chosen()
            return "break"
        if key == "space" and self._kinds[column].kind == "check":
            self._edit()
            return "break"
        if e.char and e.char.isprintable() and not e.state & (0x4 | 0x8):  # (not Ctrl or Alt shortcuts)
            self._edit(typed=e.char)
            return "break"
        return None

    def _row_height(self):
        box = self._tree.bbox(self._tree.get_children()[0]) if self._tree.get_children() else ""
        return box[3] if box else 20

    def _tab(self, step):
        """Tab: the next cell, on to the next row; from the last cell, out of the table."""
        row, column = self._cur
        column += step
        if column >= len(self._kinds):
            row, column = row + 1, 0
        elif column < 0:
            row, column = row - 1, len(self._kinds) - 1
        if not 0 <= row <= self._last_row():
            return None  # (the form's Tab: the next control)
        self._move(row, column)
        return "break"

    # ----- editing -----

    def _can_edit(self, column):
        return self._editable and self._enabled and not self._kinds[column].readonly

    def _edit(self, typed=None):
        """Edit the cell under the cursor: typed replaces it; otherwise what's there is kept."""
        row, column = self._cur
        if not self._kinds or not self._can_edit(column) or row > self._last_row():
            self._tree.bell()
            return
        kind = self._kinds[column]
        current = self._data[row][column] if row < len(self._data) else kind.blank()
        if kind.kind == "check":
            self._store(row, column, not current)
            return
        if kind.kind == "choice":
            editor = ttk.Combobox(self._tree, values=kind.choices, state="readonly")
            start = current
            if typed:
                start = next((c for c in kind.choices if c.lower().startswith(typed.lower())), current)
            editor.set(start)
            editor.bind("<<ComboboxSelected>>", lambda e: self._finish(), add="+")
        else:
            editor = ttk.Entry(self._tree)
            editor.insert(0, typed if typed is not None else kind.show(current) if row < len(self._data) else "")
            editor.icursor("end")
        style_font = ttk.Style(self._tree).lookup(self._tree.cget("style") or "Treeview", "font")
        if style_font:
            try:
                editor.configure(font=style_font)
            except tk.TclError:
                pass
        self._editor, self._editing = editor, (row, column)
        for sequence, action in (("<Return>", lambda: self._finish(1, 0)), ("<KP_Enter>", lambda: self._finish(1, 0)),
                                 ("<Tab>", lambda: self._finish(0, 1)), ("<Escape>", self._cancel)):
            editor.bind(sequence, lambda e, a=action: (a(), "break")[1])
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            editor.bind(sequence, lambda e: (self._finish(0, -1), "break")[1])
        for sequence, step in (("<Up>", -1), ("<Down>", 1)):
            if kind.kind != "choice":  # (in a choice's list, the arrows choose)
                editor.bind(sequence, lambda e, s=step: (self._finish(s, 0), "break")[1])
        editor.bind("<FocusOut>", lambda e: self.widget.after_idle(self._focus_left), add="+")
        self._follow()
        editor.focus_set()
        if kind.kind == "choice" and typed is None:
            editor.after_idle(lambda: editor.winfo_exists() and editor.event_generate("<Down>"))  # (its list opens)

    def _focus_left(self):
        """The editor lost the keyboard (a click elsewhere): keep what's typed, if it fits."""
        if self._editor is None:
            return
        try:
            focus = self._tree.focus_get()
        except (KeyError, tk.TclError):
            focus = None
        if focus is self._editor or str(focus).startswith(str(self._editor)):
            return  # (a choice's own list)
        if not self._finish():
            self._cancel()

    def _finish(self, down=0, across=0):
        """Save the edit (True), then move the cursor; False if what's typed doesn't fit."""
        if self._editor is None:
            return True
        row, column = self._editing
        text = self._editor.get()
        kind = self._kinds[column]
        if row == len(self._data) and not text.strip():
            self._cancel()  # (nothing typed in the new row: no row made)
        else:
            try:
                value = kind.convert(text)
            except ValueError:
                self._tree.bell()
                return False
            self._close_editor()
            self._store(row, column, value)
        if down or across:
            if across:
                self._tab(across)
            else:
                self._move(self._cur[0] + down, self._cur[1])
        return True

    def _cancel(self):
        self._close_editor()

    def _close_editor(self):
        if self._editor is not None:
            self._editor.destroy()
        self._editor = self._editing = None
        self._tree.focus_set()
        self._follow()

    def _store(self, row, column, value):
        """The user's change to a cell (on the new row: a new row first)."""
        if row == len(self._data):
            self._data.append([kind.blank() for kind in self._kinds])
            self._refresh()
            self._raise("rowadd", row)
        if self._data[row][column] != value:
            self._data[row][column] = value
            self._show_row(row)
            self._raise("cellchange", row, column)

    # ----- deleting and sorting -----

    def _delete_chosen(self):
        if not (self._deletable and self._editable and self._enabled):
            self._tree.bell()
            return
        chosen = sorted({int(i) for i in self._tree.selection() if i != "new"} or
                        ({self._cur[0]} if self._cur[0] < len(self._data) else set()), reverse=True)
        for row in chosen:
            values = self._data.pop(row)
            self._raise("rowdelete", row, values)
        self._refresh()

    def _header_clicked(self, column):
        if self.design or not self._sortable or self._editor is not None:
            return
        again = self._sorted is not None and self._sorted[0] == column
        self.sort(column, descending=again and not self._sorted[1])

    def sort(self, column, descending=False):
        """Sort the rows by a column (its header or number); the header shows ▲ or ▼."""
        column = self._column_at(column)
        kind = self._kinds[column]
        self._data.sort(key=lambda row: kind.sort_key(row[column]), reverse=bool(descending))
        self._sorted = (column, bool(descending))
        for i, k in enumerate(self._kinds):
            mark = (" ▼" if descending else " ▲") if i == column else ""
            self._tree.heading(f"c{i}", text=k.name + mark)
        self._refresh()

    # ----- events -----

    def _raise(self, event, *args):
        raiser = self._raisers.get(event)
        if raiser is not None:
            raiser(*args)

    def bind_event(self, event, handler):
        if event in ("cellchange", "rowadd", "rowdelete", "rowclick"):
            self._raisers[event] = handler
        elif event == "dblclick":
            self._tree.bind("<Double-Button-1>", lambda e: self._tree.identify_row(e.y) and handler(), add="+")
        else:
            super().bind_event(event, handler)
