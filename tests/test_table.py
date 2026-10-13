"""The Table control: typed columns, its data the Pythonic way, and spreadsheet editing."""

import time
from tkinter import ttk

import pytest

from readymade import Form, formfile
from readymade.controls import REGISTRY, Column
from readymade.controls import table as table_module
from readymade.controls.table import ColumnKind

COLUMNS = ["Item", "Price : number 2", "Qty : number", "In stock : check", "Size : S | M | L",
           "Total : number 2, readonly"]


# ----- columns and values (no window needed) -----

def test_column_lines():
    kinds = [ColumnKind.parse(line) for line in COLUMNS]
    assert [(k.name, k.kind, k.decimals, k.choices, k.readonly) for k in kinds] == [
        ("Item", "text", None, (), False), ("Price", "number", 2, (), False), ("Qty", "number", None, (), False),
        ("In stock", "check", None, (), False), ("Size", "choice", None, ("S", "M", "L"), False),
        ("Total", "number", 2, (), True)]
    assert [k.line() for k in kinds] == ["Item", "Price : number 2", "Qty : number", "In stock : check",
                                         "Size : S | M | L", "Total : number 2, readonly"]
    assert ColumnKind.parse("Notes : readonly").kind == "text"
    for bad in (": number", "A : date", "A : number two", "A : check, number"):
        with pytest.raises(ValueError):
            ColumnKind.parse(bad)


def test_values_take_their_columns_kind():
    price, qty, stock, size = (ColumnKind.parse(line) for line in COLUMNS[1:5])
    assert price.convert("1.2") == 1.2 and price.convert(3) == 3.0 and price.convert("1,234.567") == 1234.57
    assert price.show(1.2) == "1.20" and price.convert("") == 0
    assert qty.convert("3") == 3 and isinstance(qty.convert("3"), int) and qty.convert("2.5") == 2.5
    assert stock.convert("yes") is True and stock.convert("") is False and stock.convert(1) is True
    assert size.convert("m") == "M" and size.convert("") == "S"  # (blank: the first choice)
    for kind, bad in ((price, "abc"), (price, True), (stock, "maybe"), (size, "XL")):
        with pytest.raises(ValueError):
            kind.convert(bad)


def test_columns_arithmetic_is_element_wise():
    price, qty = Column([1.5, 2.0, 4.0], "Price"), Column([2, 3, 0], "Qty")
    assert price * qty == [3.0, 6.0, 0.0]
    assert price + 1 == [2.5, 3.0, 5.0] and 10 - qty == [8, 7, 10] and -qty == [-2, -3, 0]
    assert price / 2 == [0.75, 1.0, 2.0] and round(price * 1.1, 2) == [1.65, 2.2, 4.4]
    assert (price.sum(), qty.mean(), qty.min(), price.max()) == (7.5, 5 / 3, 0, 4.0)
    assert sum(qty) == 5 and list(qty) == [2, 3, 0] and len(qty) == 3 and qty[1:] == [3, 0]
    with pytest.raises(ValueError, match="different lengths"):
        price + Column([1])
    with pytest.raises(ValueError, match="no values"):
        Column([]).mean()


# ----- on a form -----



@pytest.fixture
def make_form(tmp_path):
    made = []

    def make(cls=Form, **props):
        design = formfile.FormDesign(name="Form1", width=480, height=260)
        spec = REGISTRY["Table"].new_spec("Stock", 8, 8, 460, 240)
        spec.update({"columns": COLUMNS, **props})
        design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = cls(tmp_path / "Form1.form")
        form.show()
        settle(form)
        made.append(form)
        return form

    yield make
    for form in made:
        form.root.destroy()


def settle(form):
    for _ in range(15):
        form.root.update()
        time.sleep(0.003)


def key(form, keysym, state=0):
    target = form.Stock._editor or form.Stock._tree
    target.event_generate("<KeyPress>", keysym=keysym, state=state)
    settle(form)


ROWS = [["Apples", 1.2, 3, True, "M"], {"Item": "Pears", "Price": "0.95", "Qty": 2}, ["Plums", 2.1, 0, "yes", "l"]]


@pytest.mark.usefixtures("display")
def test_the_data_the_pythonic_way(make_form):
    table = make_form().Stock
    table.rows = ROWS
    assert table.rows == [["Apples", 1.2, 3, True, "M", 0.0], ["Pears", 0.95, 2, False, "S", 0.0],
                          ["Plums", 2.1, 0, True, "L", 0.0]]
    table["Total"] = table["Price"] * table["Qty"]
    assert table["Total"] == [3.6, 1.9, 0.0] and table["total"] == [3.6, 1.9, 0.0]  # (headers in any case)
    assert table[1, "Price"] == 0.95 and table[-1, 4] == "L" and table.rows[0].asdict()["Size"] == "M"
    table[0, "Qty"] = "4"  # converted
    assert table[0, 2] == 4
    table.rows[0][0] = "Green apples"  # a row is a live view
    table.rows.append(["Kiwi", 0.5])
    table.rows.insert(0, ["Figs", 3])
    del table.rows[1]
    assert [r[0] for r in table.rows] == ["Figs", "Pears", "Plums", "Kiwi"] and len(table.rows) == 4
    assert table.rows[-1] == ["Kiwi", 0.5, 0, False, "S", 0.0]  # (missing cells: blank)
    table["In stock"] = True  # one value: every row
    assert all(table["In stock"])
    assert table._tree.item("1", "values")[1] == "0.95"  # (shown with its decimals)
    with pytest.raises(KeyError, match="no column 'Colour'; its columns: Item, Price"):
        table["Colour"]
    with pytest.raises(TypeError, match="a row is Stock.rows\\[2\\]"):
        table[2]
    with pytest.raises(IndexError, match="has 4 rows"):
        table[9, 0]
    with pytest.raises(ValueError, match="7 values for 6 columns"):
        table.rows.append([1, 2, 3, 4, 5, 6, 7])
    with pytest.raises(ValueError, match="Price: 'lots' isn't a number"):
        table[0, "Price"] = "lots"


@pytest.mark.usefixtures("display")
def test_editing_like_a_spreadsheet(make_form):
    changes = []

    class Form1(Form):
        def Stock_cellchange(self, row, column):
            changes.append((row, column, self.Stock[row, column]))
            self.Stock["Total"] = self.Stock["Price"] * self.Stock["Qty"]

        def Stock_rowadd(self, row):
            changes.append(("add", row))
            self.Stock[row, "Qty"] = 1  # a default

    form = make_form(Form1)
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    settle(form)
    table.current = (1, "Price")
    key(form, "2")  # typing replaces the cell...
    assert table._editor is not None and table._editor.get() == "2"
    key(form, "Return")  # ...and Enter saves it and moves down
    assert table[1, "Price"] == 2.0 and table.current == (2, 1) and changes[0] == (1, 1, 2.0)
    assert table[1, "Total"] == 4.0  # (the handler)
    key(form, "F2")  # edits what's there
    table._editor.delete(0, "end")
    table._editor.insert(0, "nope")
    key(form, "Return")  # not a number: it stays open
    assert table._editor is not None and table[2, "Price"] == 2.1
    key(form, "Escape")
    assert table._editor is None and table[2, "Price"] == 2.1
    key(form, "Right")
    key(form, "Right")  # In stock: Space ticks it
    key(form, "space")
    assert table[2, "In stock"] is False
    key(form, "Right")
    key(form, "Right")  # Total is readonly
    key(form, "5")
    assert table._editor is None
    key(form, "Down")  # the blank row at the bottom
    key(form, "Home")
    assert table.current == (3, 0)
    key(form, "K", state=0x1)  # (Shift)
    table._editor.insert("end", "iwi")
    key(form, "Tab")  # a new row, then the next cell
    assert len(table.rows) == 4 and table[3, "Item"] == "Kiwi" and table[3, "Qty"] == 1
    assert ("add", 3) in changes and table.current == (3, 1)
    key(form, "Up")
    key(form, "Up")
    key(form, "Up")
    key(form, "Up")  # (the top: it stays)
    assert table.current == (0, 1)
    table.current = (0, "Size")
    key(form, "Return")  # a choice: a list to pick from
    assert table._editor.cget("values") == ("S", "M", "L") and table._editor.get() == "M"
    table._editor.set("L")
    table._editor.event_generate("<<ComboboxSelected>>")
    settle(form)
    assert table._editor is None and table[0, "Size"] == "L" and changes[-1] == (0, 4, "L")


@pytest.mark.usefixtures("display")
def test_delete_sort_and_switches(make_form):
    deleted, clicked = [], []

    class Form1(Form):
        def Stock_rowdelete(self, row, values):
            deleted.append((row, values[0]))

        def Stock_rowclick(self, row):
            clicked.append(row)

    form = make_form(Form1)
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    settle(form)
    table._header_clicked(1)  # a header click sorts...
    assert [r[0] for r in table.rows] == ["Pears", "Apples", "Plums"] and table._tree.heading("c1", "text") == "Price ▲"
    table._header_clicked(1)  # ...and again the other way
    assert [r[0] for r in table.rows] == ["Plums", "Apples", "Pears"]
    table.rows = ROWS  # (new rows: no longer sorted)
    assert table._tree.heading("c1", "text") == "Price"
    table.current = (0, 0)
    key(form, "Down")
    assert clicked == [1]
    key(form, "Delete")
    assert deleted == [(1, "Pears")] and [r[0] for r in table.rows] == ["Apples", "Plums"]
    table.deletable = False
    key(form, "Delete")
    assert len(table.rows) == 2
    table.addable = False
    assert not table._tree.exists("new")
    table.sortable = False
    table._header_clicked(0)
    assert [r[0] for r in table.rows] == ["Apples", "Plums"]
    table.editable = False
    key(form, "x")
    assert table._editor is None


@pytest.mark.usefixtures("display")
def test_csv_and_changing_columns(make_form, tmp_path):
    table = make_form().Stock
    table.rows = ROWS
    table.save_csv("stock.csv")  # (in the program's folder)
    text = (tmp_path / "stock.csv").read_text(encoding="utf-8")
    assert text.splitlines()[0] == "Item,Price,Qty,In stock,Size,Total" and "Apples,1.20,3,True,M,0.00" in text
    (tmp_path / "other.csv").write_text("size,ITEM,ignored\nL,Melon,x\n,Lime,y\n", encoding="utf-8")
    table.load_csv(tmp_path / "other.csv")  # by header, in any order; missing columns blank
    assert table.rows == [["Melon", 0, 0, False, "L", 0], ["Lime", 0, 0, False, "S", 0]]
    (tmp_path / "bad.csv").write_text("Item,Price\nX,cheap\n", encoding="utf-8")
    with pytest.raises(ValueError, match="bad.csv, line 2: Price: 'cheap' isn't a number"):
        table.load_csv("bad.csv")
    table.columns = ["Item", "Size : number"]  # what fits stays; what doesn't is blank
    assert table.rows == [["Melon", 0], ["Lime", 0]] and table.columns == ["Item", "Size : number"]
    assert table.headers == ["Item", "Size"]
    with pytest.raises(ValueError, match="same header: item"):
        table.columns = ["Item", "item"]


@pytest.mark.usefixtures("display")
def test_a_choices_list_from_the_keyboard(make_form):
    form = make_form()
    table, call = form.Stock, form.root.tk.call
    table.rows = ROWS
    table._tree.focus_force()
    settle(form)

    def in_list(keysym):
        call("event", "generate", f"{table._editor}.popdown.f.l", "<KeyPress>", "-keysym", keysym)
        settle(form)

    table.current = (0, "Size")
    key(form, "Return")  # its list opens (and the row stays chosen)
    assert call("winfo", "ismapped", f"{table._editor}.popdown") and table._tree.selection() == ("0",)
    in_list("Down")
    in_list("Return")  # chosen: saved, and the keys are the table's again
    assert table[0, "Size"] == "L" and table._editor is None and not call("grab", "current")
    key(form, "Return")
    in_list("Up")
    in_list("Escape")  # never mind: no change, nothing left open
    assert table[0, "Size"] == "L" and table._editor is None and not call("grab", "current")
    key(form, "Down")
    assert table.current == (1, 4)


@pytest.mark.usefixtures("display")
def test_the_cell_cursor_shows_on_a_chosen_row(make_form):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table.current = (1, 0)
    settle(form)
    chosen = ttk.Style(table._tree).lookup("Treeview", "foreground", ("selected",))
    assert table._lines[0].cget("background") == chosen  # (not blue on Windows' blue)
    table._tree.selection_set("0")
    settle(form)
    assert table._lines[0].cget("background") == table_module.CURSOR_COLOR
