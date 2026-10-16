"""An order sheet: a DataTable edited like a spreadsheet, its totals worked out in code.
README.md walks through it."""

from decimal import ROUND_HALF_UP, Decimal

from readymade import Form, app_path, msgbox, open_file_dialog, save_file_dialog

TAX_RATE = Decimal("0.08")  # on the rows ticked Taxable (Price and Total are money: Decimals)
CENT = Decimal("0.01")
AT_FAULT = "#ffe0e0"  # rows that break the columns' rules (see Form1.form: Items' columns)
CSV_FILES = {"CSV files": "*.csv", "All files": "*.*"}


class Form1(Form):
    def Form_load(self):
        # Total is worked out by a formula, from each row's Price and Qty: the table keeps it up
        # to date as they change (by the user, by code, by undo), and the user can't edit it.
        self.Items.columns["Total"].formula = lambda row: row["Price"] * row["Qty"]
        self.Items.load_csv("order.csv")  # (a path from the program's folder)
        self.Items.autosize_columns("Item")  # wide enough for the longest; the rest share what's left
        self.work_out_totals()

        # Programatic example of adding a new column, defaulting to type string
        # and then adding a formula for the column to show calculations 
        # using various python techniques: list comprehensions and map
        self.Items.columns.append("Running")
        self.Items.columns["Running"].formula = lambda table: [round(x, 2) for x in (table["Qty"] * table["Price"] * (1 + TAX_RATE * table["Taxable"] ) ).cumsum() ]
        #self.Items.columns["Running"].formula = lambda table: round( (table["Qty"] * table["Price"] * (1 + TAX_RATE * table["Taxable"] ) ).cumsum()  , 2)
        #self.Items.columns["Running"].formula = lambda table: ((table["Qty"] * table["Price"] * (1 + TAX_RATE * table["Taxable"] ) ).cumsum()).map( lambda f: round(f,2) )

    def work_out_totals(self):
        """The order's totals (each row's, its formula sees to). A column is a Column: sum() and
        the like work on every value at once, as a spreadsheet's do."""
        items = self.Items
        subtotal = items["Total"].sum()
        tax = items["Total"][items["Taxable"]].sum() * TAX_RATE  # (the Totals where Taxable is ticked)
        tax = tax.quantize(CENT, rounding=ROUND_HALF_UP)  # to the cent, a half up, as a receipt does
        for number, row in enumerate(items.rows):
            row.forecolor = "#909090" if row["Qty"] == 0 else ""  # nothing ordered: grayed
            row.backcolor = AT_FAULT if items.problems(number) else ""  # breaking a rule: marked
        self.Totals.text = (f"{len(items.rows)} rows     Subtotal {subtotal:,.2f}     "
                            f"Tax {tax:,.2f}     Total {subtotal + tax:,.2f}  ")

    # ----- the table's events -----

    def Items_cellchange(self, row, column):
        self.work_out_totals()  # (column is a number: self.Items.headers[column] names it)

    def Items_rowinvalid(self, row, problems):  # the cursor left a row that breaks a rule: say so
        self.Status.text = "; ".join(str(problem) for problem in problems)  # (Price can't be empty...)

    def Items_cellrefused(self, row, column, value, reason):  # typed what can't be its kind: say so
        self.Status.text = reason  # (Qty: 'lots' isn't a number)

    def Items_rowdelete(self, row, values):
        self.Status.text = f"Removed {values[0]}"
        self.work_out_totals()

    def Items_rowclick(self, row):  # the cursor moved to another row (Enter after an edit too)
        r = self.Items.rows[row]  # (a row: by column number, or by header)
        if r["Price"] is not None and r["Qty"] is not None:  # (empty cells are None)
            self.Status.text = f"{r['Item']}: {r['Qty']} at {r['Price']:.2f} = {r['Total']:.2f}"

    # ----- the buttons -----

    def OpenButton_click(self):
        path = open_file_dialog("Open an order", CSV_FILES, folder=app_path())
        if path:
            try:
                self.Items.load_csv(path)
                self.Items.autosize_columns("Item")
            except (OSError, ValueError) as e:  # (a value that doesn't suit its column, say)
                msgbox(e, icon="error")
                return
            self.work_out_totals()
            self.Status.text = f"Opened {path.name}"

    def SaveButton_click(self):
        problems = self.Items.problems()  # (the program decides what problems mean: here, it asks)
        count = f"{len(problems)} problem" + ("s" if len(problems) > 1 else "")
        if problems and msgbox(f"{count}, the first: row {problems[0].row}: {problems[0]}."
                               "\n\nSave anyway?", buttons="yesno", icon="warning") != "yes":
            return
        path = save_file_dialog("Save the order", CSV_FILES, folder=app_path(), filename="my order.csv")
        if path:
            self.Items.save_csv(path)
            self.Status.text = f"Saved {path.name}"

    def RaiseButton_click(self):
        self.Items["Price"] = self.Items["Price"] * 1.1  # (Price keeps 2 decimals: it rounds)
        self.work_out_totals()

    def SortButton_click(self):
        self.Items.sort("Total", descending=True)

    def DropButton_click(self):
        self.Items.rows = [row for row in self.Items.rows if row["Qty"]]  # rows is a list (Qty: not 0 or empty)
        self.work_out_totals()

    def SaleButton_click(self):
        garden = self.Items["Category"].eq("Garden")  # a condition: True on the Garden rows
        self.Items[garden, "Price"] = self.Items[garden, "Price"] * 0.9  # (those rows' prices)
        self.work_out_totals()

    # ----- the switches: a control array of CheckBoxes, each named after a DataTable property -----

    def Switch_click(self, index):
        switch = self.Switch[index]
        setattr(self.Items, switch.text.lower(), switch.value)


if __name__ == "__main__":
    Form1.run()
