"""An order sheet: a Table edited like a spreadsheet, its totals worked out in code.
README.md walks through it."""

from readymade import Form, app_path, msgbox, open_file_dialog, save_file_dialog

TAX_RATE = 0.08  # on the rows ticked Taxable
CSV_FILES = {"CSV files": "*.csv", "All files": "*.*"}


class Form1(Form):
    def Form_load(self):
        self.Items.load_csv("order.csv")  # (a path from the program's folder)
        self.work_out_totals()

    def work_out_totals(self):
        """Each row's Total, then the order's. A column is a Column: arithmetic on it works on
        every value at once, as in a spreadsheet's column of formulas."""
        items = self.Items
        items["Total"] = items["Price"] * items["Qty"]
        subtotal = items["Total"].sum()
        tax = (items["Total"] * items["Taxable"]).sum() * TAX_RATE  # (a tick counts 1, none 0)
        self.Totals.text = (f"{len(items.rows)} rows     Subtotal {subtotal:,.2f}     "
                            f"Tax {tax:,.2f}     Total {subtotal + tax:,.2f}  ")

    # ----- the table's events -----

    def Items_cellchange(self, row, column):
        self.work_out_totals()  # (column is a number: self.Items.headers[column] names it)

    def Items_rowadd(self, row):
        self.Items[row, "Qty"] = 1  # a new row's defaults
        self.Items[row, "Taxable"] = True

    def Items_rowdelete(self, row, values):
        self.Status.text = f"Removed {values[0]}"
        self.work_out_totals()

    def Items_rowclick(self, row):  # the cursor moved to another row (Enter after an edit too)
        r = self.Items.rows[row]  # (a row: by column number, or by header)
        self.Status.text = f"{r['Item']}: {r['Qty']} at {r['Price']:.2f} = {r['Total']:.2f}"

    # ----- the buttons -----

    def OpenButton_click(self):
        path = open_file_dialog("Open an order", CSV_FILES, folder=app_path())
        if path:
            try:
                self.Items.load_csv(path)
            except (OSError, ValueError) as e:  # (a value that doesn't suit its column, say)
                msgbox(e, icon="error")
                return
            self.work_out_totals()
            self.Status.text = f"Opened {path.name}"

    def SaveButton_click(self):
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
        self.Items.rows = [row for row in self.Items.rows if row["Qty"] > 0]  # rows is a list
        self.work_out_totals()

    # ----- the switches: a control array of CheckBoxes, each named after a Table property -----

    def Switch_click(self, index):
        switch = self.Switch[index]
        setattr(self.Items, switch.text.lower(), switch.value)


if __name__ == "__main__":
    Form1.run()
