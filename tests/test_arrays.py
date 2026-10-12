"""Control arrays: controls that share a name and their handlers, Digit[0], Digit[1]... (VB's)."""

import tkinter as tk

import pytest

from readymade import Form, codegen, formfile, names
from readymade.controls import REGISTRY, ControlArray
from readymade.form import check_name
from readymade.ide import assist, helptext


def test_element_names():
    assert names.split_element("Digit[3]") == ("Digit", 3)
    assert names.split_element("Label1") == ("Label1", None)
    assert names.split_element("Digit[03]") == ("Digit[03]", None)  # (one name for each index)
    assert names.element_name("Digit", 3) == "Digit[3]" and names.element_name("Label1", None) == "Label1"
    names.check_control_name("Digit[32767]")
    for bad in ("Digit[32768]", "for[1]", "3d[1]", "Digit[-1]"):
        with pytest.raises(ValueError):
            names.check_control_name(bad)


def test_names_in_a_form():
    check_name("Digit[2]", {"Digit[0]": 0, "Digit[1]": 0})
    with pytest.raises(ValueError, match="already a control named 'Digit'"):
        check_name("Digit[0]", {"Digit": 0})  # (a control by itself has that name)
    with pytest.raises(ValueError, match="already the name of a control array"):
        check_name("Digit", {"Digit[0]": 0})
    with pytest.raises(ValueError, match="reserved"):
        check_name("show[0]")


def test_set_index_param():
    source = ("class Form1(Form):\n    def Digit_click(self):\n        pass\n\n"
              "    async def Digit_mousedown(self, x, y):\n        pass\n\n    def Digits_click(self):\n        pass\n")
    indexed = codegen.set_index_param(source, "Digit", ["click", "mousedown"], True)
    assert "def Digit_click(self, index):" in indexed and "def Digit_mousedown(self, index, x, y):" in indexed
    assert "def Digits_click(self):" in indexed  # (another control)
    assert codegen.set_index_param(indexed, "Digit", ["click", "mousedown"], True) == indexed
    assert codegen.set_index_param(indexed, "Digit", ["click", "mousedown"], False) == source


def test_completion_declares_an_array():
    prepared = assist.prepare("class Form1(Form):\n    pass\n", "Form1",
                              [("Button", "Digit[0]"), ("Button", "Digit[1]"), ("Label", "Display")])
    lines = prepared.source.splitlines()
    assert "    Digit: _readymade_controls.ControlArray[_readymade_controls.Button]" in lines
    assert sum("Digit" in line for line in lines) == 1  # (once)


def test_help_names_the_shared_handlers():
    text = helptext.control("Button", "Digit[3]").text
    assert "Digit_click(self, index)" in text
    assert "control array" in helptext.prop("Button", "index").text


# ----- in a program -----

@pytest.fixture
def make_form(tmp_path):
    made = []

    def make(cls, *controls):
        design = formfile.FormDesign(name="Form1", width=400, height=200)
        for type_name, name, props in controls:
            spec = REGISTRY[type_name].new_spec(name, 8, 8)
            spec.update(props)
            design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = cls(tmp_path / "Form1.form")
        form.show()
        form.root.update()
        made.append(form)
        return form

    yield make
    for form in made:
        form.root.destroy()


@pytest.mark.usefixtures("display")
def test_an_array_in_a_program(make_form):
    clicks = []

    class Form1(Form):
        def Digit_click(self, index):
            clicks.append(index)
            self.Display.text += str(index)

        def Digit_mousedown(self, index, x, y):
            clicks.append(("down", index))

    form = make_form(Form1, ("Button", "Digit[0]", {"left": 8}), ("Button", "Digit[1]", {"left": 60}),
                     ("Button", "Digit[5]", {"left": 112}), ("Label", "Display", {"top": 60, "text": ""}))
    digits = form.Digit
    assert isinstance(digits, ControlArray) and digits.indexes == [0, 1, 5] and len(digits) == 3
    assert 5 in digits and 2 not in digits and digits[5].index == 5 and digits[5].name == "Digit[5]"
    assert form.Display.index is None
    assert [b.index for b in digits] == [0, 1, 5]
    for button in digits:
        button.widget.invoke()
    assert clicks == [0, 1, 5] and form.Display.text == "015"
    with pytest.raises(IndexError, match=r"Digit has no control 2 \(it has 0, 1, 5\)"):
        digits[2]

    nine = digits.add(9)  # a copy of Digit[0], hidden
    assert nine is digits[9] and nine.name == "Digit[9]" and not nine.visible and nine.left == digits[0].left
    nine.visible = True
    nine.widget.invoke()
    assert clicks[-1] == 9  # its handlers too
    with pytest.raises(ValueError, match="already has a control 9"):
        digits.add(9)
    del digits[9]
    assert digits.indexes == [0, 1, 5] and "Digit[9]" not in form.controls and not nine.widget.winfo_exists()
    with pytest.raises(ValueError, match="made in the designer"):
        digits.remove(0)


@pytest.mark.usefixtures("display")
def test_async_handlers_and_the_default_button(make_form):
    class Form1(Form):
        async def Choice_click(self, index):
            pass

    form = make_form(Form1, ("OptionButton", "Choice[0]", {}), ("OptionButton", "Choice[1]", {"top": 40}))
    form.default_button = None
    form.Choice[1].widget.invoke()  # (an async handler, told which)
    assert form.Choice[1].value and not form.Choice[0].value  # one group, as OptionButtons in one container are


# ----- in the designer -----

@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Calc")
    yield app
    app.runner.stop()
    root.destroy()


@pytest.mark.usefixtures("display")
def test_index_starts_and_ends_an_array(app):
    form = app.form
    form.add_control("Button", 8, 8)
    form.goto_handler("Button1", "click")
    assert form.set_property("Button1", "index", "0") == "Button1[0]"  # the start of a control array
    assert "def Button1_click(self, index):" in form.code.get_source()  # (told which, now)
    assert dict(form.props_for("Button1[0]"))["name"] == "Button1" and dict(form.props_for("Button1[0]"))["index"] == 0
    assert form.code_objects()[:2] == ["Form", "Button1"]
    assert form.set_property("Button1[0]", "index", "4") == "Button1[4]"
    assert form.set_property("Button1[4]", "index", "") == "Button1"  # the last one left can leave
    assert "def Button1_click(self):" in form.code.get_source()
    form.undo()
    assert form.design.control("Button1[4]") is not None


@pytest.mark.usefixtures("display")
def test_pasting_copies(app):
    """A copy of a control gets a name of its own; a copy of one of an array's joins the array."""
    form = app.form
    form.add_control("Button", 8, 8)
    form.goto_handler("Button1", "click")
    form.select("Button1")
    form.paste(form.copy_selection())  # (no question: an array is started on purpose, with index)
    assert [c["name"] for c in form.design.controls] == ["Button1", "Button2"]
    form.set_property("Button1", "index", "0")
    form.select("Button1[0]")
    form.paste(form.copy_selection())
    assert form.design.control("Button1[1]") is not None and form.selected == "Button1[1]"
    form.select_many(["Button1[0]", "Button1[1]"])
    form.paste(form.copy_selection())  # two at once: each the next
    assert [c["name"] for c in form.design.controls][-2:] == ["Button1[2]", "Button1[3]"]
    assert form.code.get_source().count("def Button1_click(self, index):") == 1

    form.add_control("Label", 8, 80)
    form.set_property("Label1", "index", "7")
    with pytest.raises(AssertionError, match="a control array of Buttons: a Label can't join it"):  # (the error box)
        form.set_property("Label1[7]", "name", "Button1")
    assert form.design.control("Label1[7]") is not None


@pytest.mark.usefixtures("display")
def test_renaming_an_array_and_its_handlers(app):
    form = app.form
    for left in (8, 60):
        form.add_control("Button", left, 8)
    form.set_property("Button1", "index", "0")
    with pytest.raises(AssertionError, match="already the name of a control array"):  # (the error box)
        form.set_property("Button2", "name", "Button1")
    form.goto_handler("Button1[0]", "click")  # double-clicking one: the array's handler
    form.code.text.insert("sel.first", "self.Button1[index].text = 'hi'")
    assert form.set_property("Button1[0]", "name", "Digit") == "Digit[0]"
    assert [c["name"] for c in form.design.controls] == ["Digit[0]", "Button2"]
    source = form.code.get_source()
    assert "def Digit_click(self, index):" in source and "self.Digit[index].text" in source
    assert helptext.control("Button", "Digit[0]").text.count("Digit_click(self, index)") == 1


@pytest.mark.usefixtures("display")
def test_an_array_from_the_designer_runs(app):
    form = app.form
    for left in (8, 60, 112):
        form.add_control("Button", left, 8)
    form.set_property("Button1", "index", "0")
    form.goto_handler("Button1[0]", "click")
    form.goto_handler("Button2", "click")
    assert form.set_property("Button2", "index", "1") == "Button2[1]"
    assert form.set_property("Button2[1]", "name", "Button1") == "Button1[1]"  # joins Button1's array
    source = form.code.get_source()
    assert source.count("def Button1_click(") == 1 and "def Button2_click(self, index):" in source  # (left as it was)
    form.set_property("Form", "default_button", "Button1[1]")
    assert app.save()
    design = formfile.load(form.path)
    assert [c["name"] for c in design.controls] == ["Button1[0]", "Button1[1]", "Button3"]

    clicked = []

    class Form1(Form):
        def Button1_click(self, index):
            clicked.append(index)

    running = Form1(form.path)
    running.show()
    try:
        assert running.default_button is running.Button1[1]
        running.Button1[1].widget.invoke()
        assert clicked == [1]
    finally:
        running.root.destroy()
