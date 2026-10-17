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
import dataclasses
import datetime
import functools
import inspect
import json
import io
from contextlib import contextmanager
import operator
import re
import sqlite3
import tkinter as tk
from collections.abc import MutableSequence, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from pathlib import Path
from tkinter import font as tkfont
from tkinter import ttk

from readymade import data as sql
from readymade import keys
from readymade.appearance import CHECK_MARK, check_color
from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.dates import (DATETIME_FORMAT, ISO, TIME_FORMAT, DropMonth, Dropped, DropTimes, _check_format,
                                     read_date, read_datetime, read_time, show, to_date, to_datetime, to_time)
from readymade.controls.traits import Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip
from readymade.controls.trees import _TreeLook
from readymade.data import DataError, Problem  # (the rules' errors: Tk-free, as ConflictError)
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

_KINDS = ("text", "number", "money", "date", "time", "datetime", "check", "choice")
KINDS = _KINDS  # the kinds a column can be
SETTINGS = ("name", "header", "kind", "decimals", "format", "choices", "step", "readonly", "required", "default",
            "min", "max", "max_length", "unique", "key", "validator", "hidden", "formula")  # what a definition can say


@dataclass(frozen=True)
class ColumnKind:
    """One column's definition: its name, kind of value, how it shows, and the rules its values
    keep. Given as a dict (the settings in SETTINGS), or as a line, for the simple ones: "Price
    : number 2", "Size : S | M | L", "Total : money, readonly". An empty cell is None (a
    database's NULL), unless default says otherwise for new rows."""

    name: str  # what code, a CSV file and a database call it
    kind: str = "text"  # text, number, money, date, time, datetime, check or choice
    decimals: int | None = None  # for a number: the places it keeps (None: as it comes); money's (2)
    choices: tuple = ()  # for a choice
    readonly: bool = False  # the user can't edit it (code can)
    format: str = ISO  # for a date, time or datetime: how it shows (strftime's codes)
    header: str = ""  # what the table shows over it, if not its name
    step: int = 30  # for a time: the minutes between the times dropped down
    required: bool = False  # it can't be empty (a database's NOT NULL)
    default: object = None  # a new row's value (None: empty)
    min: object = None  # the least value (a number, money, date or time)
    max: object = None  # the most
    max_length: int | None = None  # for text: the most characters
    unique: bool = False  # no two rows the same (empty ones aside)
    key: bool = False  # what tells rows apart (required and unique), for a database
    validator: object = None  # a rule of the program's own: validator(value), or (value, row) (code only)
    hidden: bool = False  # kept, but not shown (a database's key, say)
    formula: object = None  # worked out: formula(row), or formula(table) for the whole column (code only)

    @property
    def label(self):
        """What's shown over the column: its header, or its name."""
        return self.header or self.name

    @property
    def locked(self):
        """Whether the user can't edit it: readonly, or worked out by a formula."""
        return self.readonly or self.formula is not None

    @classmethod
    def of(cls, definition):
        """A column's definition from what columns was given: a dict, a line, or a line holding
        a dict as JSON (as the designer's list of lines does)."""
        if isinstance(definition, ColumnKind):
            return definition
        if isinstance(definition, ColumnView):
            return definition._kind()
        if isinstance(definition, dict):
            return cls.from_dict(definition)
        text = str(definition).strip()
        if text.startswith("{"):
            try:
                return cls.from_dict(json.loads(text))
            except json.JSONDecodeError as e:
                raise ValueError(f"{text!r}: not a column's definition ({e.msg})") from None
        return cls.parse(text)

    @classmethod
    def from_dict(cls, definition):
        name = str(definition.get("name", "")).strip()
        if not name:
            raise ValueError(f"{definition!r}: a column needs a name")
        unknown = sorted(set(definition) - set(SETTINGS))
        if unknown:
            raise ValueError(f"{name}: no setting {', '.join(map(repr, unknown))}; a column's are: {', '.join(SETTINGS)}")
        kind = definition.get("kind", "choice" if "choices" in definition else "text")
        if kind not in _KINDS:
            raise ValueError(f"{name}: kind {kind!r} isn't one of {', '.join(_KINDS)}")

        def only(setting, kinds):
            if setting in definition and kind not in kinds:
                raise ValueError(f"{name}: {setting} is for a {' or '.join(kinds)} column, not {kind}")
            return definition.get(setting)

        choices = only("choices", ("choice",))
        if kind == "choice" and (not choices or isinstance(choices, str)):
            raise ValueError(f"{name}: a choice column needs choices: a list, like [\"S\", \"M\", \"L\"]")
        decimals = only("decimals", ("number", "money"))
        if decimals is None and kind == "money":
            decimals = 2
        format = only("format", tuple(_WHEN_FORMATS)) or _WHEN_FORMATS.get(kind, ISO)
        step = only("step", ("time",)) or 30
        if not 1 <= int(step) <= 720:
            raise ValueError(f"{name}: step must be from 1 to 720 minutes")
        max_length = only("max_length", ("text",))
        for setting in ("min", "max"):
            only(setting, ("number", "money", "date", "time", "datetime"))
        key = bool(definition.get("key", False))
        validator, formula = definition.get("validator"), definition.get("formula")
        for setting, function in (("validator", validator), ("formula", formula)):
            if function is not None and not callable(function):
                raise ValueError(f"{name}: {setting} must be a function (or a lambda), not {function!r}")
        column = cls(name, kind, validator=validator, hidden=bool(definition.get("hidden", False)), formula=formula, decimals=None if decimals is None else int(decimals),
                     choices=tuple(str(c) for c in choices or ()), readonly=bool(definition.get("readonly", False)),
                     format=_check_format(format), header=str(definition.get("header", "") or ""), step=int(step),
                     required=bool(definition.get("required", False)) or key,
                     max_length=None if max_length is None else int(max_length),
                     unique=bool(definition.get("unique", False)) or key, key=key)
        values = {}
        for setting in ("default", "min", "max"):
            if definition.get(setting) is not None:
                values[setting] = column.convert(definition[setting])
        if values.get("min") is not None and values.get("max") is not None and values["min"] > values["max"]:
            raise ValueError(f"{name}: min can't be more than max")
        return dataclasses.replace(column, **values)

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
        """How it's written as a line of columns; None if a line can't say it all (rules,
        defaults, a header, a step: then it's a dict)."""
        if (self.header or self.step != 30 or self.required or self.default is not None or self.min is not None
                or self.max is not None or self.max_length is not None or self.unique or self.key
                or self.validator is not None or self.hidden or self.formula is not None):
            return None
        kind = {"text": "", "check": "check", "choice": " | ".join(self.choices),
                "number": "number" + (f" {self.decimals}" if self.decimals is not None else ""),
                "money": "money" + (f" {self.decimals}" if self.decimals != 2 else ""),
                **{when: when + (f" {self.format}" if self.format != usual else "")
                   for when, usual in _WHEN_FORMATS.items()}}[self.kind]
        extras = ", ".join(p for p in (kind, "readonly" if self.readonly else "") if p)
        return f"{self.name} : {extras}" if extras else self.name

    def definition(self):
        """Its definition as a dict: the settings that aren't the usual ones (a validator too:
        a function, so not one for a .form file)."""
        usual = ColumnKind(self.name)  # (a text column's settings: what isn't said)
        found = {"name": self.name}
        for setting in SETTINGS[1:]:
            value = getattr(self, setting)
            if setting == "decimals" and self.kind == "money" and value == 2:
                continue
            if setting == "format" and value == _WHEN_FORMATS.get(self.kind, ISO):
                continue
            if (setting in ("required", "unique") and self.key) or value == getattr(usual, setting):
                continue
            if setting == "kind" and value == "choice":
                continue  # (choices say it)
            if setting in ("validator", "formula"):
                found[setting] = value
                continue
            found[setting] = list(value) if setting == "choices" else self.text(value) if setting in (
                "default", "min", "max") and not isinstance(value, (int, float, bool)) else value
        return found

    def blank(self):
        """A new cell's value: default, or None (empty)."""
        return self.default

    def convert(self, value):
        """value as this column holds it (None, or "": empty); ValueError if it can't be."""
        if value is None or (isinstance(value, str) and not value.strip() and self.kind != "text") or value == "":
            return None
        if self.kind == "text":
            return str(value)
        if self.kind == "check":
            if isinstance(value, bool) or isinstance(value, (int, float)):
                return bool(value)
            word = str(value).strip().lower()
            if word in _TRUE or word in _FALSE:
                return word in _TRUE
            raise ValueError(f"{self.name}: {value!r} isn't a tick (True or False)")
        if self.kind == "choice":
            match = next((c for c in self.choices if c.lower() == str(value).strip().lower()), None)
            if match is None:
                raise ValueError(f"{self.name}: {value!r} isn't one of {', '.join(self.choices)}")
            return match
        if self.kind == "money":
            return self._money(value)
        if self.kind in _WHEN_FORMATS:
            reading, making = {"date": (read_date, to_date), "time": (read_time, to_time),
                               "datetime": (read_datetime, to_datetime)}[self.kind]
            if isinstance(value, str):
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
        if self.decimals == 0:
            return round(value)  # (whole numbers, as an INTEGER column's)
        return round(float(value), self.decimals) if self.decimals is not None else value

    def show(self, value):
        """How a cell's value is shown ("" when it's empty)."""
        if value is None:
            return ""
        if self.kind == "check":
            return CHECK_MARK if value else ""
        if self.kind == "number" and self.decimals is not None:
            return f"{value:.{self.decimals}f}"
        if self.kind == "money":
            return f"{value:,.{self.decimals}f}"  # (1,234.50)
        if self.kind in _WHEN_FORMATS:
            return show(value, self.format)
        return str(value)

    def text(self, value):
        """A value as text for a CSV file or the clipboard ("" when it's empty): numbers with
        their decimals (money without its thousands' commas), a check as True or False, dates
        and times as ISO has them (which convert() reads back)."""
        if value is None:
            return ""
        if self.kind == "money":
            return f"{value:.{self.decimals}f}"
        if self.kind in _WHEN_FORMATS:  # (2026-10-14, 21:30, 2026-10-14 21:30: whatever's shown)
            if self.kind == "date":
                return value.isoformat()
            spec = "seconds" if value.second else "minutes"
            return value.isoformat(timespec=spec) if self.kind == "time" else value.isoformat(" ", spec)
        if self.kind == "number":
            return self.show(value)
        return str(bool(value)) if self.kind == "check" else str(value)

    def sort_key(self, value):
        """What value sorts by: empty ones last."""
        if value is None:
            return (True, 0)
        if self.kind == "text":
            return (False, str(value).casefold())
        if self.kind == "choice":
            return (False, self.choices.index(value) if value in self.choices else len(self.choices))
        return (False, value)

    def rules(self, value, row=None):
        """The rules value breaks, of those about a value alone (unique is about the column):
        [(rule, limit, what's wrong)]. row: its row's values (a _RowValues), for a validator
        that wants them."""
        broken = []
        if value is None:
            if self.required:
                broken.append(("required", None, f"{self.label} can't be empty"))
            return broken
        if self.min is not None and value < self.min:
            broken.append(("min", self.min, f"{self.label}: {self.show(value)} is less than {self.show(self.min)}"))
        if self.max is not None and value > self.max:
            broken.append(("max", self.max, f"{self.label}: {self.show(value)} is more than {self.show(self.max)}"))
        if self.max_length is not None and len(str(value)) > self.max_length:
            broken.append(("max_length", self.max_length,
                           f"{self.label}: {len(str(value))} characters, more than {self.max_length}"))
        if self.validator is not None:
            try:
                answer = self.validator(value, row) if _takes_row(self.validator) else self.validator(value)
            except ValueError as e:  # (a validator may say why by raising, too)
                answer = str(e) or False
            if answer is False or (isinstance(answer, str) and answer):
                message = answer if isinstance(answer, str) else f"{self.label}: {self.show(value)} isn't allowed"
                broken.append(("validator", None, message))
        return broken


@functools.lru_cache(maxsize=256)
def _takes_row(function):
    """Whether a validator wants its row too: validator(value, row)."""
    try:
        parameters = list(inspect.signature(function).parameters.values())
    except (TypeError, ValueError):  # (a built-in, say)
        return False
    if any(p.kind == p.VAR_POSITIONAL for p in parameters):
        return True
    return len([p for p in parameters if p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]) >= 2


def _as_text(kind):
    """A column's definition as text (its name, header and rules kept), for values that aren't
    its kind: shown as they are."""
    return ColumnKind(kind.name, header=kind.header, readonly=kind.readonly, required=kind.required,
                      unique=kind.unique, key=kind.key, hidden=kind.hidden)


def _takes_table(function):
    """Whether a formula is given the whole table (its parameter's called table), not a row."""
    try:
        names = list(inspect.signature(function).parameters)
    except (TypeError, ValueError):
        return False
    return bool(names) and names[0] == "table"


class _Money(Decimal):
    """A money value as a row formula sees it: one that goes with a float (price * 1.1), as a
    Column's do; Python's own Decimal won't."""


def _money_op(name):
    op = getattr(Decimal, name)

    def run(self, other):
        if isinstance(other, float):
            other = Decimal(repr(other))
        found = op(self, other)
        return _Money(found) if isinstance(found, Decimal) else found
    return run


for _op in ("__add__", "__radd__", "__sub__", "__rsub__", "__mul__", "__rmul__", "__truediv__", "__rtruediv__",
            "__floordiv__", "__rfloordiv__", "__mod__", "__rmod__", "__pow__", "__rpow__", "__neg__", "__abs__"):
    setattr(_Money, _op, _money_op(_op) if _op not in ("__neg__", "__abs__") else
            (lambda name: lambda self: _Money(getattr(Decimal, name)(self)))(_op))
del _op


class _FormulaRow(Sequence):
    """A row, for a row formula: row["Price"] (by name or header) or row[2]. A formula column's
    value is worked out first, if it isn't yet. Notes whether an empty value was read."""

    def __init__(self, table, kinds, row, column_values):
        self._table, self._kinds, self._row, self._column_values = table, kinds, row, column_values
        self.read_empty = False

    def __len__(self):
        return len(self._kinds)

    def __getitem__(self, column):
        index = self._table._column_in(self._kinds, column)
        value = self._column_values(index)[self._row]
        if value is None:
            self.read_empty = True
        elif self._kinds[index].kind == "money":
            value = _Money(value)  # (it goes with floats: row["Price"] * 1.1)
        return value

    def asdict(self):
        return {kind.name: self[i] for i, kind in enumerate(self._kinds)}


class _FormulaTable:
    """The table, for a table formula, read as the DataTable is: table["Amount"] is a column's
    values (a Column), table[2, "Qty"] a cell, table[1:, "Qty"] part of a column, table[2, :]
    part of a row (a list), table[1:3, "Price":"Total"] a Block; rows as numbers, slices, lists
    or conditions. A formula column's values are worked out first, if they aren't yet.
    len(table) is how many rows."""

    def __init__(self, table, kinds, count, column_values):
        self._table, self._kinds, self._count, self._column_values = table, kinds, count, column_values

    def __len__(self):
        return self._count

    def __getitem__(self, key):
        if isinstance(key, str):
            key = (slice(None), key)
        if not (isinstance(key, tuple) and len(key) == 2):
            raise TypeError(f"a formula's table[...] takes a column's name, or a row and a column: "
                            f"table[2, \"Qty\"], table[1:, \"Qty\"]; not {key!r}")
        rows, one_row = _pick(key[0], self._count, self._table.name)
        columns, one_column = self._columns(key[1])
        values = {c: self._column_values(c) for c in columns}
        if one_row and one_column:
            return values[columns[0]][rows[0]]
        if one_column:
            return Column([values[columns[0]][r] for r in rows], self._kinds[columns[0]].name)
        if one_row:
            return [values[c][rows[0]] for c in columns]
        return Block([[values[c][r] for c in columns] for r in rows], [self._kinds[c].name for c in columns])

    def _columns(self, key):
        """Column numbers, as DataTable._columns_at gives them, among this formula's columns."""
        count, find = len(self._kinds), lambda column: self._table._column_in(self._kinds, column)
        if isinstance(key, slice):
            start, stop, step = key.start, key.stop, key.step
            if not isinstance(start, str) and not isinstance(stop, str):
                return list(range(*key.indices(count))), False
            step = 1 if step is None else step
            back = step < 0
            first = (count - 1 if back else 0) if start is None else find(start)
            if stop is None:
                last = -1 if back else count
            elif isinstance(stop, str):
                last = find(stop) + (-1 if back else 1)
            else:
                last = stop + count if stop < 0 else min(stop, count)
            return list(range(first, last, step)), False
        if isinstance(key, (list, tuple)):
            return [find(k) for k in key], False
        return [find(key)], True


class _RowValues(Sequence):
    """A row's values, for a validator: row["Starts"] (by name or header) or row[1]."""

    def __init__(self, kinds, values):
        self._kinds, self._values = kinds, values

    def __len__(self):
        return len(self._values)

    def __getitem__(self, column):
        if isinstance(column, str):
            names = [k.name for k in self._kinds]
            labels = [k.label for k in self._kinds]
            lower = [n.lower() for n in names]
            for found in (names, labels, lower):
                key = column.lower() if found is lower else column
                if key in found:
                    return self._values[found.index(key)]
            raise KeyError(f"no column {column!r}; the columns: {', '.join(names)}")
        return self._values[column]

    def asdict(self):
        return {kind.name: value for kind, value in zip(self._kinds, self._values)}


class _Refused(ValueError):
    """The user's change (a paste, say) refused: a value that can't be its column's kind, or
    one cellvalidate turned down. Nothing changed."""

    def __init__(self, row, column, value, reason):
        self.row, self.column, self.value, self.reason = row, column, value, reason
        super().__init__(f"row {row}: {reason}")


_WHEN_FORMATS = {"date": ISO, "time": TIME_FORMAT, "datetime": DATETIME_FORMAT}  # each kind's usual format
FORMATS = _WHEN_FORMATS  # (the dates' and times' usual formats, by kind)
_WHAT = {"date": "date", "time": "time", "datetime": "date and time"}
_EARLIEST = {"date": datetime.date.min, "time": datetime.time.min, "datetime": datetime.datetime.min}


def _known(op):
    """A comparison where an empty value (None: a date not given) is neither more nor less than
    anything: False, as a database's NULL is in a condition."""
    def run(a, b):
        return False if a is None or b is None else op(a, b)
    return run


def _mixed(op):
    """op, able to take an empty value and a float with money: with None (empty), None, as a
    database's NULL (a price not given, times 2, isn't given either); and Python won't mix a
    Decimal with a float, so the float becomes a Decimal of its own digits (price * 1.1 is
    price * Decimal("1.1"))."""
    def run(a, b):
        if a is None or b is None:
            return None
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
        if keys and all(isinstance(k, bool) or k is None for k in keys):  # (empty: not chosen, as False)
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

    _HINTS = {"apply": "map(function) does that: column.map(int)", "astype": "map(int), map(str)... does that",
              "fillna": "map(lambda v: v) leaves out empty ones; [v if v is not None else 0 for v in column] fills them"}

    def __getattr__(self, attribute):
        if attribute in Column._HINTS:  # (pandas' names, where a Column's differ)
            raise AttributeError(f"a Column has no {attribute}(): {Column._HINTS[attribute]}")
        raise AttributeError(f"a Column has no {attribute!r}")

    def __int__(self):
        raise TypeError("a Column is many values, not one: column.map(int) makes each an int")

    def __float__(self):
        raise TypeError("a Column is many values, not one: column.map(float) makes each a float")

    def __setattr__(self, attribute, value):
        if attribute not in ("_values", "name"):  # (formula, kind, max...: the definition's, not the values')
            where = f"table.columns[{self.name!r}]" if self.name else "table.columns[...]"
            raise AttributeError(f"a Column is a copy of a column's values: it has no {attribute!r} to set. "
                                 f"The column's definition ({attribute} and its other settings) is {where}")
        super().__setattr__(attribute, value)

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

    def _each(self, other, op, reverse=False, arithmetic=True):
        """op on each value (and other's, row by row, or other itself): arithmetic is _mixed (an
        empty value giving an empty one); a comparison sees the values as they are."""
        if isinstance(other, (Column, list, tuple)):
            if len(other) != len(self):
                raise ValueError(f"columns of different lengths: {len(self)} and {len(other)}")
            pairs = zip(self._values, other)
        else:
            pairs = ((value, other) for value in self._values)
        if arithmetic:
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
        return self._each(other, _known(operator.lt), arithmetic=False)

    def __le__(self, other):
        return self._each(other, _known(operator.le), arithmetic=False)

    def __gt__(self, other):
        return self._each(other, _known(operator.gt), arithmetic=False)

    def __ge__(self, other):
        return self._each(other, _known(operator.ge), arithmetic=False)

    def eq(self, other):
        """Whether each value equals other (a value, or a column's values, row by row): a
        Column of True/False. (== compares the whole column.)"""
        return self._each(other, operator.eq, arithmetic=False)

    def ne(self, other):
        """Whether each value differs from other: a Column of True/False."""
        return self._each(other, operator.ne, arithmetic=False)

    def contains(self, text):
        """Whether each value has text in it (as text, case aside): a Column of True/False, a
        condition. table[table["Tool"].contains("shov"), :] (empty values: False)."""
        text = str(text).casefold()
        return Column([value is not None and text in str(value).casefold() for value in self._values], self.name)

    def cumsum(self):
        """The running total, row by row: a Column (an empty value stays empty, the total going
        on past it). For a formula: lambda table: table["Amount"].cumsum()."""
        add, total, running = _mixed(operator.add), 0, []
        for value in self._values:
            if value is not None:
                total = add(total, value)
            running.append(None if value is None else total)
        return Column(running, self.name)

    def shift(self, rows=1):
        """The values moved down rows rows (up, if negative), the gap left empty: shift(1) gives
        each row the one above's. For a formula: lambda table: table["Total"] - table["Total"].shift()."""
        values, count = self._values, len(self._values)
        if rows >= 0:
            moved = [None] * min(rows, count) + values[:max(count - rows, 0)]
        else:
            moved = values[-rows:] + [None] * min(-rows, count)
        return Column(moved, self.name)

    def isin(self, values):
        """Whether each value is one of values: a Column of True/False, a condition.
        table[table["Size"].isin(["S", "M"]), "Item"]."""
        values = list(values) if not isinstance(values, (str, bytes)) else [values]
        return Column([value in values for value in self._values], self.name)

    def __and__(self, other):
        return self._each(other, lambda a, b: bool(a and b), arithmetic=False)

    __rand__ = __and__

    def __or__(self, other):
        return self._each(other, lambda a, b: bool(a or b), arithmetic=False)

    __ror__ = __or__

    def __invert__(self):
        return Column([not v for v in self._values], self.name)

    def __neg__(self):
        return self.map(lambda v: -v)

    def __abs__(self):
        return self.map(abs)

    def __round__(self, places=None):
        return self.map(lambda v: round(v, places))

    def map(self, function):
        """function(value) for each value, empty ones (None) left as they are: a Column.
        notes.map(lambda s: s[:40]) keeps the first 40 characters of each."""
        return Column([None if v is None else function(v) for v in self._values], self.name)

    def clip(self, low=None, high=None):
        """Each value kept from low to high (either None: no limit), empty ones left as they
        are: a Column. totals.clip(0, 9999) brings those outside the range to its ends."""
        return self.map(lambda v: low if low is not None and v < low else high if high is not None and v > high else v)

    def _known_values(self):
        return [v for v in self._values if v is not None]

    def sum(self):
        """The values added up (empty ones left out, as a database's SUM: 0 if there are none)."""
        return sum(self._known_values())

    def mean(self):
        """The average of the values, empty ones left out (ValueError if there are none)."""
        known = self._known_values()
        if not known:
            raise ValueError(f"no values to average in {self.name or 'the column'}")
        return sum(known) / len(known)

    def min(self):
        """The smallest value, empty ones left out (None if there are none)."""
        return min(self._known_values(), default=None)

    def max(self):
        """The largest value, empty ones left out (None if there are none)."""
        return max(self._known_values(), default=None)


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
        return Block([[None if v is None else change(v) for v in row] for row in self._rows], self.headers)

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
        after = list(table._data)
        if isinstance(index, slice):
            new = [table._convert_row(v) for v in values]
            after[index] = new
        else:
            row = table._data[table._row_at(index)]
            new = [table._convert_row(values)]
            after[table._row_at(index)] = new[0]
            table._enforce(after, new)
            row[:] = new[0]  # (the same row, its values changed: its colors stay, and a database's row it is)
            table._refresh()
            return
        table._enforce(after, new)
        table._data[:] = after
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
        new = table._convert_row(values)
        after = list(table._data)
        after.insert(index, new)
        table._enforce(after, [new])
        table._data[:] = after
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


# ----- columns: the definitions, live -----

class ColumnView:
    """One column's definition, live (table.columns["Qty"]): its settings (name, header, kind,
    required, default, min, max, max_length, unique, key, validator... see SETTINGS) to read or
    set. Setting one applies it at once, checked as a dict's is (ValueError, nothing changed, if
    it can't be): columns["Qty"].max = 50; columns["Price"].kind = "number" converts the values
    (empty, those that can't be). values is the column's values: table["Qty"], to read or set.

    A rule set now holds for what's written from now on; values already there that break it
    are problems() to see to, as the user's are."""

    def __init__(self, table, name):
        self._table, self._name = table, name

    def _index(self):
        names = [kind.name for kind in self._table._kinds]
        if self._name not in names:
            raise KeyError(f"{self._table.name} has no column {self._name!r} now")
        return names.index(self._name)

    def _kind(self):
        return self._table._kinds[self._index()]

    @property
    def values(self):
        """The column's values: a Column (as table["Qty"] is). Set them as table["Qty"] = ... does."""
        return self._table[self._name]

    @values.setter
    def values(self, values):
        self._table[self._name] = values

    def definition(self):
        """Its settings as a dict (those that aren't the usual ones)."""
        return self._kind().definition()

    def line(self):
        """It as a line of columns, if a line can say it all (else None)."""
        return self._kind().line()

    def __eq__(self, other):
        try:
            return self._kind() == ColumnKind.of(other)
        except (ValueError, TypeError):
            return False

    __hash__ = None

    def __repr__(self):
        kind = self._kind()
        return f"ColumnView({kind.line() or kind.definition()!r})"


def _setting(setting):
    def get(self):
        value = getattr(self._kind(), setting)
        return list(value) if setting == "choices" else value

    def set(self, value):
        self._table._change_setting(self._index(), setting, value)
        if setting == "name":
            self._name = str(value).strip()

    return property(get, set, doc=f"The column's {setting} (see SETTINGS); set it to change it.")


for _name in SETTINGS:
    setattr(ColumnView, _name, _setting(_name))
del _name


class Columns(MutableSequence):
    """A DataTable's columns' definitions, as a live list: columns["Qty"] or columns[3] is one
    (a ColumnView, its settings to read or set); append and insert add a column (a dict, or a
    line: each row gets its default, or empty), del takes one away (and its values); len, in
    ("Qty" in columns) and a loop work as on a list. It compares equal to a list of definitions
    (lines or dicts), and tolist() gives one."""

    def __init__(self, table):
        self._table = table

    def __len__(self):
        return len(self._table._kinds)

    def __getitem__(self, key):
        kinds = self._table._kinds
        if isinstance(key, slice):
            return [ColumnView(self._table, kind.name) for kind in kinds[key]]
        return ColumnView(self._table, kinds[self._table._column_at(key)].name)

    def __setitem__(self, key, definition):
        self._table._replace_column(self._table._column_at(key), ColumnKind.of(definition))

    def __delitem__(self, key):
        self._table._remove_column(self._table._column_at(key))

    def insert(self, index, definition):
        self._table._insert_column(index, definition)

    def __contains__(self, key):
        try:
            self._table._column_at(key)
        except (KeyError, IndexError, TypeError):
            return False
        return True

    def __eq__(self, other):
        if not isinstance(other, (Columns, list, tuple)):
            return False
        try:
            return list(self._table._kinds) == [ColumnKind.of(item) for item in other]
        except (ValueError, TypeError):
            return False

    __hash__ = None

    def tolist(self):
        """The definitions as a list: a line where one says it all, else a dict."""
        return [kind.line() or kind.definition() for kind in self._table._kinds]

    def __repr__(self):
        return repr(self.tolist())


# ----- the control -----

@register
class DataTable(_TreeLook, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A table of data, as a database has: each column holds one kind of value (text, a
    number, money, a date or time, a tick or a choice) for every row, or nothing (None, as a
    database's NULL). The user edits it like a spreadsheet.

    columns defines them: a dict for each ({"name": "Qty", "kind": "number", "min": 0,
    "default": 1}: see SETTINGS), or a line for a simple one ("Price : money", "Size : S | M |
    L", "Total : money, readonly"). A new row's cells are empty, but for a column's default.
    The rules (required, min, max, max_length, unique, key) hold for code: a change breaking
    one raises DataError, nothing changed (but inside unchecked()). The user's changes are
    kept, broken rules and all, and rowinvalid says what's wrong as the cursor leaves the row:
    the program decides. Money is a decimal.Decimal, exact to the cent. enter_moves says where
    Enter goes after an edit (down; right, for typing along rows). Code reaches the data
    Pythonically:

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
    (return False, or a message why, to refuse it); cellrefused when one isn't kept (it can't
    be the column's kind, or cellvalidate refused it): the table shows nothing itself, the
    program says it as it likes; cellchange after a change; rowinvalid as above; rowadd when a new row is
    made (for defaults); rowdelete as one is deleted; columnclick when a header is clicked
    (after sorting, if sortable: off, it can sort its own way, with sort()'s key).

    A column can be worked out by a formula (columns["Total"].formula = lambda row: row["Price"]
    * row["Qty"]; or lambda table: ... for the whole column), kept up to date as the rest
    change. filter shows only the rows it's True for; find() goes through the cells matching
    some text; a column can be hidden (columns["Id"].hidden = True).

    Ctrl+Z takes back the user's last change, and Ctrl+Y (or Ctrl+Shift+Z) makes it again: undo()
    and redo() from code, can_undo and can_redo for an Edit menu. A row's backcolor and
    forecolor are set from code (self.Stock.rows[2].backcolor = "#ffe0e0"), and stay with it.

    load_sql() fills it from an SQLite database (a table's rows, or a query's; the columns made
    from the table's definition), and save_sql() saves the changes back, every row kept, the
    columns' changes too (a column added, renamed...). changed and changes() say what's changed
    since, and revert() takes it all back.

    The columns share its width out (none narrower than its header), and scroll sideways when
    they don't fit. autosize_columns() fits some or all to what they hold, and widths sets
    them; those keep their widths, and the others share what's left."""

    type_name = "DataTable"
    default_size = (320, 200)
    default_event = "cellchange"
    events = (Event("cellchange", ("row", "column")), Event("cellvalidate", ("row", "column", "value")),
              Event("cellrefused", ("row", "column", "value", "reason")), Event("rowinvalid", ("row", "problems")),
              Event("rowadd", ("row",)), Event("rowdelete", ("row", "values")),
              Event("rowclick", ("row",), policy="latest"), Event("columnclick", ("column",)),
              Event("dblclick"), *_FOCUS_EVENTS)
    extra_props = {"columns": ["Name", "Amount : number"], "editable": True, "addable": True, "deletable": True,
                   "sortable": True, "enter_moves": "down"}
    prop_choices = {"enter_moves": ENTER_MOVES}
    prop_dialogs = {"columns": "columns"}  # (the designer's Columns dialog, not lines to type)

    def create_widget(self, parent):
        self._data, self._kinds = [], []
        self._origins = []  # each column's in the database (sql.Binding says): its name there, None (new), sql.OWN
        self._binding = None  # where load_sql() read the rows from (a sql.Binding), to save them back
        self._cur = (0, 0)
        self._anchor = 0  # where Shift+arrows start choosing rows from
        self._editor = None
        self._editor_box = None  # what's placed over the cell: a text editor's frame (a choice's list is itself)
        self._editing = None  # (row, column) being edited
        self._sorted = None  # (column, descending, key)
        self._raisers = {}  # event -> what on() (or a Name_event method) attached
        self._editable = self._addable = self._deletable = self._sortable = True
        self._enter_moves = "down"
        self._undone, self._redone = [], []  # steps: lists of ("cell", row, column, old, new), ("add"/"delete", row, index)
        self._recording = None  # the step being recorded (a user's change under way)
        self._row_colors = {}  # id(row) -> (row, backcolor, forecolor)
        self._unchecked = 0  # inside unchecked(): code's changes not checked against the rules
        self._touched = {}  # id(row) -> row: rows the user changed, their rules not yet checked (rowinvalid)
        self._filter = None  # filter(row): the rows shown (None: all)
        self._in_view = []  # the rows shown, in order (their numbers)
        self._pinned = None  # a row the user's editing, shown though the filter wouldn't (till the cursor leaves)
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
            tree.bind("<FocusOut>", lambda e: self.widget.after_idle(self._keyboard_left), add="+")
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
        """The columns' definitions, as a live list (a Columns): columns["Qty"] (or columns[3]) is
        one, its settings to read or set (columns["Qty"].max = 50); append, insert and del add
        and take away columns. Set a list of definitions to replace them all: each a dict (see
        SETTINGS: name, kind, required, default, min, max...), or a line for a simple one:
        "Item", "Price : number 2", "In stock : check", "Size : S | M | L", "Total : money,
        readonly". The rows stay, each value converted to its column's new kind (empty if it
        can't be)."""
        return Columns(self)

    @columns.setter
    def columns(self, definitions):
        kinds = [ColumnKind.of(definition) for definition in definitions] or [ColumnKind("Column 1")]
        self._check_names(kinds)
        old = self._kinds
        if any(kind.formula is not None for kind in kinds):  # (tried on a copy first)
            trial, self._data = self._data, [[self._keep(kinds[i], row[i]) if i < len(old) else kinds[i].blank()
                                              for i in range(len(kinds))] for row in self._data]
            try:
                self._recompute(kinds, dry=True)
            finally:
                self._data = trial
        for row in self._data:  # (the same row lists, changed: their colors stay)
            row[:] = [self._keep(kinds[i], row[i]) if i < len(old) else kinds[i].blank() for i in range(len(kinds))]
        self._kinds = kinds
        self._origins = (self._origins + [None] * len(kinds))[:len(kinds)]  # (as the values: by place)
        self._forget()
        self._show_columns()

    # ----- formulas: computed columns -----

    def _column_in(self, kinds, column):
        """A column's number among kinds (by name, header or number), for a formula's reading."""
        if isinstance(column, int) and not isinstance(column, bool):
            return column % len(kinds)
        for names in ([k.name for k in kinds], [k.label for k in kinds]):
            if column in names:
                return names.index(column)
        lowered = str(column).lower()
        for names in ([k.name.lower() for k in kinds], [k.label.lower() for k in kinds]):
            if lowered in names:
                return names.index(lowered)
        raise KeyError(f"{self.name} has no column {column!r}; its columns: {', '.join(k.name for k in kinds)}")

    def _recompute(self, kinds=None, dry=False):
        """Work out the formula columns, every row, and put the values in (not with dry: a try,
        for a formula about to be set). ValueError (nothing changed) for a circular reference,
        or a value a formula gives that can't be its column's kind."""
        kinds = self._kinds if kinds is None else kinds
        formulas = [c for c, kind in enumerate(kinds) if kind.formula is not None]
        if not formulas:
            return
        data, done, working = self._data, {}, []

        def column_values(c):
            if c in done:
                return done[c]
            kind = kinds[c]
            if kind.formula is None:
                return [row[c] for row in data]
            if c in working:  # (a formula reaching, by others, back to itself)
                loop = working[working.index(c):] + [c]
                raise ValueError("a circular reference: " + " \u2192 ".join(kinds[i].label for i in loop))
            working.append(c)
            try:
                if _takes_table(kind.formula):
                    found = kind.formula(_FormulaTable(self, kinds, len(data), column_values))
                    values = list(found) if isinstance(found, (Column, list, tuple)) else [found] * len(data)
                    if len(values) != len(data):
                        raise ValueError(f"{kind.label}'s formula gave {len(values)} values for {len(data)} rows")
                else:
                    values = [self._by_row(kind, _FormulaRow(self, kinds, r, column_values)) for r in range(len(data))]
                done[c] = [kind.convert(value) for value in values]
            finally:
                working.pop()
            return done[c]

        for c in formulas:
            column_values(c)
        if not dry:
            for c in formulas:
                for row, value in zip(data, done[c]):
                    row[c] = value

    @staticmethod
    def _by_row(kind, row):
        """A row formula's value for row: empty, if it can't be worked out from an empty value
        (Price times an empty Qty), or for a division by 0."""
        try:
            return kind.formula(row)
        except (ZeroDivisionError, InvalidOperation):
            return None
        except TypeError:
            if row.read_empty:
                return None
            raise

    def _check_names(self, kinds):
        """New columns' definitions, checked together before any takes effect."""
        names = [n for k in kinds for n in {k.name.lower(), k.label.lower()}]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"two columns have the same name or header: {', '.join(repeated)}")
        if all(kind.hidden for kind in kinds):
            raise ValueError(f"{self.name} has to show at least one column")

    def _show_columns(self, keep_widths=False):
        """The Treeview's columns as the definitions say: headings, alignment, widths (shared
        out again, or kept as they were, with keep_widths)."""
        widths = self.widths if keep_widths else None
        ids = [f"c{i}" for i in range(len(self._kinds))]
        self._tree.configure(columns=ids, displaycolumns=[ids[i] for i in self._view_columns()])
        for i, kind in enumerate(self._kinds):
            anchor = {"number": "e", "money": "e", "check": "center"}.get(kind.kind, "w")  # (dates, times: as text)
            self._tree.column(ids[i], anchor=anchor, stretch=False, minwidth=NARROWEST)
            self._tree.heading(ids[i], text=kind.label, anchor=anchor, command=lambda c=i: self._header_clicked(c))
        self._sorted = None
        if widths and len(widths) == len(ids):
            for i, width in enumerate(widths):
                self._tree.column(ids[i], width=width)
        else:
            self._sized = set()
            self._fit_columns()
        self._refresh()

    def _insert_column(self, index, definition):
        kind = ColumnKind.of(definition)
        kinds = list(self._kinds)
        kinds.insert(index, kind)
        self._check_names(kinds)
        if kind.formula is not None:  # (tried on a copy: the data has no cells for it yet)
            trial, self._data = self._data, [row[:index] + [None] + row[index:] for row in self._data]
            try:
                self._recompute(kinds, dry=True)
            finally:
                self._data = trial
        index = kinds.index(kind) if kinds.count(kind) == 1 else min(max(index, 0), len(kinds) - 1)
        for row in self._data:
            row.insert(index, kind.blank())  # (each row: its default, or empty)
        self._origins.insert(index, None)
        self._kinds = kinds
        self._forget_steps()
        self._show_columns()

    def _remove_column(self, index):
        if len(self._kinds) == 1:
            raise ValueError(f"{self.name} keeps at least one column")
        kinds = list(self._kinds)
        del kinds[index]
        self._check_names(kinds)
        for row in self._data:
            del row[index]
        del self._origins[index]
        self._kinds = kinds
        self._forget_steps()
        self._show_columns()

    def _replace_column(self, index, kind):
        """A column's new definition: its values converted to it (empty, those that can't be)."""
        kinds = list(self._kinds)
        old, kinds[index] = kinds[index], kind
        self._check_names(kinds)
        self._recompute(kinds, dry=True)
        if kind.kind != old.kind or kind.decimals != old.decimals or kind.choices != old.choices:
            for row in self._data:
                row[index] = self._keep(kind, row[index])
            self._forget_steps()  # (values changed under undo's steps)
        self._kinds = kinds
        self._show_columns(keep_widths=True)

    def _change_setting(self, index, setting, value):
        """One setting of a column changed (a ColumnView's): the definition made again, checked
        as a dict is (ValueError, nothing changed, if it can't be)."""
        settings = self._kinds[index].definition()
        if setting == "kind":  # (a new kind keeps what still fits it: no choices for a number)
            fits = {**{k: set() for k in _KINDS}, "choice": {"choices"}, "number": {"decimals", "min", "max"},
                    "money": {"min", "max"}, "date": {"format", "min", "max"},  # (money: its own 2 places)
                    "time": {"format", "step", "min", "max"}, "datetime": {"format", "min", "max"},
                    "text": {"max_length"}}
            for only in ("choices", "decimals", "format", "step", "max_length", "min", "max"):
                if only not in fits.get(value, set()):
                    settings.pop(only, None)
        if value is None or (setting == "choices" and not value):
            settings.pop(setting, None)
        else:
            settings[setting] = value
        self._replace_column(index, ColumnKind.from_dict(settings))

    @property
    def headers(self):
        """The columns' headers, as shown, in order: what a column number names (table.headers[2])."""
        return [kind.label for kind in self._kinds]

    @property
    def names(self):
        """The columns' names, in order (a header shown may differ: a definition's header)."""
        return [kind.name for kind in self._kinds]

    def _fit_columns(self):
        """Share its width out among the columns, none narrower than its header, except those
        whose widths someone set (widths, autosize_columns(), dragging a header's edge): the
        others share what those leave. Columns that don't fit scroll sideways."""
        width = self._tree.winfo_width()
        free = [column for column in self._view_columns() if column not in self._sized]
        if width <= 1 or not free:
            return
        _, heading = self._fonts()
        taken = sum(int(self._tree.column(f"c{column}", "width")) for column in self._sized
                    if column in self._view_columns())
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
        return heading.measure(kind.label + " \u25b2") + PADDING  # (with room for a sort's arrow)

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
        shown = self._view_columns()
        total, view = sum(widths[c] for c in shown), self._tree.winfo_width()
        if total <= view or view <= 1 or column not in shown:
            return
        left = sum(widths[c] for c in shown[:shown.index(column)])
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
            self._tree.heading(f"c{i}", text=kind.label)

    @staticmethod
    def _keep(kind, value):
        try:
            return kind.convert(value)
        except ValueError:
            return None  # (a column that changed kind: what doesn't fit is empty)

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
        new = [self._convert_row(row) for row in rows]
        self._enforce(new)
        self._data = new
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
        for c in columns:
            if kinds[c].formula is not None:
                raise ValueError(f"{kinds[c].label} is worked out by its formula: it can't be set")
        converted = [[kinds[c].convert(v) for c, v in zip(columns, line)] for line in grid]  # (all, then change)
        after = list(self._data)
        for r, line in zip(rows, converted):
            after[r] = list(after[r]) if after[r] is self._data[r] else after[r]
            for c, v in zip(columns, line):
                after[r][c] = v
        self._enforce(after, rows, columns)
        for r, line in zip(rows, converted):
            for c, v in zip(columns, line):
                self._data[r][c] = v
        if one_row and one_column:
            self._shown_again(rows[0])
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
        for names in ([k.name for k in self._kinds], [k.label for k in self._kinds]):  # (by name, or header shown)
            if column in names:
                return names.index(column)
        for names in ([k.name.lower() for k in self._kinds], [k.label.lower() for k in self._kinds]):
            if str(column).lower() in names:
                return names.index(str(column).lower())
        raise KeyError(f"{self.name} has no column {column!r}; its columns: {', '.join(k.name for k in self._kinds)}")

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
        places = {}
        for i, header in enumerate(lines[0]):  # (by name, or by the header shown)
            try:
                places[i] = self._column_at(header.strip())
            except KeyError:
                pass
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
        self._enforce(rows)
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

    # ----- a database: SQLite -----

    def load_sql(self, db, source, params=(), table=None, columns="schema"):
        """Replace the rows with a database's: db is an SQLite file (a path from the program's
        folder, or a full path; the table keeps it open) or a sqlite3 connection of the
        program's own. source is a table's name, or a query: "SELECT * FROM items WHERE qty
        < ?", with params for its ?s; table says which table a query's rows are saved to.

        columns="schema" makes the columns from the table's: each column's kind from its type
        (INTEGER, REAL, DECIMAL(10,2) as money, DATE, BOOLEAN as a check...), required from NOT
        NULL, unique, key, default. A key the database numbers (INTEGER PRIMARY KEY) is
        readonly, empty on a new row till it's saved; a table with no key has a hidden rowid
        column (last). columns="keep" keeps the columns as they are, filling those the table
        has (by name): the others are the program's own, not saved (the key's added, hidden,
        if it isn't there).

        The rules aren't checked: problems() says what breaks them. A value that isn't its
        column's kind (SQLite keeps anything anywhere: text in a number column) makes that
        column text, so all's shown as it is; the list returned says what was (each a
        Mismatch: row, column, value, declared). save_sql() writes the changes back."""
        if columns not in ("schema", "keep"):
            raise ValueError(f'columns is "schema" (the table\'s) or "keep" (the table\'s own), not {columns!r}')
        connection, owned, path = self._database(db, must_exist=True)
        try:
            reading = sql.read(connection, source, params, table)
        except Exception:
            if owned and not self._bound_to(path):
                connection.close()
            raise
        names = {name.lower(): j for j, name in enumerate(reading.names)}
        if columns == "schema":
            found = [(definition, origin, j) for j, (definition, origin) in enumerate(reading.definitions())
                     if definition is not None]
            kinds = [ColumnKind.of(definition) for definition, _, _ in found]
            origins = [origin for _, origin, _ in found]
            places = [j for _, _, j in found]
        else:
            kinds, origins, places = list(self._kinds), [], []
            schema = reading.schema
            for kind in kinds:
                j = names.get(kind.name.lower())
                places.append(j)
                saved = j is not None and schema is not None and (schema.column(kind.name) is not None
                                                                     or kind.name.lower() == sql.AUTONUMBER)
                origins.append(reading.names[j] if saved else sql.OWN)
            for key in schema.keys if schema is not None else ():
                if key.lower() not in {o.lower() for o in origins if isinstance(o, str)}:  # (hidden: it's the database's)
                    kinds.append(ColumnKind.of({**sql.definition_of(schema, key), "hidden": True}))
                    origins.append(reading.names[names[key.lower()]])
                    places.append(names[key.lower()])
        self._check_names(kinds)
        rows = [[None if j is None else raw[j] for j in places] for raw in reading.rows]
        mismatches = []
        for c, kind in enumerate(kinds):
            if places[c] is None:
                for row in rows:
                    row[c] = kind.blank()
                continue
            try:
                values = [sql.from_db(kind, row[c]) for row in rows]
            except ValueError:
                declared = reading.schema.column(kind.name) if reading.schema is not None else None
                declared = declared.declared if declared is not None else ""
                for r, row in enumerate(rows):
                    try:
                        sql.from_db(kind, row[c])
                    except ValueError:
                        mismatches.append(sql.Mismatch(r, kind.name, row[c], declared))
                kinds[c] = kind = _as_text(kind)
                values = [None if isinstance(row[c], bytes) else sql.from_db(kind, row[c]) for row in rows]
            for row, value in zip(rows, values):
                row[c] = value
        raw = {}
        for row, values in zip(rows, reading.rows):
            raw[id(row)] = {o.lower(): values[places[c]] for c, o in enumerate(origins) if isinstance(o, str)}
        if self._binding is not None and self._binding.connection is not connection:
            self._binding.close()
        self._binding = sql.Binding(connection, owned, reading.schema, source, params)
        self._binding.path = path
        self._kinds, self._origins, self._data = kinds, origins, rows
        self._binding.remember(kinds, origins, rows, raw)
        self._touched.clear()
        self._forget()
        self._show_columns()
        return mismatches

    def save_sql(self, db=None, table=None, replace=False, overwrite=False):
        """Save the changes since load_sql() (or the last save) to the database: the rows
        added, edited and deleted, and the columns' changes (a column added, renamed or
        deleted; a kind or rule changed), every other row kept. A new column with a formula
        isn't added (it's worked out), nor are the program's own (columns="keep"'s). It's all
        or nothing: DataError (nothing saved) if a row written breaks a rule (problems() says
        all), ConflictError if rows written were changed in the database since they were
        loaded (by another program, or user: overwrite=True writes over them), and a database
        error (sqlite3.IntegrityError, say, a foreign key not there) names the row. The rows
        saved are read back: a new row's autonumbered key is filled in.

        save_sql(db, "table") writes all the rows to a new table instead, made from the
        columns' definitions (ValueError if it's there already, unless replace=True drops it
        first; db as load_sql has it, or None: the one loaded from). The DataTable then
        belongs to the new table: save_sql() saves there. (Where the rows came from, it's a
        save_sql(): unless replace=True, which makes it again.)"""
        if (db is None and table is None) or (not replace and self._is_bound_table(db, table)):
            self._save_changes(overwrite)
        else:
            self._save_to(db, table, replace)

    def _save_changes(self, overwrite):
        binding = self._binding
        if binding is None:
            raise ValueError(f"{self.name}'s rows weren't loaded from a database: save_sql(db, \"table\") makes a "
                             "new table of them")
        changes = binding.changes(self._kinds, self._origins, self._data)
        problems = self._problems_in(self._data, changes.added + changes.edited)
        if problems:
            raise DataError(self.name, problems)
        raw, origins = binding.save(self._kinds, self._origins, self._data, overwrite)
        self._saved(raw, origins)

    def _save_to(self, db, table, replace):
        if not table:
            raise ValueError("save_sql(db, \"table\"): the table to make")
        if db is None:
            if self._binding is None:
                raise ValueError(f"{self.name}'s rows weren't loaded from a database: save_sql(db, \"{table}\") "
                                 "says which")
            connection, owned, path = self._binding.connection, self._binding.owned, self._binding.path
        else:
            connection, owned, path = self._database(db, must_exist=False)
        problems = self._problems_in(self._data)
        if problems:
            raise DataError(self.name, problems)
        columns = [c for c, (kind, origin) in enumerate(zip(self._kinds, self._origins))
                   if origin is not sql.OWN and kind.formula is None and kind.name.lower() != sql.AUTONUMBER]
        if not columns:
            raise ValueError(f"{self.name} has no columns to save: they're worked out, or the program's own")
        try:
            raw, schema = sql.create(connection, table, self._kinds, self._data, columns, replace)
        except Exception:
            if owned and not self._bound_to(path):
                connection.close()
            raise
        if self._binding is not None and self._binding.connection is not connection:
            self._binding.close()
        origins = [kind.name if c in columns else (None if origin is not sql.OWN else origin)
                   for c, (kind, origin) in enumerate(zip(self._kinds, self._origins))]
        for c, kind in enumerate(self._kinds):
            if kind.name.lower() == sql.AUTONUMBER:
                origins[c] = sql.AUTONUMBER if schema.autonumber == sql.AUTONUMBER else sql.OWN
        keep_widths = True
        if schema.autonumber == sql.AUTONUMBER and sql.AUTONUMBER not in origins:  # (no key: rowid's it, hidden)
            keep_widths = False
            self._kinds.append(ColumnKind.of(sql.definition_of(schema, sql.AUTONUMBER)))
            origins.append(sql.AUTONUMBER)
            for row in self._data:
                row.append(None)
        self._binding = sql.Binding(connection, owned, schema, table)
        self._binding.path = path
        self._saved(raw, origins, keep_widths)

    def _saved(self, raw, origins, keep_widths=None):
        """The rows read back after a save: their values as the database has them now (a new
        row's key, numbered), and how they are now, to find the next changes. keep_widths:
        the columns shown again (keeping their widths, or not); None: they're as they were."""
        self._origins = origins
        for row in self._data:
            values = raw.get(id(row))
            if values is None:
                continue
            for c, (kind, origin) in enumerate(zip(self._kinds, origins)):
                if isinstance(origin, str) and origin.lower() in values:
                    try:
                        row[c] = sql.from_db(kind, values[origin.lower()])
                    except ValueError:
                        pass  # (kept as it is here)
        self._binding.remember(self._kinds, origins, self._data, raw)
        if keep_widths is not None:
            self._show_columns(keep_widths=keep_widths)
        else:
            self._refresh()

    def _database(self, db, must_exist):
        """(a connection, whether it's the table's own to close, its path) for db: a sqlite3
        connection, or a path (the table's connection to it already, if it has one)."""
        if isinstance(db, sqlite3.Connection):
            return db, False, None
        path = self._path(db).resolve()
        if self._bound_to(path):
            return self._binding.connection, True, path
        return (sql.connect(path) if must_exist else sql.open_database(path)), True, path

    def _bound_to(self, path):
        binding = self._binding
        return path is not None and binding is not None and getattr(binding, "path", None) == path

    def _is_bound_table(self, db, table):
        """Whether save_sql(db, table) names where the rows came from (so it's a save there)."""
        binding = self._binding
        if binding is None or table is None or binding.table is None or table.lower() != binding.table.lower():
            return False
        if db is None or db is binding.connection:
            return True
        return not isinstance(db, sqlite3.Connection) and self._bound_to(self._path(db).resolve())

    @property
    def database(self):
        """The sqlite3 connection load_sql() read from (None if it didn't): for the program's
        own queries, self.Items.database.execute("SELECT ...")."""
        return self._binding.connection if self._binding is not None else None

    @property
    def changed(self):
        """Whether anything's changed since load_sql() (or the last save_sql()): for a "Save
        changes?" when the program closes."""
        return bool(self.changes())

    def changes(self):
        """What's changed since load_sql() (or the last save_sql()): .added and .edited (row
        numbers), .deleted (the rows deleted, as they were loaded: dicts by column name),
        .columns (("add", name), ("rename", old, new), ("drop", name), ("change", name)).
        False if nothing has."""
        if self._binding is None:
            return sql.Changes()
        return self._binding.changes(self._kinds, self._origins, self._data)

    def revert(self):
        """Put the rows (and columns) back as they were loaded (or last saved): changes since
        are forgotten."""
        binding = self._binding
        if binding is None:
            raise ValueError(f"{self.name}'s rows weren't loaded from a database: there's nothing to go back to")
        for loaded in binding.loaded.values():
            loaded.row[:] = loaded.values
        self._kinds, self._origins = list(binding.kinds), list(binding.origins)
        self._data = [loaded.row for loaded in binding.loaded.values()]
        self._touched.clear()
        self._forget_steps()
        self._show_columns()

    # ----- the rules: required, min, max, max_length, unique -----

    def _enforce(self, after, rows=None, columns=None):
        """Code's change: after, the rows it would leave, broken rules in the cells written (in
        rows: row lists or numbers, None: all; and columns: numbers, None: all) raising
        DataError, nothing changed. Rules broken elsewhere (by the user, say) are the program's
        to see to: they're not this change's fault. (Not inside unchecked().)"""
        if self._unchecked:
            return
        if rows is None:
            numbers = range(len(after))
        elif rows and not isinstance(rows[0], int):
            wanted = {id(row) for row in rows}
            numbers = [i for i, row in enumerate(after) if id(row) in wanted]
        else:
            numbers = rows
        problems = self._problems_in(after, numbers)
        if columns is not None:
            problems = [problem for problem in problems if problem.column in columns]
        if problems:
            raise DataError(self.name, problems)

    def _problems_in(self, data, rows=None):
        """The rules broken in data (rows of values), in rows (their numbers; None: all)."""
        rows = range(len(data)) if rows is None else rows
        found = []
        for r in rows:
            values = _RowValues(self._kinds, data[r])
            for c, kind in enumerate(self._kinds):
                found.extend(Problem(r, c, data[r][c], rule, limit, message)
                             for rule, limit, message in kind.rules(data[r][c], values))
        wanted = set(rows)
        for c, kind in enumerate(self._kinds):
            if not kind.unique:
                continue
            places = {}
            for r, row in enumerate(data):
                if row[c] is not None:
                    places.setdefault(row[c], []).append(r)
            for value, rows_with in places.items():
                for r in rows_with if len(rows_with) > 1 else ():
                    if r in wanted:
                        other = next(o for o in rows_with if o != r)
                        found.append(Problem(r, c, value, "unique", None,
                                             f"{kind.label}: {kind.show(value)} is in row {other} too"))
        found.sort(key=lambda problem: (problem.row, problem.column))
        return found

    def find(self, what, columns=None, after=None):
        """The cells that match what, one by one: an iterator of (row, column), in the rows and
        columns shown, left to right and down. what is text (found in what's shown, case aside:
        "1,234" finds 1,234.50), a function given each value (empty ones left out) that's True
        for a match, or another value (equal to it). columns: the column (or a list) to look in,
        by name or number. after: a cell to start after, going round to it (after=table.current,
        for a "find next"). Moving the cursor there is the program's choice: table.current = cell.

            for row, column in self.Items.find("shovel"): ...
            first = next(self.Items.find("shovel"), None)"""
        if columns is None:
            looking = self._view_columns()
        else:
            wanted = {self._column_at(c) for c in ([columns] if isinstance(columns, (str, int)) else columns)}
            looking = [c for c in self._view_columns() if c in wanted]
        cells = [(r, c) for r in list(self._in_view) for c in looking]
        if after is not None and tuple(after) in cells:
            at = cells.index(tuple(after)) + 1
            cells = cells[at:] + cells[:at]
        if callable(what):
            def matches(value, kind):
                return value is not None and bool(what(value))
        elif isinstance(what, str):
            text = what.casefold()

            def matches(value, kind):
                return value is not None and text in kind.show(value).casefold()
        else:
            def matches(value, kind):
                return value is not None and value == what
        for r, c in cells:
            if r < len(self._data) and matches(self._data[r][c], self._kinds[c]):
                yield r, c

    def problems(self, rows=None):
        """The rules broken in its rows now (or in rows: a row number, or several): a list of
        Problem (row, column, value, rule, limit, message). Empty if all's well: for a Save
        button to check first, or to color the rows at fault."""
        if isinstance(rows, int):
            rows = [rows]
        return self._problems_in(self._data, None if rows is None else [self._row_at(r) for r in rows])

    def check(self, column, value, row=None):
        """The rules value would break in column (its name or number): a list of Problem, empty
        if none. row: the row it would go in (left out when looking for duplicates); None: a
        new row. ValueError if value can't be the column's kind at all. For cellvalidate, say,
        to refuse a user's value that breaks the rules."""
        column = self._column_at(column)
        kind = self._kinds[column]
        value = kind.convert(value)
        after = list(self._data)
        if row is None:
            after.append([None] * len(self._kinds))
            row = len(after) - 1
        else:
            row = self._row_at(row)
        after[row] = list(after[row])
        after[row][column] = value
        return [problem for problem in self._problems_in(after, [row]) if problem.column == column]

    @contextmanager
    def unchecked(self):
        """Inside it, code's changes aren't checked against the rules (their kinds still are):
        to load data as it is, say, and fix it after. problems() says what's broken.

            with self.Items.unchecked():
                self.Items.load_csv("old orders.csv")"""
        self._unchecked += 1
        try:
            yield
        finally:
            self._unchecked -= 1

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
        self._recompute()
        tree.delete(*tree.get_children())
        self._in_view = self._filtered()
        for place, i in enumerate(self._in_view):
            tree.insert("", "end", iid=str(i), values=self._shown(self._data[i]), tags=self._row_tags(place, self._data[i]))
        if self._new_row():
            tree.insert("", "end", iid="new", values=[""] * len(self._kinds), tags=("new",))
        last = len(self._data) if self._new_row() else len(self._data) - 1
        row = min(self._cur[0], max(last, 0))
        self._cur = (self._nearest(self._view_rows(), row), self._nearest(self._view_columns(), self._cur[1]))
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
            self._tree.item(str(index), tags=self._row_tags(self._tree.index(str(index)), values))

    def _check_sorted(self):
        """After a change: if the rows aren't in their sorted order now, the header's arrow goes."""
        if self._sorted is None:
            return
        column, descending, key = self._sorted
        values = [row[column] for row in self._data]
        filled = [key(value) for value in values if value is not None]
        empties_last = all(value is None for value in values[len(filled):])
        if not empties_last or filled != sorted(filled, reverse=descending):
            self._unsort()

    def _shown(self, row):
        return [kind.show(value) for kind, value in zip(self._kinds, row)]

    def _shown_again(self, row):
        """After a change to a row: it shown again (all of them, with formulas to work out, or a
        filter to apply)."""
        if self._filter is not None or any(kind.formula is not None for kind in self._kinds):
            self._refresh()
        else:
            self._show_row(row)

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

    def _view_rows(self):
        """The rows the cursor can be on, in order: those shown, and the blank row at the bottom."""
        return self._in_view + ([len(self._data)] if self._new_row() else [])

    def _view_columns(self):
        """The columns shown, in order (the hidden left out)."""
        return [i for i, kind in enumerate(self._kinds) if not kind.hidden]

    @staticmethod
    def _nearest(places, wanted):
        """wanted, if it's in places (an ordered list); else the next one after it, or the last."""
        if not places or wanted in places:
            return wanted
        return next((p for p in places if p > wanted), places[-1])

    def _row_after(self, row, step):
        """The row step rows on (or back) from row, among those in view (stopping at the ends)."""
        rows = self._view_rows()
        if not rows:
            return row
        at = rows.index(self._nearest(rows, row))
        return rows[max(0, min(at + step, len(rows) - 1))]

    def _column_after(self, column, step):
        columns = self._view_columns()
        at = columns.index(self._nearest(columns, column))
        return columns[max(0, min(at + step, len(columns) - 1))]

    def _filtered(self):
        """The rows the filter shows (all of them, with none), the one pinned too."""
        if self._filter is None:
            return list(range(len(self._data)))
        return [i for i, row in enumerate(self._data)
                if row is self._pinned or self._filter(_RowValues(self._kinds, row))]

    @property
    def filter(self):
        """A function given each row (by name or number: row["Category"]), True for those to show;
        None (the usual) shows them all. The rows hidden are still there: rows, table[...],
        problems() and save_csv() have them all, and row numbers are the same; only what's shown
        and where the cursor goes are filtered. A row the user edits so it doesn't fit stays in
        sight till the cursor leaves it.

            self.Items.filter = lambda row: row["Category"] == "Garden"
            self.Items.filter = None"""
        return self._filter

    @filter.setter
    def filter(self, function):
        if function is not None and not callable(function):
            raise ValueError(f"filter must be a function given a row (or None), not {function!r}")
        self._filter, self._pinned = function, None
        self._refresh()

    def refilter(self):
        """Apply the filter again (a row the user just changed included)."""
        self._pinned = None
        self._refresh()

    @property
    def shown(self):
        """The numbers of the rows shown (all of them, with no filter), in order."""
        return list(self._in_view)

    def _move(self, row, column, by_user=True, extend=False, keep=False):
        """Move the cell cursor. As in a spreadsheet, a move un-chooses the chosen rows, except
        with extend (Shift: the rows from where it started to here) or keep (code moving it)."""
        if not self._kinds or self._last_row() < 0:
            return
        row = self._nearest(self._view_rows(), max(0, min(row, self._last_row())))
        column = self._nearest(self._view_columns(), max(0, min(column, len(self._kinds) - 1)))
        moved_row = row != self._cur[0]
        if moved_row and self._pinned is not None and self._filter is not None:
            left = self._pinned  # (the row edited, kept in sight: not now, if it doesn't fit)
            self._pinned = None
            if not self._filter(_RowValues(self._kinds, left)):
                self._cur = (row, column)
                self._refresh()
        self._cur = (row, column)
        iid = self._iid(row)
        if self._tree.exists(iid):
            self._tree.see(iid)
            self._tree.focus(iid)
        self._see_column(column)
        if extend:
            low, high = sorted((self._anchor, row))
            self._tree.selection_set([str(i) for i in self._in_view if low <= i <= high])
        elif not keep:
            self._anchor = row
            self._tree.selection_set(())
        self._tree.update_idletasks()
        self._follow()
        if by_user and moved_row and row < len(self._data):
            self._raise("rowclick", row)
        if moved_row:
            self._check_rows(keep=row)

    def _check_rows(self, keep=None):
        """The rows the user changed, checked against the rules (but not keep, the row number
        still being edited): rowinvalid for each that breaks any, for the program to decide."""
        keeping = self._data[keep] if keep is not None and 0 <= keep < len(self._data) else None
        for key, row in list(self._touched.items()):
            if row is keeping:
                continue
            del self._touched[key]
            where = next((i for i, r in enumerate(self._data) if r is row), None)
            if where is not None:
                problems = self._problems_in(self._data, [where])
                if problems:
                    self._raise("rowinvalid", where, problems)

    def _keyboard_left(self):
        """The keyboard left the table (and its editors): the rows changed, checked."""
        try:
            focus = str(self._tree.tk.call("focus"))
        except tk.TclError:
            return
        dropped = Dropped.current
        if focus.startswith(str(self.widget)) or (dropped is not None and dropped.field is self._tree):
            return
        self._check_rows()

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
        column = self._view_columns()[int(column[1:]) - 1]  # (#2: the second shown)
        if e.state & _PRIMARY:  # Ctrl+click (⌘ on a Mac): this row chosen too, or not
            self._move(row, column, keep=True)
            self._choose_row(row, toggle=True)
        else:  # (Shift+click: the rows from the last plain click's to this one)
            self._move(row, column, extend=bool(e.state & 0x1))
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
            rows, columns = self._view_rows(), self._view_columns()
            moves = {"Up": (self._row_after(row, -1), column), "Down": (self._row_after(row, 1), column),
                     "Left": (row, self._column_after(column, -1)), "Right": (row, self._column_after(column, 1)),
                     "Home": (rows[0] if ctrl and rows else row, columns[0]),
                     "End": (rows[-1] if ctrl and rows else row, columns[-1]),
                     "PgUp": (self._row_after(row, -page), column), "PgDn": (self._row_after(row, page), column)}
            if key in moves:
                self._move(*moves[key], extend=held == ["Shift"] and key in ("Up", "Down", "PgUp", "PgDn"))
                return "break"
        if held == ["Ctrl"] and key in ("Up", "Down", "Left", "Right"):  # to the edge, as in a spreadsheet
            rows, columns = self._view_rows() or [row], self._view_columns()
            self._move(*{"Up": (rows[0], column), "Down": (rows[-1], column), "Left": (row, columns[0]),
                         "Right": (row, columns[-1])}[key])
            return "break"
        if key in ("Up", "Down", "Left", "Right", "Home", "End", "PgUp", "PgDn"):
            return "break"  # (with other keys held: nothing, rather than Tk's own moves)
        if key == "Tab" and held in ([], ["Shift"]):
            return self._tab(-1 if held or e.keysym == "ISO_Left_Tab" else 1)
        if name in ("Enter", "F2"):
            self._edit(as_text=name == "F2")  # (F2: a date or time's text, as a text cell's; Enter: its list)
            return "break"
        if name in ("Del", "Backspace"):  # (Backspace: the Mac's delete key)
            self._keyed(self._delete_chosen)
            return "break"
        if e.keysym == "space" and held == [] and e.state & 0x1:  # Shift+Space: this row, as in a spreadsheet
            self._choose_row(row)
            return "break"
        if name == "Esc" and self._tree.selection():
            self._tree.selection_set(())
            return "break"
        shortcuts = {"Ctrl+Z": self.undo, "Ctrl+Y": self.redo, "Ctrl+Shift+Z": self.redo,
                     "Ctrl+C": self.copy, "Ctrl+X": lambda: self._keyed(self.cut),
                     "Ctrl+V": lambda: self._keyed(self.paste), "Ctrl+A": self.select_all}
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
        columns, rows = self._view_columns(), self._view_rows()
        at = columns.index(self._nearest(columns, column)) + step
        if 0 <= at < len(columns):
            self._move(row, columns[at])
            return "break"
        place = rows.index(self._nearest(rows, row)) + (1 if at >= len(columns) else -1) if rows else -1
        if not 0 <= place < len(rows):
            return None  # (the form's Tab: the next control)
        self._move(rows[place], columns[0] if at >= len(columns) else columns[-1])
        return "break"

    # ----- editing -----

    def _can_edit(self, column):
        return self._editable and self._enabled and not self._kinds[column].locked

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
                self._refused(row, column, not current, refused)
            else:
                self._store(row, column, not current)
            return
        if kind.kind == "choice":
            editor = ttk.Combobox(self._tree, values=kind.choices, state="readonly")
            start = current
            if typed:
                start = next((c for c in kind.choices if c.lower().startswith(typed.lower())), current)
            editor.set("" if start is None else start)  # (an empty cell: nothing chosen yet)
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
            self._refused(row, column, day, refused)
            return
        self._store(row, column, day)
        down, across = _ENTER_STEPS[self._enter_moves] if how == "key" else (0, 0)
        if across:
            self._tab(across)
        elif down:
            self._move(self._row_after(self._cur[0], down), self._cur[1])

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
        if focus == str(self._editor) or focus.startswith(str(self._editor) + "."):
            return  # (the editor, or a choice's own list)
        if not self._finish(tell=False):
            self._cancel()

    def _finish(self, down=0, across=0, tell=True):
        """Save the edit (True), then move the cursor; False if what's typed can't be its
        column's kind or cellvalidate refuses it (cellrefused says so)."""
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
                value, refused = text, str(e)
            if refused:
                self._refused(row, column, value, refused)
                return False
            self._close_editor()
            self._store(row, column, value)
        if down or across:
            if across:
                self._tab(across)
            else:
                self._move(self._row_after(self._cur[0], down), self._cur[1])
        return True

    def _cancel(self):
        self._close_editor()

    def _refusal(self, row, column, value):
        """Why the user's value can't go in the cell, from cellvalidate (None if it can): it
        returns False, or a message saying why."""
        answer = self._raise("cellvalidate", row, column, value)
        if answer is False:
            return f"{self._kinds[column].label}: {self._kinds[column].text(value)} isn't allowed"
        if isinstance(answer, str) and answer:
            return answer
        return None

    def _refused(self, row, column, value, reason):
        """The user's value couldn't be kept: cellrefused says so, for the program to tell the user
        (or not) as it likes; an editor open keeps the keyboard, and what was typed."""
        self._raise("cellrefused", row, column, value, reason)
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
                self._touched[id(self._data[row])] = self._data[row]
                self._pinned = self._data[row]  # (in sight, filter or not, till the cursor leaves it)
                self._shown_again(row)
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
        self._forget_steps()
        self._row_colors.clear()

    def _forget_steps(self):
        """Undo's steps no longer fit (a column added, taken away, or its values converted)."""
        self._undone.clear()
        self._redone.clear()

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
                self._touched[id(row)] = row
        self._check_rows(keep=self._cur[0])

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
                 if not self._kinds[c].locked]
        self._change({cell: None for cell in cells})

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
        columns = self._view_columns()
        if all(len(line) == len(columns) for line in lines):
            left = columns[0]  # whole rows (copied from here, say): from the first column, wherever the cursor is
        chosen = sorted(int(i) for i in self._tree.selection() if i != "new")
        if len(lines) == 1 and len(lines[0]) == 1 and chosen:
            cells = {(row, left): lines[0][0] for row in chosen}
        else:
            rows = self._view_rows()  # (down the rows shown, then new ones; across the columns shown)
            rows = rows[rows.index(self._nearest(rows, top)):]
            rows += list(range(max(rows[-1] + 1, len(self._data)) if rows else len(self._data),
                               len(self._data) + len(lines)))
            across = columns[columns.index(self._nearest(columns, left)):]
            cells = {(rows[i], across[j]): value for i, line in enumerate(lines) for j, value in enumerate(line)
                     if i < len(rows) and j < len(across)}
        cells = {(r, c): v for (r, c), v in cells.items()  # (past the bottom: new rows, if addable)
                 if not self._kinds[c].locked and (r < len(self._data) or self._new_row())}
        converted = {}
        for (row, column), value in cells.items():  # (all of them, before anything changes)
            try:
                converted[row, column] = self._kinds[column].convert(value)
            except ValueError as e:
                raise _Refused(row, column, value, str(e)) from None
        self._change(converted)

    def _keyed(self, action):
        """A key's action (paste, cut, delete): if refused, nothing changed: cellrefused says why."""
        try:
            action()
        except _Refused as e:
            self._refused(e.row, e.column, e.value, e.reason)

    def select_all(self):
        """Choose every row. Ctrl+A."""
        self._tree.selection_set([str(i) for i in self._in_view])

    def _copied(self):
        """What copy() takes: [(row, [columns])]."""
        chosen = sorted(int(i) for i in self._tree.selection() if i != "new")
        if chosen:
            return [(row, self._view_columns()) for row in chosen]  # (the columns shown)
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
                raise _Refused(row, column, value, refused)
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
                self._touched[id(self._data[row])] = self._data[row]
            if self._cur[0] < len(self._data):
                self._pinned = self._data[self._cur[0]]  # (the cursor's row stays in sight)
            self._refresh()
            for row, column in changed:
                self._raise("cellchange", row, column)
        self._check_rows(keep=self._cur[0])  # (a paste's rows: now, but the one the cursor's on)

    # ----- deleting and sorting -----

    def _delete_chosen(self):
        """Delete: the chosen rows go (deletable); with none chosen, the cell is emptied, as in
        a spreadsheet."""
        chosen = sorted((int(i) for i in self._tree.selection() if i != "new"), reverse=True)
        if not chosen:
            row, column = self._cur
            if row < len(self._data) and self._editable and self._enabled and not self._kinds[column].locked:
                self._change({(row, column): None})
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
        natsort_keygen(). (The usual: text ignoring case, choices in their order.) Empty values go
        last, either way, as a database's NULLs do."""
        column = self._column_at(column)
        kind = self._kinds[column]
        key = key or kind.sort_key
        filled = [row for row in self._data if row[column] is not None]
        try:
            filled.sort(key=lambda row: key(row[column]), reverse=bool(descending))
        except TypeError as e:
            raise TypeError(f"{kind.name} can't be sorted that way: {e}") from None
        self._data[:] = filled + [row for row in self._data if row[column] is None]
        self._sorted = (column, bool(descending), key)
        for i, k in enumerate(self._kinds):
            mark = (" \u25bc" if descending else " \u25b2") if i == column else ""
            self._tree.heading(f"c{i}", text=k.label + mark)
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
        if event in ("cellchange", "cellvalidate", "cellrefused", "rowinvalid", "rowadd", "rowdelete", "rowclick",
                     "columnclick"):
            self._raisers[event] = handler
        elif event == "dblclick":
            self._tree.bind("<Double-Button-1>", lambda e: self._tree.identify_row(e.y) and handler(), add="+")
        else:
            super().bind_event(event, handler)
