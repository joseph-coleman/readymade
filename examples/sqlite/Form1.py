"""An inventory kept in an SQLite database: a DataTable loaded from a table, edited like a
spreadsheet, and saved back. README.md walks through it."""

import sqlite3

from readymade import Form, app_path, msgbox
from readymade.controls import ConflictError, DataError

DATABASE = "inventory.db"  # (next to Form1.py: made by make_database() the first time it runs)
LOW = "#fff2cc"  # rows with no more in stock than their Reorder at


class Form1(Form):
    def Form_load(self):
        if not app_path(DATABASE).exists():
            make_database(app_path(DATABASE))
        self.load_items()

    def load_items(self):
        items = self.Items
        # The columns come from the table's: their kinds from its types (DECIMAL is money, DATE a
        # date), their rules from NOT NULL, UNIQUE and DEFAULT, and id, its key, numbered by the
        # database (readonly: a new row's is filled in when it's saved).
        odd = items.load_sql(DATABASE, "items")
        items.columns["id"].hidden = True  # (it tells rows apart; nobody needs to see it)
        # A category is text in the database; here it's one of the categories table's.
        names = [name for (name,) in items.database.execute("SELECT name FROM categories ORDER BY name")]
        items.columns["Category"].choices = names
        items.autosize_columns("Item")
        self.show_changes()
        if odd:  # (values that aren't their column's kind: loaded as text, so you see them)
            self.Status.text = f"{len(odd)} values aren't their column's kind: the first, {odd[0].value!r} in {odd[0].column}"

    def show_changes(self):
        """What's not saved yet, in the status line and the title (a * as editors have)."""
        for row in self.Items.rows:
            row.backcolor = LOW if low_on_stock(row) else ""
        changes = self.Items.changes()
        self.text = "Inventory" + (" *" if changes else "")
        if changes:
            self.Status.text = (f"Not saved yet: {len(changes.edited)} edited, {len(changes.added)} added, "
                                f"{len(changes.deleted)} deleted")
        else:
            self.Status.text = "Everything's saved"

    def save_items(self):
        """Save the changes; False if they weren't (a rule broken, someone else's change...)."""
        try:
            self.Items.save_sql()
        except ConflictError as e:  # (rows changed in the database since they were loaded: nothing saved)
            answer = msgbox(f"{e}.\n\nSave yours over theirs? (No: load theirs, and lose your changes.)",
                            buttons="yesnocancel", icon="warning")
            if answer == "yes":
                self.Items.save_sql(overwrite=True)
            elif answer == "no":
                self.load_items()
                return False
            else:
                return False
        except DataError as e:  # (a rule broken: required, unique...; nothing saved)
            problem = e.problems[0]
            self.Items.current = (problem.row, problem.column)  # (the cursor to the first)
            self.Status.text = f"Not saved: row {problem.row}: {problem}"
            return False
        except sqlite3.Error as e:  # (a rule only the database has: here, its CHECK that Price >= 0)
            msgbox(f"The database said no, so nothing was saved: {e}", icon="error")
            return False
        self.show_changes()
        return True

    # ----- the table's events -----

    def Items_cellchange(self, row, column):
        self.show_changes()

    def Items_rowadd(self, row):
        self.show_changes()

    def Items_rowdelete(self, row, values):
        self.show_changes()

    def Items_rowinvalid(self, row, problems):  # the cursor left a row that breaks a rule
        self.Status.text = "; ".join(str(problem) for problem in problems)

    def Items_cellrefused(self, row, column, value, reason):  # typed what can't be its kind
        self.Status.text = reason

    # ----- the buttons -----

    def SaveButton_click(self):
        self.save_items()

    def RevertButton_click(self):
        self.Items.revert()  # (as loaded, or last saved: the changes since are gone)
        self.show_changes()

    def ReloadButton_click(self):
        if self.Items.changed and msgbox("Lose your changes, and load the rows again?", buttons="yesno",
                                         icon="question") != "yes":
            return
        self.load_items()

    def OtherButton_click(self):
        """Another program (or user) changes the cursor's row in the database, not here: edit
        that row and Save, and the save finds it changed underneath (a ConflictError)."""
        row = self.Items.current[0]
        if row >= len(self.Items.rows) or self.Items[row, "id"] is None:
            self.Status.text = "Choose a row that's been saved first"
            return
        other = sqlite3.connect(app_path(DATABASE))  # (its own connection: another program, as it were)
        with other:  # (commits)
            other.execute('UPDATE items SET "In stock" = "In stock" + 10 WHERE id = ?', (self.Items[row, "id"],))
        other.close()
        self.Status.text = (f"Someone else just put 10 more {self.Items[row, 'Item']} in stock, in the database. "
                            "Edit that row and Save")

    def LowStock_click(self):
        self.Items.filter = low_on_stock if self.LowStock.value else None

    def Form_unload(self):
        if not self.Items.changed:
            return None
        answer = msgbox("Save your changes?", buttons="yesnocancel", icon="question")
        if answer == "cancel" or (answer == "yes" and not self.save_items()):
            return True  # (the form stays open)
        return None


def low_on_stock(row):
    return (row["In stock"] or 0) <= (row["Reorder at"] or 0)


def make_database(path):
    """The inventory's database, made the first time: two tables, the items' categories one
    of the other's (a foreign key)."""
    connection = sqlite3.connect(path)
    connection.executescript("""
        CREATE TABLE categories (name TEXT PRIMARY KEY);
        INSERT INTO categories VALUES ('Garden'), ('Hardware'), ('Kitchen');
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            "Item" VARCHAR(40) NOT NULL UNIQUE,
            "Category" TEXT NOT NULL DEFAULT 'Hardware' REFERENCES categories (name),
            "Price" DECIMAL(10,2) NOT NULL CHECK ("Price" >= 0),
            "In stock" INTEGER NOT NULL DEFAULT 0,
            "Reorder at" INTEGER NOT NULL DEFAULT 5,
            "Counted" DATE
        );
        INSERT INTO items ("Item", "Category", "Price", "In stock", "Reorder at", "Counted") VALUES
            ('Garden rake', 'Garden', 18.99, 12, 4, '2026-10-01'),
            ('Hose, 25 ft', 'Garden', 24.50, 3, 5, '2026-10-01'),
            ('Trowel', 'Garden', 6.25, 30, 10, '2026-09-28'),
            ('Claw hammer', 'Hardware', 15.00, 8, 5, '2026-10-02'),
            ('Box of nails', 'Hardware', 4.79, 2, 10, '2026-10-02'),
            ('Tape measure', 'Hardware', 9.95, 14, 6, NULL),
            ('Cast iron pan', 'Kitchen', 32.00, 5, 3, '2026-09-30'),
            ('Chef''s knife', 'Kitchen', 45.00, 1, 2, '2026-09-30');
    """)
    connection.commit()
    connection.close()


if __name__ == "__main__":
    Form1.run()
