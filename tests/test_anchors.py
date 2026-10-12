"""Anchors: controls following their container (the form, or a Frame) as it changes size."""

import tkinter as tk

import pytest

from readymade import Form, formfile, layout
from readymade.controls import REGISTRY
from readymade.form import FORM

pytestmark = pytest.mark.usefixtures("display")


# ----- the rule -----

@pytest.mark.parametrize("anchor, expected", [
    ("top left", (10, 20, 100, 30)),  # stays put
    ("top right", (60, 20, 100, 30)),  # moves with the right edge
    ("bottom right", (60, 60, 100, 30)),
    ("top left right", (10, 20, 150, 30)),  # stretches across
    ("top bottom left right", (10, 20, 150, 70)),  # both ways
    ("top", (35, 20, 100, 30)),  # neither left nor right: stays centered across
    ("none", (35, 40, 100, 30)),
    ("left right", (10, 40, 150, 30)),
])
def test_follow(anchor, expected):
    assert layout.follow((10, 20, 100, 30), anchor, 50, 40) == expected
    assert layout.follow(expected, anchor, -50, -40) == (10, 20, 100, 30)  # and back again


def test_anchor_names():
    assert layout.normalize("Right, top") == "top right"
    assert layout.normalize("none") == "none"
    assert [layout.normalize(a) for a in layout.CHOICES] == list(layout.CHOICES)
    assert len(set(layout.CHOICES)) == 16
    for bad in ("", "middle", "top sideways"):
        with pytest.raises(ValueError, match="anchor must name edges"):
            layout.parse(bad)
    assert layout.follow((0, 0, 50, 50), "top bottom left right", -80, -80) == (0, 0, 1, 1)  # never below 1


# ----- a running form -----

@pytest.fixture
def form(tmp_path):
    seen = []

    class Form1(Form):
        def Form_resize(self):
            seen.append((self.width, self.OK.left))

    design = formfile.FormDesign(name="Form1", width=400, height=300)
    for type_name, name, rect, anchor, container in (
        ("TextBox", "Name", (16, 16, 280, 24), "top left right", None),
        ("Button", "OK", (304, 260, 80, 28), "bottom right", None),
        ("ListBox", "Items", (16, 56, 200, 120), "top bottom left right", None),
        ("Label", "Middle", (300, 100, 60, 20), "none", None),
        ("Label", "Fixed", (16, 260, 60, 20), "top left", None),
        ("Frame", "Box", (224, 56, 160, 120), "top bottom right", None),
        ("Button", "Inner", (60, 60, 80, 24), "bottom right", "Box"),
        ("Timer", "Tick", (8, 8, 32, 32), None, None),
    ):
        spec = REGISTRY[type_name].new_spec(name, *rect, container=container)
        if anchor:
            spec["anchor"] = anchor
        design.controls.append(spec)
    formfile.save(design, tmp_path / "Form1.form")
    form = Form1(tmp_path / "Form1.form")
    form.seen = seen
    form.show()
    settle(form)
    yield form
    form.root.destroy()


def settle(form):
    for _ in range(5):
        form.root.update()


def resize(form, width, height):
    form.width, form.height = width, height
    settle(form)


def rect(control):
    return control.left, control.top, control.width, control.height


def test_controls_follow_the_form(form):
    resize(form, 500, 350)  # 100 wider, 50 taller
    assert rect(form.Name) == (16, 16, 380, 24)
    assert rect(form.OK) == (404, 310, 80, 28)
    assert rect(form.Items) == (16, 56, 300, 170)
    assert rect(form.Middle) == (350, 125, 60, 20)
    assert rect(form.Fixed) == (16, 260, 60, 20)
    assert rect(form.Box) == (324, 56, 160, 170)  # moved right, stretched down
    assert rect(form.Inner) == (60, 110, 80, 24)  # in the Box, which grew 50 down: anchored to its bottom
    ok = form.OK.widget
    assert (ok.winfo_x(), ok.winfo_y(), ok.winfo_width()) == (404, 310, 80)  # where Tk put it
    assert form.seen[-1] == (500, 404)  # Form_resize ran after they moved
    resize(form, 400, 300)  # back to the designed size
    assert rect(form.OK) == (304, 260, 80, 28) and rect(form.Inner) == (60, 60, 80, 24)


def test_code_moving_an_anchored_control(form):
    resize(form, 500, 350)
    form.OK.left = 300  # where it is now; it keeps following from there
    assert form.OK.left == 300
    resize(form, 400, 300)
    assert form.OK.left == 200
    form.Name.anchor = "top left"  # changing the anchor leaves it where it is
    resize(form, 500, 350)
    assert rect(form.Name) == (16, 16, 280, 24)
    assert form.Tick.width == 32  # a Timer has no anchor
    assert not hasattr(form.Tick, "anchor")


# ----- the designer -----

@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    yield app
    app.runner.stop()
    root.destroy()


def spec_rect(editor, name):
    spec = editor.design.control(name)
    return spec["left"], spec["top"], spec["width"], spec["height"]


def test_designer_resizing_follows_anchors(app):
    editor = app.form
    editor.set_form_size(400, 300)
    editor.add_control("Button", 304, 256, 80, 32)
    editor.set_property("Button1", "anchor", "bottom right")
    assert editor.choices_for("Button1", "anchor") == layout.CHOICES
    editor.add_control("Frame", 16, 16, 200, 160)
    editor.add_control("Button", 104, 112, 80, 24, container="Frame1")
    editor.set_property("Button2", "anchor", "bottom right")
    editor.add_control("Label", 16, 200)  # top left: stays put
    editor.set_property("Frame1", "anchor", "top bottom left")

    editor.set_form_size(480, 340)
    assert spec_rect(editor, "Button1") == (384, 296, 80, 32)
    assert spec_rect(editor, "Frame1") == (16, 16, 200, 200)  # stretched down 40
    assert spec_rect(editor, "Button2") == (104, 152, 80, 24)  # and its contents followed it
    assert spec_rect(editor, "Label1")[:2] == (16, 200)
    button = editor.surface.controls["Button1"].widget
    assert (button.winfo_x(), button.winfo_y()) == (384, 296)

    editor.set_geometries({"Frame1": (16, 16, 240, 200)})  # resizing the Frame itself
    assert spec_rect(editor, "Button2") == (144, 152, 80, 24)

    editor.undo()
    editor.undo()
    assert spec_rect(editor, "Button1") == (304, 256, 80, 32) and spec_rect(editor, "Button2") == (104, 112, 80, 24)


def test_old_forms_without_anchors(app):
    editor = app.form
    editor.add_control("Button", 16, 16)
    del editor.design.control("Button1")["anchor"]
    editor.select(FORM)
    editor.set_form_size(600, 500)
    assert spec_rect(editor, "Button1")[:2] == (16, 16)


# ----- docking -----

def test_dock_takes_edges_in_order():
    rects = layout.dock(400, 300, [("top", (999, 30)), ("left", (100, 0)), ("none", (5, 5)), ("fill", (1, 1)),
                                   ("bottom", (0, 20)), ("right", (50, 0))])
    assert rects == [(0, 0, 400, 30), (0, 30, 100, 270), None, (100, 30, 250, 250), (100, 280, 300, 20),
                     (350, 30, 50, 250)]  # (fill: what the edges leave, wherever it comes)
    assert layout.dock(100, 50, [("top", (0, 80)), ("fill", (0, 0))]) == [(0, 0, 100, 50), (0, 50, 100, 0)]


@pytest.fixture
def docked(tmp_path):
    design = formfile.FormDesign(name="Form1", width=400, height=300)
    for type_name, name, props in (
        ("Label", "Status", {"dock": "bottom", "height": 24}),
        ("ListBox", "Side", {"dock": "left", "width": 100}),
        ("Frame", "Box", {"dock": "top", "height": 60}),
        ("Button", "Inner", {"container": "Box", "dock": "right", "width": 80}),
        ("TextBox", "Main", {"dock": "fill"}),
        ("Button", "Free", {"left": 150, "top": 150, "anchor": "bottom right"}),
        ("TabStrip", "Tabs", {"left": 150, "top": 100, "width": 200, "height": 120}),
        ("Label", "OnPage", {"container": "Tabs", "dock": "fill"}),
    ):
        spec = REGISTRY[type_name].new_spec(name, 0, 0)
        spec.update(props)
        design.controls.append(spec)
    formfile.save(design, tmp_path / "Form1.form")
    form = Form(tmp_path / "Form1.form")
    form.show()
    settle(form)
    yield form
    form.root.destroy()


def test_docked_controls_fill_their_edges(docked):
    form = docked
    assert rect(form.Status) == (0, 276, 400, 24)
    assert rect(form.Side) == (0, 0, 100, 276)  # (drawn before Box: the whole left side)
    assert rect(form.Box) == (100, 0, 300, 60)
    assert rect(form.Main) == (100, 60, 300, 216)
    inner = form.Box.inner
    assert rect(form.Inner) == (inner.winfo_width() - 80, 0, 80, inner.winfo_height())  # docked in the Frame
    page = form.Tabs._inner_for(0)
    assert rect(form.OnPage) == (0, 0, page.winfo_width(), page.winfo_height())  # and on a TabStrip page
    assert rect(form.Free)[:2] == (150, 150)  # (not docked: where it was put)

    resize(form, 500, 400)
    assert rect(form.Status) == (0, 376, 500, 24) and rect(form.Main) == (100, 60, 400, 316)
    assert rect(form.Free)[:2] == (250, 250)  # (its anchor, as before)
    form.Side.visible = False  # its edge goes to the others
    settle(form)
    assert rect(form.Main) == (0, 60, 500, 316)
    form.Side.visible = True
    form.Side.width = 150  # its own width, along its edge
    settle(form)
    assert rect(form.Side) == (0, 0, 150, 376) and rect(form.Main) == (150, 60, 350, 316)
    form.Status.dock = "none"
    settle(form)
    assert rect(form.Main)[3] == 340
    with pytest.raises(ValueError, match="dock must be one of"):
        form.Status.dock = "middle"


def test_docking_in_the_designer(app):
    editor = app.form
    editor.add_control("Label", 40, 40)
    editor.set_property("Label1", "dock", "top")
    app.root.update()
    label = editor.surface.controls["Label1"]
    assert (label.left, label.top, label.width) == (0, 0, editor.design.width)
    assert editor.choices_for("Label1", "dock") == ("none", "top", "bottom", "left", "right", "fill")
    before = spec_rect(editor, "Label1")
    editor.set_geometries({"Label1": (100, 100, 50, 48)})  # dragged and resized: just its height counts
    after = spec_rect(editor, "Label1")
    assert after == (before[0], before[1], before[2], 48)
    app.root.update()
    assert (label.top, label.width, label.height) == (0, editor.design.width, 48)
    editor.set_property("Form", "width", "480")  # the form wider: the docked Label too
    app.root.update()
    assert editor.surface.controls["Label1"].width == 480
    editor.undo()
    editor.undo()
    editor.undo()
    assert editor.design.control("Label1")["dock"] == "none"
