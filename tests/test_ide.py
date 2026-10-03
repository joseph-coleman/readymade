"""Drive the IDE through the core loop: draw, double-click to code, rename, save, run."""

import time
import tkinter as tk
from pathlib import Path

import pytest

from pybasic import formfile
from pybasic.form import FORM

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from pybasic.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Hello.form")
    yield app
    app.stop()
    root.destroy()


def test_new_document_is_named_after_the_file_and_clean(app):
    assert app.design.name == "Hello"
    assert "class Hello(Form):" in app.code.get_source()
    assert not app.is_dirty()


def test_draw_double_click_rename_save(app):
    app.add_control("Button", 16, 16)
    app.add_control("Button", 16, 56, 120, 32)
    assert [c["name"] for c in app.design.controls] == ["Button1", "Button2"]
    assert app.design.control("Button2")["width"] == 120
    assert app.selected == "Button2"

    app.goto_handler("Button1", "click")
    assert "    def Button1_click(self):\n        pass\n" in app.code.get_source()
    assert app.code.text.get("sel.first", "sel.last") == "pass"  # typing replaces it

    app.code.text.insert("sel.first", "self.Button1.text = 'Clicked'")
    app.code.text.delete("sel.first", "sel.last")
    assert app.set_property("Button1", "name", "btnHello") == "btnHello"
    source = app.code.get_source()
    assert "def btnHello_click(self):\n        self.btnHello.text = 'Clicked'" in source

    assert app.is_dirty()
    assert app.save()
    assert not app.is_dirty()
    saved = formfile.load(app.path)
    assert [c["name"] for c in saved.controls] == ["btnHello", "Button2"]
    assert app.path.with_suffix(".py").read_text() == source
    compile(source, "Hello.py", "exec")


def test_properties_panel_edits_the_design(app):
    app.add_control("Label", 8, 8)
    app.properties._rows["text"][0].set("Greeting")
    app.properties.commit("text")
    assert app.design.control("Label1")["text"] == "Greeting"
    assert app.surface.controls["Label1"].text == "Greeting"

    app.select(FORM)
    app.properties._rows["width"][0].set("480")
    app.properties.commit("width")
    assert app.design.width == 480


def test_design_time_immediate_window(app):
    app.immediate_line("? 6 * 7")
    assert "42" in app.immediate.output.get("1.0", "end")


def test_relative_path_is_stored_absolute(tmp_path, monkeypatch):
    from pybasic.ide.app import App

    monkeypatch.chdir(tmp_path)
    root = tk.Tk()
    try:
        app = App(root, Path("forms") / "Hello.form")
        assert app.path == tmp_path / "forms" / "Hello.form"
    finally:
        root.destroy()


def test_run_and_talk_to_the_program(app):
    app.add_control("Label", 8, 8)
    app.run()
    assert app.process is not None
    app.immediate_line("? Label1.text")
    app.immediate_line("form.close()")
    deadline = time.time() + 15
    while app.process is not None and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    output = app.immediate.output.get("1.0", "end")
    assert "Label1\n" in output
    assert "--- Ended (exit code 0) ---" in output


def test_frames_rename_and_delete_with_their_contents(app):
    app.add_control("Frame", 8, 8, 200, 120)
    app.add_control("OptionButton", 8, 8, container="Frame1")
    app.add_control("OptionButton", 8, 40, container="Frame1")
    assert app.surface.controls["OptionButton1"].widget.master is app.surface.controls["Frame1"].inner

    assert app.set_property("Frame1", "name", "fraSize") == "fraSize"
    assert {c["name"]: c.get("container") for c in app.design.controls} == {
        "fraSize": None, "OptionButton1": "fraSize", "OptionButton2": "fraSize"
    }
    assert app.save()
    assert formfile.load(app.path).controls[1]["container"] == "fraSize"

    app.delete_control("fraSize")
    assert app.design.controls == [] and app.surface.controls == {}


def test_list_property_and_timer(app):
    app.add_control("ListBox", 8, 8)
    assert app.set_property("ListBox1", "items", "one\ntwo\n\n") == "ListBox1"
    assert app.design.control("ListBox1")["items"] == ["one", "two"]
    assert app.surface.controls["ListBox1"].items == ["one", "two"]
    app.properties.update_values()  # as the list editor dialog does after OK
    assert app.properties._rows["items"][0].get() == "one; two"

    app.add_control("Timer", 100, 100, 64, 64)
    assert "width" not in app.design.control("Timer1")
    app.goto_handler("Timer1", "timer")
    assert "def Timer1_timer(self):" in app.code.get_source()


def test_toggling_multiline_rebuilds_the_textbox_in_place(app):
    app.add_control("TextBox", 8, 8)
    app.add_control("Label", 8, 40)
    original = app.surface.controls["TextBox1"].widget
    app.select("TextBox1")
    assert app.properties._rows["text"][1] is False  # edited inline

    assert app.set_property("TextBox1", "multiline", "True") == "TextBox1"
    textbox = app.surface.controls["TextBox1"]
    assert isinstance(textbox.editor, tk.Text) and not original.winfo_exists()
    # Still stacked below Label1, which was drawn after it.
    stacking = [str(w) for w in app.surface.canvas.winfo_children()]
    assert stacking.index(str(textbox.widget)) < stacking.index(str(app.surface.controls["Label1"].widget))
    assert app.properties._rows["text"][1] is True  # now edited in the dialog

    assert app.set_property("TextBox1", "text", "first\nsecond") == "TextBox1"
    assert textbox.text == "first\nsecond"
    app.properties.update_values()
    assert app.properties._rows["text"][0].get() == "first ⏎ second"

    app.set_property("TextBox1", "multiline", "False")
    assert app.design.control("TextBox1")["text"] == "first second"
    assert isinstance(app.surface.controls["TextBox1"].editor, tk.Entry)


def test_scrollbars_choice_in_the_designer(app):
    app.add_control("TextBox", 8, 8)
    assert app.choices_for("TextBox1", "scrollbars") == ("none", "horizontal", "vertical", "both")
    assert app.choices_for("TextBox1", "text") is None
    app.set_property("TextBox1", "multiline", "True")
    editor = app.properties.grid_frame.grid_slaves(row=_row(app, "scrollbars"), column=1)[0]
    assert editor.winfo_class() == "TCombobox" and str(editor.cget("state")) == "readonly"

    assert app.set_property("TextBox1", "scrollbars", "both") == "TextBox1"
    control = app.surface.controls["TextBox1"]
    assert len([w for w in control.widget.winfo_children() if w.winfo_class() == "Scrollbar"]) == 2
    # Clicking a scrollbar in the designer selects the TextBox.
    assert all(w in control.design_widgets() for w in control.widget.winfo_children())


def _row(app, prop):
    labels = {w.cget("text"): w for w in app.properties.grid_frame.grid_slaves(column=0)}
    return labels[prop].grid_info()["row"]
