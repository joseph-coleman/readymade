"""Grids: rows and columns sized WPF-style ("auto, *, 2*, 120"), with controls in cells."""

import tkinter as tk
import types
from tkinter import messagebox

import pytest

from readymade import Form, formfile, layout
from readymade.controls import REGISTRY

pytestmark = pytest.mark.usefixtures("display")


# ----- the sizes -----

def test_track_lists():
    assert layout.normalize_tracks("Auto,*, 2* ,120px, 1.5*") == "auto, *, 2*, 120, 1.5*"
    for bad in ("", "wide", "-3", "0*", "auto, , x"):
        with pytest.raises(ValueError):
            layout.parse_tracks(bad)


def lines(columns, width, items, gap=0, padding=0):
    """Column widths for items (column, span, preferred width) in one row."""
    cells = [(0, column, 1, span, "top left", (own, 10)) for column, span, own in items]
    _, xs, _ = layout.arrange_grid(columns, "*", width, 100, cells, gap, padding)
    return list(xs.sizes)


def test_sizes():
    assert lines("*, 3*, *", 500, []) == [100, 300, 100]  # weights: 20%, 60%, 20%
    assert lines("auto, *", 400, [(0, 1, 80), (0, 1, 60)]) == [80, 320]  # auto fits its widest
    assert lines("auto, *, 2*, 100", 500, [(0, 1, 80)]) == [80, 106, 214, 100]  # stars share what's left
    assert lines("150, *", 400, []) == [150, 250]
    assert lines("*, *", 300, [], gap=10, padding=5) == [140, 140]  # 300 - 2*5 - 10, halved
    assert lines("auto, auto", 400, [(0, 2, 200), (0, 1, 50)]) == [50, 150]  # a span widens its last auto
    assert lines("*, *", 200, [(5, 3, 40)]) == [100, 100]  # past the end: no columns are added (as in WPF)
    assert lines("100, *", 50, []) == [100, 0]  # too small: fixed stays, stars get nothing


def test_cells_stay_inside_the_grid():
    assert layout.fit_cell(0, 0, 1, 3, 2, 2) == (0, 0, 1, 2)  # a span stops at the edge
    assert layout.fit_cell(5, 9, 1, 1, 2, 2) == (1, 1, 1, 1)  # past the end: the last row and column
    rects, xs, _ = layout.arrange_grid("auto, 250", "*, *", 400, 100,
                                       [(0, 0, 1, 3, "top left right", (300, 20)), (1, 0, 1, 1, "left", (60, 20))])
    assert len(xs.sizes) == 2  # still two columns, as defined (this once made a third)
    assert rects[0][2] == 60 + 250  # the label spans both (with no * column, the grid uses 310 of 400)


def test_controls_in_cells():
    cells = [
        (0, 0, 1, 1, "top bottom left right", (20, 20)),  # fills its cell
        (0, 1, 1, 1, "right", (40, 20)),  # its own size, at the right, centered up and down
        (1, 0, 1, 2, "left right", (10, 10)),  # stretches across both columns
        (1, 1, 1, 1, "none", (500, 500)),  # bigger than its cell: no bigger than the cell
    ]
    rects, xs, ys = layout.arrange_grid("100, 100", "50, 50", 210, 110, cells, gap=10)
    assert xs.starts == (0, 110) and ys.starts == (0, 60)
    assert rects == [(0, 0, 100, 50), (170, 15, 40, 20), (0, 80, 210, 10), (110, 60, 100, 50)]
    assert xs.index_at(105) == 1 and xs.index_at(5000) == 1 and ys.index_at(-5) == 0


# ----- at run time -----

def make_grid_form(tmp_path):
    design = formfile.FormDesign(name="Form1", width=400, height=300)
    grid = REGISTRY["Grid"].new_spec("Grid1", 0, 0, 400, 300)
    grid.update(columns="auto, *", rows="auto, auto, *, auto", anchor="top bottom left right", padding=8)
    design.controls.append(grid)
    for name, kind, row, column, anchor, width, height in [
        ("lblName", "Label", 0, 0, "left", 60, 24),
        ("txtName", "TextBox", 0, 1, "left right", 100, 24),
        ("lblNotes", "Label", 1, 0, "left", 80, 24),
        ("txtNotes", "TextBox", 2, 1, "top bottom left right", 100, 60),
        ("btnOK", "Button", 3, 1, "right", 80, 28),
    ]:
        spec = REGISTRY[kind].new_spec(name, 0, 0, width, height, container="Grid1")
        spec.update(row=row, column=column, anchor=anchor)
        design.controls.append(spec)
    formfile.save(design, tmp_path / "Form1.form")
    form = Form(tmp_path / "Form1.form")
    form.show()
    settle(form)
    return form


def settle(form):
    for _ in range(5):
        form.root.update()


def rect(control):
    return control.left, control.top, control.width, control.height


def test_a_grid_form_resizes(tmp_path):
    form = make_grid_form(tmp_path)
    try:
        assert rect(form.txtName) == (92, 8, 300, 24)  # the label column is as wide as "lblNotes" asks
        assert rect(form.txtNotes) == (92, 64, 300, 196)  # the * row takes the spare height
        assert rect(form.btnOK) == (312, 264, 80, 28)  # its own size, at the right
        assert (form.txtName.widget.winfo_x(), form.txtName.widget.winfo_width()) == (92, 300)
        form.width, form.height = 600, 400  # the Grid is anchored all round, so it follows the window
        settle(form)
        assert rect(form.txtName) == (92, 8, 500, 24)
        assert rect(form.txtNotes) == (92, 64, 500, 296)
        assert rect(form.btnOK) == (512, 364, 80, 28)
    finally:
        form.root.destroy()


def test_code_can_rearrange_a_grid(tmp_path):
    form = make_grid_form(tmp_path)
    try:
        form.btnOK.column = 0  # another cell
        assert form.btnOK.left == 8 + 80 - 80  # right-aligned in the auto column, which is 80 wide
        form.lblNotes.width = 120  # asks for more: the auto column widens
        assert form.txtName.left == 8 + 120 + 4
        form.txtNotes.columnspan = 2
        form.txtNotes.column = 0
        assert rect(form.txtNotes)[0] == 8 and rect(form.txtNotes)[2] == 384
        form.Grid1.columns = "*, *"
        assert form.Grid1.columns == "*, *" and form.txtName.left == 8 + 190 + 4
        form.lblName.visible = False  # hidden controls leave their cell
        form.Grid1.gap = 0
        assert form.txtName.left == 8 + 192
        with pytest.raises(ValueError, match="isn't a size"):
            form.Grid1.rows = "tall"
        with pytest.raises(ValueError, match="rowspan can't be less than 1"):
            form.btnOK.rowspan = 0
        assert form.Grid1.cell_at(300, 20) == (0, 1)
    finally:
        form.root.destroy()


# ----- the designer -----

@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    yield app
    app.runner.stop()
    root.destroy()


def test_designing_a_grid(app, monkeypatch):
    editor = app.form
    editor.add_control("Grid", 8, 8, 320, 200)
    editor.set_property("Grid1", "columns", "auto, *")
    editor.set_property("Grid1", "rows", "auto, *")
    app.root.update()
    grid = editor.surface.controls["Grid1"]
    # Drawing a control into the Grid puts it in the cell under the mouse, filling it.
    editor.add_control("TextBox", 250, 150, container="Grid1")
    spec = editor.design.control("TextBox1")
    assert (spec["row"], spec["column"], spec["anchor"]) == (1, 1, "top bottom left right")
    props = dict(editor.props_for("TextBox1"))
    assert "left" not in props and "top" not in props
    assert (props["row"], props["column"], props["rowspan"], props["columnspan"]) == (1, 1, 1, 1)
    box = editor.surface.controls["TextBox1"]
    assert (box.left, box.top) == grid.cell_box(1, 1)[:2]

    editor.set_property("TextBox1", "row", "0")
    assert editor.design.control("TextBox1")["row"] == 0 and box.top == grid.cell_box(0, 1)[1]
    editor.select("TextBox1")
    editor.nudge(dx=-1)  # the arrow keys move between cells
    assert editor.design.control("TextBox1")["column"] == 0
    editor.nudge(dwidth=1)  # Shift+arrows: span more
    assert editor.design.control("TextBox1")["columnspan"] == 2
    editor.nudge(dwidth=1)  # no further: the Grid has two columns
    assert editor.design.control("TextBox1")["columnspan"] == 2
    editor.nudge(dx=1)  # nor can it move right while it spans both
    assert editor.design.control("TextBox1")["column"] == 0
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **kw: errors.append(message))
    assert editor.set_property("TextBox1", "columnspan", "3") is None
    assert errors[-1] == "Grid1 has 2 rows and 2 columns, so columnspan can be 1 to 2 here (add more in its rows or columns)"
    editor.set_property("Grid1", "columns", "auto,250")
    assert editor.design.control("Grid1")["columns"] == "auto, 250"  # saved as the Grid tidied it
    editor.set_geometries({"TextBox1": (100, 100, 150, 30)})  # the Format tools: the size it asks for only
    spec = editor.design.control("TextBox1")
    assert (spec["width"], spec["height"]) == (150, 30) and spec["left"] != 100
    editor.undo()  # the size
    editor.undo()  # the columns
    editor.undo()  # the span
    assert editor.design.control("TextBox1").get("columnspan", 1) == 1  # (unset means 1)
    assert app.save()
    saved = formfile.load(editor.path).control("TextBox1")
    assert (saved["row"], saved["column"]) == (0, 0)


def test_dragging_in_a_grid(app):
    editor = app.form
    editor.add_control("Grid", 8, 8, 320, 200)
    editor.set_property("Grid1", "columns", "*, *, *")
    editor.add_control("Button", 10, 10, container="Grid1")
    app.root.update()
    surface, grid = editor.surface, editor.surface.controls["Grid1"]
    button = surface.controls["Button1"]
    editor.select("Button1")

    def at(row, column):
        x, y, width, height = grid.cell_box(row, column)
        return types.SimpleNamespace(x_root=grid.inner.winfo_rootx() + x + width // 2,
                                     y_root=grid.inner.winfo_rooty() + y + height // 2, state=0)

    surface._start_drag(at(0, 0), "move", button)  # drag it to the bottom-right cell
    surface._motion(at(1, 2))
    surface._release(at(1, 2))
    spec = editor.design.control("Button1")
    assert (spec["row"], spec["column"]) == (1, 2)
    surface._start_drag(at(1, 2), (1, 1), button)  # its bottom-right handle, dragged left: no smaller than 1
    surface._motion(at(1, 0))
    surface._release(at(1, 0))
    assert editor.design.control("Button1").get("columnspan", 1) == 1  # (unset means 1)
    editor.set_cells({"Button1": {"column": 0}})
    surface._start_drag(at(1, 0), (1, 1), button)  # now stretched over three columns
    surface._motion(at(1, 2))
    surface._release(at(1, 2))
    assert editor.design.control("Button1")["columnspan"] == 3
    editor.delete_control("Button1")
    assert grid.children() == []
