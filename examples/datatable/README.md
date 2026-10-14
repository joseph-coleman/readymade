# An order sheet in a DataTable

A DataTable holds rows of values under typed columns, edited like a spreadsheet. Open it in the IDE:

    readymade examples/datatable

and press **F5**. The code is in **Form1** (F7 on the form).

## A database table, not a spreadsheet

The keys work as in a spreadsheet, but the data is a database table's (an Access datasheet's,
say). In Excel every cell starts empty and holds whatever is typed in it. Here each
**column** has a kind: Price holds numbers, Taxable ticks, Category one of its choices. Every
row's cell in that column is that kind, so there's no such thing as an empty Price: it's 0.

So a new row is never truly empty. It starts with each column's blank value: empty text, 0,
no tick, a choice's first choice (Category: Food). Then the `rowadd` event can set others,
and here it does: Qty 1 and Taxable ticked. Paste one price onto the blank row at the bottom
and the new row shows Food, Qty 1, a tick and a Total too: not copied from anywhere, but the
blanks, the defaults, and the Total worked out from them.

## The columns

Select the table in the designer and look at `columns` in the Properties panel, one per line:

    Item
    Category : Food | Hardware | Garden
    Price : number 2
    Qty : number
    Taxable : check
    Total : number 2, readonly

A header, then maybe a kind: text (the usual), `number` (`number 2` keeps two decimal places),
`check` (a tick), or choices separated by `|`. `readonly` means the user can't edit it (code
still can). Values are converted to their column's kind: `"3"` in Qty becomes the number 3,
and a value that can't be raises a ValueError saying which column and value.

There are no rows in the designer: they come from code.

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
  moves down, and Esc cancels. A Price of "lots" is refused (a beep) and the editor stays open.
- Category gives a list to choose from (Enter in it chooses and moves down; a click chooses
  and stays), and Space ticks Taxable.
- Type in the blank row at the bottom to add a row. Qty and Taxable start filled in.
- Ctrl with an arrow jumps to the edge: the top, the bottom, the first or last column.
- As in a spreadsheet, moving selects no rows: only the cell has the cursor. Select rows on
  purpose: Shift+Space for the cursor's row, Shift with an arrow or a click for a run of them,
  Ctrl-click (⌘-click on a Mac) to add or take away one, Ctrl+A for all. Esc unselects them.
- Delete removes the selected rows. With none selected, it empties the cell instead.
- Ctrl+C copies the selected rows, or with none selected, the cell, as tab-separated text, so
  it pastes into a spreadsheet. Ctrl+V pastes from the cursor across and down, adding rows at
  the bottom as needed; whole rows go from the first column wherever the cursor is. Copy a few
  rows from Excel (or this table) and paste them in. One value pasted with rows selected goes
  in each. Total, being readonly, is skipped. A value that doesn't suit its column stops the
  paste, with a message saying which. Ctrl+X cuts. (⌘ in place of Ctrl on a Mac.)
- Click a header to sort by it, and again for the other way.
- Untick the switches at the bottom to turn off `editable`, `addable`, `deletable` and
  `sortable`.

**How:** each change raises an event:

```python
def Items_cellvalidate(self, row, column, value):  # before a change is kept: refuse it?
def Items_cellchange(self, row, column):           # the user changed a cell
def Items_rowadd(self, row):                       # the blank row became a real one
def Items_rowdelete(self, row, values):            # a row was deleted (values: what it held)
def Items_rowclick(self, row):                     # the cursor moved to another row
def Items_columnclick(self, column):               # a header was clicked
```

Here `cellchange` works out the totals again, and `rowclick` puts the row in the status line.
(Enter after an edit moves down a row, so `rowclick` follows `cellchange` then.)

**Refusing a change:** `cellvalidate` runs before the user's change to a cell is kept,
given the new value already converted to its column's kind (a number, for Qty). Return False
to refuse it, or a message saying why: the user sees it, and the editor stays open to fix it.
Try a Qty of -2:

```python
def Items_cellvalidate(self, row, column, value):
    if self.Items.headers[column] == "Qty" and value < 0:
        return "Qty can't be less than 0"
    return None
```

It checks every way the user changes a cell: typing, a tick, a choice, and each cell of a
paste, cut or Delete (if one is refused, nothing in the paste is kept). Code setting cells
isn't checked. (Raising an error won't refuse it: in the IDE, that pauses the program to
show the error, as any handler's error does.)

`rowadd` is the place for a new row's defaults:

```python
def Items_rowadd(self, row):
    self.Items[row, "Qty"] = 1
    self.Items[row, "Taxable"] = True
```

A paste is the user changing cells too: `rowadd` for each row it adds, then `cellchange`
for each cell. For an Edit menu, `self.Items.copy()`, `cut()`, `paste()` and `select_all()`
do what the keys do.

`self.Items[row, "Qty"]` is one cell, by header or column number (`self.Items[row, 3]`).
`self.Items.headers[column]` names a column number.

## Columns: arithmetic on every row at once

`self.Items["Price"]` is a whole column: a `Column`, which works like a list. Arithmetic on
it works on every value at once, as a spreadsheet's column of formulas does. That's how the
totals are worked out after each change:

```python
def work_out_totals(self):
    items = self.Items
    items["Total"] = items["Price"] * items["Qty"]
    subtotal = items["Total"].sum()
    tax = items["Total"][items["Taxable"]].sum() * TAX_RATE  # (the Totals where Taxable is ticked)
```

(`items["Total"][items["Taxable"]]` is the Totals of the ticked rows: a column of True/False
chooses values, as below.)

Two columns go together row by row; with one number, each value gets it: **Prices +10%** is

```python
self.Items["Price"] = self.Items["Price"] * 1.1  # (Price keeps 2 decimals: it rounds)
```

Setting a column to one value sets every row (`self.Items["Taxable"] = True`). A Column also
has `mean()`, `min()` and `max()`, and `sum(column)`, `for value in column` and `column[2]`
work as on any list.

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
self.Items.rows = [row for row in self.Items.rows if row["Qty"] > 0]
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
then the biggest Total first, `key=lambda row: (row["Category"], -row["Total"])`. Plain Python works on
`rows` as on any list, conditions or not.

## CSV files

The order is loaded from **order.csv** in `Form_load`: `self.Items.load_csv("order.csv")`, a
path from the program's folder. The file's first line, the headers, says which column is
which, in any order. Columns the file hasn't (here, Total) start blank. **Open...** loads
another, and a bad value is reported with its line number. **Save...** writes the rows with
`save_csv(path)`, headers first.
