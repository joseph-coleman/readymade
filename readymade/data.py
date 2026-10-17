"""A DataTable's rows in an SQLite database: reading a table's columns from its schema, values
to and from SQLite, and saving the changes back. Plain Python (no Tk): the DataTable
(readymade.controls.datatable) uses it for load_sql() and save_sql().

Saving keeps every row. The changes are found by comparing the rows with how they were
loaded. A change to the columns is made in place where SQLite can (ADD, RENAME and DROP
COLUMN), else by rebuilding the table from its own definition, every row, index and trigger
carried across. It's all one transaction (BEGIN IMMEDIATE), rolled back if anything fails.
A row is written only if it still holds what was loaded: if someone else changed it
meanwhile, nothing is saved (ConflictError).
"""

from __future__ import annotations

import datetime
import re
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

AUTONUMBER = "rowid"  # SQLite's own row number: a hidden column, for a table with no key of its own
BUSY_SECONDS = 5  # how long a save waits while another program writes to the database


# ----- errors -----

@dataclass(frozen=True)
class Problem:
    """A rule a cell breaks: its row and column (numbers), its value, the rule ("required",
    "min", "max", "max_length", "unique" or "validator"), the rule's limit (min's least value, say: None
    for required and unique), and what's wrong, for a person (str(problem) says it too)."""

    row: int
    column: int
    value: object
    rule: str
    limit: object
    message: str

    def __str__(self):
        return self.message


class DataError(ValueError):
    """Code's change to a DataTable breaks its columns' rules: nothing was changed. problems
    lists each cell at fault (a Problem: row, column, value, rule, limit, message), to fix
    and try again."""

    def __init__(self, table, problems):
        self.problems = list(problems)
        first = self.problems[0]
        more = f" (and {len(self.problems) - 1} more)" if len(self.problems) > 1 else ""
        super().__init__(f"{table}: row {first.row}: {first.message}{more}")


class ConflictError(DataError):
    """save_sql() found rows changed (or deleted) in the database by someone else since they
    were loaded, so nothing was saved. rows lists them: (the row's number in the DataTable, or
    None for a row deleted here; its values in the database now, a dict by column name, or
    None if it's gone there). load_sql() again to see the others' changes, or
    save_sql(overwrite=True) to write over them."""

    def __init__(self, table, rows):
        self.rows = list(rows)
        self.problems = []
        first, values = self.rows[0]
        which = f"row {first}" if first is not None else "a row deleted here"
        what = "deleted from" if values is None else "changed in"
        more = f" (and {len(self.rows) - 1} more)" if len(self.rows) > 1 else ""
        ValueError.__init__(self, f"{table}: {which} was {what} the database since it was loaded{more}; "
                                  "nothing was saved")


class _Own:
    def __repr__(self):
        return "OWN"


OWN = _Own()  # a column's origin: the program's own, not the database's (never saved)


def quote(name):
    """An SQL name, quoted: "Unit price"."""
    return '"' + str(name).replace('"', '""') + '"'


def default_of(kind):
    """A column's default as SQL writes it, for its DEFAULT: money as a number (2.50)."""
    value = to_db(kind, kind.default)
    return value if kind.kind == "money" and value is not None else literal(value)


def literal(value):
    """A value as SQL writes it (where a ? can't go)."""
    if value is None:
        return "NULL"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


# ----- declared types and kinds -----

_VARCHAR = re.compile(r"(?:VAR)?CHAR(?:ACTER)?\s*\(\s*(\d+)\s*\)", re.IGNORECASE)
_DECIMAL = re.compile(r"(?:DECIMAL|MONEY)\s*(?:\(\s*\d+\s*(?:,\s*(\d+)\s*)?\))?", re.IGNORECASE)


def kind_of(declared):
    """A column's kind (with decimals or max_length) from its declared SQL type: INTEGER, REAL,
    TEXT, VARCHAR(30), DECIMAL(10,2), DATE, BOOLEAN...; None for a BLOB (pictures and the
    like: not loaded)."""
    text = " ".join((declared or "").upper().split())
    if text in ("BOOLEAN", "BOOL"):
        return {"kind": "check"}
    if text in ("DATE", "TIME"):
        return {"kind": text.lower()}
    if text in ("DATETIME", "TIMESTAMP"):
        return {"kind": "datetime"}
    found = _DECIMAL.fullmatch(text)
    if found:
        return {"kind": "money", "decimals": int(found.group(1)) if found.group(1) is not None else 2}
    found = _VARCHAR.fullmatch(text)
    if found:
        return {"kind": "text", "max_length": int(found.group(1))}
    # The rest by SQLite's own rules for a type's affinity (sqlite.org/datatype3.html, 3.1).
    if "INT" in text:
        return {"kind": "number", "decimals": 0}
    if any(word in text for word in ("CHAR", "CLOB", "TEXT")) or not text:
        return {"kind": "text"}
    if "BLOB" in text:
        return None
    return {"kind": "number"}  # (REAL, FLOAT, DOUBLE, NUMERIC...)


def declared_of(kind, strict=False):
    """The SQL type a new column of kind is made with (what kind_of() reads back as kind).
    strict: for a STRICT table, which knows only INTEGER, REAL, TEXT, BLOB and ANY."""
    if strict:
        if kind.kind == "check" or (kind.kind == "number" and kind.decimals == 0):
            return "INTEGER"
        return "REAL" if kind.kind == "number" else "TEXT"
    if kind.kind == "money":
        return f"DECIMAL(18,{kind.decimals})"
    if kind.kind == "number":
        return "INTEGER" if kind.decimals == 0 else "REAL"
    if kind.kind == "text" and kind.max_length is not None:
        return f"VARCHAR({kind.max_length})"
    return {"check": "BOOLEAN", "date": "DATE", "time": "TIME", "datetime": "DATETIME"}.get(kind.kind, "TEXT")


def to_db(kind, value):
    """A value as it's written to SQLite: money as text (exact: a DECIMAL column keeps it as a
    number, read back to the cent), dates and times as ISO text, a tick as 1 or 0."""
    if value is None:
        return None
    if kind.kind == "money":
        return kind.text(value)
    if kind.kind == "check":
        return 1 if value else 0
    if kind.kind in ("date", "time", "datetime"):
        return kind.text(value)
    if kind.kind in ("text", "choice"):
        return str(value)
    return value


def from_db(kind, value):
    """A value read from SQLite, as kind holds it. ValueError if it can't be: SQLite keeps
    anything in any column (text in a number one, a Unix timestamp in a date one)."""
    if value is None:
        return None
    if isinstance(value, bytes):
        raise ValueError(f"{kind.name}: {len(value)} bytes of data, not a {kind.kind}")
    if kind.kind in ("date", "time", "datetime") and not isinstance(value, str):
        raise ValueError(f"{kind.name}: {value!r} isn't a {kind.kind} written as text (a timestamp?)")
    if kind.kind == "text" and not isinstance(value, str):
        return str(value)
    return kind.convert(value)


def guess(values):
    """A definition for a query's column that isn't a table's (no schema to read it from),
    from its values: a number, a date or time (as ISO text has them), or text; None for BLOBs."""
    known = [v for v in values if v is not None]
    if any(isinstance(v, bytes) for v in known):
        return None
    if known and all(isinstance(v, int) for v in known):
        return {"kind": "number", "decimals": 0}
    if known and all(isinstance(v, (int, float)) for v in known):
        return {"kind": "number"}
    if known and all(isinstance(v, str) for v in known):
        for kind, reading in (("date", datetime.date.fromisoformat), ("time", datetime.time.fromisoformat),
                              ("datetime", datetime.datetime.fromisoformat)):
            try:
                if all(reading(v) is not None and (kind != "datetime" or len(v) > 10) for v in known):
                    return {"kind": kind}
            except ValueError:
                pass
    return {"kind": "text"}


# ----- a table's schema -----

@dataclass
class SchemaColumn:
    name: str
    declared: str
    notnull: bool
    default: str | None  # (as SQL writes it: 'Food', 1, CURRENT_TIMESTAMP)
    pk: int  # its place in the primary key (1, 2...), or 0
    unique: bool = False


@dataclass
class Schema:
    """What SQLite says of a table: its columns, its key, whether it's a view."""

    name: str
    columns: list = field(default_factory=list)
    view: bool = False
    rowid: bool = True  # (a WITHOUT ROWID table has none)
    strict: bool = False

    @property
    def keys(self):
        """The key's columns, in order: its primary key's, or rowid if it has none."""
        found = sorted((c for c in self.columns if c.pk), key=lambda c: c.pk)
        return [c.name for c in found] or ([AUTONUMBER] if self.rowid and not self.view else [])

    @property
    def autonumber(self):
        """The key SQLite numbers itself (an INTEGER PRIMARY KEY, or rowid), or None."""
        found = [c for c in self.columns if c.pk]
        if not self.rowid or self.view:
            return None
        if not found:
            return AUTONUMBER
        if len(found) == 1 and found[0].declared.strip().upper() == "INTEGER":
            return found[0].name
        return None

    def column(self, name):
        return next((c for c in self.columns if c.name.lower() == str(name).lower()), None)


def table_named(connection, name):
    """The name of the table (or view) called name (case aside), as the database has it; None
    if there's none."""
    found = connection.execute("SELECT name FROM sqlite_master WHERE type IN ('table', 'view') AND "
                               "lower(name) = lower(?)", (str(name),)).fetchone()
    return found[0] if found else None


def read_schema(connection, table):
    """A table's schema (or a view's). ValueError if there's no such table."""
    found = connection.execute("SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'view') AND "
                               "lower(name) = lower(?)", (table,)).fetchone()
    if found is None:
        raise ValueError(f"the database has no table {table!r}")
    kind, name, sql = found
    tail = []
    if kind == "table":
        _, _, after = _items(_tokens(sql))
        tail = [t.upper() for t in _significant(after)]
    schema = Schema(name, view=kind == "view", rowid=kind == "table" and "ROWID" not in tail, strict="STRICT" in tail)
    for _, column, declared, notnull, default, pk in connection.execute(f"PRAGMA table_info({quote(name)})"):
        schema.columns.append(SchemaColumn(column, declared or "", bool(notnull), default, pk))
    for _, index, unique, origin, _ in connection.execute(f"PRAGMA index_list({quote(name)})"):
        if unique and origin in ("u", "c"):  # (UNIQUE in its definition, or a unique index, on one column)
            names = [row[2] for row in connection.execute(f"PRAGMA index_info({quote(index)})")]
            column = schema.column(names[0]) if len(names) == 1 else None
            if column is not None and not column.pk:
                column.unique = True
    return schema


def definition_of(schema, column):
    """A schema column's definition (a dict): its kind from its declared type, required from
    NOT NULL, default from a constant DEFAULT, unique, key. An autonumbered key is readonly,
    and empty on a new row till it's saved (the database numbers it). None for a BLOB."""
    if column == AUTONUMBER and schema.autonumber == AUTONUMBER and not schema.column(AUTONUMBER):
        return {"name": AUTONUMBER, "kind": "number", "decimals": 0, "readonly": True, "unique": True,
                "hidden": True}
    found = schema.column(column)
    made = kind_of(found.declared)
    if made is None:
        return None
    definition = {"name": found.name, **made}
    if found.name == schema.autonumber:
        return {**definition, "readonly": True, "unique": True}
    if found.pk:
        definition["key"] = True
    else:
        if found.notnull:
            definition["required"] = True
        if found.unique:
            definition["unique"] = True
    constant = _constant(found.default)
    if constant is not None:
        definition["default"] = constant
    return definition


def _constant(default):
    """A DEFAULT's value if it's a constant ('Food', 1, 2.5), else None (CURRENT_TIMESTAMP and
    other expressions are the database's to work out)."""
    if default is None:
        return None
    text = default.strip()
    if len(text) >= 2 and text[0] == text[-1] == "'":
        return text[1:-1].replace("''", "'")
    for making in (int, float):
        try:
            return making(text)
        except ValueError:
            pass
    return None


# ----- reading rows -----

@dataclass
class Reading:
    """What load_sql() read: the rows' columns (their names), the rows (as SQLite gave them),
    and the schema of the table they're saved to (None for a query's or a view's rows, with
    no table= to save them to)."""

    names: list
    rows: list
    schema: Schema | None

    def definitions(self):
        """Each column's definition and origin: (a dict, its database column's name) for a
        table's column; (a guessed dict, readonly, OWN) for one of a query's that isn't the
        table's; (None, None) for one left out (BLOBs)."""
        found = []
        for i, name in enumerate(self.names):
            if self.schema is not None and (self.schema.column(name) or name.lower() == AUTONUMBER):
                definition = definition_of(self.schema, name)
                found.append((definition, None if definition is None else name))
                continue
            definition = guess(row[i] for row in self.rows)
            found.append((None, None) if definition is None else ({"name": name, **definition, "readonly": True}, OWN))
        return found


def connect(path):
    """A database file opened for a DataTable, its foreign keys enforced (SQLite leaves them
    off). FileNotFoundError if it isn't there."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"no database {path}")
    return open_database(path)


def open_database(path):
    """A database file opened (made, if it isn't there), its foreign keys enforced."""
    connection = sqlite3.connect(path)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def read(connection, source, params=(), table=None):
    """The rows of source: a table's (or a view's) name, or a query (SELECT ..., with ? for
    params). table: the table a query's (or view's) rows are saved to; they need its key."""
    named = table_named(connection, source) if not params else None
    if named is not None:
        schema = read_schema(connection, named)
        names = [c.name for c in schema.columns if kind_of(c.declared) is not None]
        if schema.autonumber == AUTONUMBER and not schema.column(AUTONUMBER):
            names.append(AUTONUMBER)  # (last: rows given as lists still fill the columns shown)
        rows = connection.execute(f"SELECT {', '.join(quote(n) for n in names)} FROM {quote(named)}").fetchall()
        if table is not None and table_named(connection, table) != named:
            schema = read_schema(connection, table)
        reading = Reading(names, rows, schema)
    else:
        cursor = connection.execute(source, params)
        if cursor.description is None:
            raise ValueError(f"{source!r} isn't a query (SELECT ...) or a table's name")
        names = [d[0] for d in cursor.description]
        reading = Reading(names, cursor.fetchall(), read_schema(connection, table) if table is not None else None)
    schema = reading.schema
    if schema is not None and schema.view:
        if table is not None:
            raise ValueError(f"{schema.name} is a view: rows are saved to a table")
        reading.schema = None  # (a view's rows: shown, not saved)
    elif schema is not None:
        missing = [k for k in schema.keys if k.lower() not in {n.lower() for n in reading.names}]
        if missing:
            raise ValueError(f"to be saved to {schema.name}, the rows need its key: "
                             f"SELECT {', '.join(map(quote, missing))}, ...")
    return reading


# ----- the rows, as loaded and now -----

@dataclass(frozen=True)
class Mismatch:
    """A value load_sql() found that isn't its column's kind (text in a number column, say):
    the column was loaded as text, so it's shown as it is. row and column: where it is; value:
    as the database has it; declared: the column's type there ("INTEGER")."""

    row: int
    column: str
    value: object
    declared: str


@dataclass
class _Loaded:
    row: list  # the DataTable's row (its list: it's the same row as long as that is)
    values: list  # its values as loaded (or last saved), a cell for each column then
    raw: dict  # its database columns' values as SQLite has them (by lowercase name)


@dataclass
class Changes:
    """What's changed since the rows were loaded (or last saved): added and edited are row
    numbers; deleted, the deleted rows as they were loaded (dicts by column name); columns,
    the changes to the database's columns: ("add", name), ("rename", old, new), ("drop",
    name), ("change", name). False when nothing has changed."""

    added: list = field(default_factory=list)
    edited: list = field(default_factory=list)
    deleted: list = field(default_factory=list)
    columns: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.added or self.edited or self.deleted or self.columns)


@dataclass
class _Plan:
    """What a save does, worked out from the changes."""

    drops: list  # database columns taken away
    renames: list  # (old, new)
    adds: list  # column numbers (in kinds) of new columns
    alters: dict  # name -> its changes ("type", "notnull", "unique", "default": the new ones)
    deleted: list  # _Loaded
    edited: list  # (row number, _Loaded, column numbers changed)
    added: list  # row numbers


class Binding:
    """Where a DataTable's rows came from (a database, a table or a query), and how they were
    then: to find what's changed, and save it. A DataTable's origins (one for each column)
    say where each column's values are in the database: its column's name (as loaded), None
    for a column new since (added when saved, unless it has a formula), or OWN."""

    def __init__(self, connection, owned, schema, source, params=()):
        self.connection, self.owned = connection, owned  # (owned: opened from a path, so closed by us)
        self.path = None  # (the database file's, if it was opened from one)
        self.schema = schema
        self.source, self.params = source, params
        self.kinds, self.origins, self.loaded = [], [], {}

    @property
    def table(self):
        """The table the rows are saved to, or None (a query's or a view's rows)."""
        return self.schema.name if self.schema is not None else None

    def close(self):
        if self.owned:
            self.connection.close()

    def remember(self, kinds, origins, data, raw):
        """The rows as they are now, as loaded (or saved). raw: each row's database values
        (a dict by lowercase name), by id(row); a row left out keeps those it had."""
        old = self.loaded
        self.kinds, self.origins = list(kinds), list(origins)
        self.loaded = {id(row): _Loaded(row, list(row), raw[id(row)] if id(row) in raw else old[id(row)].raw)
                       for row in data if id(row) in raw or id(row) in old}

    def _loaded_place(self):
        return {o.lower(): i for i, o in enumerate(self.origins) if isinstance(o, str)}

    def _edited_columns(self, kinds, origins, row, loaded):
        """The columns of a loaded row changed since: its database columns', and new ones'
        (not their default: what a new column gives every row)."""
        place = self._loaded_place()
        found = []
        for i, (kind, origin) in enumerate(zip(kinds, origins)):
            if origin is None and kind.formula is None:
                if row[i] != kind.default:
                    found.append(i)
            elif isinstance(origin, str) and origin.lower() != AUTONUMBER and origin.lower() in place:
                if row[i] != loaded.values[place[origin.lower()]]:
                    found.append(i)
        return found

    def _row_changes(self, kinds, origins, data):
        present = {id(row) for row in data}
        deleted = [loaded for key, loaded in self.loaded.items() if key not in present]
        edited, added = [], []
        for r, row in enumerate(data):
            loaded = self.loaded.get(id(row))
            if loaded is None:
                added.append(r)
            else:
                columns = self._edited_columns(kinds, origins, row, loaded)
                if columns:
                    edited.append((r, loaded, columns))
        return deleted, edited, added

    def _column_changes(self, kinds, origins):
        """(drops, renames, adds, alters): the changes to the database's columns."""
        if self.schema is None:
            return [], [], [], {}
        now = {o.lower() for o in origins if isinstance(o, str)}
        drops = [o for o in self.origins if isinstance(o, str) and o.lower() != AUTONUMBER and o.lower() not in now]
        renames, alters = [], {}
        place = self._loaded_place()
        for kind, origin in zip(kinds, origins):
            if not isinstance(origin, str) or origin.lower() == AUTONUMBER:
                continue
            if kind.name.lower() != origin.lower():
                renames.append((origin, kind.name))
            if origin.lower() in place:
                changes = _altered(self.kinds[place[origin.lower()]], kind, self.schema.strict)
                if changes:
                    alters[kind.name] = changes
        adds = [i for i, (kind, origin) in enumerate(zip(kinds, origins)) if origin is None and kind.formula is None]
        for i in adds:  # (ADD COLUMN can't make a column NOT NULL or UNIQUE: a rebuild does)
            kind = kinds[i]
            changes = {k: True for k, wanted in (("notnull", kind.required), ("unique", kind.unique)) if wanted}
            if changes:
                alters[kind.name] = changes
        return drops, renames, adds, alters

    def changes(self, kinds, origins, data):
        deleted, edited, added = self._row_changes(kinds, origins, data)
        drops, renames, adds, alters = self._column_changes(kinds, origins)
        new = {kinds[i].name for i in adds}
        columns = ([("drop", name) for name in drops] + [("rename", old, name) for old, name in renames]
                   + [("add", kinds[i].name) for i in adds] + [("change", name) for name in alters if name not in new])
        return Changes(added=added, edited=[r for r, _, _ in edited], columns=columns,
                       deleted=[{k.name: v for k, v in zip(self.kinds, loaded.values)} for loaded in deleted])

    # ----- saving -----

    def save(self, kinds, origins, data, overwrite=False):
        """Save the changes: the columns' first, then the rows' (deleted, edited, added). The
        rows written are read back: returns ({id(row): their database values}, the origins
        the columns have now: a new column's is its name). ConflictError, nothing saved, for
        rows changed by someone else since they were loaded (unless overwrite)."""
        schema = self.schema
        if schema is None:
            raise ValueError("these rows came from a query (or a view), with no table to save them to: "
                             "load_sql(..., table=\"its table\") says which")
        for key in schema.keys:
            if key.lower() not in {o.lower() for o in origins if isinstance(o, str)}:
                raise ValueError(f"{schema.name}'s key, {key}, isn't one of the columns now: the rows can't be "
                                 "saved without it")
        drops, renames, adds, alters = self._column_changes(kinds, origins)
        keys = {k.lower() for k in schema.keys}
        place = self._loaded_place()
        for kind, origin in zip(kinds, origins):
            if not isinstance(origin, str) or origin.lower() not in place:
                continue
            if origin.lower() in keys and kind.name in alters:
                raise ValueError(f"{kind.name} is {schema.name}'s key: its kind and rules stay as they are")
            if origin.lower() != AUTONUMBER and kind.key != self.kinds[place[origin.lower()]].key:
                raise ValueError(f"{kind.name}: a table's key (its primary key) stays as it is")
        for i in adds:
            if kinds[i].key:
                raise ValueError(f"{kinds[i].name}: a new column can't be the table's key (its primary key "
                                 "stays as it is)")
        deleted, edited, added = self._row_changes(kinds, origins, data)
        plan = _Plan(drops, renames, adds, alters, deleted, edited, added)
        structure = bool(drops or renames or adds or alters)
        with transaction(self.connection, foreign_keys_off=bool(alters)):
            self._check_conflicts(plan, overwrite)
            self._change_columns(plan, kinds)
            found = self._write_rows(plan, kinds, origins, data)
            now = [kind.name if (isinstance(origin, str) and origin.lower() != AUTONUMBER) or i in adds else origin
                   for i, (kind, origin) in enumerate(zip(kinds, origins))]
            raw = self._read_back(now, data, found, everything=structure)
        self.schema = read_schema(self.connection, schema.name)
        return raw, now

    def _check_conflicts(self, plan, overwrite):
        """ConflictError if a row to be written (or deleted) isn't as it was loaded."""
        if overwrite:
            return
        names = [o for o in self.origins if isinstance(o, str)]
        kinds = [self.kinds[self.origins.index(o)] for o in names]
        keys = self.schema.keys
        select = (f"SELECT {', '.join(map(quote, names))} FROM {quote(self.schema.name)} WHERE "
                  + " AND ".join(f"{quote(k)} = ?" for k in keys))
        conflicts = []
        for number, loaded in [(None, loaded) for loaded in plan.deleted] + [(r, loaded) for r, loaded, _ in plan.edited]:
            now = self.connection.execute(select, [loaded.raw.get(k.lower()) for k in keys]).fetchone()
            if now is None or list(now) != [loaded.raw.get(n.lower()) for n in names]:
                values = None if now is None else {k.name: _readable(k, v) for k, v in zip(kinds, now)}
                conflicts.append((number, values))
        if conflicts:
            raise ConflictError(self.schema.name, conflicts)

    def _change_columns(self, plan, kinds):
        connection, table = self.connection, quote(self.schema.name)
        for name in plan.drops:
            connection.execute(f"ALTER TABLE {table} DROP COLUMN {quote(name)}")
        renames = plan.renames
        if len(renames) > 1:  # (by way of names nobody has: a swap, A to B and B to A, works too)
            passing = [(old, f"_readymade_{i}_{old}") for i, (old, _) in enumerate(renames)]
            for old, temporary in passing:
                connection.execute(f"ALTER TABLE {table} RENAME COLUMN {quote(old)} TO {quote(temporary)}")
            renames = [(temporary, new) for (_, temporary), (_, new) in zip(passing, renames)]
        for old, new in renames:
            connection.execute(f"ALTER TABLE {table} RENAME COLUMN {quote(old)} TO {quote(new)}")
        for i in plan.adds:
            kind = kinds[i]
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {quote(kind.name)} "
                               f"{declared_of(kind, self.schema.strict)}"
                               + (f" DEFAULT {default_of(kind)}" if kind.default is not None else ""))
        if plan.alters:
            _rebuild(connection, self.schema.name, plan.alters)

    def _write_rows(self, plan, kinds, origins, data):
        """Delete, update, insert: {id(row): how it's found again} for the rows written."""
        connection, table, schema = self.connection, quote(self.schema.name), self.schema
        renamed = {old.lower(): new for old, new in plan.renames}
        keys = [renamed.get(k.lower(), k) for k in schema.keys]  # (the key's names now)
        where = " AND ".join(f"{quote(k)} = ?" for k in keys)
        writable = [i for i, origin in enumerate(origins) if isinstance(origin, str) and origin.lower() != AUTONUMBER]
        writable += plan.adds
        numbered = (schema.autonumber or "").lower()  # (the database's: not written over)
        key_columns = {kinds[i].name.lower(): i for i in writable
                       if kinds[i].name.lower() in {k.lower() for k in keys} and kinds[i].name.lower() != numbered}

        def key_now(row, loaded):
            return ("key", [to_db(kinds[key_columns[k.lower()]], row[key_columns[k.lower()]]) if k.lower() in key_columns
                            else loaded.raw.get(old.lower()) for k, old in zip(keys, schema.keys)])

        found = {}
        for loaded in plan.deleted:
            _run(connection, f"DELETE FROM {table} WHERE {where}", [loaded.raw.get(k.lower()) for k in schema.keys],
                 "a row deleted")
        for r, loaded, columns in plan.edited:
            sets = [i for i in columns if i in writable and kinds[i].name.lower() != numbered]
            if sets:
                _run(connection, f"UPDATE {table} SET {', '.join(f'{quote(kinds[i].name)} = ?' for i in sets)} "
                                 f"WHERE {where}",
                     [to_db(kinds[i], data[r][i]) for i in sets] + [loaded.raw.get(k.lower()) for k in schema.keys],
                     f"row {r}")
                found[id(data[r])] = key_now(data[r], loaded)
        for r in plan.added:
            row = data[r]
            given = [i for i in writable if row[i] is not None]  # (empty ones left out: the database's defaults)
            cursor = _run(connection, _insert(table, [kinds[i].name for i in given]),
                          [to_db(kinds[i], row[i]) for i in given], f"row {r}")
            found[id(row)] = ("rowid", [cursor.lastrowid]) if schema.rowid else key_now(row, None)
        return found

    def _read_back(self, origins, data, found, everything):
        """The rows' database values now: those written (found by their keys), or every row's
        when the columns changed (a column's values may be kept differently)."""
        connection = self.connection
        names = [o for o in origins if isinstance(o, str)]
        keys = read_schema(connection, self.schema.name).keys
        select = f"SELECT {', '.join(map(quote, names))} FROM {quote(self.schema.name)} WHERE "
        raw = {}
        for row in data:
            how = found.get(id(row))
            if how is None:
                loaded = self.loaded.get(id(row))
                if not everything or loaded is None:
                    continue
                how = ("key", [loaded.raw.get(k.lower()) for k in self.schema.keys])
            sql = select + ("rowid = ?" if how[0] == "rowid" else " AND ".join(f"{quote(k)} = ?" for k in keys))
            values = connection.execute(sql, how[1]).fetchone()
            if values is not None:
                raw[id(row)] = {n.lower(): v for n, v in zip(names, values)}
        return raw


def _insert(table, names):
    if not names:
        return f"INSERT INTO {table} DEFAULT VALUES"
    return f"INSERT INTO {table} ({', '.join(map(quote, names))}) VALUES ({', '.join('?' * len(names))})"


def _readable(kind, value):
    try:
        return from_db(kind, value)
    except ValueError:
        return value


def _run(connection, sql, values, what):
    """A statement, a database error saying which row it was for."""
    try:
        return connection.execute(sql, values)
    except sqlite3.Error as e:
        raise type(e)(f"{what}: {e}") from e


def _altered(was, now, strict):
    """What's changed between two definitions of a column, as the database keeps it: its
    declared type, NOT NULL, UNIQUE, DEFAULT ({} if nothing: a header, a format, a choice's
    choices, min and max are the DataTable's own)."""
    changes = {}
    if kind_of(declared_of(was, strict)) != kind_of(declared_of(now, strict)):
        changes["type"] = declared_of(now, strict)
    if was.required != now.required:
        changes["notnull"] = now.required
    if was.unique != now.unique:
        changes["unique"] = now.unique
    if was.default != now.default:  # (0 and Decimal("0.00") alike)
        changes["default"] = default_of(now) if now.default is not None else None
    return changes


# ----- transactions -----

@contextmanager
def transaction(connection, foreign_keys_off=False):
    """BEGIN IMMEDIATE (the database's write lock first, waiting a while for another program's
    save) ... COMMIT, or ROLLBACK if anything fails. foreign_keys_off: for a rebuild (as SQLite
    does it), the foreign keys checked once it's done."""
    if getattr(connection, "autocommit", -1) is False:
        raise ValueError("a connection made with autocommit=False always has a transaction open: connect without it")
    if connection.in_transaction:
        raise ValueError("the database connection has changes not committed: commit() (or rollback()) first")
    isolation = connection.isolation_level
    connection.isolation_level = None  # (the statements as written: this BEGIN, this COMMIT)
    timeout = connection.execute("PRAGMA busy_timeout").fetchone()[0]
    keys = connection.execute("PRAGMA foreign_keys").fetchone()[0] if foreign_keys_off else 0
    try:
        connection.execute(f"PRAGMA busy_timeout = {BUSY_SECONDS * 1000}")
        if keys:
            connection.execute("PRAGMA foreign_keys = OFF")  # (it can't change inside a transaction)
        connection.execute("BEGIN IMMEDIATE")
        try:
            yield connection
            if keys:
                broken = connection.execute("PRAGMA foreign_key_check").fetchone()
                if broken:
                    raise sqlite3.IntegrityError(f"FOREIGN KEY constraint failed: a row of {broken[0]} refers to "
                                                 f"no row of {broken[2]}")
        except BaseException:
            connection.execute("ROLLBACK")
            raise
        connection.execute("COMMIT")
    finally:
        if keys:
            connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(f"PRAGMA busy_timeout = {timeout}")
        connection.isolation_level = isolation


# ----- rebuilding a table (a column's type or rules changed) -----

_TOKEN = re.compile(r"""\s+|--[^\n]*|/\*.*?(?:\*/|$)|"(?:[^"]|"")*"|`(?:[^`]|``)*`|\[[^\]]*\]|'(?:[^']|'')*'|[(),]"""
                    r"""|[^\s(),'"`\[]+""", re.DOTALL)
_STARTS = {"CONSTRAINT", "PRIMARY", "NOT", "NULL", "UNIQUE", "CHECK", "DEFAULT", "COLLATE", "REFERENCES",
           "GENERATED", "AS"}  # (what begins a column's constraint)
_TABLE_CONSTRAINTS = {"CONSTRAINT", "PRIMARY", "UNIQUE", "CHECK", "FOREIGN"}


def _tokens(sql):
    return _TOKEN.findall(sql)


def _significant(tokens):
    return [t for t in tokens if not (t.isspace() or t.startswith(("--", "/*")))]


def _unquoted(token):
    if token[:1] in ('"', "`") and token[-1:] == token[:1]:
        return token[1:-1].replace(token[0] * 2, token[0])
    if token[:1] == "[" and token[-1:] == "]":
        return token[1:-1]
    return token


def _word(token):
    """A keyword's token, in capitals (None for a quoted name or a string)."""
    return token.upper() if token[:1] not in ('"', "`", "[", "'") else None


def _items(tokens):
    """A CREATE TABLE's tokens split: (before its definitions, [each definition's tokens],
    after them: WITHOUT ROWID, STRICT)."""
    start = tokens.index("(")
    depth, items, current = 0, [], []
    for i in range(start, len(tokens)):
        token = tokens[i]
        if token == "(":
            depth += 1
            if depth == 1:
                continue
        elif token == ")":
            depth -= 1
            if depth == 0:
                items.append(current)
                return tokens[:start], items, tokens[i + 1:]
        elif token == "," and depth == 1:
            items.append(current)
            current = []
            continue
        current.append(token)
    raise ValueError("the table's definition (its CREATE TABLE) couldn't be read")


def _parts(tokens):
    """A column definition's tokens split: (its name, its type's tokens, [each constraint's
    tokens]), the spaces between kept (so each is as it was written)."""
    words = _significant(tokens)
    name = words[0]
    rest = tokens[tokens.index(name) + 1:]
    groups, depth, current, kind, previous = [], 0, [], [], None
    for token in rest:
        if token not in words:  # (a space, a comment: with what's before it)
            (current or kind).append(token)
            continue
        word = _word(token)
        starts = depth == 0 and word in _STARTS
        if starts and current and _what(current[:1]) == "REFERENCES":  # (ON DELETE SET NULL, NOT DEFERRABLE)
            starts = not (word == "NOT" or (word in ("NULL", "DEFAULT") and previous == "SET"))
        if starts and current and _word(current[0]) == "CONSTRAINT" and len(_significant(current)) == 2:
            starts = False  # (CONSTRAINT name NOT NULL: one)
        if starts:
            if current:
                groups.append(current)
            current = [token]
        elif current:
            current.append(token)
        else:
            kind.append(token)
        depth += (token == "(") - (token == ")")
        previous = word
    if current:
        groups.append(current)
    return name, kind, groups


def _what(group):
    """What a constraint is: its first word, after CONSTRAINT name."""
    words = [_word(t) for t in _significant(group)]
    if words and words[0] == "CONSTRAINT":
        words = words[2:]
    return words[0] if words else ""


def _altered_definition(tokens, changes):
    """A column's definition with its type, NOT NULL, UNIQUE or DEFAULT changed (the rest as
    it was written)."""
    name, kind, groups = _parts(tokens)
    if "type" in changes:
        kind = [changes["type"]]
    dropping = {what for setting, whats in (("notnull", ("NOT", "NULL")), ("unique", ("UNIQUE",)),
                                            ("default", ("DEFAULT",))) if setting in changes for what in whats}
    kept = ["".join(group).strip() for group in groups if _what(group) not in dropping]
    added = ["NOT NULL"] * bool(changes.get("notnull")) + ["UNIQUE"] * bool(changes.get("unique"))
    if changes.get("default") is not None:
        added.append(f"DEFAULT {changes['default']}")
    leading = "".join(tokens[:tokens.index(name)]) or " "  # (on its line, as it was)
    return leading + " ".join(part for part in [name, "".join(kind).strip(), *kept, *added] if part)


def _one_column(words):
    """The column a UNIQUE (column) is about, lowercase; None if it's several."""
    if "(" not in words or ")" not in words:
        return None
    inside = [w for w in words[words.index("(") + 1:words.index(")")] if w != ","]
    names = [_unquoted(w).lower() for w in inside if _word(w) not in ("ASC", "DESC", "COLLATE")]
    return names[0] if len(names) == 1 else None


def _rebuild(connection, table, alters):
    """Rebuild table with some columns' definitions changed (alters: name -> changes), as
    SQLite says to (sqlite.org/lang_altertable.html, "Making Other Kinds Of Table Schema
    Changes"): a new table from its own CREATE TABLE, changed; every row copied across; the
    old one dropped; the new one renamed; its indexes and triggers made again. Its CHECKs,
    foreign keys, collations and columns not loaded are carried across as they were."""
    sql = connection.execute("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)).fetchone()[0]
    _, items, after = _items(_tokens(sql))
    wanted = {name.lower(): changes for name, changes in alters.items()}
    not_unique = {name for name, changes in wanted.items() if changes.get("unique") is False}
    made, found = [], set()
    for item in items:
        words = _significant(item)
        if not words:
            continue
        if _word(words[0]) in _TABLE_CONSTRAINTS:
            if _what(words) == "UNIQUE" and _one_column(words) in not_unique:
                continue  # (UNIQUE (column), for a column no longer so)
            made.append("".join(item))
            continue
        name = _unquoted(words[0]).lower()
        if name in wanted:
            found.add(name)
            made.append(_altered_definition(item, wanted[name]))
        else:
            made.append("".join(item))
    missing = set(wanted) - found
    if missing:
        raise ValueError(f"{table}: its definition has no column {', '.join(sorted(missing))} to change")
    temporary = f"_readymade_new_{table}"
    columns = ", ".join(quote(row[1]) for row in connection.execute(f"PRAGMA table_info({quote(table)})"))
    others = connection.execute("SELECT type, sql FROM sqlite_master WHERE tbl_name = ? AND type IN "
                                "('index', 'trigger') AND sql IS NOT NULL", (table,)).fetchall()
    sequence = None
    if connection.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone():
        sequence = connection.execute("SELECT seq FROM sqlite_sequence WHERE name = ?", (table,)).fetchone()
    connection.execute(f"CREATE TABLE {quote(temporary)} ({','.join(made)}){''.join(after)}")
    connection.execute(f"INSERT INTO {quote(temporary)} ({columns}) SELECT {columns} FROM {quote(table)}")
    connection.execute(f"DROP TABLE {quote(table)}")
    legacy = connection.execute("PRAGMA legacy_alter_table").fetchone()[0]
    connection.execute("PRAGMA legacy_alter_table = ON")  # (views and triggers name the old one: so they stay)
    try:
        connection.execute(f"ALTER TABLE {quote(temporary)} RENAME TO {quote(table)}")
    finally:
        connection.execute(f"PRAGMA legacy_alter_table = {'ON' if legacy else 'OFF'}")
    for kind, statement in others:
        words = _significant(_tokens(statement))
        if kind == "index" and _word(words[1]) == "UNIQUE" and _one_column(words) in not_unique:
            continue  # (a unique index on a column no longer unique)
        connection.execute(statement)
    if sequence is not None:  # (AUTOINCREMENT's highest number so far, as it was)
        connection.execute("UPDATE sqlite_sequence SET seq = max(seq, ?) WHERE name = ?", (sequence[0], table))


# ----- a new table, from a DataTable -----

def create(connection, table, kinds, data, columns, replace=False):
    """A new table made from some columns' definitions (columns: their numbers in kinds), and
    the rows (data) written to it. ValueError if there's a table so called already, unless
    replace (it's dropped first). A single key that's a number is SQLite's own (INTEGER
    PRIMARY KEY): numbered for a new row without one. Returns {id(row): its database values}
    (rowid too) and the table's schema."""
    existing = table_named(connection, table)
    if existing is not None and not replace:
        raise ValueError(f"the database has a table {existing} already: save_sql(..., replace=True) replaces it")
    chosen = [kinds[i] for i in columns]
    keys = [kind for kind in chosen if kind.key]
    definitions = []
    for kind in chosen:
        if len(keys) == 1 and kind.key:
            declared = "INTEGER PRIMARY KEY" if kind.kind == "number" else f"{declared_of(kind)} PRIMARY KEY"
        else:
            declared = declared_of(kind)
        rules = ["NOT NULL"] * (kind.required and not kind.key) + ["UNIQUE"] * (kind.unique and not kind.key)
        if kind.default is not None:
            rules.append(f"DEFAULT {default_of(kind)}")
        definitions.append(" ".join([quote(kind.name), declared, *rules]))
    if len(keys) > 1:
        definitions.append(f"PRIMARY KEY ({', '.join(quote(k.name) for k in keys)})")
    names = ", ".join(quote(k.name) for k in chosen)
    raw = {}
    with transaction(connection):
        if existing is not None:
            connection.execute(f"DROP TABLE {quote(existing)}")
        connection.execute(f"CREATE TABLE {quote(table)} ({', '.join(definitions)})")
        for r, row in enumerate(data):
            given = [i for i in columns if row[i] is not None]
            cursor = _run(connection, _insert(quote(table), [kinds[i].name for i in given]),
                          [to_db(kinds[i], row[i]) for i in given], f"row {r}")
            values = connection.execute(f"SELECT {names}, rowid FROM {quote(table)} WHERE rowid = ?",
                                        (cursor.lastrowid,)).fetchone()
            raw[id(row)] = {**{k.name.lower(): v for k, v in zip(chosen, values)}, AUTONUMBER: values[-1]}
    return raw, read_schema(connection, table)
