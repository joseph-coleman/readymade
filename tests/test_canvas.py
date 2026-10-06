"""The Canvas control and its Shapes."""

import tkinter as tk

import pytest

from pybasic import Form, formfile
from pybasic.controls import REGISTRY

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def make_form(tmp_path):
    forms = []

    def make(cls=Form, **props):
        design = formfile.FormDesign(name="Form1", width=400, height=300)
        spec = REGISTRY["Canvas"].new_spec("Canvas1", 0, 0, 300, 200)
        spec.update(props)
        design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = cls(tmp_path / "Form1.form")
        form.show()
        form.root.update()
        forms.append(form)
        return form

    yield make
    for form in forms:
        form.root.destroy()


def test_drawing_returns_shapes(make_form):
    canvas = make_form().Canvas1
    line = canvas.line(0, 0, 50, 20, 80, 40, color="#ff0000", thickness=3, arrow="end")
    box = canvas.rectangle(10, 20, 30, 40, fill="#00ff00")
    ball = canvas.circle(100, 80, 20, fill="#e04040")
    oval = canvas.oval(0, 0, 40, 20)
    slice_ = canvas.arc(0, 0, 40, 40, 0, 90)
    triangle = canvas.polygon((10, 10), (60, 10), (35, 50), fill="#0000ff")
    label = canvas.text(5, 5, "Score: 0", font=("Arial", 12, "bold"))
    dot = canvas.point(3, 4, color="#123456")
    assert canvas.shapes() == [line, box, ball, oval, slice_, triangle, label, dot]
    assert [s.kind for s in canvas.shapes()] == ["line", "rectangle", "circle", "oval", "arc", "polygon", "text", "point"]
    assert line.points == [(0, 0), (50, 20), (80, 40)]
    assert (line.color, line.thickness) == ("#ff0000", 3)
    assert box.points == [(10, 20), (40, 60)] and (box.x, box.y) == (10, 20)
    assert (box.color, box.fill) == ("#000000", "#00ff00")
    assert (ball.x, ball.y) == (100, 80)  # a circle is where its centre is
    assert (label.x, label.y, label.text, label.color) == (5, 5, "Score: 0", "#000000")
    assert (dot.x, dot.y, dot.color) == (3, 4, "#123456")
    assert triangle.points == [(10, 10), (60, 10), (35, 50)]


def test_changing_and_moving_shapes(make_form):
    canvas = make_form().Canvas1
    ball = canvas.circle(100, 80, 20)
    ball.move(5, -10)
    assert (ball.x, ball.y) == (105, 70)
    ball.x = 50
    ball.y += 1
    assert (ball.x, ball.y) == (50, 71)
    ball.fill = "#00ff00"
    ball.color = ""
    ball.thickness = 4
    assert (ball.fill, ball.color, ball.thickness) == ("#00ff00", "", 4)
    label = canvas.text(0, 0, "a")
    label.text = 42
    assert label.text == "42"
    label.points = [(30, 40)]
    assert (label.x, label.y) == (30, 40)
    with pytest.raises(AttributeError, match="a text has no fill"):
        label.fill = "#ff0000"
    with pytest.raises(AttributeError, match="a circle has no text"):
        ball.text = "no"
    with pytest.raises(ValueError):
        ball.fill = "not a colour"


def test_order_visibility_groups_and_deleting(make_form):
    canvas = make_form().Canvas1
    back = canvas.rectangle(0, 0, 50, 50, fill="#ff0000", group="walls")
    front = canvas.rectangle(25, 25, 50, 50, fill="#00ff00")
    assert canvas.shape_at(30, 30) is front
    assert canvas.shape_at(10, 10) is back
    assert canvas.shape_at(200, 150) is None
    back.bring_to_front()
    assert canvas.shape_at(30, 30) is back and canvas.shapes() == [front, back]
    back.send_to_back()
    assert canvas.shape_at(30, 30) is front
    front.visible = False
    assert canvas.shape_at(30, 30) is back and not front.visible

    other_wall = canvas.circle(150, 100, 10, group="walls")
    assert canvas.shapes("walls") == [back, other_wall]
    front.group = "walls"
    front.group = "doors"
    assert canvas.shapes("walls") == [back, other_wall] and canvas.shapes("doors") == [front]
    canvas.clear("walls")
    assert canvas.shapes() == [front]
    assert back.deleted and not front.deleted
    front.delete()
    assert canvas.shapes() == [] and front.deleted
    front.delete()  # again: nothing happens


def test_overlaps(make_form):
    canvas = make_form().Canvas1
    a = canvas.rectangle(0, 0, 20, 20)
    b = canvas.rectangle(15, 15, 20, 20)
    c = canvas.circle(100, 100, 5)
    assert a.overlaps(b) and b.overlaps(a)
    assert not a.overlaps(c)
    c.x, c.y = 18, 18
    assert a.overlaps(c)


def test_unfilled_shapes_are_hit_on_their_outline(make_form):
    canvas = make_form().Canvas1
    ring = canvas.circle(100, 100, 40, thickness=3)
    assert canvas.shape_at(100, 100) is None
    assert canvas.shape_at(140, 100) is ring
    ring.fill = "#ffffff"
    assert canvas.shape_at(100, 100) is ring


def test_bad_arguments(make_form):
    canvas = make_form().Canvas1
    with pytest.raises(ValueError, match="arrow must be one of"):
        canvas.line(0, 0, 1, 1, arrow="middle")
    with pytest.raises(ValueError, match="at least 3 points"):
        canvas.polygon(0, 0, 10, 10)
    with pytest.raises(ValueError, match="an x and a y"):
        canvas.polygon(0, 0, 10, 10, 5)
    with pytest.raises(ValueError, match="anchor must be one of"):
        canvas.text(0, 0, "x", anchor="middle")
    with pytest.raises(ValueError):
        canvas.rectangle(0, 0, 5, 5, fill="nope")
    with pytest.raises(OSError):
        canvas.picture(0, 0, "missing.png")
    with pytest.raises(ValueError, match="isn't a colour"):
        canvas.backcolor = "nope"


def test_picture_shape(make_form, tmp_path):
    root = tk.Tk()
    photo = tk.PhotoImage(master=root, width=12, height=8)
    photo.put("#ff0000", to=(0, 0, 12, 8))
    photo.write(str(tmp_path / "ship.png"), format="png")
    root.destroy()
    canvas = make_form().Canvas1
    ship = canvas.picture(20, 30, "ship.png")
    assert (ship.kind, ship.x, ship.y) == ("picture", 20, 30)
    assert ship.bounds == (20, 30, 32, 38)
    assert canvas.shape_at(25, 35) is ship
    with pytest.raises(AttributeError, match="a picture has no color"):
        ship.color = "#000000"


def test_design_properties(make_form):
    canvas = make_form(backcolor="#000080", border=True).Canvas1
    assert canvas.backcolor == "#000080" and canvas.border
    assert int(canvas.widget["bd"]) == 1


def test_mouse_events_say_where_and_which_shape(make_form):
    seen = []

    class Form1(Form):
        def Form_load(self):
            self.ball = self.Canvas1.circle(50, 50, 10, fill="#ff0000")

        def Canvas1_click(self, x, y, shape):
            seen.append(("click", x, y, shape))

        def Canvas1_mousedown(self, x, y, shape):
            seen.append(("down", x, y, shape))

        def Canvas1_mouseup(self, x, y, shape):
            seen.append(("up", x, y, shape))

        def Canvas1_mousemove(self, x, y):
            seen.append(("move", x, y))

        def Canvas1_drag(self, x, y):
            seen.append(("drag", x, y))

    form = make_form(Form1)
    widget = form.Canvas1.widget
    widget.event_generate("<Motion>", x=10, y=12)
    widget.event_generate("<ButtonPress-1>", x=50, y=52)
    widget.event_generate("<B1-Motion>", x=60, y=62)
    widget.event_generate("<ButtonRelease-1>", x=150, y=100)
    widget.event_generate("<ButtonPress-1>", x=48, y=50)
    widget.event_generate("<ButtonRelease-1>", x=48, y=50)
    for _ in range(5):
        form.root.update()
    ball = form.ball
    assert ("move", 10, 12) in seen
    assert ("down", 50, 52, ball) in seen
    assert ("drag", 60, 62) in seen
    assert ("up", 150, 100, None) in seen
    assert [e for e in seen if e[0] == "click"] == [("click", 48, 50, ball)]  # the end of a drag isn't a click


def test_new_handler_gets_the_events_parameters():
    from pybasic import codegen

    module = codegen.new_module("Form1")
    source = codegen.add_method(module, "Form1", "Canvas1_click", ("x", "y", "shape")).apply(module)
    assert "def Canvas1_click(self, x, y, shape):" in source


def test_designing_a_canvas(tmp_path, monkeypatch):
    from tkinter import messagebox

    from pybasic.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Drawing")
    try:
        editor = app.form
        editor.add_control("Canvas", 16, 16)
        assert editor.selected == "Canvas1"
        assert editor.design.control("Canvas1")["backcolor"] == "#ffffff"
        editor.set_property("Canvas1", "backcolor", "#000080")
        assert editor.surface.controls["Canvas1"].backcolor == "#000080"
        errors = []
        monkeypatch.setattr(messagebox, "showerror", lambda title, message, **kw: errors.append(message))
        assert editor.set_property("Canvas1", "backcolor", "navy blue please") is None
        assert "isn't a colour" in errors[0]
        assert editor.design.control("Canvas1")["backcolor"] == "#000080"  # unchanged
        assert app.properties._rows["backcolor"][0].get() == "#000080"
        editor.goto_handler("Canvas1", "click")
        assert "def Canvas1_click(self, x, y, shape):" in editor.code.get_source()
    finally:
        app.stop()
        root.destroy()
