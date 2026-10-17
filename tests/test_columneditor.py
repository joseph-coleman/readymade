"""The DataTable's Columns dialog, from the Properties panel's "..." button."""

import json
import tkinter as tk

import pytest

from readymade.ide.columneditor import ColumnsEditor

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Hello")  # a new project
    yield app
    app.runner.stop()
    root.destroy()


def opened(app):
    return next(w for w in app.root.winfo_children() if isinstance(w, ColumnsEditor) and w.winfo_exists())


def choose(dialog, row):
    dialog.list.selection_set(str(row))
    dialog.update()


def shown(dialog, setting):
    return bool(dialog.rows[setting][1].winfo_manager())


def test_columns_are_chosen_not_typed(app):
    form = app.form
    form.add_control("DataTable", 8, 8, 320, 200)
    assert form.dialog_for("DataTable1", "columns") == "columns" and form.dialog_for("DataTable1", "tag") is None
    form.set_property("DataTable1", "columns", 'Item\n{"name": "Price", "kind": "money", "min": 0, "required": true}\nSize : S | M | L')
    app.properties._edit_lines("columns")  # the "..." button: the Columns dialog, not lines
    dialog = opened(app)
    assert dialog.title() == "DataTable1.columns"
    assert [dialog.list.item(i, "values")[0] for i in dialog.list.get_children()] == ["Item", "Price", "Size"]

    choose(dialog, 1)  # Price: its settings, those that fit money
    assert (dialog.vars["kind"].get(), dialog.vars["min"].get(), dialog.vars["required"].get()) == ("money", "0.00", True)
    assert shown(dialog, "decimals") and shown(dialog, "min") and not shown(dialog, "choices") and not shown(dialog, "format")
    dialog.vars["max"].set("-1")  # checked as it's typed
    assert "min can't be more than max" in dialog.problem.cget("text")
    assert dialog.list.item("1", "values")[1].endswith("(!)")
    dialog.ok()  # (a problem: not closed, nothing given)
    assert dialog.winfo_exists() and form.design.control("DataTable1")["columns"][0] == "Item"
    dialog.vars["max"].set("500")
    assert dialog.problem.cget("text") == ""

    choose(dialog, 2)  # Size: a choice, its choices a line each
    assert shown(dialog, "choices") and dialog.choices.get("1.0", "end-1c") == "S\nM\nL"
    assert tuple(dialog.default_field.cget("values")) == ("", "S", "M", "L")
    dialog.vars["default"].set("M")

    dialog.add()  # a new column, after Size
    assert dialog.chosen() == 3 and dialog.vars["name"].get() == "Column4" and dialog.vars["kind"].get() == "text"
    dialog.vars["name"].set("Due")
    dialog.vars["kind"].set("date")
    assert shown(dialog, "format") and not shown(dialog, "max_length")
    assert "%m/%d/%Y" in dialog.format_field.cget("values")
    dialog.vars["format"].set("%m/%d/%Y")
    dialog.vars["header"].set("Due date")
    dialog.move(-1)  # (before Size)
    assert [dialog.list.item(i, "values")[0] for i in dialog.list.get_children()] == ["Item", "Price", "Due", "Size"]
    choose(dialog, 0)
    dialog.vars["hidden"].set(True)
    dialog.vars["name"].set("Price")  # the same name as another: said
    assert dialog.problem.cget("text") == "Another column has the same name or header"
    dialog.vars["name"].set("Id")
    dialog.ok()
    assert not dialog.winfo_exists()
    assert form.design.control("DataTable1")["columns"] == [
        {"name": "Id", "hidden": True},
        {"name": "Price", "kind": "money", "required": True, "min": "0.00", "max": "500.00"},
        {"name": "Due", "header": "Due date", "kind": "date", "format": "%m/%d/%Y"},
        {"name": "Size", "choices": ["S", "M", "L"], "default": "M"},
    ]
    table = form.surface.controls["DataTable1"]
    assert table.headers == ["Id", "Price", "Due date", "Size"] and table.columns["Size"].default == "M"
    assert json.loads(json.dumps(form.design.control("DataTable1")["columns"]))  # (the .form file can hold them)


def test_the_dialogs_own_rules(app):
    dialog = ColumnsEditor(app, "T.columns", ["A"], lambda text: None)
    dialog.delete()  # (the last column stays: a DataTable keeps one)
    assert len(dialog.columns) == 1
    dialog.vars["hidden"].set(True)
    dialog.ok()  # (none shown: refused)
    assert dialog.winfo_exists() and "At least one column" in dialog.problem.cget("text")
    dialog.vars["hidden"].set(False)
    dialog.vars["kind"].set("number")
    dialog.vars["decimals"].set("two")
    assert "must be a whole number" in dialog.problem.cget("text")
    dialog.vars["decimals"].set("2")
    given = []
    dialog.apply = given.append
    dialog.ok()
    assert given == ["A : number 2"]  # (a line, where one says it all)
    dialog = ColumnsEditor(app, "T.columns", ["A"], given.append)
    dialog.vars["temporary"].set(True)  # (beside Hidden: never saved to a database)
    dialog.ok()
    assert given[-1] == '{"name": "A", "temporary": true}'


def test_help_and_a_size_that_stays_put(app):
    from readymade.ide import helptext

    dialog = ColumnsEditor(app, "T.columns", ["A", "B : number", "C : time"], lambda text: None)
    row = next(w for w in dialog.winfo_children() if w is not dialog.body)
    assert "Help" in [b.cget("text") for b in row.winfo_children()[0].winfo_children()] and dialog.bind("<F1>")
    topic = helptext.dialog("columns")
    assert topic.title == "Columns" and "Minutes between" in topic.text and "rowinvalid" in topic.text
    dialog.update()
    size = (dialog.winfo_width(), dialog.winfo_height())
    for kind in ("time", "datetime", "choice", "text", "money"):  # (each kind's settings shown in turn)
        dialog.vars["kind"].set(kind)
        dialog.update()
        assert (dialog.winfo_width(), dialog.winfo_height()) == size, kind
    dialog.cancel()


def test_measured_out_of_sight_then_shown_once(app, monkeypatch):
    seen = []
    fit = ColumnsEditor._fit_to_kind
    monkeypatch.setattr(ColumnsEditor, "_fit_to_kind",
                        lambda self, kind=None: (seen.append(self.winfo_viewable()), fit(self, kind))[1])
    app.root.update()
    dialog = ColumnsEditor(app, "T.columns", ["A", "B : number"], lambda text: None)
    from readymade.ide.columneditor import KINDS
    hidden = seen.count(0)  # (each kind tried while it's hidden, no jumping about on the screen; shown after)
    assert hidden > len(KINDS) and seen == [0] * hidden + [1] * (len(seen) - hidden)
    assert dialog.winfo_viewable() and dialog.grab_current() is dialog
    dialog.update()
    root = app.root
    middle = dialog.winfo_rootx() + dialog.winfo_width() // 2
    assert abs(middle - (root.winfo_rootx() + root.winfo_width() // 2)) <= 2  # (over the middle of the IDE)
    dialog.cancel()
