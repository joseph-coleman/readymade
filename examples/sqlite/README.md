# An inventory in an SQLite database

A DataTable loaded from a database table, edited like a spreadsheet, and saved back. Open it
in the IDE:

    readymade examples/sqlite

and press **F5**. The first time it runs, it makes **inventory.db** next to Form1.py (see
`make_database()` at the bottom of Form1: two tables, `items` and `categories`). Delete the
file to start over.

SQLite comes with Python (the `sqlite3` module): no server and nothing to install. A
database is one file, which [DB Browser for SQLite](https://sqlitebrowser.org) and other
tools open too.

## Loading: the columns come from the table

```python
odd = self.Items.load_sql("inventory.db", "items")
```

That's all it takes. The DataTable's columns are made from the table's own definition:

| In the database | In the DataTable |
| --- | --- |
| `INTEGER`, `REAL` | a number (`INTEGER`: whole numbers) |
| `DECIMAL(10,2)` | money: exact, a `Decimal`, to the cent |
| `TEXT`, `VARCHAR(40)` | text (`VARCHAR(40)`: `max_length` 40) |
| `DATE`, `TIME`, `DATETIME` | a date, time or datetime |
| `BOOLEAN` | a check (a tick) |
| `NOT NULL` | `required` |
| `UNIQUE` | `unique` |
| `DEFAULT 'Hardware'` | `default`: a new row starts with it |
| `INTEGER PRIMARY KEY` | the key, numbered by the database: `readonly`, and empty on a new row until it's saved |

A table without a key of its own gets a hidden `rowid` column (SQLite's row number), last.
`BLOB` columns (pictures and the like) aren't loaded, and are kept as they are when saving.

In the designer, the table shows a single column, Item: the rest come from the database when
the program runs.

After loading, the program changes how things look, not what's in the database: `id` is
hidden, and Category becomes a choice of the `categories` table's names (it's text in the
database). The table's connection is `self.Items.database`, for queries of the program's own.

**A query** loads any rows: `load_sql("inventory.db", 'SELECT * FROM items WHERE "In stock" <
?', (5,), table="items")`. `table=` says which table they're saved to (the query needs its
key, `id`). A query's columns that aren't the table's (`"Price" * 2 AS twice`) are shown,
readonly, and not saved. Without `table=`, the rows can be shown but not saved.

**Columns of the program's own.** `load_sql(..., columns="keep")` keeps the columns defined in
the designer and fills those the table has, by name. The others (a "Picked" tick, say) are the
program's own and aren't saved. If the key isn't among them, it's added, hidden.

**Values that aren't their column's kind.** SQLite keeps whatever it's given in any column,
so an `INTEGER` column can hold the text `lots`. Nothing is lost or changed: the column is
loaded as text, and `load_sql()` returns what didn't fit, so the program can say so (here, in
the status line). Each is a `Mismatch` with `row`, `column`, `value` and `declared` (the
column's type in the database).

## What's changed

`self.Items.changed` says whether anything has changed since loading (or the last save), and
`changes()` says what: `.edited` and `.added` (row numbers), `.deleted` (the deleted rows, as
they were loaded) and `.columns`. Here `show_changes()` puts them in the status line, with a
`*` in the title, after each change. `revert()` puts everything back as it was loaded. The
rows are compared with how they were loaded, so an edit undone (Ctrl+Z) is no change at all.

## Saving

```python
self.Items.save_sql()
```

The rows added are inserted, those edited are updated (only the cells changed), and those
deleted are deleted, all in one transaction. Either everything is saved or nothing is. Then
the rows saved are read back, so a new row's `id` appears.

What can go wrong is an exception, and the program decides what to do (`save_items()` in
Form1):

- **`DataError`**: a row breaks one of the columns' rules (required, unique...). Nothing is
  saved. `e.problems` lists each cell at fault. Here the cursor goes to the first one.
- **`ConflictError`** (a kind of `DataError`, so catch it first): someone else changed or
  deleted a row in the database since it was loaded. Nothing is saved, so nobody's changes
  are lost without anyone knowing. `e.rows` lists them: the row's number, and its values in
  the database now (`None` if it's gone). Here the program asks: save over theirs
  (`save_sql(overwrite=True)`), or load theirs again.
- **`sqlite3.Error`**: a rule only the database knows. Here the `items` table has `CHECK
  ("Price" >= 0)`, which the DataTable doesn't know about. The message says which row.

**Try a conflict.** Click a row, then **Someone else**. That button changes the row's `In
stock` in the database through a connection of its own, as another program would. The
table still shows the old number. Now edit that row (its Price, say) and **Save**.

**Closing** with changes not saved asks first (`Form_unload`: return `True` to stay open).

A save waits up to 5 seconds while another program is saving to the same database, then
gives up with `sqlite3.OperationalError` ("database is locked").

## Changing the columns keeps the rows

The table's columns can change too, and saving changes the database table to match. Every
row is kept: it's never a delete-and-make-again.

```python
self.Items.columns.append({"name": "Notes", "max_length": 200})  # ALTER TABLE ... ADD COLUMN
self.Items.columns["Counted"].name = "Last counted"               # ... RENAME COLUMN
del self.Items.columns["Reorder at"]                              # ... DROP COLUMN
self.Items.columns["In stock"].kind = "money"                     # a new type: the table rebuilt
self.Items.save_sql()
```

Adding, renaming and deleting a column are done in place. A new type, or a rule changed
(`required`, `unique`, `default`), needs the table rebuilt, the way SQLite's documentation
says to: a new table is made from the old one's own definition, with only that column
changed. The rows are copied across, and the indexes and triggers are made again. Its CHECKs,
foreign keys and the columns the DataTable didn't load stay as they were.

Some changes are only the DataTable's: a header, hidden, a format, choices, min and max. The
database doesn't change for those. A new column with a `formula` isn't added either, since
it's worked out. The table's key stays as it is.

## A new table

```python
self.Items.save_sql("backup.db", "items")  # every row, in a new table made from the columns
```

This makes the table from the columns' definitions. It's a `ValueError` if the table is
there already, unless `replace=True` drops it first. Afterwards the DataTable belongs to the
new table, so `save_sql()` saves there. A program can start with no database at all: define
the columns in the designer, then `save_sql("my data.db", "things")` makes the database file,
and the table in it.
