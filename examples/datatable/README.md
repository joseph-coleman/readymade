# An order sheet in a DataTable

A DataTable holds rows of values under typed columns, edited like a spreadsheet. Open it in the IDE:

    readymade examples/datatable

and press **F5**. The code is in **Form1** (F7 on the form).

## A database table, not a spreadsheet

The keys work as in a spreadsheet, but the data is a database table's (an Access datasheet's,
say). In Excel every cell holds whatever is typed in it. Here each **column** has a kind:
Price holds money, Qty numbers, Taxable ticks, Category one of its choices. Every row's cell
in that column is that kind, or empty: `None`, as a database's NULL.

A new row starts empty, but for the columns with a `default`: here Qty 1 and Taxable ticked.
Paste one price onto the blank row at the bottom and the new row shows Qty 1, a tick and a
Total (worked out from the price and the Qty), and nothing else: Item, Category and the rest
are empty, as nothing was given for them.

## The columns

Select the table in the designer and look at `columns` in the Properties panel: each column's
definition, one per line. A simple one is a line (`Total : money, readonly`); one with more to
say is a dict, as JSON:

    {"name": "Item", "required": true, "max_length": 30}
    {"name": "Category", "choices": ["Food", "Hardware", "Garden"]}
    {"name": "Price", "kind": "money", "required": true, "min": 0}
    {"name": "Qty", "kind": "number", "min": 0, "default": 1}
    {"name": "Taxable", "kind": "check", "default": true}
    Total : money, readonly

In code, they're Python dicts, the same: `self.Items.columns = [{"name": "Qty", "kind":
"number", "min": 0}, ...]`. What a definition can say:

- `name`: what code, CSV files and a database call it; `header`: what's shown, if not that.
- `kind`: text (the usual), `number`, `money`, `date`, `time`, `datetime`, `check` (a tick),
  or `choice` (`choices`, a list, says it's one); `decimals` for a number or money, `format`
  for a date or time, `step` for a time's minutes.
- `readonly`: the user can't edit it (code still can).
- `default`: a new row's value. Without one, a new cell is empty (None).
- The rules: `required` (it can't be empty), `min` and `max`, `max_length` (text),
  `unique` (no two rows alike), and `key` (required and unique: what tells rows apart).

A misspelled setting (`requird`) is an error at once, not quietly ignored. A line is a short
way to say the simple ones: a name, then maybe `:` and a kind (`Price : money`, `Size : S |
M | L`, `Qty : number 2`) and `readonly`, in any order.

Values are converted to their column's kind: `"3"` in Qty becomes the number 3, and a value
that can't be raises a ValueError saying which column and value. There are no rows in the
designer: they come from code.

**Columns from code.** `self.Items.columns` is a live list of the definitions, as `rows` is of
the rows:

```python
cols = self.Items.columns
cols.append({"name": "Discount", "kind": "money", "default": 0})  # each row gets its default
cols.insert(1, "Note")              # a line works too
del cols["Note"]                    # by name or number: its values go too
cols["Qty"].max = 50                # one setting, applied at once
cols["Qty"].header = "Quantity"
cols["Price"].kind = "number"       # values converted (empty, those that can't be)
cols["Qty"].values                  # the column's values: the same as self.Items["Qty"]
```

A change that can't be (`min` more than `max`, a name already taken) is refused with a
ValueError, and nothing changes. A rule set now holds for what's written from now on: values
already there that break it show in `problems()`. `self.Items.columns = [...]` replaces them
all at once.

**Money** is exact. A `number 2` column holds a float, and floats can't hold most cents exactly
(2.675 rounds to 2.67, as it's really 2.67499999...). A `money` column holds a
`decimal.Decimal`, kept to the cent (`money 0` for yen), rounding a half up as a receipt does:
2.675 is 2.68. Cells show thousands' commas (1,234.50), and an amount typed or pasted with a
currency sign is fine ($1,234.50). In code, a money value is a Decimal: arithmetic on a Column
of them takes plain numbers (`items["Price"] * 1.1`), but on its own a Decimal won't mix with a
float, so the tax rate here is `Decimal("0.08")`.

**Widths** aren't part of `columns` (that says what each column holds, not how it looks).
The columns share the table's width, none narrower than its header, and a scrollbar appears
along the bottom when they don't all fit. In code, `autosize_columns()` fits columns to what
they hold, and `widths` sets them (`self.Items.widths = {"Item": 160}`). Those keep their
widths, and the rest share what's left. Here `Form_load` fits Item to its longest name:

```python
self.Items.load_csv("order.csv")
self.Items.autosize_columns("Item")
```

Drag a header's edge to make a column wider or narrower: from then on, the widths are yours.

## Editing like a spreadsheet

**Try:**
- The arrows (and Home/End, Page Up/Down) move the cell cursor. Tab moves right and on to the
  next row. Tab from the last cell leaves the table for the next control.
- Type to replace a cell. Enter, F2 or a double-click edits what's there. Enter saves and
  moves down, and Esc cancels. A Price of "lots" can't be money: it's refused (the status
  line says why) and the editor stays open to fix it. For typing along rows, set the table's `enter_moves` to "right" in the
  Properties panel: Enter then moves to the next cell along (and on to the next row), as Tab
  does. ("left" for right-to-left languages; "up", or "stay".)
- Category gives a list to choose from (Enter in it chooses and moves on, as Enter does; a
  click chooses and stays), and Space ticks Taxable.
- Type in the blank row at the bottom to add a row. Qty and Taxable start filled in (their
  columns' `default`s).
- Ctrl with an arrow jumps to the edge: the top, the bottom, the first or last column.
- As in a spreadsheet, moving selects no rows: only the cell has the cursor. Select rows on
  purpose: Shift+Space for the cursor's row, Shift with an arrow or a click for a run of them,
  Ctrl-click (⌘-click on a Mac) to add or take away one, Ctrl+A for all. Esc unselects them.
- Delete removes the selected rows. With none selected, it empties the cell instead.
- Ctrl+C copies the selected rows, or with none selected, the cell, as tab-separated text, so
  it pastes into a spreadsheet. Ctrl+V pastes from the cursor across and down, adding rows at
  the bottom as needed; whole rows go from the first column wherever the cursor is. Copy a few
  rows from Excel (or this table) and paste them in. One value pasted with rows selected goes
  in each. Total, being readonly, is skipped. A value that can't be its column's kind stops
  the paste (and `cellrefused` says which). Ctrl+X cuts. (⌘ in place of Ctrl on a Mac.)
- Ctrl+Z takes back your last change (an edit, a paste, a Delete: rows and all), and Ctrl+Y
  makes it again (Ctrl+Shift+Z too; ⌘Z and ⌘⇧Z on a Mac). The totals follow, as undo runs the
  same events as a change: `cellchange` for each cell changed back, `rowdelete` for a row it
  takes away. For an Edit menu: `self.Items.undo()`, `redo()`, and `can_undo` and `can_redo`
  to say whether there's anything to undo or redo. Changes your code makes aren't taken back,
  and setting the rows (or loading them) starts afresh.
- Click a header to sort by it, and again for the other way.
- Untick the switches at the bottom to turn off `editable`, `addable`, `deletable` and
  `sortable`.

**How:** each change raises an event:

```python
def Items_cellvalidate(self, row, column, value):  # before a change is kept: refuse it?
def Items_cellrefused(self, row, column, value, reason):  # a change that couldn't be kept
def Items_cellchange(self, row, column):           # the user changed a cell
def Items_rowinvalid(self, row, problems):         # a row the user changed breaks the rules
def Items_rowadd(self, row):                       # the blank row became a real one
def Items_rowdelete(self, row, values):            # a row was deleted (values: what it held)
def Items_rowclick(self, row):                     # the cursor moved to another row
def Items_columnclick(self, column):               # a header was clicked
```

Here `cellchange` works out the totals again, and `rowclick` puts the row in the status line.
(Enter after an edit moves down a row, so `rowclick` follows `cellchange` then.)

A paste is the user changing cells too: `rowadd` for each row it adds, then `cellchange`
for each cell. For an Edit menu, `self.Items.copy()`, `cut()`, `paste()` and `select_all()`
do what the keys do.

`self.Items[row, "Qty"]` is one cell, by header or column number (`self.Items[row, 3]`).
`self.Items.headers[column]` names a column number.

## Rules

The rules (`required`, `min`, `max`, `max_length`, `unique`) hold **for code**: a change your
code makes that breaks one raises `DataError` (a ValueError), and nothing changes. It lists
each cell at fault, for the program to decide what to do: here, clamp to the limit and write
again.

```python
try:
    self.Items["Qty"] = new_quantities
except DataError as e:          # from readymade.controls import DataError
    for p in e.problems:        # each: p.row, p.column, p.value, p.rule ("max"...), p.limit
        if p.rule == "max":
            self.Items[p.row, p.column] = p.limit
```

A **validator** is a rule of the program's own: a function, set from code (a .form file
can't hold one), checked with the other rules, for code and the user alike. It's given the
value (never an empty one: that's `required`'s), already its column's kind, and returns True,
or False (or a message saying why) if it's not allowed. One that takes two arguments is given
the row too, for a rule between columns:

```python
cols = self.Items.columns
cols["Price"].validator = lambda price: 0 < price < 1_000_000
cols["Ends"].validator = lambda ends, row: row["Starts"] is None or ends >= row["Starts"]
```

Or make values fit before writing them: `column.clip(0, 99)` keeps each in a range,
`column.map(function)` changes each as you like (`notes.map(lambda s: s[:40])`, the first 40
characters). To load data as it is, broken rules and all, and fix it after:

```python
with self.Items.unchecked():
    self.Items.load_csv("old orders.csv")
```

**For the user**, the rules don't refuse anything: what's typed is kept, and the program is
told. Try a Qty of -2, or a new row with no Price. When the cursor leaves a row the user
changed (and after a paste), `rowinvalid` says what's wrong with it:

```python
def Items_rowinvalid(self, row, problems):
    self.Status.text = "; ".join(str(problem) for problem in problems)  # Price can't be empty
```

Here, after each change, rows that break a rule are tinted (`self.Items.problems(row)` lists
a row's), and **Save** asks first if any do. What to do is the program's choice: tint them,
say so, fix them, refuse to save, or let it be. A user filling in rows column by column, say,
leaves them incomplete for a while, and that's fine.

What the table can't keep is a value that isn't its column's kind (letters for a number):
the editor stays open with what was typed, and `cellrefused` says why, for the program to
tell the user its own way (the table shows no message itself):

```python
def Items_cellrefused(self, row, column, value, reason):
    self.Status.text = reason  # Qty: 'lots' isn't a number
```

`cellvalidate` runs before the user's change is kept, for a program that wants to refuse
something itself: return False, or a message saying why (and `cellrefused` follows). It's
given the value already its column's kind; `self.Items.check(column, value)` lists the rules
it would break, if the program wants those refused too. `self.Items.problems()` lists every
rule broken in the table, any time.

## Columns: arithmetic on every row at once

`self.Items["Price"]` is a whole column: a `Column`, which works like a list. Arithmetic on
it works on every value at once, as a spreadsheet's column of formulas does: `items["Price"] *
items["Qty"]` multiplies each row's pair. The order's totals are worked out after each change:

```python
def work_out_totals(self):
    items = self.Items
    subtotal = items["Total"].sum()
    tax = items["Total"][items["Taxable"]].sum() * TAX_RATE  # (the Totals where Taxable is ticked)
    tax = tax.quantize(CENT, rounding=ROUND_HALF_UP)  # to the cent, a half up, as a receipt does
```

(`items["Total"][items["Taxable"]]` is the Totals of the ticked rows: a column of True/False
chooses values, as below.)

Two columns go together row by row; with one number, each value gets it: **Prices +10%** is

```python
self.Items["Price"] = self.Items["Price"] * 1.1  # (Price is money: to the cent)
```

Setting a column to one value sets every row (`self.Items["Taxable"] = True`). A Column also
has `mean()`, `min()` and `max()`, and `sum(column)`, `for value in column` and `column[2]`
work as on any list.

## Computed columns: formulas

Each row's Total is worked out by a **formula**, set in `Form_load`:

```python
self.Items.columns["Total"].formula = lambda row: row["Price"] * row["Qty"]
```

The table keeps it up to date as Price and Qty change: the user's edits, a paste, undo, your
own code. The user can't edit a formula's column, nor can code set it (a ValueError). An empty
value in it gives an empty Total (no Price yet: no Total), and so does a division by 0. Its
values change without a `cellchange` of their own: they follow from the change that ran one.

A formula given **the table** instead of a row works out the whole column at once, for
what a row alone can't: a running total, a share of the whole, the row above (its parameter
is called `table`, which is how the table tells them apart):

```python
cols = self.Items.columns
cols.append({"name": "Running", "kind": "money",
             "formula": lambda table: table["Total"].cumsum()})       # the total so far
cols.append({"name": "Change", "kind": "money",
             "formula": lambda table: table["Total"] - table["Total"].shift()})  # from the row above
```

A table formula reads `table` as you read `self.Items`: `table["Total"]` (a column),
`table[0, "Qty"]` (a cell), `table[1:, "Qty"]` (part of a column), conditions and all. It
returns the column's values, one for each row (or one value, for every row: `lambda table:
table[0, "Qty"]` gives each row the first row's Qty).

Formulas can use other formula columns, in any order: those are worked out first. One that
comes back round to itself (Total from Tax, Tax from Total) is a **circular reference**:
setting it is refused with a ValueError naming the loop, and nothing changes. A formula is a
function, so it's set from code (a .form file can't hold one); set it to None for an
ordinary column again, its values kept.

## Filtering: showing some rows

```python
self.Items.filter = lambda row: row["Category"] == "Garden"   # only these show
self.Items.filter = None                                       # all of them again
```

The rows hidden are still there: `rows`, `self.Items[...]`, `problems()`, `save_csv()` and
the totals have them all, and row numbers (in events too) are the same. Only what's shown,
and where the cursor and keys go, is filtered. A row the user edits so it no longer fits stays
in sight till the cursor leaves it; changes from code apply the filter at once, and
`refilter()` applies it again. `self.Items.shown` is the numbers of the rows shown.

## Finding

`find()` goes through the cells that match, in the rows and columns shown, for the program to
do as it likes with: there's no Find box of the table's own.

```python
for row, column in self.Items.find("shovel"): ...       # text: in what's shown, case aside
first = next(self.Items.find("shovel"), None)           # just the first (None: none)
self.Items.current = next(self.Items.find("shovel", after=self.Items.current), self.Items.current)  # find next
self.Items.find(lambda value: value > 100, columns="Price")   # a function: anything else
```

Within a column, `contains()` gives a condition: `self.Items[self.Items["Item"].contains("shov"),
:]` is the rows with "shov" in their Item.

## Hidden columns

`self.Items.columns["Id"].hidden = True` (or `"hidden": true` in its definition) keeps a column
and its values without showing it: a database's key, say. Code reaches it as ever
(`self.Items["Id"]`); the cursor, copy and paste skip it; `save_csv()` writes it.

## Choosing cells: slices and conditions

`self.Items[rows, columns]` reaches any part of the table, as numpy's slicing does. Rows are a
number, a slice or a list of numbers; columns are a header or number, a slice of either, or a
list:

```python
items[2, "Price"]               # one cell
items[1:4, "Price"]             # rows 1 to 3 of a column: a Column
items[2, "Price":"Total"]       # part of a row: a list
items[:, ["Item", "Total"]]     # every row, two columns: a Block
items[-3:, 2:4]                 # the last three rows, columns 2 and 3
```

A slice of headers includes its last one (`"Price":"Total"` is Price through Total), as
there's no header past it to name. A slice of numbers stops before its end, as Python's do.

A **Block** is a copy of some rows of some columns. It loops as rows (`for price, qty in
block`), `block["Price"]` is a Column, `block.shape` is (rows, columns), and arithmetic works
on every cell: `items[:, "Price":"Qty"] * 2`. What you read from `items[...]` is a copy;
assigning puts values back, converted to their columns' kinds:

```python
items[0, "Price":"Qty"] = [2.5, 4]          # the same shape
items[:, "Price":"Qty"] = block * 2         # a Block, or a list of lists
items[3:, "Taxable"] = False                # one value: every cell chosen
```

If any value doesn't suit its column, nothing changes (they're all converted first).

**Conditions** choose rows. Comparing a Column (`< <= > >=`) gives a Column of True and False,
one for each row; `.eq()` and `.ne()` compare each value for equality. **Garden -10%** is:

```python
garden = self.Items["Category"].eq("Garden")  # True on the Garden rows
self.Items[garden, "Price"] = self.Items[garden, "Price"] * 0.9
```

Combine conditions with `&` (and), `|` (or) and `~` (not), in brackets:
`items[(items["Qty"] > 0) & ~items["Taxable"], "Item"]`. A condition chooses from a
Column too: `items["Total"][items["Qty"] > 2].sum()`. (`==` compares whole columns, as lists
do: `items["Qty"] == [2, 1, 1]`.)

A condition isn't True or False itself: `if items["Total"] > 20:` is an error, as in numpy,
since it could mean any row or every row. Say which: `(items["Total"] > 20).any()` or
`.all()`. (`and`, `or` and `not` ask the same question, so they're errors too: use `&`, `|`,
`~`.)

## Rows: a list

`self.Items.rows` is a list of the rows. Index it, slice it, loop over it, `append`,
`insert`, `del`, `len`. A row reads and writes by column number or header (`row["Qty"]`),
and changes show at once. Setting `rows` replaces them all (lists, or dicts by header), so
**Drop unordered** is one list comprehension:

```python
self.Items.rows = [row for row in self.Items.rows if row["Qty"]]  # (not 0, nor empty)
```

**Biggest first** is `self.Items.sort("Total", descending=True)`.

### Sorting your own way

A header click sorts while `sortable` is on (the usual order: text ignoring case, choices in
their listed order). Then `columnclick` runs, given the column's number. To sort another way,
turn `sortable` off and sort in `columnclick`: `sort()` takes a `key`, as `sorted()` does, and
`sorted_by` says how the rows are sorted now, (column, descending), so a second click can turn
it around. For natural order ("Item 2" before "Item 10"), the natsort package's key, if it's
installed in the project:

```python
from natsort import natsort_keygen

def Items_columnclick(self, column):
    descending = self.Items.sorted_by == (column, False)  # (this column, already up: down)
    self.Items.sort(column, descending, key=natsort_keygen())
```

`self.Items.rows.sort(key=...)` sorts by whole rows, as a list's `sort()`: say, by Category,
then the biggest Total first, `key=lambda row: (row["Category"], -row["Total"])`. Plain Python
works on `rows` as on any list, conditions or not.

### Row colors

A row has a `backcolor` and a `forecolor`, set from code, and they stay with the row as rows
are sorted, added and deleted. Rows with nothing ordered are grayed after each change:

```python
for row in items.rows:
    row.forecolor = "#909090" if row["Qty"] == 0 else ""
```

(Colors are for whole rows: Tk's tables can't color a single cell.)

## CSV files

The order is loaded from **order.csv** in `Form_load`: `self.Items.load_csv("order.csv")`, a
path from the program's folder. The file's first line, the headers, says which column is
which, in any order. Columns the file hasn't (here, Total), and empty cells, are empty (or
their column's `default`). **Open...** loads another; a value that can't be its column's kind
is reported with its line number, and one that breaks a rule raises DataError (Open shows
either in a message: the program's choice). **Save...** writes the rows with
`save_csv(path)`, headers first.
