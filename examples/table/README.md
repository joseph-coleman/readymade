# An order sheet in a Table

A Table holds rows of values under typed columns, edited like a spreadsheet. Open it in the IDE:

    readymade examples/table

and press **F5**. The code is in **Form1** (F7 on the form).

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

## Editing like a spreadsheet

**Try:**
- The arrows (and Home/End, Page Up/Down) move the cell cursor. Tab moves right and on to the
  next row. Tab from the last cell leaves the table for the next control.
- Type to replace a cell. Enter, F2 or a double-click edits what's there. Enter saves and
  moves down, and Esc cancels. A Price of "lots" is refused (a beep) and the editor stays open.
- Category gives a list to choose from, and Space ticks Taxable.
- Type in the blank row at the bottom to add a row. Qty and Taxable start filled in.
- Select rows (Shift or Ctrl with a click or arrow) and press Delete to remove them.
- Click a header to sort by it, and again for the other way.
- Untick the switches at the bottom to turn off `editable`, `addable`, `deletable` and
  `sortable`.

**How:** each change raises an event:

```python
def Items_cellchange(self, row, column):     # the user changed a cell
def Items_rowadd(self, row):                 # the blank row became a real one
def Items_rowdelete(self, row, values):      # a row was deleted (values: what it held)
def Items_rowclick(self, row):               # the cursor moved to another row
```

Here `cellchange` works out the totals again, and `rowclick` puts the row in the status line.
(Enter after an edit moves down a row, so `rowclick` follows `cellchange` then.)

`rowadd` is the place for a new row's defaults:

```python
def Items_rowadd(self, row):
    self.Items[row, "Qty"] = 1
    self.Items[row, "Taxable"] = True
```

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
    tax = (items["Total"] * items["Taxable"]).sum() * TAX_RATE  # (a tick counts 1, none 0)
```

Two columns go together row by row; with one number, each value gets it: **Prices +10%** is

```python
self.Items["Price"] = self.Items["Price"] * 1.1  # (Price keeps 2 decimals: it rounds)
```

Setting a column to one value sets every row (`self.Items["Taxable"] = True`). A Column also
has `mean()`, `min()` and `max()`, and `sum(column)`, `for value in column` and `column[2]`
work as on any list.

## Rows: a list

`self.Items.rows` is a list of the rows. Index it, slice it, loop over it, `append`,
`insert`, `del`, `len`. A row reads and writes by column number or header (`row["Qty"]`),
and changes show at once. Setting `rows` replaces them all (lists, or dicts by header), so
**Drop unordered** is one list comprehension:

```python
self.Items.rows = [row for row in self.Items.rows if row["Qty"] > 0]
```

**Biggest first** is `self.Items.sort("Total", descending=True)`.

## CSV files

The order is loaded from **order.csv** in `Form_load`: `self.Items.load_csv("order.csv")`, a
path from the program's folder. The file's first line, the headers, says which column is
which, in any order. Columns the file hasn't (here, Total) start blank. **Open...** loads
another, and a bad value is reported with its line number. **Save...** writes the rows with
`save_csv(path)`, headers first.
