"""examples/sqlite, the inventory: it does what its README.md says (run on a copy, its database
made afresh)."""

import importlib.util
import shutil
import sqlite3
import time
from decimal import Decimal as D
from pathlib import Path

import pytest

from readymade import form as form_module

pytestmark = pytest.mark.usefixtures("display")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "sqlite"
AS_PUBLISHED = shutil.ignore_patterns(".readymade", "__pycache__", "*.db")  # (not this machine's)


@pytest.fixture
def program(tmp_path, monkeypatch):
    folder = shutil.copytree(EXAMPLE, tmp_path / "sqlite", ignore=AS_PUBLISHED)
    monkeypatch.chdir(folder)
    monkeypatch.setattr(form_module, "_folder", folder)  # (app_path(): the copy's folder)
    spec = importlib.util.spec_from_file_location("inventory", folder / "Form1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.said, module.answers = [], []
    monkeypatch.setattr(module, "msgbox", lambda message, *a, **kw: (module.said.append(str(message)),
                                                                     module.answers.pop(0) if module.answers
                                                                     else "ok")[1])
    module.folder = folder
    return module


@pytest.fixture
def form(program):
    form = program.Form1("Form1.form")
    form.show()
    settle(form)
    yield form
    if form.Items.database is not None:
        form.Items.database.close()
    form.root.destroy()


def settle(form):
    for _ in range(10):
        form.root.update()
        time.sleep(0.005)


def in_database(program, sql):
    with sqlite3.connect(program.folder / "inventory.db") as connection:
        return connection.execute(sql).fetchall()


def test_loaded_from_the_database(form, program):
    items = form.Items
    assert (program.folder / "inventory.db").exists()  # (made the first time)
    assert items.headers == ["id", "Item", "Category", "Price", "In stock", "Reorder at", "Counted"]
    assert items.columns["id"].hidden and items.columns["Category"].choices == ["Garden", "Hardware", "Kitchen"]
    assert items.rows[0][1:4] == ["Garden rake", "Garden", D("18.99")] and items.columns["Item"].unique
    assert form.text == "Inventory" and form.Status.text == "Everything's saved"
    assert items.rows[1].backcolor == "#fff2cc" and items.rows[0].backcolor == ""  # (Hose: 3 in stock, reorder at 5)


def test_edit_add_delete_and_save(form, program):
    items = form.Items
    items[0, "Price"] = "19.49"
    items.rows.append({"Item": "Watering can", "Price": 12})
    del items.rows[2]
    form.show_changes()
    assert form.text == "Inventory *" and form.Status.text == "Not saved yet: 1 edited, 1 added, 1 deleted"
    form.SaveButton_click()
    assert form.Status.text == "Everything's saved" and items[-1, "id"] == 9
    assert in_database(program, 'SELECT "Item", "Category", "Price" FROM items WHERE id IN (1, 9)') == [
        ("Garden rake", "Garden", 19.49), ("Watering can", "Hardware", 12)]  # (its Category: the default)
    assert in_database(program, "SELECT count(*) FROM items") == [(8,)]


def test_the_rules_and_the_databases_own(form, program):
    items = form.Items
    with items.unchecked():
        items[1, "Item"] = "Trowel"  # (Item is UNIQUE: another row has it)
    form.SaveButton_click()
    assert form.Status.text.startswith("Not saved: row 1: Item: Trowel is in row") and items.current == (1, 1)
    items[1, "Item"] = "Hose"
    items[1, "Price"] = -1  # (the DataTable doesn't know the database's CHECK: the database says no)
    form.SaveButton_click()
    assert "CHECK constraint failed" in program.said[-1] and items.changed
    assert in_database(program, 'SELECT "Item" FROM items WHERE id = 2') == [("Hose, 25 ft",)]  # (nothing saved)


def test_someone_else_changes_the_row(form, program):
    items = form.Items
    items.current = (3, "In stock")
    form.OtherButton_click()
    assert "Someone else just put 10 more Claw hammer in stock" in form.Status.text
    items[3, "In stock"] = 7
    program.answers.append("no")  # (theirs, then: loaded again)
    form.SaveButton_click()
    assert "row 3 was changed in the database" in program.said[-1]
    assert items[3, "In stock"] == 18 and not items.changed
    items[3, "In stock"] = 7
    form.OtherButton_click()
    program.answers.append("yes")  # (mine, over theirs)
    form.SaveButton_click()
    assert in_database(program, 'SELECT "In stock" FROM items WHERE id = 4') == [(7,)] and not items.changed


def test_revert_low_stock_and_closing(form, program):
    items = form.Items
    items[0, "In stock"] = 1
    form.RevertButton_click()
    assert items[0, "In stock"] == 12 and form.text == "Inventory"
    form.LowStock.value = True
    form.LowStock_click()
    assert [items[r, "Item"] for r in items.shown] == ["Hose, 25 ft", "Box of nails", "Chef's knife"]
    items[0, "In stock"] = 2
    program.answers.append("cancel")
    assert form.Form_unload() is True  # (still open)
    program.answers.append("yes")
    assert form.Form_unload() is None
    assert in_database(program, 'SELECT "In stock" FROM items WHERE id = 1') == [(2,)]
