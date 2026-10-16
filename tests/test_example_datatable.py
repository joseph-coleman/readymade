"""examples/datatable, the order sheet: it does what its README.md says (run on a copy)."""

import importlib.util
import shutil
import time
from decimal import Decimal as D
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("display")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "datatable"
AS_PUBLISHED = shutil.ignore_patterns(".readymade", "__pycache__")  # (not this machine's settings for it)


@pytest.fixture
def program(tmp_path, monkeypatch):
    folder = shutil.copytree(EXAMPLE, tmp_path / "datatable", ignore=AS_PUBLISHED)
    monkeypatch.chdir(folder)
    spec = importlib.util.spec_from_file_location("order_sheet", folder / "Form1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.said = []
    monkeypatch.setattr(module, "msgbox", lambda message, *a, **kw: module.said.append(str(message)))
    return module


@pytest.fixture
def form(program):
    form = program.Form1("Form1.form")
    form.show()
    settle(form)
    yield form
    form.root.destroy()


def settle(form):
    for _ in range(10):
        form.root.update()
        time.sleep(0.005)


def test_loaded_and_totaled(form):
    assert len(form.Items.rows) == 9 and form.Items.rows[0] == ["Apples (1 kg)", "Food", D("3.49"), 2, False, D("6.98")]  # (money: exact)
    assert form.Totals.text.split() == ["9", "rows", "Subtotal", "101.67", "Tax", "6.42", "Total", "108.09"]


def test_editing_works_out_the_totals(form):
    items = form.Items
    items._tree.focus_force()
    items.current = (0, "Qty")
    settle(form)
    items._edit(typed="5")
    items._finish(down=1)
    settle(form)
    assert items[0, "Total"] == D("17.45") and "Subtotal 112.14" in form.Totals.text
    assert form.Status.text == "Bread: 1 at 2.99 = 2.99"  # (Enter moved down a row)
    items._move(len(items.rows), 0)  # the blank row: a new row with its defaults
    items._edit(typed="Rake")
    items._finish(down=1)
    settle(form)
    assert items.rows[-1] == ["Rake", None, None, 1, True, None] and "10 rows" in form.Totals.text  # (Qty, Taxable: defaults)


def test_the_buttons(form, program, monkeypatch, tmp_path):
    form.RaiseButton.widget.invoke()
    assert form.Items[0, "Price"] == D("3.84") and form.Items[0, "Total"] == D("7.68")  # (3.49 * 1.1, to the cent)
    form.DropButton.widget.invoke()
    assert len(form.Items.rows) == 7 and all(form.Items["Qty"])
    form.SortButton.widget.invoke()
    assert form.Items["Total"] == sorted(form.Items["Total"], reverse=True)
    saved = tmp_path / "saved.csv"
    monkeypatch.setattr(program, "save_file_dialog", lambda *a, **kw: saved)
    form.SaveButton.widget.invoke()
    assert saved.read_text(encoding="utf-8").startswith("Item,Category,Price,Qty,Taxable,Total\n")
    saved.write_text("Item,Price\nPeaches,cheap\n", encoding="utf-8")
    monkeypatch.setattr(program, "open_file_dialog", lambda *a, **kw: saved)
    form.OpenButton.widget.invoke()  # a bad value: said, and the rows kept
    assert program.said == ["saved.csv, line 2: Price: 'cheap' isn't a number"] and len(form.Items.rows) == 7


def test_a_condition_chooses_the_garden_rows(form):
    form.SaleButton.widget.invoke()
    assert form.Items[form.Items["Category"].eq("Garden"), "Price"] == [D("4.05"), D("8.78"), D("10.80")]
    assert form.Items[0, "Price"] == D("3.49")  # (Food: no sale)
    assert form.Totals.text.split()[3] == f"{form.Items['Total'].sum():,.2f}"


def test_the_switches_are_a_control_array(form):
    form.Switch[0].widget.invoke()  # Editable
    form.Switch[3].widget.invoke()  # Sortable
    assert form.Items.editable is False and form.Items.sortable is False and form.Items.addable is True


def test_rules_mark_rows_and_say_why(form, program, monkeypatch):
    items = form.Items
    items.current = (0, "Qty")
    items._edit(typed="-2")
    assert items._finish() is True and items[0, "Qty"] == -2  # (the user's, against min: kept...)
    items._move(1, 2)  # ...and when the cursor leaves the row, said and marked
    assert form.Status.text == "Qty: -2 is less than 0" and items.rows[0].backcolor == "#ffe0e0"
    items.current = (1, "Price")
    items._edit(typed="lots")
    assert items._finish() is False and form.Status.text == "Price: 'lots' isn't a number"  # (refused: can't be money)
    items._cancel()
    asked = []
    monkeypatch.setattr(program, "msgbox", lambda message, **kw: asked.append(message) or "no")
    monkeypatch.setattr(program, "save_file_dialog", lambda *a, **kw: pytest.fail("saved anyway"))
    form.SaveButton.widget.invoke()  # problems: the program asks first (its own choice), and here, no
    assert asked and asked[0].startswith("1 problem, the first: row 0: Qty: -2 is less than 0")
    items[0, "Qty"] = 2  # (fixed by code: Qty's rules hold)
    assert items.problems() == []


def test_unordered_rows_are_gray_and_ctrl_z_takes_an_edit_back(form):
    items = form.Items
    assert [row["Item"] for row in items.rows if row.forecolor] == ["Work gloves", "Watering can"]
    items.current = (5, "Qty")  # Work gloves
    items._edit(typed="2")
    items._finish(down=1)
    assert items.rows[5].forecolor == "" and items[5, "Total"] == D("17.98")
    items.undo()  # its cellchange works the totals out again, and the gray comes back
    assert items[5, "Qty"] == 0 and items[5, "Total"] == D("0.00") and items.rows[5].forecolor == "#909090"
    assert form.Totals.text.split()[3] == "101.67"
