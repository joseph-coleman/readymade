"""Runtime behavior of each control type."""

import time

import pytest

from readymade import Form, formfile
from readymade.controls import REGISTRY

pytestmark = pytest.mark.usefixtures("display")


def make_form(tmp_path, *controls, cls=Form):
    """controls: (type, name, container or None, extra props)."""
    design = formfile.FormDesign(name="Form1")
    for type_name, name, container, props in controls:
        spec = REGISTRY[type_name].new_spec(name, 8, 8, container=container)
        spec.update(props)
        design.controls.append(spec)
    path = tmp_path / "Form1.form"
    formfile.save(design, path)
    form = cls(path)
    form.show()
    return form


def pump(form, seconds):
    end = time.time() + seconds
    while time.time() < end:
        form.root.update()
        time.sleep(0.005)


@pytest.fixture
def closing():
    forms = []
    yield forms.append
    for form in forms:
        form.root.destroy()


def test_checkbox(tmp_path, closing):
    clicks = []

    class Form1(Form):
        def CheckBox1_click(self):
            clicks.append(self.CheckBox1.value)

    form = make_form(tmp_path, ("CheckBox", "CheckBox1", None, {"value": True}), cls=Form1)
    closing(form)
    assert form.CheckBox1.value is True
    form.CheckBox1.widget.invoke()
    assert clicks == [False]


def test_option_buttons_are_grouped_by_container(tmp_path, closing):
    form = make_form(
        tmp_path,
        ("OptionButton", "optA", None, {"value": True}),
        ("OptionButton", "optB", None, {}),
        ("Frame", "Frame1", None, {}),
        ("OptionButton", "optC", "Frame1", {"value": True}),
        ("OptionButton", "optD", "Frame1", {}),
    )
    closing(form)
    assert [form.controls[n].value for n in ("optA", "optB", "optC", "optD")] == [True, False, True, False]
    form.optB.value = True  # selecting B deselects A, but not the frame's group
    form.optD.widget.invoke()
    assert [form.controls[n].value for n in ("optA", "optB", "optC", "optD")] == [False, True, False, True]
    assert form.optA.widget.cget("tristatevalue") != form.optA._group.get()  # not drawn "mixed"


def test_frame_holds_its_controls(tmp_path, closing):
    form = make_form(tmp_path, ("Frame", "Frame1", None, {"left": 40, "top": 40}), ("Label", "Label1", "Frame1", {}))
    closing(form)
    assert form.Label1.widget.master is form.Frame1.inner
    form.Frame1.text = "Options"
    assert form.Frame1.widget.cget("text") == "Options"


def test_listbox(tmp_path, closing):
    clicks = []

    class Form1(Form):
        def ListBox1_click(self):
            clicks.append(self.ListBox1.text)

    form = make_form(tmp_path, ("ListBox", "ListBox1", None, {"items": ["red", "green"]}), cls=Form1)
    closing(form)
    box = form.ListBox1
    box.add_item("blue")
    box.add_item("black", 0)
    assert box.items == ["black", "red", "green", "blue"]
    assert (box.list_index, box.text, box.list_count) == (-1, "", 4)
    box.list_index = 2
    assert box.text == "green"
    pump(form, 0.05)  # Tk drops events for windows that aren't on screen yet
    box.widget.event_generate("<<ListboxSelect>>")
    pump(form, 0.05)
    assert clicks == ["green"]
    box.remove_item(0)
    assert box.items == ["red", "green", "blue"]
    box.clear()
    assert box.items == []


def test_combobox(tmp_path, closing):
    changes = []

    class Form1(Form):
        def ComboBox1_change(self):
            changes.append(self.ComboBox1.text)

    form = make_form(tmp_path, ("ComboBox", "ComboBox1", None, {"items": ["S", "M", "L"], "text": ""}), cls=Form1)
    closing(form)
    combo = form.ComboBox1
    assert combo.items == ["S", "M", "L"]
    combo.list_index = 1
    assert (combo.text, combo.list_index) == ("M", 1)
    assert changes == ["M"]
    combo.editable = False
    assert str(combo.widget.cget("state")) == "readonly"
    combo.enabled = False
    assert str(combo.widget.cget("state")) == "disabled"
    combo.enabled = True
    assert str(combo.widget.cget("state")) == "readonly"


def test_timer_ticks_until_disabled(tmp_path, closing):
    ticks = []

    class Form1(Form):
        def Timer1_timer(self):
            ticks.append(1)
            if len(ticks) == 3:
                self.Timer1.enabled = False

    form = make_form(tmp_path, ("Timer", "Timer1", None, {"interval": 10}), cls=Form1)
    closing(form)
    assert not form.Timer1.widget.winfo_manager()  # never shown at runtime
    pump(form, 0.3)
    assert len(ticks) == 3


def test_timer_spec_has_no_size():
    spec = REGISTRY["Timer"].new_spec("Timer1", 8, 8, 100, 100)
    assert "width" not in spec and "height" not in spec
    formfile.loads(formfile.dumps(formfile.FormDesign(controls=[spec])))


def test_list_defaults_are_not_shared():
    a = REGISTRY["ListBox"].new_spec("List1", 0, 0)
    b = REGISTRY["ListBox"].new_spec("List2", 0, 0)
    a["items"].append("x")
    assert b["items"] == []


def test_multiline_textbox(tmp_path, closing):
    changes = []

    class Form1(Form):
        def TextBox1_change(self):
            changes.append(self.TextBox1.text)

    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "text": "one\ntwo"}), cls=Form1)
    closing(form)
    box = form.TextBox1
    assert isinstance(box.editor, __import__("tkinter").Text)
    assert box.text == "one\ntwo"
    pump(form, 0.05)
    assert changes == []  # the initial text isn't a change

    box.text = "a\nb\nc"
    pump(form, 0.05)
    assert changes == ["a\nb\nc"]  # one event per assignment

    box.editor.insert("end", "!")  # as if typed
    pump(form, 0.05)
    assert changes[-1] == "a\nb\nc!"

    box.enabled = False
    box.text = "set while disabled"
    assert box.text == "set while disabled"

    with pytest.raises(AttributeError, match="designer"):
        box.multiline = False


def test_single_line_textbox_is_still_an_entry(tmp_path, closing):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {}))
    closing(form)
    assert isinstance(form.TextBox1.widget, __import__("tkinter").Entry)
    assert form.TextBox1.multiline is False


@pytest.mark.parametrize(
    "scrollbars, orients, wrap",
    [("none", [], "word"), ("vertical", ["vertical"], "word"),
     ("horizontal", ["horizontal"], "none"), ("both", ["vertical", "horizontal"], "none")],
)
def test_scrollbars(tmp_path, closing, scrollbars, orients, wrap):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "scrollbars": scrollbars}))
    closing(form)
    box = form.TextBox1
    bars = [w for w in box.widget.winfo_children() if w.winfo_class() == "Scrollbar"]
    assert [str(b.cget("orient")) for b in bars] == orients
    assert str(box.editor.cget("wrap")) == wrap
    assert box.scrollbars == scrollbars
    with pytest.raises(AttributeError, match="designer"):
        box.scrollbars = "none" if scrollbars != "none" else "both"


def test_vertical_scrollbar_follows_the_text(tmp_path, closing):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "scrollbars": "vertical", "height": 48}))
    closing(form)
    box = form.TextBox1
    box.text = "\n".join(f"line {i}" for i in range(50))
    pump(form, 0.1)
    bar = next(w for w in box.widget.winfo_children() if w.winfo_class() == "Scrollbar")
    assert bar.get()[1] < 1.0  # the thumb shows only part of the text


def test_scrollbars_are_ignored_on_single_line_boxes(tmp_path, closing):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"scrollbars": "both"}))
    closing(form)
    assert form.TextBox1.widget is form.TextBox1.editor
    assert form.TextBox1.editor.winfo_class() == "Entry"


def test_unknown_scrollbars_value_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="none, horizontal, vertical, both"):
        make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "scrollbars": "sideways"}))
