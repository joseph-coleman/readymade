"""The DataTable control: typed columns, its data the Pythonic way, and spreadsheet editing."""

import datetime
import re
import time
from decimal import Decimal as D
from tkinter import font as tkfont
from tkinter import ttk
from types import SimpleNamespace

import pytest

from readymade import Form, formfile
from readymade.controls import REGISTRY, Block, Column
from readymade.controls import datatable as datatable_module
from readymade.controls.datatable import ColumnKind, _shared

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
    for bad in (": number", "A : when", "A : number two", "A : check, number"):
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


def test_sharing_out_widths():
    assert _shared(300, [50, 50, 50]) == [100, 100, 100]
    assert _shared(300, [50, 150, 50]) == [75, 150, 75]  # (one needs more: the rest share what's left)
    assert _shared(100, [60, 60]) == [60, 60]  # (they don't fit: the least, scrolled sideways)


def test_money_is_exact():
    money, yen = ColumnKind.parse("Price : money"), ColumnKind.parse("Yen : money 0, readonly")
    assert (money.kind, money.decimals, money.line(), yen.line()) == ("money", 2, "Price : money", "Yen : money 0, readonly")
    assert money.convert("2.675") == D("2.68")  # (a half up, as a receipt; a float rounds this to 2.67)
    assert money.convert(1.1) == D("1.10") and money.convert(3) == D("3.00") and money.convert("") == D("0.00")
    assert money.convert("$1,234.5") == D("1234.50") and money.convert(" \u20ac9.99 ") == D("9.99")
    assert yen.convert("1500.4") == D("1500")
    assert money.show(D("1234.5")) == "1,234.50" and money.text(D("1234.5")) == "1234.50"  # (CSV: no commas)
    for bad in ("lots", True, "NaN", "inf"):
        with pytest.raises(ValueError, match="isn't a number"):
            money.convert(bad)
    price = Column([D("3.49"), D("12.00")], "Price")
    assert price * 1.1 == [D("3.839"), D("13.200")] and 2 * price == [D("6.98"), D("24.00")]  # (a float goes with money)
    assert price + 0.01 == [D("3.50"), D("12.01")] and (price > 5) == [False, True] and price.sum() == D("15.49")
    assert Block([[D("1.00"), 2]], ["A", "B"]) * 0.5 == [[D("0.500"), 1.0]]
    assert ColumnKind.parse("N : number 2").convert(D("3.456")) == 3.46  # (number takes money too)


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


def test_conditions_choose_values():
    qty, size = Column([2, 0, 5, 1], "Qty"), Column(["S", "M", "L", "M"], "Size")
    assert (qty > 1) == [True, False, True, False] and (qty <= 1) == [False, True, False, True]
    assert (0 < qty) == [True, False, True, True]  # (the number first works too)
    assert size.eq("M") == [False, True, False, True] and size.ne("M") == [True, False, True, False]
    assert size == ["S", "M", "L", "M"]  # (== is still the whole column)
    assert size.isin(["S", "L"]) == [True, False, True, False] and size.isin("M") == [False, True, False, True]
    assert qty[qty.isin(range(1, 3))] == [2, 1] and size.isin([]) == [False] * 4
    assert ((qty > 0) & size.eq("M")) == [False, False, False, True]
    assert ((qty > 4) | size.eq("S")) == [True, False, True, False] and ~(qty > 0) == [False, True, False, False]
    assert qty[qty > 1] == [2, 5] and qty[qty > 1].sum() == 7 and qty[qty > 9] == []
    assert (qty > 4).any() and not (qty > 5).any() and (qty >= 0).all() and not (qty > 0).all()
    for ambiguous in (lambda: bool(qty > 4), lambda: (qty > 0) and (qty < 3), lambda: not qty):
        with pytest.raises(TypeError, match="isn't True or False: ask column.any"):
            ambiguous()
    assert qty[[3, 0]] == [1, 2] and size[1:3] == ["M", "L"] and qty[-1] == 1
    with pytest.raises(ValueError, match="a condition of 2 True/False for Qty's 4 values"):
        qty[[True, False]]
    with pytest.raises(IndexError, match="Qty has 4 values, so there's no value 7"):
        qty[[7]]


def test_blocks_of_cells():
    block = Block([[1.5, 2], [2.0, 3]], ["Price", "Qty"])
    assert block.shape == (2, 2) and len(block) == 2 and block.headers == ["Price", "Qty"]
    assert block == [[1.5, 2], [2.0, 3]] and block.tolist() == [[1.5, 2], [2.0, 3]]
    assert block[1] == [2.0, 3] and block["qty"] == Column([2, 3]) and block["Price"].name == "Price"
    assert block[1:] == [[2.0, 3]] and [price * qty for price, qty in block] == [3.0, 6.0]
    assert block * 2 == [[3.0, 4], [4.0, 6]] and 10 - block == [[8.5, 8], [8.0, 7]]
    assert block + block == [[3.0, 4], [4.0, 6]] and -block == [[-1.5, -2], [-2.0, -3]]
    assert round(block / 3, 1) == [[0.5, 0.7], [0.7, 1.0]]
    with pytest.raises(ValueError, match="different shapes: 2 x 2 and 1 x 2"):
        block + [[1, 2]]
    with pytest.raises(TypeError, match="a number or a block of the same shape"):
        block * Column([1, 2])
    with pytest.raises(KeyError, match="no column 'Total'; its columns: Price, Qty"):
        block["Total"]


# ----- on a form -----



@pytest.fixture
def make_form(tmp_path):
    made = []

    def make(cls=Form, **props):
        design = formfile.FormDesign(name="Form1", width=480, height=260)
        spec = REGISTRY["DataTable"].new_spec("Stock", 8, 8, 460, 240)
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
def test_editing_like_a_spreadsheet(make_form, monkeypatch):
    changes, said = [], []
    monkeypatch.setattr(datatable_module.messagebox, "showwarning", lambda title, message, **kw: said.append(message))

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
    key(form, "Return")  # not a number: it says so, and stays open
    assert table._editor is not None and table[2, "Price"] == 2.1 and said == ["Price: 'nope' isn't a number"]
    assert str(table._tree.tk.call("focus")) == str(table._editor)  # (the keyboard back in it)
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
    assert clicked == [1] and table._tree.selection() == ()  # (moving chooses no rows, as in a spreadsheet)
    key(form, "space", state=0x1)  # Shift+Space: this row
    assert table._tree.selection() == ("1",)
    key(form, "Delete")  # a chosen row: it goes
    assert deleted == [(1, "Pears")] and [r[0] for r in table.rows] == ["Apples", "Plums"]
    key(form, "Delete")  # none chosen: the cell is emptied
    assert [r[0] for r in table.rows] == ["Apples", ""] and len(deleted) == 1
    key(form, "Up")
    key(form, "Down", state=0x1)  # Shift+Down: from here to there
    assert table._tree.selection() == ("0", "1")
    key(form, "Escape")  # (not editing: none chosen)
    assert table._tree.selection() == ()
    table.deletable = False
    key(form, "space", state=0x1)
    key(form, "Delete")
    assert len(table.rows) == 2
    table.addable = False
    assert not table._tree.exists("new")
    table.sortable = False
    table._header_clicked(0)
    assert [r[0] for r in table.rows] == ["Apples", ""]  # (not sorted)
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
    key(form, "Return")  # its list opens (and the cursor stays)
    assert call("winfo", "ismapped", f"{table._editor}.popdown") and table._tree.selection() == ()
    in_list("Down")
    in_list("Return")  # chosen: saved, down a row (as Enter does), and the keys are the table's again
    assert table[0, "Size"] == "L" and table._editor is None and not call("grab", "current")
    assert table.current == (1, 4)
    key(form, "Return")
    in_list("Up")
    in_list("Escape")  # never mind: no change, nothing left open
    assert table[1, "Size"] == "S" and table._editor is None and not call("grab", "current")
    key(form, "Down")
    assert table.current == (2, 4)
    key(form, "Return")
    table._editor.set("M")
    table._editor.event_generate("<<ComboboxSelected>>")  # chosen with a click: it stays here
    settle(form)
    assert table[2, "Size"] == "M" and table.current == (2, 4)


@pytest.mark.usefixtures("display")
def test_the_cell_cursor_shows_on_a_chosen_row(make_form):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table.current = (1, 0)
    table._choose_row(1)
    settle(form)
    style = ttk.Style(table._tree)
    chosen_text = style.lookup("Treeview", "foreground", ("selected",))
    highlight = style.lookup("Treeview", "background", ("selected",))
    assert table._lines[0].cget("background") == chosen_text  # (not blue on Windows' blue)
    table._tree.selection_set("0")
    settle(form)
    assert table._lines[0].cget("background") == highlight  # (the system's, as the chosen rows)
    usual = style.map("Treeview", "background")
    style.map("Treeview", background=[("selected", "")])  # a theme without one: blue
    try:
        table._follow()
        assert table._lines[0].cget("background") == datatable_module.CURSOR_COLOR
    finally:
        style.map("Treeview", background=usual)


@pytest.mark.usefixtures("display")
def test_slicing_like_numpy(make_form):
    table = make_form().Stock
    table.rows = ROWS + [["Figs", 3, 1]]
    table["Total"] = table["Price"] * table["Qty"]
    assert table[1:3, "Price":"Qty"] == [[0.95, 2], [2.1, 0]]  # (a header ends it, included)
    assert table[1:3, 1:3] == [[0.95, 2], [2.1, 0]]  # (a number doesn't, as in Python)
    assert table[:, ["Item", "Total"]] == [["Apples", 3.6], ["Pears", 1.9], ["Plums", 0.0], ["Figs", 3.0]]
    block = table[-2:, "Size":]
    assert isinstance(block, Block) and block.headers == ["Size", "Total"] and block.shape == (2, 2)
    assert table[0, "Price":"Total"] == [1.2, 3, True, "M", 3.6] and table[0, :2] == ["Apples", 1.2]
    assert table[0, "Total":"Qty":-1] == [3.6, "M", True, 3]  # (backward, both ends included)
    assert table[1:, "Price"] == Column([0.95, 2.1, 3.0]) and table[1:, "Price"].name == "Price"
    assert table[[3, 0], "Item"] == ["Figs", "Apples"] and table[2, :] == table.rows[2].tolist()
    big = table["Total"] > 2
    assert table[big, "Item"] == ["Apples", "Figs"] and table[~big, :].shape == (2, 6)
    assert table[table["Size"].eq("S") & (table["Qty"] > 0), "Item"] == ["Pears", "Figs"]

    table[big, "Price"] = table[big, "Price"] * 0.5  # setting what a condition chose
    assert table["Price"] == [0.6, 0.95, 2.1, 1.5]
    prices = table[:, "Price":"Qty"]
    table[:, "Price":"Qty"] = prices * 2  # a block back where it came from
    assert table[:, "Price":"Qty"] == [[1.2, 6], [1.9, 4], [4.2, 0], [3.0, 2]]
    table[2, "Price":"Qty"] = ["7.5", "4"]  # (converted, as ever)
    table[:2, ["In stock", "Size"]] = [[False, "s"], [True, "l"]]
    assert table.rows[:3] == [["Apples", 1.2, 6, False, "S", 3.6], ["Pears", 1.9, 4, True, "L", 1.9],
                              ["Plums", 7.5, 4, True, "L", 0.0]]
    table[1:, "Total"] = 0  # one value: every cell chosen
    table[:2, "Price":"Qty"] = 1
    assert table["Total"] == [3.6, 0, 0, 0] and table[:2, "Price":"Qty"] == [[1, 1], [1, 1]]
    assert table._tree.item("1", "values")[1] == "1.00"  # (shown)

    before = [r.tolist() for r in table.rows]
    with pytest.raises(ValueError, match="Qty: 'x' isn't a number"):
        table[:2, "Price":"Qty"] = [[5, 5], [5, "x"]]
    assert [r.tolist() for r in table.rows] == before  # (nothing changed: all are converted first)
    with pytest.raises(ValueError, match="a block of 1 x 2 for 2 rows x 2 columns"):
        table[:2, "Price":"Qty"] = [[5, 5]]
    with pytest.raises(ValueError, match="3 values for 4 rows"):
        table[:, "Price"] = [1, 2, 3]
    with pytest.raises(ValueError, match="a Column fills one column"):
        table[:, "Price":"Qty"] = table["Price"]
    with pytest.raises(ValueError, match="a condition of 2 True/False for Stock's 4 rows"):
        table[[True, False], :]
    with pytest.raises(TypeError, match="or Stock\\[2, :\\], a copy of its values"):
        table[2]
    with pytest.raises(TypeError, match="rows are chosen by a number"):
        table["Apples", "Price"]


@pytest.mark.usefixtures("display")
def test_chosen_rows_stay_chosen_and_a_sort_says_when_it_isnt(make_form):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table.current = (1, 0)
    table._tree.selection_set("0", "1")
    table["Total"] = 5  # only values changed: the same rows chosen
    assert table._tree.selection() == ("0", "1")
    table.rows.append(["Figs"])  # rows added: none chosen
    assert table._tree.selection() == ()
    table.sort("Price")
    table[0, "Price"] = 0.5  # still in order: still sorted
    assert table._tree.heading("c1", "text") == "Price ▲"
    table[0, "Price"] = 9  # not now
    assert table._tree.heading("c1", "text") == "Price"


@pytest.mark.usefixtures("display")
def test_choosing_rows_by_click_ctrl_click_and_cmd_on_a_mac(make_form, monkeypatch):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table.current = (0, 0)
    settle(form)

    def click(row, state=0):
        settle(form)
        x, y, width, height = table._tree.bbox(str(row), "c1")
        return table._click(SimpleNamespace(x=x + width // 2, y=y + height // 2, state=state))

    assert click(1) == "break" and table.current == (1, 1) and table._tree.selection() == ()  # just the cell
    click(2, state=0x1)  # Shift+click: from the last plain click's row
    assert table._tree.selection() == ("1", "2")
    monkeypatch.setattr(datatable_module, "_PRIMARY", 0x8)  # Command, as on a Mac
    click(0, state=0x8)  # ⌘-click: that row too
    assert table._tree.selection() == ("0", "1", "2") and table.current == (0, 1)
    click(1, state=0x8)  # and again: not now
    assert table._tree.selection() == ("0", "2")
    click(2)
    assert table._tree.selection() == ()


@pytest.mark.usefixtures("display")
def test_typing_starts_an_edit_by_each_systems_rules(make_form, monkeypatch):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table.current = (0, "Item")
    real = datatable_module.keys.name
    monkeypatch.setattr(datatable_module.keys, "name", lambda char, keysym, state: real(char, keysym, state, "win32"))
    assert table._key(SimpleNamespace(char="f", keysym="f", state=0x20000)) is None  # Alt+F: an access key's
    assert table._editor is None
    assert table._key(SimpleNamespace(char="@", keysym="at", state=0x20004)) == "break"  # AltGr types @
    assert table._editor.get() == "@"
    table._cancel()
    assert table._key(SimpleNamespace(char="", keysym="Down", state=0x20000)) == "break"  # (Alt+Down: nothing)
    assert table.current == (0, 0)
    assert table._key(SimpleNamespace(char="", keysym="Down", state=0x4)) == "break"  # Ctrl+Down: the bottom
    assert table.current == (3, 0)  # (the blank row)


@pytest.mark.usefixtures("display")
def test_copy_and_paste_like_a_spreadsheet(make_form):
    events = []

    class Form1(Form):
        def Stock_cellchange(self, row, column):
            events.append(("change", row, column))

        def Stock_rowadd(self, row):
            events.append(("add", row))
            self.Stock[row, "Qty"] = 1

    form = make_form(Form1)
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    table.current = (0, "Price")
    settle(form)
    key(form, "c", state=0x4)  # Ctrl+C: the cell
    assert form.root.clipboard_get() == "1.20"
    table._tree.selection_set("0", "2")
    table.copy()  # several rows chosen: those rows, tab-separated, as spreadsheets copy
    assert form.root.clipboard_get() == "Apples\t1.20\t3\tTrue\tM\t0.00\nPlums\t2.10\t0\tTrue\tL\t0.00"

    table.current = (1, "Item")
    table.paste('Melon\t"4.5"\t2\r\nLime, "Persian"\t0.4\t9\r\n')  # (as Excel copies it)
    assert table.rows[1][:3] == ["Melon", 4.5, 2] and table.rows[2][:3] == ['Lime, "Persian"', 0.4, 9]
    assert events == [("change", 1, 0), ("change", 1, 1), ("change", 2, 0), ("change", 2, 1), ("change", 2, 2)]
    events.clear()
    table.current = (2, "Size")
    table.paste("S\t99\textra\nM\t98\textra")  # Total is readonly and nothing's past it; a new row at the bottom
    assert table[2, "Size"] == "S" and table[2, "Total"] == 0 and table.rows[3] == ["", 0, 1, False, "M", 0]
    assert events == [("add", 3), ("change", 2, 4), ("change", 3, 4)]
    table.current = (0, "Price")
    with pytest.raises(ValueError, match="row 1: Price: 'cheap' isn't a number"):
        table.paste("1\ncheap")  # (nothing changes)
    assert table[0, "Price"] == 1.2

    table.current = (0, "Qty")
    table._tree.selection_set("0", "1", "2")
    table.paste("7")  # one value, several rows chosen: each of them
    assert table["Qty"] == [7, 7, 7, 1]
    table._tree.selection_set(())
    table.cut()  # the cell: copied, then emptied
    assert form.root.clipboard_get() == "7" and table[0, "Qty"] == 0
    table._choose_row(0)
    table.copy()  # one chosen row: the row
    assert form.root.clipboard_get() == "Apples\t1.20\t0\tTrue\tM\t0.00"
    key(form, "a", state=0x4)  # Ctrl+A
    assert table._tree.selection() == ("0", "1", "2", "3")
    table.editable = False
    form.root.clipboard_clear()
    form.root.clipboard_append("5")
    key(form, "v", state=0x4)  # (not editable: nothing)
    assert table[0, "Qty"] == 0


@pytest.mark.usefixtures("display")
def test_whole_rows_paste_from_the_first_column_and_a_refused_paste_says_why(make_form, monkeypatch):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    table._tree.selection_set("0", "1")
    table.copy()
    table._move(3, 2)  # the blank row, in Qty
    settle(form)
    key(form, "v", state=0x4)  # whole rows: from Item, not from Qty
    assert table.rows[3:] == [["Apples", 1.2, 3, True, "M", 0], ["Pears", 0.95, 2, False, "S", 0]]
    said = []
    monkeypatch.setattr(datatable_module.messagebox, "showwarning", lambda title, message, **kw: said.append(message))
    form.root.clipboard_clear()
    form.root.clipboard_append("Apples")
    table.current = (0, "Price")
    key(form, "v", state=0x4)
    assert said == ["Nothing was pasted: row 0: Price: 'Apples' isn't a number"] and table[0, "Price"] == 1.2


@pytest.mark.usefixtures("display")
def test_widths_shared_set_or_autosized(make_form):
    form = make_form()
    table = form.Stock
    table.rows = ROWS + [["A rather long name for an item", 1]]
    settle(form)
    shared = table.widths
    assert table._tree.winfo_width() - len(shared) - 6 <= sum(shared)  # shared out: all its width used
    assert table._tree.xview() == (0.0, 1.0)  # (all of them in sight)
    assert not table._parts[3].winfo_ismapped()  # (they fit: no scrollbar across)
    table.width = 400  # still shared: they follow the table's size
    settle(form)
    assert sum(table.widths) < sum(shared)
    table.autosize_columns("Item")  # what it holds; the others share what's left
    settle(form)
    cell, _ = table._fonts()
    item = table.widths[0]
    assert item >= cell.measure("A rather long name for an item")
    assert table._parts[3].winfo_ismapped()  # (too narrow for them all now: they scroll sideways)
    narrow = table.widths[1:]
    table.width = 900  # Item's width is someone's: it stays, and the others share the rest
    settle(form)
    assert table.widths[0] == item and all(w > n for w, n in zip(table.widths[1:], narrow))
    assert table._tree.xview() == (0.0, 1.0) and not table._parts[3].winfo_ismapped()
    table.widths = {"price": 120, 2: 90}
    assert table.widths[1:3] == [120, 90]
    table.widths = [100] * 6
    assert table.widths == [100] * 6
    with pytest.raises(ValueError, match="2 widths for 6 columns"):
        table.widths = [1, 2]
    table.columns = COLUMNS  # new columns: shared out again
    settle(form)
    assert table.widths != [100] * 6 and table._tree.xview() == (0.0, 1.0)


@pytest.mark.usefixtures("display")
def test_many_columns_scroll_sideways(make_form):
    form = make_form()
    table = form.Stock
    table.columns = [f"Column number {i}" for i in range(12)]  # (none narrower than its header)
    table.rows = [[f"r{r}c{c}" for c in range(12)] for r in range(3)]
    table._tree.focus_force()
    settle(form)
    across = table._parts[3]
    assert across.winfo_ismapped() and sum(table.widths) > table._tree.winfo_width()
    assert table._tree.xview()[0] == 0
    table.current = (0, 0)
    key(form, "End")  # the last column: scrolled to it
    assert table.current == (0, 11) and table._tree.xview()[1] > 0.99
    assert table._lines[0].winfo_ismapped()  # (the cursor's there)
    key(form, "Home")
    assert table._tree.xview()[0] == 0.0


@pytest.mark.usefixtures("display")
def test_an_edit_scrolled_out_of_sight_ends_and_current_reaches_the_blank_row(make_form):
    form = make_form()
    table = form.Stock
    table.rows = [[f"Row {i}", i] for i in range(40)]
    table._tree.focus_force()
    table.current = (0, "Price")
    settle(form)
    key(form, "7")
    table._tree.yview_moveto(1.0)  # (the mouse wheel)
    settle(form)
    assert table._editor is None and table[0, "Price"] == 7  # kept, as when clicking elsewhere
    table.current = (40, "Item")  # len(rows): the blank row at the bottom
    assert table.current == (40, 0)
    table.addable = False  # (no blank row now)
    with pytest.raises(IndexError, match="has 40 rows"):
        table.current = (40, 0)


@pytest.mark.usefixtures("display")
def test_cellvalidate_refuses_what_the_program_wont_have(make_form, monkeypatch):
    seen, said = [], []
    monkeypatch.setattr(datatable_module.messagebox, "showwarning", lambda title, message, **kw: said.append(message))

    class Form1(Form):
        def Stock_cellvalidate(self, row, column, value):
            seen.append((row, column, value))
            if self.Stock.headers[column] == "Qty" and value < 0:
                return "Qty can't be less than 0"
            if self.Stock.headers[column] == "In stock":
                return False  # (no reason given)
            return None

    form = make_form(Form1)
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    table.current = (0, "Qty")
    settle(form)
    key(form, "minus")
    table._editor.insert("end", "2")
    key(form, "Return")  # refused: said, and the editor stays open
    assert seen[-1] == (0, 2, -2) and said == ["Qty can't be less than 0"]  # (the value as its column's kind)
    assert table._editor is not None and table[0, "Qty"] == 3
    table._editor.delete(0, "end")
    table._editor.insert(0, "5")
    key(form, "Return")
    assert table[0, "Qty"] == 5 and table._editor is None
    table.current = (0, "In stock")
    key(form, "space")  # a tick refused
    assert table[0, "In stock"] is True and said[-1] == "In stock: False isn't allowed"
    table.current = (0, "Qty")
    form.root.clipboard_clear()
    form.root.clipboard_append("4\n-1")
    key(form, "v", state=0x4)  # a paste: every cell checked first, so nothing changes
    assert table["Qty"][:2] == [5, 2] and said[-1] == "Nothing was pasted: row 1: Qty can't be less than 0"
    with pytest.raises(ValueError, match="row 1: Qty can't be less than 0"):
        table.paste("4\n-1")  # (from code: the ValueError)
    table[1, "Qty"] = -7  # code isn't checked
    assert table[1, "Qty"] == -7


@pytest.mark.usefixtures("display")
def test_columnclick_and_sorting_your_own_way(make_form):
    clicks = []

    def natural(text):  # (as natsort's natsort_keygen() does, roughly)
        return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", text)]

    class Form1(Form):
        def Stock_columnclick(self, column):
            clicks.append(column)
            if column == 0:  # Item: in natural order, the other way if it already is
                self.Stock.sort(column, descending=self.Stock.sorted_by == (0, False), key=natural)

    form = make_form(Form1)
    table = form.Stock
    table.rows = [["Item 10"], ["item 2"], ["Item 1"]]
    table.sortable = False
    table._header_clicked(0)
    assert clicks == [0] and table["Item"] == ["Item 1", "item 2", "Item 10"] and table.sorted_by == (0, False)
    assert table._tree.heading("c0", "text") == "Item \u25b2"
    table._header_clicked(0)
    assert table["Item"] == ["Item 10", "item 2", "Item 1"] and table.sorted_by == (0, True)
    table[0, "Item"] = "Item 11"  # still in its (natural) order: still sorted
    assert table.sorted_by == (0, True)
    table._header_clicked(1)  # (not sortable, and the handler leaves Price alone)
    assert clicks == [0, 0, 1] and table["Item"] == ["Item 11", "item 2", "Item 1"]
    table.sortable = True
    table._header_clicked(1)  # sortable: sorted first, then columnclick
    assert clicks[-1] == 1 and table.sorted_by == (1, False)
    table.rows = [["b", 2], ["a", 2], ["c", 1]]
    table.rows.sort(key=lambda row: (row["Price"], row["Item"]))  # rows sort as a list does
    assert table["Item"] == ["c", "a", "b"] and table.sorted_by is None
    table.rows.sort(reverse=True)
    assert table["Item"] == ["c", "b", "a"]
    with pytest.raises(TypeError, match="Item can't be sorted that way"):
        table.sort("Item", key=lambda value: None if value == "a" else value)


@pytest.mark.usefixtures("display")
def test_enter_moves_where_its_told(make_form):
    form = make_form(enter_moves="right")  # (as set in the designer)
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    table.current = (0, "Item")
    settle(form)
    for typed in ("Figs", "3.5", "4"):  # typing along a row, with no arrow keys
        key(form, typed[0])
        table._editor.delete(0, "end")
        table._editor.insert(0, typed)
        key(form, "Return")
    assert table.rows[0][:3] == ["Figs", 3.5, 4] and table.current == (0, 3)
    table.current = (0, "Size")
    key(form, "Return")  # a choice's list, answered with Enter: right too
    table._editor.set("L")
    table._choice_keyed = True
    table._editor.event_generate("<<ComboboxSelected>>")
    settle(form)
    assert table[0, "Size"] == "L" and table.current == (0, 5)
    for where, then in (("stay", (1, 2)), ("left", (1, 1)), ("up", (0, 2)), ("down", (2, 2)), ("right", (1, 3))):
        table.enter_moves = where
        table.current = (1, "Qty")
        key(form, "7")
        key(form, "Return")
        assert table.current == then, where
    with pytest.raises(ValueError, match="enter_moves must be one of: down, right, left, up, stay"):
        table.enter_moves = "sideways"


@pytest.mark.usefixtures("display")
def test_undo_and_redo_the_users_changes(make_form):
    events = []

    class Form1(Form):
        def Stock_cellchange(self, row, column):
            events.append(("change", row, column))

        def Stock_rowadd(self, row):
            self.Stock[row, "Qty"] = 1  # (a default: code's, so not a step of its own)

        def Stock_rowdelete(self, row, values):
            events.append(("delete", row, values[0]))

    form = make_form(Form1)
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    assert not table.can_undo and not table.can_redo
    table.current = (0, "Price")
    settle(form)
    key(form, "9")
    key(form, "Return")  # an edit...
    assert table[0, "Price"] == 9 and table.can_undo
    events.clear()
    key(form, "z", state=0x4)  # ...taken back with Ctrl+Z
    assert table[0, "Price"] == 1.2 and events == [("change", 0, 1)] and table.current == (0, 1)
    key(form, "y", state=0x4)  # and made again (Ctrl+Y; Ctrl+Shift+Z too)
    assert table[0, "Price"] == 9 and not table.can_redo
    table[1, "Price"] = 5  # code's changes aren't steps
    table.undo()
    assert table[0, "Price"] == 1.2 and table[1, "Price"] == 5

    table._move(3, 0)  # the blank row: a new row, with rowadd's default
    key(form, "K", state=0x1)
    key(form, "Return")
    assert table.rows[3][:3] == ["K", 0, 1]
    events.clear()
    table.undo()  # the whole new row goes
    assert len(table.rows) == 3 and events == [("delete", 3, "K")]
    table.redo()  # and comes back as it was, default and all
    assert table.rows[3][:3] == ["K", 0, 1]

    table.sort("Item")  # (rows sorted between: undo still finds its rows)
    table.current = (0, "Item")
    table._choose_row(0)
    table._tree.selection_add("1")
    gone = [table[0, "Item"], table[1, "Item"]]
    key(form, "Delete")  # two rows deleted...
    assert len(table.rows) == 2
    events.clear()
    key(form, "z", state=0x5)  # (Ctrl+Shift+Z is redo: nothing to redo yet)
    assert len(table.rows) == 2
    table.undo()  # ...put back where they were, each cell a cellchange (totals and the like follow)
    assert table["Item"][:2] == gone and len(events) == 2 * 6
    table.current = (0, "Price")
    table.paste("1\n2\n3\n4\n5")  # a paste: one step, its new row too
    assert len(table.rows) == 5
    table.undo()
    assert len(table.rows) == 4 and table[0, "Price"] != 1

    table.rows = ROWS  # new rows: what came before is forgotten
    assert not table.can_undo and not table.can_redo
    table.current = (0, "Price")
    key(form, "7")
    key(form, "Return")
    table.editable = False  # (the user can't change it now: nor undo)
    assert not table.can_undo
    table.undo()
    assert table[0, "Price"] == 7


@pytest.mark.usefixtures("display")
def test_row_colors_stay_with_their_rows(make_form):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    table.rows[1].backcolor = "#ffe0e0"  # (an odd row: its color, not the shading)
    table.rows[2].forecolor = "#c00000"
    tree = table._tree

    def tags(iid):
        return list(tree.item(iid, "tags"))

    assert tags("1") == ["color #ffe0e0 "] and str(tree.tag_configure("color #ffe0e0 ", "background")) == "#ffe0e0"
    assert tags("2") == ["color  #c00000"]
    assert table.rows[1].backcolor == "#ffe0e0" and table.rows[0].backcolor == "" and table.rows[2].forecolor == "#c00000"
    table.sort("Item", descending=True)  # Plums, Pears, Apples: the colors go with them
    assert table.rows[0].forecolor == "#c00000" and table.rows[1].backcolor == "#ffe0e0"
    assert tags("1") == ["color #ffe0e0 "] and tags("0") == ["color  #c00000"]
    table.rows[1].backcolor = ""  # (back to the usual: shaded, as an odd row)
    assert tags("1") == ["odd"]
    with pytest.raises(ValueError):
        table.rows[0].backcolor = "reddish"
    table.rows = ROWS  # new rows: no colors
    assert table.rows[2].forecolor == "" and all(tags(i) in ([], ["odd"], ["new"]) for i in tree.get_children())


@pytest.mark.usefixtures("display")
def test_numbers_and_money_line_up_on_the_right(make_form):
    table = make_form().Stock
    table.columns = ["Item", "Price : money", "Qty : number", "Ok : check"]
    assert [str(table._tree.column(f"c{i}", "anchor")) for i in range(4)] == ["w", "e", "e", "center"]


@pytest.mark.usefixtures("display")
def test_the_editor_isnt_clipped_by_short_rows(make_form):
    form = make_form()
    table = form.Stock
    table.rows = ROWS
    style = ttk.Style(table._tree)
    usual = style.lookup("Treeview", "rowheight")
    style.configure("Treeview", rowheight=12)  # (shorter than a text box: as on a Mac)
    try:
        table._refresh()
        table._tree.focus_force()
        table.current = (1, "Item")
        settle(form)
        table._edit()
        settle(form)
        editor, (_, y, _, h) = table._editor_box, table._tree.bbox("1", "c0")
        assert h < editor.winfo_reqheight() == editor.winfo_height()  # all of it, not the cell's height
        assert abs((editor.winfo_y() + editor.winfo_height() / 2) - (y + h / 2)) <= 1  # centered on the cell
    finally:
        style.configure("Treeview", rowheight=usual)  # ("": as before, the theme's own)


@pytest.mark.usefixtures("display")
def test_a_big_fonts_editor_is_as_tall_as_its_text(make_form):
    form = make_form(font="TkDefaultFont, 20")
    table = form.Stock
    table.rows = ROWS
    table._tree.focus_force()
    table.current = (0, "Item")
    settle(form)
    table._edit()
    settle(form)
    box, entry = table._editor_box, table._editor
    assert box.winfo_height() >= entry.winfo_reqheight() and box.winfo_ismapped()
    assert tkfont.Font(font=entry.cget("font")).actual("size") == 20
    shown = ttk.Style(table._tree).lookup(table._tree.cget("style"), "font")  # (the rows' font: 20 too)
    assert tkfont.Font(font=shown).actual("size") == 20
    assert entry.cget("justify") == "left"
    table._cancel()
    table.current = (0, "Price")
    table._edit()
    assert table._editor.cget("justify") == "right"  # (as the column's numbers line up: no jump)
    table._cancel()
    style = ttk.Style(table._tree)
    table.current = (1, "Item")
    table._edit()
    assert str(table._editor_box.cget("highlightcolor")) == str(table._cursor_color(False))  # the cursor's color
    table._cancel()
    table._choose_row(1)
    table._edit()  # on a chosen row: the chosen text's color, as the cursor (not lost in the highlight)
    assert str(table._editor_box.cget("highlightcolor")) == str(style.lookup(table._tree.cget("style"), "foreground", ("selected",)))


def test_date_columns():
    due, us = ColumnKind.parse("Due : date"), ColumnKind.parse("When : date %m/%d/%Y, readonly")
    assert (due.kind, due.format, due.line(), us.line()) == ("date", "%Y-%m-%d", "Due : date", "When : date %m/%d/%Y, readonly")
    assert due.convert("2026-10-14") == datetime.date(2026, 10, 14) and due.convert("") is None and due.blank() is None
    assert us.convert("10/14/2026") == datetime.date(2026, 10, 14) == us.convert("2026-10-14")  # (and year-month-day)
    assert us.show(datetime.date(2026, 1, 2)) == "01/02/2026" and us.text(datetime.date(2026, 1, 2)) == "2026-01-02"
    assert us.show(None) == "" and us.text(None) == ""
    assert due.convert(datetime.datetime(2026, 1, 2, 9, 30)) == datetime.date(2026, 1, 2)
    for bad in ("soon", 7, True):
        with pytest.raises(ValueError, match="isn't a date"):
            due.convert(bad)
    days = Column([datetime.date(2026, 1, 5), None, datetime.date(2026, 3, 1)], "Due")
    assert (days < datetime.date(2026, 2, 1)) == [True, False, False]  # (an empty date: neither before nor after)
    assert (days >= datetime.date(2026, 2, 1)) == [False, False, True]
    assert sorted(days, key=due.sort_key) == [datetime.date(2026, 1, 5), datetime.date(2026, 3, 1), None]


@pytest.mark.usefixtures("display")
def test_a_date_cells_month_drops_down(make_form):
    from readymade.controls.dates import DropMonth

    changes = []

    class Form1(Form):
        def Stock_cellchange(self, row, column):
            changes.append((row, column, self.Stock[row, column]))

    form = make_form(Form1)
    table = form.Stock
    table.columns = ["Item", "Due : date %d %b %Y"]
    table.rows = [["Apples", "2026-10-14"], ["Pears"]]
    assert table.rows == [["Apples", datetime.date(2026, 10, 14)], ["Pears", None]]
    assert table._tree.item("0", "values")[1] == "14 Oct 2026" and table._tree.item("1", "values")[1] == ""
    table._tree.focus_force()
    table.current = (0, "Due")
    settle(form)
    key(form, "Return")  # the month drops down, at its date...
    month = DropMonth.current.month
    assert month.value == datetime.date(2026, 10, 14) and form.root.focus_get() is month.canvas
    month.canvas.event_generate("<KeyPress>", keysym="Right")
    month.canvas.event_generate("<KeyPress>", keysym="Return")  # ...Enter chooses, and moves on
    settle(form)
    assert table[0, "Due"] == datetime.date(2026, 10, 15) and changes == [(0, 1, datetime.date(2026, 10, 15))]
    assert DropMonth.current is None and table.current == (1, 1) and form.root.focus_get() is table._tree
    key(form, "Return")  # an empty date: today's month
    assert DropMonth.current.month.value is None and DropMonth.current.month.shown[1] == datetime.date.today().month
    DropMonth.current.month.canvas.event_generate("<KeyPress>", keysym="Escape")  # Esc: no change
    settle(form)
    assert table[1, "Due"] is None and DropMonth.current is None
    key(form, "2")  # typing: a text edit, read in its format (or year-month-day)
    table._editor.delete(0, "end")
    table._editor.insert(0, "3 Feb 2027")
    key(form, "Tab")
    assert table[1, "Due"] == datetime.date(2027, 2, 3)
    table.current = (1, "Due")
    key(form, "5")
    table._editor.delete(0, "end")
    table._editor.insert(0, "2027-04-05")
    key(form, "F4")  # F4 while typing: the month, at what's typed
    assert table._editor is None and DropMonth.current.month.value == datetime.date(2027, 4, 5)
    DropMonth.current.close()
    table.save_csv("dates.csv")
    assert (table.folder / "dates.csv").read_text(encoding="utf-8").splitlines()[1:] == ["Apples,2026-10-15", "Pears,2027-02-03"]


def test_time_and_datetime_columns():
    T, DT = datetime.time, datetime.datetime
    starts, logged = ColumnKind.parse("Starts : time"), ColumnKind.parse("Logged : datetime %d/%m/%Y %H:%M")
    assert (starts.line(), logged.line()) == ("Starts : time", "Logged : datetime %d/%m/%Y %H:%M")
    assert starts.convert("9:30 pm") == T(21, 30) and starts.convert("") is None and starts.blank() is None
    assert starts.show(T(9, 5)) == "9:05 AM" and starts.text(T(21, 30)) == "21:30" and starts.text(T(1, 2, 3)) == "01:02:03"
    assert logged.convert("14/10/2026 21:30") == DT(2026, 10, 14, 21, 30) == logged.convert("2026-10-14 21:30")
    assert logged.show(DT(2026, 10, 14, 9, 5)) == "14/10/2026 09:05" and logged.text(DT(2026, 10, 14, 9, 5)) == "2026-10-14 09:05"
    assert logged.convert(datetime.date(2026, 1, 2)) == DT(2026, 1, 2)  # (a date: its midnight)
    for kind, bad in ((starts, "soon"), (starts, True), (logged, "later"), (logged, 5)):
        with pytest.raises(ValueError, match="isn't a"):
            kind.convert(bad)
    assert sorted([T(9), None, T(7)], key=starts.sort_key) == [T(7), T(9), None]


@pytest.mark.usefixtures("display")
def test_time_and_datetime_cells_drop_down(make_form):
    from readymade.controls.dates import Dropped

    form = make_form()
    table = form.Stock
    table.columns = ["Item", "Starts : time", "Logged : datetime"]
    table.rows = [["Apples", "9:00 AM", "2026-10-14 21:30"]]
    assert table._tree.item("0", "values")[1:] == ("9:00 AM", "2026-10-14 9:30 PM")
    table._tree.focus_force()
    table.current = (0, "Starts")
    settle(form)
    key(form, "Return")  # a time: the times drop down
    times = Dropped.current
    assert type(times).__name__ == "DropTimes" and times.list.get(times.list.curselection()) == "9:00 AM"
    key_on = times.list
    key_on.event_generate("<KeyPress>", keysym="Down")
    key_on.event_generate("<KeyPress>", keysym="Return")
    settle(form)
    assert table[0, "Starts"] == datetime.time(9, 30) and Dropped.current is None
    table.current = (0, "Logged")
    key(form, "Return")  # a datetime: the month, for its day
    month = Dropped.current.month
    assert month.value == datetime.date(2026, 10, 14)
    month.canvas.event_generate("<KeyPress>", keysym="Right")
    month.canvas.event_generate("<KeyPress>", keysym="Return")
    settle(form)
    assert table[0, "Logged"] == datetime.datetime(2026, 10, 15, 21, 30)  # (its time kept)
    table.save_csv("times.csv")
    assert (table.folder / "times.csv").read_text(encoding="utf-8").splitlines()[1] == "Apples,09:30,2026-10-15 21:30"


@pytest.mark.usefixtures("display")
def test_typing_into_a_date_or_time_cell_however_it_was_opened(make_form):
    from readymade.controls.dates import Dropped

    form = make_form()
    table = form.Stock
    table.columns = ["Item", "Due : date", "Starts : time"]
    table.rows = [["Apples", "2026-10-14", "9:00 AM"]]
    table._tree.focus_force()
    table.current = (0, "Starts")
    settle(form)
    table._edit()  # (a double-click: the times drop down)
    settle(form)
    Dropped.current.list.event_generate("<KeyPress>", keysym="7")  # typing: the cell's text instead
    settle(form)
    assert Dropped.current is None and table._editor is not None and table._editor.get() == "7"
    table._editor.insert("end", " pm")
    key(form, "Return")
    assert table[0, "Starts"] == datetime.time(19)
    table.current = (0, "Due")
    key(form, "F2")  # F2: its text to edit, as a text cell's
    assert Dropped.current is None and table._editor.get() == "2026-10-14"
    table._editor.delete(0, "end")
    table._editor.insert(0, "Oct 20, 2026")
    key(form, "Tab")
    assert table[0, "Due"] == datetime.date(2026, 10, 20)
