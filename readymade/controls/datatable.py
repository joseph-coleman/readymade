"""The DataTable control: rows of values under typed columns, edited like a spreadsheet.

It's a database table rather than a spreadsheet: each column holds one kind of value (text,
number, check or a choice), and every row's cell in that column is that kind. Its data is
rows of Python values, each converted to its column's kind; a new row starts with each
column's blank value (empty text, 0, no tick, the first choice). Code reaches it the
Pythonic way:

    table.rows                     a list of rows: index, append, insert, del, len, loop
    table[2, "Price"]              a cell (a column by header or number)
    table["Price"]                 a Column: element-wise arithmetic, sum(), mean()...
    table["Total"] = table["Price"] * table["Qty"]
    table[1:4, "Price":"Total"]    a Block of cells, as numpy slices (a header ends it, included)
    table[table["Qty"] > 0, :]     the rows where a condition holds

A ttk Treeview shows it, with an editor placed over the cell being edited.
"""

from __future__ import annotations

import csv
import datetime
import io
from contextlib import contextmanager
import operator
import re
import tkinter as tk
from collections.abc import MutableSequence, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tkinter import font as tkfont
from tkinter import messagebox, ttk

from readymade import keys
from readymade.appearance import CHECK_MARK, check_color
from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.dates import (DATETIME_FORMAT, ISO, TIME_FORMAT, DropMonth, DropTimes, _check_format,
                                     read_date, read_datetime, read_time, show, to_date, to_datetime, to_time)
from readymade.controls.traits import Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip
from readymade.controls.trees import _TreeLook
from readymade.menus import primary_mask

_PRIMARY = primary_mask()  # Ctrl in a Tk event's state (⌘ on a Mac), as in Ctrl+click
PADDING = 16  # a column's room around its text, in pixels
NARROWEST = 30  # (a column's least width)
ENTER_MOVES = ("down", "right", "left", "up", "stay")  # where Enter after an edit takes the cursor
_ENTER_STEPS = {"down": (1, 0), "right": (0, 1), "left": (0, -1), "up": (-1, 0), "stay": (0, 0)}
UNDO_STEPS = 100  # how many of the user's changes Ctrl+Z can take back
CURSOR_COLOR = "#2f6fd0"  # (the cell cursor, if the theme has no highlight color)
_TRUE = {"true", "yes", "y", "1", "x", "on", "\u2713"}  # (and a check mark, as Windows and macOS show a tick)
_FALSE = {"false", "no", "n", "0", "", "off"}
_WHOLE = re.compile(r"^[+-]?\d+$")
_CURRENCY = "$\u20ac\u00a3\u00a5 "  # (what a pasted amount may have around it: $ € £ ¥)


# ----- columns: what each holds -----

@dataclass(frozen=True)
class ColumnKind:
    """One column: its header, its kind of value, and whether the user can edit it. Written
    as a line of the DataTable's columns: "Price : number 2", "Size : S | M | L", "Total :
    money, readonly"."""

    name: str
    kind: str = "text"  # text, number, money, date, time, datetime, check or choice
    decimals: int | None = None  # for a number: the places it keeps (None: as it comes); money's (2)
    choices: tuple = ()  # for a choice
    readonly: bool = False
    format: str = ISO  # for a date, time or datetime: how it shows (strftime's codes)

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
        if words[0] == "money" and len(words) <= 2:
            if len(words) == 2 and not words[1].isdigit():
                raise ValueError(f"{line!r}: after money, how many decimal places (money 0, for yen)")
            return cls(name, "money", decimals=int(words[1]) if len(words) == 2 else 2, readonly=readonly)
        if words[0] in _WHEN_FORMATS:
            format = _check_format(spec[len(words[0]):].strip() or _WHEN_FORMATS[words[0]])
            return cls(name, words[0], format=format, readonly=readonly)
        if words in (["text"], ["check"]):
            return cls(name, words[0], readonly=readonly)
        raise ValueError(f"{line!r}: a column's kind is text, number (number 2: with 2 decimal places), money, "
                         "date (date %m/%d/%Y: shown so), time, datetime, check, or choices like S | M | L; "
                         "and maybe readonly")

    def line(self):
        """How it's written in the DataTable's columns."""
        kind = {"text": "", "check": "check", "choice": " | ".join(self.choices),
                "number": "number" + (f" {self.decimals}" if self.decimals is not None else ""),
                "money": "money" + (f" {self.decimals}" if self.decimals != 2 else ""),
                **{when: when + (f" {self.format}" if self.format != usual else "")
                   for when, usual in _WHEN_FORMATS.items()}}[self.kind]
        extras = ", ".join(p for p in (kind, "readonly" if self.readonly else "") if p)
        return f"{self.name} : {extras}" if extras else self.name

    def blank(self):
        """An empty cell's value."""
        if self.kind == "money":
            return Decimal(0).quantize(self._cents())
        if self.kind in _WHEN_FORMATS:
            return None  # (a date or time has no zero: an empty one is None, as a database's NULL)
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
        if self.kind == "money":
            return self._money(value)
        if self.kind in _WHEN_FORMATS:
            reading, making = {"date": (read_date, to_date), "time": (read_time, to_time),
                               "datetime": (read_datetime, to_datetime)}[self.kind]
            if isinstance(value, str) and value.strip():
                return reading(value, self.format, self.name)
            if isinstance(value, bool) or (self.kind == "date" and isinstance(value, datetime.time)):
                raise ValueError(f"{self.name}: {value!r} isn't a {_WHAT[self.kind]}")
            try:
                return making(value, self.name)
            except (ValueError, TypeError):
                raise ValueError(f"{self.name}: {value!r} isn't a {_WHAT[self.kind]}") from None
        return self._number(value)

    def _cents(self):
        return Decimal(1).scaleb(-self.decimals)  # (0.01, for 2 places)

    def _money(self, value):
        """An amount as a Decimal, rounded to its places (a half up, as on a receipt): a float's
        own digits (1.1 is 1.10, not 1.100000000000000088817841970012523233890533447265625)."""
        if value is None or (isinstance(value, str) and not value.strip()):
            return self.blank()
        if isinstance(value, bool):
            raise ValueError(f"{self.name}: {value!r} isn't a number")
        if isinstance(value, float):
            value = repr(value)
        try:
            amount = Decimal(str(value).strip().strip(_CURRENCY).replace(",", ""))  # ($1,234.50)
        except InvalidOperation:
            raise ValueError(f"{self.name}: {value!r} isn't a number") from None
        if not amount.is_finite():
            raise ValueError(f"{self.name}: {value!r} isn't a number")
        return amount.quantize(self._cents(), rounding=ROUND_HALF_UP)

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
                value = float(value)  # (a Decimal, from a money column)
            except (TypeError, ValueError):
                raise ValueError(f"{self.name}: {value!r} isn't a number") from None
        return round(float(value), self.decimals) if self.decimals is not None else value

    def show(self, value):
        """How a cell's value is shown."""
        if self.kind == "check":
            return CHECK_MARK if value else ""
        if self.kind == "number" and self.decimals is not None:
            return f"{value:.{self.decimals}f}"
        if self.kind == "money":
            return f"{value:,.{self.decimals}f}"  # (1,234.50)
        if self.kind in _WHEN_FORMATS:
            return show(value, self.format) if value is not None else ""
        return str(value)

    def text(self, value):
        """A value as text for a CSV file or the clipboard: numbers with their decimals (money
        without its thousands' commas), a check as True or False (which convert() reads back)."""
        if self.kind == "money":
            return f"{value:.{self.decimals}f}"
        if self.kind in _WHEN_FORMATS:  # (ISO's form, whatever's shown: 2026-10-14, 21:30, 2026-10-14 21:30)
            if value is None:
                return ""
            if self.kind == "date":
                return value.isoformat()
            spec = "seconds" if value.second else "minutes"
            return value.isoformat(timespec=spec) if self.kind == "time" else value.isoformat(" ", spec)
        if self.kind == "number":
            return self.show(value)
        return str(bool(value)) if self.kind == "check" else str(value)

    def sort_key(self, value):
        if self.kind == "text":
            return str(value).casefold()
        if self.kind == "choice":
            return self.choices.index(value) if value in self.choices else len(self.choices)
        if self.kind in _WHEN_FORMATS:  # (empty ones last)
            return (value is None, value if value is not None else _EARLIEST[self.kind])
        return value


_WHEN_FORMATS = {"date": ISO, "time": TIME_FORMAT, "datetime": DATETIME_FORMAT}  # each kind's usual format
_WHAT = {"date": "date", "time": "time", "datetime": "date and time"}
_EARLIEST = {"date": datetime.date.min, "time": datetime.time.min, "datetime": datetime.datetime.min}


def _known(op):
    """A comparison where an empty value (None: a date not given) is neither more nor less than
    anything: False, as a database's NULL is in a condition."""
    def run(a, b):
        return False if a is None or b is None else op(a, b)
    return run


def _mixed(op):
    """op, able to take a float with money: Python won't mix a Decimal with a float, so the
    float becomes a Decimal of its own digits (price * 1.1 is price * Decimal("1.1"))."""
    def run(a, b):
        if isinstance(a, Decimal) and isinstance(b, float):
            b = Decimal(repr(b))
        elif isinstance(b, Decimal) and isinstance(a, float):
            a = Decimal(repr(a))
        return op(a, b)
    return run


def _shared(total, least):
    """Widths for columns sharing total out evenly, none less than its least: those that need
    more than an even share get their least, and the others share what's left. If even the
    least don't fit, the least (and the table scrolls sideways)."""
    wide = set()
    while True:
        rest = [i for i in range(len(least)) if i not in wide]
        if not rest:
            return list(least)
        share = (total - sum(least[i] for i in wide)) // len(rest)
        more = {i for i in rest if least[i] > share}
        if not more:
            return [least[i] if i in wide else share for i in range(len(least))]
        wide |= more


# ----- choosing some: by number, slice, list of numbers, or a condition -----

def _pick(key, count, name, what="rows"):
    """Which of count things key chooses, as numpy does: (their numbers, whether key named just
    one). key is a number, a slice, a list of numbers, or a condition: a Column (or list) of
    True/False, one for each."""
    if isinstance(key, int) and not isinstance(key, bool):
        if not -count <= key < count:
            raise IndexError(f"{name} has {count} {what}, so there's no {what[:-1]} {key}")
        return [key % count], True
    if isinstance(key, slice):
        return list(range(*key.indices(count))), False
    if isinstance(key, _SEQUENCES):
        keys = list(key)
        if keys and all(isinstance(k, bool) for k in keys):
            if len(keys) != count:
                raise ValueError(f"a condition of {len(keys)} True/False for {name}'s {count} {what}")
            return [i for i, chosen in enumerate(keys) if chosen], False
        for k in keys:
            if isinstance(k, bool) or not isinstance(k, int):
                raise TypeError(f"a list of {what} is of their numbers (or all True/False), not {k!r}")
        return [_pick(k, count, name, what)[0][0] for k in keys], False
    raise TypeError(f"{what} are chosen by a number, a slice, a list of numbers or a condition, not {key!r}")


# ----- a column's values, with element-wise arithmetic -----

class Column(Sequence):
    """A column's values (table["Price"]). It's like a list to read (index, len, loop, sum),
    but arithmetic is element-wise, as in numpy: table["Price"] * table["Qty"] multiplies
    each row's pair; table["Price"] * 1.2 each value. Assign one to a column to put it there:
    table["Total"] = table["Price"] * table["Qty"].

    Comparing with < <= > >= is element-wise too, giving a Column of True/False: a condition,
    to choose rows with (table[table["Qty"] > 0, :]) or values (column[column > 0]). Combine
    conditions with & | ~ (and, or, not). == compares whole columns, as lists do; for each
    value, column.eq("Garden"), column.ne(0) and column.isin(["S", "M"]) (one of them). A
    Column isn't True or False itself (if column > 20: is an error, as in numpy): ask
    column.any() or column.all()."""

    def __init__(self, values, name=""):
        self._values = list(values)
        self.name = name

    def __len__(self):
        return len(self._values)

    def __getitem__(self, index):
        if isinstance(index, (slice, *_SEQUENCES)):
            chosen, _ = _pick(index, len(self), self.name or "the column", "values")
            return Column([self._values[i] for i in chosen], self.name)
        return self._values[index]

    def __iter__(self):
        return iter(self._values)

    def __eq__(self, other):
        return isinstance(other, (Column, list, tuple)) and list(self) == list(other)

    def __bool__(self):
        raise TypeError(f"a Column ({self.name or 'its values'}) isn't True or False: ask column.any() "
                        f"(any true?) or column.all() (all true?), or len(column) for whether it has "
                        f"values; combine conditions with & | ~, not and, or, not")

    def any(self):
        """Whether any value is true: (table["Qty"] > 10).any()."""
        return any(self._values)

    def all(self):
        """Whether every value is true (True for no values)."""
        return all(self._values)

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
        op = _mixed(op)
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

    def __lt__(self, other):
        return self._each(other, _known(operator.lt))

    def __le__(self, other):
        return self._each(other, _known(operator.le))

    def __gt__(self, other):
        return self._each(other, _known(operator.gt))

    def __ge__(self, other):
        return self._each(other, _known(operator.ge))

    def eq(self, other):
        """Whether each value equals other (a value, or a column's values, row by row): a
        Column of True/False. (== compares the whole column.)"""
        return self._each(other, operator.eq)

    def ne(self, other):
        """Whether each value differs from other: a Column of True/False."""
        return self._each(other, operator.ne)

    def isin(self, values):
        """Whether each value is one of values: a Column of True/False, a condition.
        table[table["Size"].isin(["S", "M"]), "Item"]."""
        values = list(values) if not isinstance(values, (str, bytes)) else [values]
        return Column([value in values for value in self._values], self.name)

    def __and__(self, other):
        return self._each(other, lambda a, b: bool(a and b))

    __rand__ = __and__

    def __or__(self, other):
        return self._each(other, lambda a, b: bool(a or b))

    __ror__ = __or__

    def __invert__(self):
        return Column([not v for v in self._values], self.name)

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


# ----- a block: several rows of several columns -----

class Block(Sequence):
    """Some rows of some columns, copied from a DataTable: table[1:4, "Price":"Total"],
    table[:, ["Item", "Total"]]. It loops as rows (lists of values), block[2] is a row,
    block["Price"] a Column, and arithmetic works on every cell, as numpy's does: block * 1.1,
    or block + other_block (the same shape), cell by cell. Put one back in the table with
    table[...] = block."""

    def __init__(self, rows, headers):
        self.headers = list(headers)
        self._rows = [list(row) for row in rows]
        for row in self._rows:
            if len(row) != len(self.headers):
                raise ValueError(f"a row of {len(row)} values for {len(self.headers)} headers: {row!r}")

    @property
    def shape(self):
        """(rows, columns), as numpy has it."""
        return len(self._rows), len(self.headers)

    def __len__(self):
        return len(self._rows)

    def __getitem__(self, key):
        if isinstance(key, str):
            lower = [h.lower() for h in self.headers]
            if key in self.headers:
                column = self.headers.index(key)
            elif key.lower() in lower:
                column = lower.index(key.lower())
            else:
                raise KeyError(f"the block has no column {key!r}; its columns: {', '.join(self.headers)}")
            return Column([row[column] for row in self._rows], self.headers[column])
        if isinstance(key, slice):
            return Block(self._rows[key], self.headers)
        return list(self._rows[key])

    def __iter__(self):
        return (list(row) for row in self._rows)

    def __eq__(self, other):
        return isinstance(other, (Block, *_SEQUENCES)) and self.tolist() == [list(row) for row in other]

    __hash__ = None

    def __repr__(self):
        return f"Block({self.headers!r}, {self._rows!r})"

    def tolist(self):
        """Its rows, as a list of lists."""
        return [list(row) for row in self._rows]

    def _each(self, other, op, reverse=False):
        if isinstance(other, Column):
            raise TypeError("a Block's arithmetic is with a number or a block of the same shape "
                            "(for one column, use block[\"header\"])")
        if isinstance(other, (Block, *_SEQUENCES)):
            others = [list(row) for row in other]
            if [len(row) for row in others] != [len(self.headers)] * len(self._rows):
                raise ValueError(f"blocks of different shapes: {_shape_of(self._rows)} and {_shape_of(others)}")
        else:
            others = [[other] * len(self.headers) for _ in self._rows]
        op = _mixed(op)
        return Block([[op(b, a) if reverse else op(a, b) for a, b in zip(row, more)]
                      for row, more in zip(self._rows, others)], self.headers)

    def _cells(self, change):
        return Block([[change(v) for v in row] for row in self._rows], self.headers)

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
        return self._cells(operator.neg)

    def __abs__(self):
        return self._cells(abs)

    def __round__(self, places=None):
        return self._cells(lambda v: round(v, places))


def _shape_of(rows):
    widths = {len(row) for row in rows}
    return f"{len(rows)} x {widths.pop()}" if len(widths) == 1 else f"{len(rows)} rows of {sorted(widths)} values"


# ----- rows: the table's rows as a list -----

class Row(Sequence):
    """One row of a DataTable (table.rows[2]): its cells, by column number or header. Setting a
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

    @property
    def backcolor(self):
        """The row's background color, "#rrggbb" ("" for the usual). Set from code: rows have no
        colors in the designer. It stays with the row as rows are sorted, added or deleted."""
        return self._table._colors_of(self._index)[0]

    @backcolor.setter
    def backcolor(self, value):
        self._table._color_row(self._index, back=check_color(value))

    @property
    def forecolor(self):
        """The row's text color ("" for the usual), as backcolor."""
        return self._table._colors_of(self._index)[1]

    @forecolor.setter
    def forecolor(self, value):
        self._table._color_row(self._index, fore=check_color(value))

    def asdict(self):
        """Its values by header: {"Item": "Apples", "Price": 1.2}."""
        return {kind.name: value for kind, value in zip(self._table._kinds, self._table._data[self._index])}


class Rows(MutableSequence):
    """A DataTable's rows, as a list: table.rows[2], table.rows[-1], table.rows.append([...]),
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

    def sort(self, key=None, reverse=False):
        """Sort the rows, as a list sorts: key gives what to sort each row by (a Row: by column
        number or header), table.rows.sort(key=lambda row: (row["Category"], -row["Total"]))."""
        table = self._table
        order = list(range(len(table._data)))
        if key is not None:
            keys = [key(Row(table, i)) for i in order]  # (worked out before any row moves)
            order.sort(key=keys.__getitem__, reverse=reverse)
        else:
            order.sort(key=table._data.__getitem__, reverse=reverse)
        table._data[:] = [table._data[i] for i in order]
        table._unsort()
        table._refresh()

    def __eq__(self, other):
        return isinstance(other, (Rows, list, tuple)) and [list(r) for r in self] == [list(r) for r in other]

    __hash__ = None

    def __repr__(self):
        return repr([list(r) for r in self._table._data])


_SEQUENCES = (list, tuple, Column, Row)  # (what holds several values, for _pick and setting cells)


# ----- the control -----

@register
class DataTable(_TreeLook, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A table of data, as a database has: each column holds one kind of value (text, a
    number, money, a tick or a choice) for every row, and a new row starts with each
    column's blank value. The user edits it like a spreadsheet.

    columns says what each column holds, one per line: "Item", "Price : number 2", "In stock :
    check", "Size : S | M | L", "Total : money, readonly". Money is a decimal.Decimal, exact to
    the cent. The blank values: empty text, 0, no tick, the first choice; rowadd can set others
    for a new row. enter_moves says where Enter goes after an edit (down; right, for typing
    along rows). Code reaches the data Pythonically:

        self.Stock.rows = [["Apples", 1.2, True, "M"], ["Pears", 0.95, False, "L"]]
        self.Stock[0, "Price"] = 1.25
        self.Stock["Total"] = self.Stock["Price"] * self.Stock["Qty"]
        self.Stock[1:4, "Price":"Total"]           # a Block, sliced as numpy does
        self.Stock[self.Stock["Qty"] > 0, "Item"]  # the rows where a condition holds

    The user moves a cell cursor with the arrows, Tab and a click; typing replaces a cell,
    and Enter, F2 or a double-click edits it (Enter again saves and moves down; Esc cancels).
    As in a spreadsheet, rows are chosen only on purpose: Shift with an arrow or a click,
    Ctrl+click (⌘ on a Mac), Shift+Space for the cursor's row, Ctrl+A for all; Esc un-chooses.
    Delete removes the chosen rows (deletable), or with none chosen empties the cell. A blank
    row at the bottom makes new ones (addable); a header click sorts (sortable). Ctrl+C,
    Ctrl+X and Ctrl+V copy, cut and paste as spreadsheets do (tab-separated text: to and from
    Excel too): the chosen rows, or else the cell. copy(), cut(), paste() and select_all() do
    the same from code, for an Edit menu. cellvalidate runs before the user's change is kept
    (return False, or a message why, to refuse it); cellchange after; rowadd when a new row is
    made (for defaults); rowdelete as one is deleted; columnclick when a header is clicked
    (after sorting, if sortable: off, it can sort its own way, with sort()'s key).

    Ctrl+Z takes back the user's last change, and Ctrl+Y (or Ctrl+Shift+Z) makes it again: undo()
    and redo() from code, can_undo and can_redo for an Edit menu. A row's backcolor and
    forecolor are set from code (self.Stock.rows[2].backcolor = "#ffe0e0"), and stay with it.

    The columns share its width out (none narrower than its header), and scroll sideways when
    they don't fit. autosize_columns() fits some or all to what they hold, and widths sets
    them; those keep their widths, and the others share what's left."""

    type_name = "DataTable"
    default_size = (320, 200)
    default_event = "cellchange"
    events = (Event("cellchange", ("row", "column")), Event("cellvalidate", ("row", "column", "value")),
              Event("rowadd", ("row",)), Event("rowdelete", ("row", "values")),
              Event("rowclick", ("row",), policy="latest"), Event("columnclick", ("column",)),
              Event("dblclick"), *_FOCUS_EVENTS)
    extra_props = {"columns": ["Name", "Amount : number"], "editable": True, "addable": True, "deletable": True,
                   "sortable": True, "enter_moves": "down"}
    prop_choices = {"enter_moves": ENTER_MOVES}

    def create_widget(self, parent):
        self._data, self._kinds = [], []
        self._cur = (0, 0)
        self._anchor = 0  # where Shift+arrows start choosing rows from
        self._editor = None
        self._editor_box = None  # what's placed over the cell: a text editor's frame (a choice's list is itself)
        self._editing = None  # (row, column) being edited
        self._sorted = None  # (column, descending, key)
        self._telling = False  # a message is up (the editor losing the keyboard to it isn't leaving)
        self._raisers = {}  # event -> what on() (or a Name_event method) attached
        self._editable = self._addable = self._deletable = self._sortable = True
        self._enter_moves = "down"
        self._undone, self._redone = [], []  # steps: lists of ("cell", row, column, old, new), ("add"/"delete", row, index)
        self._recording = None  # the step being recorded (a user's change under way)
        self._row_colors = {}  # id(row) -> (row, backcolor, forecolor)
        self._enabled = True
        self._sized = set()  # the columns whose widths are someone's (dragged, set, autosized); the rest share
        self._choice_keyed = False  # a choice's list was answered with Enter (so: down a row)
        self._noted_enter = None  # the Tcl command that notes it
        frame = tk.Frame(parent)
        self._tree = ttk.Treeview(frame, show="headings", selectmode="extended", takefocus=1)
        look = "Preview." if self.design else ""
        bar = ttk.Scrollbar(frame, command=self._tree.yview, style=f"{look}Vertical.TScrollbar")
        across = ttk.Scrollbar(frame, orient="horizontal", command=self._tree.xview,
                               style=f"{look}Horizontal.TScrollbar")
        self._tree.configure(yscrollcommand=lambda first, last: (bar.set(first, last), self._follow()),
                             xscrollcommand=lambda first, last: self._scrolled_across(across, first, last))
        self._tree.grid(row=0, column=0, sticky="nsew")
        bar.grid(row=0, column=1, sticky="ns")
        across.grid(row=1, column=0, sticky="ew")
        across.grid_remove()  # (shown when the columns are wider than the table)
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._parts = [frame, self._tree, bar, across]
        # The cell cursor: four thin lines around the cell.
        self._lines = [tk.Frame(self._tree, background=CURSOR_COLOR) for _ in range(4)]
        if not self.design:
            tree = self._tree
            tree.bind("<ButtonPress-1>", self._click, add="+")
            tree.bind("<Double-Button-1>", self._double, add="+")
            tree.bind("<B1-Motion>", lambda e: self._follow(), add="+")  # (a header's edge dragged)
            tree.bind("<KeyPress>", self._key)
            # The tree has the keyboard back while an editor is open (Esc in a choice's list):
            # the edit is over.
            tree.bind("<FocusIn>", lambda e: self.widget.after_idle(self._focus_left), add="+")
        self._tree.bind("<Configure>", lambda e: (self._fit_columns(), self._follow()), add="+")
        self._tree.bind("<<TreeviewSelect>>", lambda e: self._follow(), add="+")  # (its color)
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
        self._forget()
        self._data = [[self._keep(kinds[i], row[i]) if i < len(old) else kinds[i].blank() for i in range(len(kinds))]
                      for row in self._data]
        ids = [f"c{i}" for i in range(len(kinds))]
        self._tree.configure(columns=ids, displaycolumns=ids)
        for i, kind in enumerate(kinds):
            anchor = {"number": "e", "money": "e", "check": "center"}.get(kind.kind, "w")  # (dates, times: as text)
            self._tree.column(ids[i], anchor=anchor, stretch=False, minwidth=NARROWEST)
            self._tree.heading(ids[i], text=kind.name, anchor=anchor, command=lambda c=i: self._header_clicked(c))
        self._sorted = None
        self._sized = set()
        self._fit_columns()
        self._refresh()

    @property
    def headers(self):
        """The columns' headers, in order: what a column number names (table.headers[2])."""
        return [kind.name for kind in self._kinds]

    def _fit_columns(self):
        """Share its width out among the columns, none narrower than its header, except those
        whose widths someone set (widths, autosize_columns(), dragging a header's edge): the
        others share what those leave. Columns that don't fit scroll sideways."""
        width = self._tree.winfo_width()
        free = [column for column in range(len(self._kinds)) if column not in self._sized]
        if width <= 1 or not free:
            return
        _, heading = self._fonts()
        taken = sum(int(self._tree.column(f"c{column}", "width")) for column in self._sized)
        least = [self._header_width(heading, self._kinds[column]) for column in free]
        for column, share in zip(free, _shared(width - 6 - taken, least)):  # (inside its border: 2 px a side, or more)
            self._tree.column(f"c{column}", width=share)

    @property
    def widths(self):
        """The columns' widths, in pixels. Set a list (one for each column), or a dict of some
        by header or number: table.widths = {"Item": 160}. A width set (or autosized, or dragged
        at a header's edge) stays as it is when the table's size changes; the other columns
        share what's left."""
        return [int(self._tree.column(f"c{i}", "width")) for i in range(len(self._kinds))]

    @widths.setter
    def widths(self, widths):
        if isinstance(widths, dict):
            chosen = {self._column_at(column): width for column, width in widths.items()}
        else:
            widths = list(widths)
            if len(widths) != len(self._kinds):
                raise ValueError(f"{len(widths)} widths for {len(self._kinds)} columns")
            chosen = dict(enumerate(widths))
        for column, width in chosen.items():
            self._tree.column(f"c{column}", width=max(NARROWEST, int(width)))
        self._sized |= set(chosen)
        self._fit_columns()  # (the others share what's left)
        self._follow()

    def autosize_columns(self, *columns):
        """Fit columns to what they hold (a choice's choices and the header too): every column,
        or those given, by header or number. autosize_columns("Item", "Notes")."""
        chosen = [self._column_at(column) for column in columns] or range(len(self._kinds))
        cell, heading = self._fonts()
        for column in chosen:
            kind = self._kinds[column]
            texts = {kind.show(row[column]) for row in self._data} | set(kind.choices)
            widest = max((cell.measure(text) for text in texts), default=0) + PADDING
            self._tree.column(f"c{column}", width=max(NARROWEST, widest, self._header_width(heading, kind)))
        self._sized |= set(chosen)
        self._fit_columns()  # (the others share what's left)
        self._follow()

    def _fonts(self):
        """The cells' and headers' fonts, for measuring."""
        style, name = ttk.Style(self._tree), self._tree.cget("style") or "Treeview"
        cell = style.lookup(name, "font") or "TkDefaultFont"
        heading = style.lookup(f"{name}.Heading", "font") or "TkHeadingFont"
        return tkfont.Font(root=self._tree, font=cell), tkfont.Font(root=self._tree, font=heading)

    @staticmethod
    def _header_width(heading, kind):
        return heading.measure(kind.name + " \u25b2") + PADDING  # (with room for a sort's arrow)

    def _scrolled_across(self, bar, first, last):
        bar.set(first, last)
        if float(first) <= 0 and float(last) >= 1:
            bar.grid_remove()
        else:
            bar.grid()
        self._follow()

    def _see_column(self, column):
        """Scroll sideways to show a column (a Treeview's see() only scrolls up and down)."""
        widths = self.widths
        total, view = sum(widths), self._tree.winfo_width()
        if total <= view or view <= 1:
            return
        left = sum(widths[:column])
        right = left + widths[column]
        shown = self._tree.xview()[0] * total
        if left < shown:
            self._tree.xview_moveto(left / total)
        elif right > shown + view:
            self._tree.xview_moveto(min(left, right - view) / total)

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
    def enter_moves(self):
        """Where Enter takes the cell cursor after an edit: "down" (the usual), "right" (along
        the row, then on to the next, for typing in rows: "left" for right-to-left ones), "up",
        or "stay"."""
        return self._enter_moves

    @enter_moves.setter
    def enter_moves(self, value):
        if value not in ENTER_MOVES:
            raise ValueError(f"enter_moves must be one of: {', '.join(ENTER_MOVES)}")
        self._enter_moves = value

    def _after_enter(self):
        """Finish the edit (Enter), and move as enter_moves says."""
        return self._finish(*_ENTER_STEPS[self._enter_moves])

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
        self._forget()
        self._unsort()
        self._refresh()

    def __getitem__(self, key):
        rows, columns, one_row, one_column = self._cells(key)
        data = self._data
        if one_row and one_column:
            return data[rows[0]][columns[0]]
        if one_column:
            return Column([data[r][columns[0]] for r in rows], self._kinds[columns[0]].name)
        if one_row:
            return [data[rows[0]][c] for c in columns]
        return Block([[data[r][c] for c in columns] for r in rows], [self._kinds[c].name for c in columns])

    def __setitem__(self, key, value):
        rows, columns, one_row, one_column = self._cells(key)
        if one_row and one_column:
            grid = [[value]]
        elif one_row or one_column:
            count = len(columns) if one_row else len(rows)
            if isinstance(value, _SEQUENCES):
                values = list(value)
                if len(values) != count:
                    raise ValueError(f"{len(values)} values for {count} {'columns' if one_row else 'rows'}")
            else:
                values = [value] * count  # one value for every cell
            grid = [values] if one_row else [[v] for v in values]
        elif isinstance(value, Column):
            raise ValueError(f"a Column fills one column: {self.name}[rows, \"{value.name or 'header'}\"] = ...")
        elif isinstance(value, (Block, *_SEQUENCES)):
            grid = [list(row) if isinstance(row, _SEQUENCES) else [row] for row in value]
            if [len(row) for row in grid] != [len(columns)] * len(rows):
                raise ValueError(f"a block of {_shape_of(grid)} for {len(rows)} rows x {len(columns)} columns")
        else:
            grid = [[value] * len(columns) for _ in rows]  # one value for every cell
        kinds = self._kinds
        converted = [[kinds[c].convert(v) for c, v in zip(columns, line)] for line in grid]  # (all, then change)
        for r, line in zip(rows, converted):
            for c, v in zip(columns, line):
                self._data[r][c] = v
        if one_row and one_column:
            self._show_row(rows[0])
        else:
            self._refresh()

    def _cells(self, key):
        """What table[key] reaches: (row numbers, column numbers, one row?, one column?). key is
        rows, columns as numpy has them, or a column's header (all its rows)."""
        if isinstance(key, str):
            key = (slice(None), key)
        if not (isinstance(key, tuple) and len(key) == 2):
            if isinstance(key, int) and not isinstance(key, bool):
                raise TypeError(f"{self.name}[{key}]: a row is {self.name}.rows[{key}] (or {self.name}[{key}, :], "
                                f"a copy of its values)")
            raise TypeError(f"{self.name}[...] takes a row and a column ({self.name}[2, \"Price\"], "
                            f"{self.name}[1:4, \"Price\":\"Total\"]) or a column's header")
        rows, one_row = _pick(key[0], len(self._data), self.name)
        columns, one_column = self._columns_at(key[1])
        return rows, columns, one_row, one_column

    def _columns_at(self, key):
        """Column numbers from a header or number, a list of them, or a slice of either. A slice
        by headers includes its last one ("Price":"Total"), as there's no header past it to name."""
        count = len(self._kinds)
        if isinstance(key, slice):
            start, stop, step = key.start, key.stop, key.step
            if not isinstance(start, str) and not isinstance(stop, str):
                return list(range(*key.indices(count))), False
            step = 1 if step is None else step
            back = step < 0
            first = (count - 1 if back else 0) if start is None else self._column_at(start)
            if stop is None:
                last = -1 if back else count
            elif isinstance(stop, str):
                last = self._column_at(stop) + (-1 if back else 1)
            else:
                last = stop + count if stop < 0 else min(stop, count)
            return list(range(first, last, step)), False
        if isinstance(key, (list, tuple)):
            return [self._column_at(k) for k in key], False
        return [self._column_at(key)], True

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
        self._forget()
        self._unsort()
        self._refresh()

    def save_csv(self, path):
        """Write the rows to a CSV file, headers first. A path from the program's folder, or a full path."""
        with open(self._path(path), "w", newline="", encoding="utf-8") as file:
            writer = csv.writer(file)
            writer.writerow([k.name for k in self._kinds])
            for row in self._data:
                writer.writerow([k.text(v) for k, v in zip(self._kinds, row)])

    def _path(self, path):
        path = Path(path)
        return path if path.is_absolute() else self.folder / path

    @property
    def current(self):
        """The cell cursor, (row, column). Set it to move it: table.current = (2, "Price"); a
        row of len(table.rows) is the blank row at the bottom (when addable)."""
        return self._cur

    @current.setter
    def current(self, cell):
        row, column = cell
        if not (row == len(self._data) and self._new_row()):  # (that's the blank row at the bottom)
            row = self._row_at(row)
        self._move(row, self._column_at(column), by_user=False, keep=True)

    # ----- showing it -----

    def _new_row(self):
        """Whether the blank row at the bottom is there."""
        return self._addable and self._editable and self._enabled and not self.design

    def _refresh(self):
        tree = self._tree
        chosen, before = tree.selection(), len(tree.get_children())
        tree.delete(*tree.get_children())
        for i, row in enumerate(self._data):
            tree.insert("", "end", iid=str(i), values=self._shown(row), tags=self._row_tags(i, row))
        if self._new_row():
            tree.insert("", "end", iid="new", values=[""] * len(self._kinds), tags=("new",))
        last = len(self._data) if self._new_row() else len(self._data) - 1
        self._cur = (min(self._cur[0], max(last, 0)), min(self._cur[1], max(len(self._kinds) - 1, 0)))
        # The chosen rows stay chosen when only values changed (with rows added or gone, none are).
        here = self._iid(self._cur[0])
        if chosen and len(tree.get_children()) == before:
            tree.selection_set([i for i in chosen if tree.exists(i)])
        if tree.exists(here):
            tree.focus(here)
        self._check_sorted()
        self._paint_rows()
        self._follow()

    def _row_tags(self, i, row):
        """A row's tags: every other one shaded, unless it has a backcolor; its colors, if any."""
        _, back, fore = self._row_colors.get(id(row), (None, "", ""))
        tags = ["odd"] if i % 2 and not back else []
        if back or fore:
            tag = f"color {back} {fore}"
            self._tree.tag_configure(tag, **{option: color for option, color in
                                             (("background", back), ("foreground", fore)) if color})
            tags.append(tag)
        return tuple(tags)

    def _colors_of(self, row):
        _, back, fore = self._row_colors.get(id(self._data[self._row_at(row)]), (None, "", ""))
        return back, fore

    def _color_row(self, row, back=None, fore=None):
        """Color a row (the list itself, kept with it, so its colors go where it goes)."""
        index = self._row_at(row)
        values = self._data[index]
        _, old_back, old_fore = self._row_colors.get(id(values), (None, "", ""))
        back, fore = old_back if back is None else back, old_fore if fore is None else fore
        if back or fore:
            self._row_colors[id(values)] = (values, back, fore)  # (holding the row: its id stays its own)
        else:
            self._row_colors.pop(id(values), None)
        if self._tree.exists(str(index)):  # (just this row: a loop coloring many stays quick)
            self._tree.item(str(index), tags=self._row_tags(index, values))

    def _check_sorted(self):
        """After a change: if the rows aren't in their sorted order now, the header's arrow goes."""
        if self._sorted is None:
            return
        column, descending, key = self._sorted
        order = [key(row[column]) for row in self._data]
        if order != sorted(order, reverse=descending):
            self._unsort()

    def _shown(self, row):
        return [kind.show(value) for kind, value in zip(self._kinds, row)]

    def _show_row(self, row):
        if self._tree.exists(str(row)):
            self._tree.item(str(row), values=self._shown(self._data[row]))
        self._check_sorted()

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
                (self._editor_box or self._editor).place_forget()
                self.widget.after_idle(self._edit_out_of_sight)
            return
        x, y, w, h = box
        color = self._cursor_color(iid in self._tree.selection())
        for line, (lx, ly, lw, lh) in zip(self._lines, ((x, y, w, 2), (x, y + h - 2, w, 2), (x, y, 2, h),
                                                         (x + w - 2, y, 2, h))):
            line.configure(background=color)
            line.place(x=lx, y=ly, width=lw, height=lh)
            line.lift()
        if self._editor is not None:
            # As tall as it needs, if that's more than the cell (a Mac's text box is taller than
            # its rows), centered on it: over the rows beside it while it's open, not clipped.
            placed = self._editor_box or self._editor
            if not placed.winfo_ismapped():
                placed.update_idletasks()  # (its size, from its font, before it's first placed)
            tall = max(h, placed.winfo_reqheight())
            placed.place(x=x, y=y - (tall - h) // 2, width=w, height=tall)
            placed.lift()

    def _cursor_color(self, chosen):
        """The cell cursor's color: the theme's highlight, as chosen rows have (so the system's
        accent color, where Tk follows it); on a chosen row, the chosen rows' text color."""
        style = ttk.Style(self._tree)
        name = self._tree.cget("style") or "Treeview"
        if chosen:
            color, fallback = style.lookup(name, "foreground", ("selected",)), "white"
        else:
            color, fallback = style.lookup(name, "background", ("selected",)), CURSOR_COLOR
        try:
            self._tree.winfo_rgb(color)  # (a color Tk knows, by value or by system name)
        except tk.TclError:
            return fallback
        return color or fallback

    # ----- moving the cell cursor -----

    def _last_row(self):
        return len(self._data) if self._new_row() else len(self._data) - 1

    def _move(self, row, column, by_user=True, extend=False, keep=False):
        """Move the cell cursor. As in a spreadsheet, a move un-chooses the chosen rows, except
        with extend (Shift: the rows from where it started to here) or keep (code moving it)."""
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
        self._see_column(column)
        if extend:
            low, high = sorted((self._anchor, row))
            self._tree.selection_set([str(i) for i in range(low, min(high, len(self._data) - 1) + 1)])
        elif not keep:
            self._anchor = row
            self._tree.selection_set(())
        self._tree.update_idletasks()
        self._follow()
        if by_user and moved_row and row < len(self._data):
            self._raise("rowclick", row)

    def _choose_row(self, row, toggle=False):
        """Shift+Space (choose the cursor's row) and Ctrl+click (⌘ on a Mac: add or take away one)."""
        if row >= len(self._data):
            return
        if toggle:
            self._tree.selection_toggle(str(row))
        else:
            self._tree.selection_set(str(row))
        self._anchor = row

    def _click(self, e):
        tree = self._tree
        region = tree.identify_region(e.x, e.y)
        if region == "separator":
            self._sized = set(range(len(self._kinds)))  # (the user's widths from now on)
        if region not in ("cell", "tree"):
            return None  # (a header: sorting or resizing)
        if self._editor is not None and not self._finish(tell=False):
            return "break"
        tree.focus_set()
        iid, column = tree.identify_row(e.y), tree.identify_column(e.x)
        if not iid or not column:
            return "break"
        row = len(self._data) if iid == "new" else int(iid)
        if e.state & _PRIMARY:  # Ctrl+click (⌘ on a Mac): this row chosen too, or not
            self._move(row, int(column[1:]) - 1, keep=True)
            self._choose_row(row, toggle=True)
        else:  # (Shift+click: the rows from the last plain click's to this one)
            self._move(row, int(column[1:]) - 1, extend=bool(e.state & 0x1))
        return "break"

    def _double(self, e):
        if self._tree.identify_region(e.x, e.y) == "cell":
            self._edit()

    def _key(self, e):
        if self._editor is not None:
            self._focus_left()  # (the keys are the tree's: the editor was left)
            if self._editor is not None:
                return "break"
        name = keys.name(e.char, e.keysym, e.state)  # "a", "Shift+Down", "Ctrl+C" (Ctrl: ⌘ on a Mac)
        *held, key = name.split("+") if len(name) > 1 else [name]
        row, column = self._cur
        if held in ([], ["Shift"]) or key in ("Home", "End") and held == ["Ctrl"]:
            ctrl = held == ["Ctrl"]
            page = max(1, self._tree.winfo_height() // max(1, self._row_height()) - 1)
            moves = {"Up": (row - 1, column), "Down": (row + 1, column), "Left": (row, column - 1),
                     "Right": (row, column + 1), "Home": (0 if ctrl else row, 0),
                     "End": (self._last_row() if ctrl else row, len(self._kinds) - 1),
                     "PgUp": (row - page, column), "PgDn": (row + page, column)}
            if key in moves:
                self._move(*moves[key], extend=held == ["Shift"] and key in ("Up", "Down", "PgUp", "PgDn"))
                return "break"
        if held == ["Ctrl"] and key in ("Up", "Down", "Left", "Right"):  # to the edge, as in a spreadsheet
            self._move(*{"Up": (0, column), "Down": (self._last_row(), column), "Left": (row, 0),
                         "Right": (row, len(self._kinds) - 1)}[key])
            return "break"
        if key in ("Up", "Down", "Left", "Right", "Home", "End", "PgUp", "PgDn"):
            return "break"  # (with other keys held: nothing, rather than Tk's own moves)
        if key == "Tab" and held in ([], ["Shift"]):
            return self._tab(-1 if held or e.keysym == "ISO_Left_Tab" else 1)
        if name in ("Enter", "F2"):
            self._edit(as_text=name == "F2")  # (F2: a date or time's text, as a text cell's; Enter: its list)
            return "break"
        if name in ("Del", "Backspace"):  # (Backspace: the Mac's delete key)
            self._keyed(self._delete_chosen, "Delete", "emptied")
            return "break"
        if e.keysym == "space" and held == [] and e.state & 0x1:  # Shift+Space: this row, as in a spreadsheet
            self._choose_row(row)
            return "break"
        if name == "Esc" and self._tree.selection():
            self._tree.selection_set(())
            return "break"
        shortcuts = {"Ctrl+Z": self.undo, "Ctrl+Y": self.redo, "Ctrl+Shift+Z": self.redo,
                     "Ctrl+C": self.copy, "Ctrl+X": lambda: self._keyed(self.cut, "Cut", "cut"),
                     "Ctrl+V": lambda: self._keyed(self.paste, "Paste", "pasted"), "Ctrl+A": self.select_all}
        if name in shortcuts:
            shortcuts[name]()
            return "break"
        if e.keysym == "space" and not e.state & 0x1 and not held and self._kinds[column].kind == "check":
            self._edit()
            return "break"
        if e.char and name == e.char:  # it types (not a shortcut): an edit, starting with it
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

    def _edit(self, typed=None, as_text=False):
        """Edit the cell under the cursor: typed replaces it; otherwise what's there is kept."""
        row, column = self._cur
        if not self._kinds or not self._can_edit(column) or row > self._last_row():
            self._tree.bell()
            return
        kind = self._kinds[column]
        current = self._data[row][column] if row < len(self._data) else kind.blank()
        if kind.kind in ("date", "time", "datetime") and typed is None and not as_text:
            self._drop_for(row, column, current)
            return
        if kind.kind == "check":
            refused = self._refusal(row, column, not current)
            if refused:
                self._tell(kind.name, refused)
            else:
                self._store(row, column, not current)
            return
        if kind.kind == "choice":
            editor = ttk.Combobox(self._tree, values=kind.choices, state="readonly")
            start = current
            if typed:
                start = next((c for c in kind.choices if c.lower().startswith(typed.lower())), current)
            editor.set(start)
            # (finished once Tk's own handling of the choice is done; chosen with Enter: on, as
            # enter_moves says, as Enter does elsewhere; with a click: here)
            self._choice_keyed = False
            self._listen_for_enter(editor)
            editor.bind("<<ComboboxSelected>>", lambda e: editor.after_idle(
                lambda: editor is self._editor and (self._after_enter() if self._choice_keyed else self._finish())),
                add="+")
        else:
            editor = self._text_editor(kind)
            editor.insert(0, typed if typed is not None else kind.show(current) if row < len(self._data) else "")
            editor.icursor("end")
        style_font = ttk.Style(self._tree).lookup(self._tree.cget("style") or "Treeview", "font")
        try:
            editor.configure(font=style_font or "TkDefaultFont")
        except tk.TclError:
            pass
        self._editor, self._editing = editor, (row, column)
        for sequence, action in (("<Return>", self._after_enter), ("<KP_Enter>", self._after_enter),
                                 ("<Tab>", lambda: self._finish(0, 1)), ("<Escape>", self._cancel)):
            editor.bind(sequence, lambda e, a=action: (a(), "break")[1])
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):
            editor.bind(sequence, lambda e: (self._finish(0, -1), "break")[1])
        for sequence, step in (("<Up>", -1), ("<Down>", 1)):
            if kind.kind != "choice":  # (in a choice's list, the arrows choose)
                editor.bind(sequence, lambda e, s=step: (self._arrow_in_editor(e, s), "break")[1])
        if kind.kind in ("date", "time", "datetime"):
            editor.bind("<F4>", lambda e: (self._typed_to_month(), "break")[1])
        editor.bind("<FocusOut>", lambda e: self.widget.after_idle(self._focus_left), add="+")
        self._follow()
        editor.focus_set()
        if kind.kind == "choice" and typed is None:
            editor.after_idle(lambda: self._post(editor))

    def _arrow_in_editor(self, e, step):
        """Up or Down in a text editor: done, and up or down a row; Alt+Down in a date's: its month."""
        if self._editing and self._kinds[self._editing[1]].kind in ("date", "time", "datetime") and \
                keys.name(e.char, e.keysym, e.state) == "Alt+Down":
            self._typed_to_month()
        else:
            self._finish(step, 0)

    def _typed_to_month(self):
        """F4 or Alt+Down while typing a date or time: its month (or times) drop down, at what's
        typed (if it reads as one)."""
        row, column = self._editing
        kind = self._kinds[column]
        try:
            day = kind.convert(self._editor.get())
        except ValueError:
            day = None
        self._cancel()
        self._drop_for(row, column, day if day is not None else self._cell_or_blank(row, column))

    def _cell_or_blank(self, row, column):
        return self._data[row][column] if row < len(self._data) else self._kinds[column].blank()

    def _drop_for(self, row, column, value):
        """A date, time or datetime cell's editor: its month (a datetime's day) or a list of
        times, dropped down under it. A click chooses (and stays), Enter chooses and moves on
        (as enter_moves says); Esc, or a click elsewhere, leaves it."""
        box = self._tree.bbox(self._iid(row), f"c{column}")
        if not box:
            return
        kind = self._kinds[column]
        font = self._font if isinstance(self._font, str) else ""
        below = (self._tree, *box)
        typing = self._edit_typed  # (typed while it's down: the cell's text, starting with that)
        if kind.kind == "time":
            DropTimes(self._tree, value, lambda chosen, how: self._month_chosen(row, column, chosen, how),
                      format=kind.format, below=below, font=font, on_type=typing)
            return

        def chosen(day, how):
            if kind.kind == "datetime":  # (the day chosen, the time as it was: midnight, if none)
                day = datetime.datetime.combine(day, value.time() if value is not None else datetime.time())
            self._month_chosen(row, column, day, how)

        DropMonth(self._tree, value.date() if isinstance(value, datetime.datetime) else value, chosen,
                  below=below, font=font, on_type=typing)

    def _edit_typed(self, character):
        self._edit(typed=character)

    def _month_chosen(self, row, column, day, how):
        refused = self._refusal(row, column, day)
        if refused:
            self._tell(self._kinds[column].name, refused)
            return
        self._store(row, column, day)
        down, across = _ENTER_STEPS[self._enter_moves] if how == "key" else (0, 0)
        if across:
            self._tab(across)
        elif down:
            self._move(self._cur[0] + down, self._cur[1])

    def _text_editor(self, kind):
        """A text cell's editor: a classic Entry in a thin frame of the cursor's color, the cell
        cursor opened up. (Not ttk's: a Mac's native text box is half again as tall as a row.)"""
        style, name = ttk.Style(self._tree), self._tree.cget("style") or "Treeview"
        back = self._background() or style.lookup(name, "fieldbackground") or "#ffffff"
        fore = self._foreground() or style.lookup(name, "foreground") or "#000000"
        edge = self._cursor_color(self._iid(self._cur[0]) in self._tree.selection())  # (as the cursor's, on a chosen row too)
        box = tk.Frame(self._tree, background=back, bd=0, highlightthickness=1,
                       highlightbackground=edge, highlightcolor=edge)
        editor = tk.Entry(box, relief="flat", bd=0, highlightthickness=0, background=back, foreground=fore,
                          insertbackground=fore, justify="right" if kind.kind in ("number", "money") else "left")
        editor.pack(fill="both", expand=True, padx=(2, 1))  # (the text a little in, as a cell's is)
        self._editor_box = box
        return editor

    def _listen_for_enter(self, editor):
        """Note Enter in a choice's list (Tk's own, which a click chooses in too)."""
        try:
            popdown = editor.tk.call("ttk::combobox::PopdownWindow", editor)  # (made now if need be)
            if self._noted_enter is None:  # (one Tcl command, for every edit's list)
                self._noted_enter = self._tree.register(lambda: setattr(self, "_choice_keyed", True))
            noted = self._noted_enter
            for key in ("<KeyPress-Return>", "<KeyPress-KP_Enter>"):
                editor.tk.call("bind", f"{popdown}.f.l", key, f"+{noted}")
        except tk.TclError:  # (another Tk's list: Enter chooses and stays)
            pass

    def _post(self, editor):
        """Open a choice's list. (Not a generated <Down>: key events go to the focus, which may
        not have reached the new editor yet.)"""
        if editor is self._editor and editor.winfo_exists():
            editor.update_idletasks()
            editor.tk.call("ttk::combobox::Post", editor)

    def _edit_out_of_sight(self):
        """The cell being edited scrolled out of sight: the edit ends, kept if it fits, as when
        the user clicks elsewhere."""
        if self._editor is not None and not self._editor.winfo_ismapped() and not self._finish(tell=False):
            self._cancel()

    def _focus_left(self):
        """The editor lost the keyboard (a click elsewhere): keep what's typed, if it fits."""
        if self._editor is None:
            return
        focus = str(self._tree.tk.call("focus"))  # (a path: focus_get() fails in a choice's list)
        if focus == str(self._editor) or focus.startswith(str(self._editor) + ".") or self._telling:
            return  # (the editor, or a choice's own list, or a message about it)
        if not self._finish(tell=False):
            self._cancel()

    def _finish(self, down=0, across=0, tell=True):
        """Save the edit (True), then move the cursor; False if what's typed doesn't fit its
        column or cellvalidate refuses it (said in a message, with tell)."""
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
                refused = self._refusal(row, column, value)
            except ValueError as e:
                refused = str(e)
            if refused:
                if tell:
                    self._tell(kind.name, refused)
                else:
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

    def _refusal(self, row, column, value):
        """Why the user's value can't go in the cell, from cellvalidate (None if it can): it
        returns False, or a message saying why."""
        answer = self._raise("cellvalidate", row, column, value)
        if answer is False:
            return f"{self._kinds[column].name}: {self._kinds[column].text(value)} isn't allowed"
        if isinstance(answer, str) and answer:
            return answer
        return None

    def _tell(self, title, message):
        """A refusal, said in a message (the editor, if open, keeps the keyboard after it)."""
        self._tree.bell()
        self._telling = True
        try:
            messagebox.showwarning(title, message, parent=self._tree)
        finally:
            self._telling = False
        if self._editor is not None:
            self._editor.focus_set()

    def _close_editor(self):
        if self._editor is not None:
            if isinstance(self._editor, ttk.Combobox):
                try:
                    self._editor.tk.call("ttk::combobox::Unpost", self._editor)  # (and its grab)
                except tk.TclError:
                    pass
            (self._editor_box or self._editor).destroy()
        self._editor = self._editing = self._editor_box = None
        self._tree.focus_set()
        self._follow()

    def _store(self, row, column, value):
        """The user's change to a cell (on the new row: a new row first)."""
        with self._step():
            if row == len(self._data):
                self._data.append([kind.blank() for kind in self._kinds])
                self._record("add", self._data[row], row)
                self._refresh()
                self._raise("rowadd", row)
            if self._data[row][column] != value:
                self._record("cell", self._data[row], column, self._data[row][column], value)
                self._data[row][column] = value
                self._show_row(row)
                self._raise("cellchange", row, column)

    # ----- undo -----

    @contextmanager
    def _step(self):
        """One user change (an edit, a paste, a delete), recorded as one step for undo."""
        if self._recording is not None:  # (inside another: part of it)
            yield
            return
        self._recording = []
        try:
            yield
        finally:
            step, self._recording = self._recording, None
            if step:
                self._undone.append(step)
                del self._undone[:-UNDO_STEPS]
                self._redone.clear()

    def _record(self, *change):
        if self._recording is not None:
            self._recording.append(change)

    def _forget(self):
        """Its rows are new (set from code, loaded, new columns): no taking back changes to the
        old ones, and their colors go with them."""
        self._undone.clear()
        self._redone.clear()
        self._row_colors.clear()

    @property
    def can_undo(self):
        """Whether undo() has a change of the user's to take back (for an Edit menu's Undo)."""
        return bool(self._undone) and self._editable and self._enabled

    @property
    def can_redo(self):
        """Whether redo() has an undone change to make again."""
        return bool(self._redone) and self._editable and self._enabled

    def undo(self):
        """Take back the user's last change: an edit, a paste, a cut, a Delete (rows and all).
        Ctrl+Z (⌘Z on a Mac). It's the user changing things back, so the same events run:
        cellchange for each cell changed back (each cell of a row put back), rowdelete for a
        row taken away. Changes made by code aren't taken back, and setting rows (or loading
        them, or new columns) forgets what came before."""
        if self.can_undo:
            self._replay(self._undone.pop(), backward=True)

    def redo(self):
        """Make the last undone change again. Ctrl+Y, or Ctrl+Shift+Z (⌘⇧Z on a Mac)."""
        if self.can_redo:
            self._replay(self._redone.pop(), backward=False)

    def _replay(self, step, backward):
        data = self._data

        def place(row):  # (a row's number now: rows are kept by themselves, so sorting doesn't matter)
            return next((i for i, r in enumerate(data) if r is row), None)

        deleted, touched = [], []
        was = {id(change[1]): list(change[1]) for change in step}  # (a row taken away: as it was before)
        for change in reversed(step) if backward else step:
            kind, row = change[0], change[1]
            if kind == "cell":
                _, _, column, old, new = change
                if place(row) is not None:
                    row[column] = old if backward else new
                    touched.append((row, column))
            else:
                index = change[2]
                if (kind == "add") == backward:  # taken away again
                    where = place(row)
                    if where is not None:
                        data.pop(where)
                        deleted.append((where, was[id(row)]))
                else:  # put back
                    data.insert(min(index, len(data)), row)
                    touched.extend((row, column) for column in range(len(self._kinds)))
        (self._redone if backward else self._undone).append(step)
        self._refresh()
        first = next(((place(row), column) for row, column in touched if place(row) is not None), None)
        if first is not None:  # (the cursor goes to what changed, as in a spreadsheet)
            self._move(*first, by_user=False)
        for where, values in deleted:
            self._raise("rowdelete", where, values)
        for row, column in touched:
            if place(row) is not None:
                self._raise("cellchange", place(row), column)

    # ----- the clipboard -----

    def copy(self):
        """Copy to the clipboard as tab-separated text, as spreadsheets do (so it pastes into
        one): the chosen rows, or with none chosen, the cell under the cursor. Ctrl+C."""
        cells = self._copied()
        text = io.StringIO()
        writer = csv.writer(text, delimiter="\t", lineterminator="\n")
        for row, columns in cells:
            line = self._data[row] if row < len(self._data) else [k.blank() for k in self._kinds]
            writer.writerow([self._kinds[c].text(line[c]) for c in columns])
        self._tree.clipboard_clear()
        self._tree.clipboard_append(text.getvalue().removesuffix("\n"))

    def cut(self):
        """Copy, then empty the cells copied (those the user can edit). Ctrl+X."""
        self.copy()
        if not (self._editable and self._enabled):
            return
        cells = [(r, c) for r, columns in self._copied() if r < len(self._data) for c in columns
                 if not self._kinds[c].readonly]
        self._change({cell: self._kinds[cell[1]].blank() for cell in cells})

    def paste(self, text=None):
        """Paste tab-separated text (the clipboard's, unless text is given), as a spreadsheet
        does: from the cell cursor, across and down, with rows added at the bottom (if addable).
        Whole rows (as wide as the table) go from the first column; one value with rows chosen
        goes in each of them. Readonly columns are skipped,
        as is what's past the last column. Ctrl+V. ValueError, with nothing changed, if a value
        doesn't suit its column."""
        if not (self._editable and self._enabled):
            return
        if text is None:
            try:
                text = self._tree.clipboard_get()
            except tk.TclError:  # (nothing on the clipboard)
                return
        lines = list(csv.reader(io.StringIO(text.replace("\r\n", "\n").removesuffix("\n")), delimiter="\t"))
        if not lines:
            return
        top, left = self._cur
        if all(len(line) == len(self._kinds) for line in lines):
            left = 0  # whole rows (copied from here, say): from the first column, wherever the cursor is
        chosen = sorted(int(i) for i in self._tree.selection() if i != "new")
        if len(lines) == 1 and len(lines[0]) == 1 and chosen:
            cells = {(row, left): lines[0][0] for row in chosen}
        else:
            cells = {(top + i, left + j): value for i, line in enumerate(lines) for j, value in enumerate(line)
                     if left + j < len(self._kinds)}
        cells = {(r, c): v for (r, c), v in cells.items()  # (past the bottom: new rows, if addable)
                 if not self._kinds[c].readonly and (r < len(self._data) or self._new_row())}
        converted = {}
        for (row, column), value in cells.items():  # (all of them, before anything changes)
            try:
                converted[row, column] = self._kinds[column].convert(value)
            except ValueError as e:
                raise ValueError(f"row {row}: {e}") from None
        self._change(converted)

    def _keyed(self, action, title, done):
        """A key's action (paste, cut, delete): if refused, nothing changed, so say why."""
        try:
            action()
        except ValueError as e:
            self._tell(title, f"Nothing was {done}: {e}")

    def select_all(self):
        """Choose every row. Ctrl+A."""
        self._tree.selection_set([str(i) for i in range(len(self._data))])

    def _copied(self):
        """What copy() takes: [(row, [columns])]."""
        chosen = sorted(int(i) for i in self._tree.selection() if i != "new")
        if chosen:
            return [(row, list(range(len(self._kinds)))) for row in chosen]
        return [(self._cur[0], [self._cur[1]])]

    def _change(self, cells):
        """The user's change to these cells, {(row, column): value}: each checked by cellvalidate
        (ValueError, with nothing changed, if any is refused), then new rows (rowadd), the values,
        and cellchange for each that changed."""
        if not cells:
            return
        for (row, column), value in sorted(cells.items()):  # (all of them, before anything changes)
            refused = self._refusal(row, column, value)
            if refused:
                raise ValueError(f"row {row}: {refused}")
        with self._step():
            added = range(len(self._data), max(row for row, _ in cells) + 1)
            for row in added:
                self._data.append([kind.blank() for kind in self._kinds])
                self._record("add", self._data[row], row)
            if added:
                self._refresh()
                for row in added:
                    self._raise("rowadd", row)
            changed = [(row, column) for (row, column), value in sorted(cells.items())
                       if self._data[row][column] != value]
            for row, column in changed:
                self._record("cell", self._data[row], column, self._data[row][column], cells[row, column])
                self._data[row][column] = cells[row, column]
            self._refresh()
            for row, column in changed:
                self._raise("cellchange", row, column)

    # ----- deleting and sorting -----

    def _delete_chosen(self):
        """Delete: the chosen rows go (deletable); with none chosen, the cell is emptied, as in
        a spreadsheet."""
        chosen = sorted((int(i) for i in self._tree.selection() if i != "new"), reverse=True)
        if not chosen:
            row, column = self._cur
            if row < len(self._data) and self._editable and self._enabled and not self._kinds[column].readonly:
                self._change({(row, column): self._kinds[column].blank()})
            else:
                self._tree.bell()
            return
        if not (self._deletable and self._editable and self._enabled):
            self._tree.bell()
            return
        with self._step():
            for row in chosen:
                values = self._data.pop(row)
                self._record("delete", values, row)
                self._raise("rowdelete", row, values)
            self._refresh()

    def _header_clicked(self, column):
        if self.design or self._editor is not None:
            return
        if self._sortable:
            again = self._sorted is not None and self._sorted[0] == column
            self.sort(column, descending=again and not self._sorted[1])
        self._raise("columnclick", column)

    def sort(self, column, descending=False, key=None):
        """Sort the rows by a column (its header or number); the header shows ▲ or ▼. key, as
        sorted()'s, gives what to sort each value by: natural order, say, with natsort's
        natsort_keygen(). (The usual: text ignoring case, choices in their order.)"""
        column = self._column_at(column)
        kind = self._kinds[column]
        key = key or kind.sort_key
        try:
            self._data.sort(key=lambda row: key(row[column]), reverse=bool(descending))
        except TypeError as e:
            raise TypeError(f"{kind.name} can't be sorted that way: {e}") from None
        self._sorted = (column, bool(descending), key)
        for i, k in enumerate(self._kinds):
            mark = (" \u25bc" if descending else " \u25b2") if i == column else ""
            self._tree.heading(f"c{i}", text=k.name + mark)
        self._refresh()

    @property
    def sorted_by(self):
        """(column, descending) for the column the rows are sorted by, as its header shows; None
        if they aren't. For a columnclick that sorts its own way: the other way if it's this one."""
        return self._sorted[:2] if self._sorted else None

    # ----- events -----

    def _raise(self, event, *args):
        raiser = self._raisers.get(event)
        return raiser(*args) if raiser is not None else None

    def bind_event(self, event, handler):
        if event in ("cellchange", "cellvalidate", "rowadd", "rowdelete", "rowclick", "columnclick"):
            self._raisers[event] = handler
        elif event == "dblclick":
            self._tree.bind("<Double-Button-1>", lambda e: self._tree.identify_row(e.y) and handler(), add="+")
        else:
            super().bind_event(event, handler)
