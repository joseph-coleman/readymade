"""Drive the IDE: projects, documents, and the core loop of draw, double-click to code, rename, save, run."""

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
    app = App(root, tmp_path / "Hello")  # a new project
    yield app
    app.stop()
    root.destroy()


def wait_for_exit(app, seconds=15):
    deadline = time.time() + seconds
    while app.process is not None and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    return app.immediate.output.get("1.0", "end")


def test_new_project_opens_its_first_form(app):
    assert app.project.name == "hello"
    assert app.project.startup == "Form1"
    assert app.form.design.name == "Form1"
    assert app.properties.app is app.form
    assert app.explorer.tree.exists("form:Form1")
    assert not app.is_dirty()


def test_draw_double_click_rename_save(app):
    form = app.form
    form.add_control("Button", 16, 16)
    form.add_control("Button", 16, 56, 120, 32)
    assert [c["name"] for c in form.design.controls] == ["Button1", "Button2"]
    assert form.design.control("Button2")["width"] == 120
    assert form.selected == "Button2"

    form.goto_handler("Button1", "click")
    assert form.frame.select() == str(form.code)
    assert "    def Button1_click(self):\n        pass\n" in form.code.get_source()
    assert form.code.text.get("sel.first", "sel.last") == "pass"  # typing replaces it

    form.code.text.insert("sel.first", "self.Button1.text = 'Clicked'")
    form.code.text.delete("sel.first", "sel.last")
    assert form.set_property("Button1", "name", "btnHello") == "btnHello"
    source = form.code.get_source()
    assert "def btnHello_click(self):\n        self.btnHello.text = 'Clicked'" in source

    assert app.is_dirty() and form.title() == "Form1*"
    assert app.save()
    assert not app.is_dirty()
    saved = formfile.load(form.path)
    assert [c["name"] for c in saved.controls] == ["btnHello", "Button2"]
    assert form.path.with_suffix(".py").read_text() == source
    compile(source, "Form1.py", "exec")


def test_properties_panel_edits_the_design(app):
    app.form.add_control("Label", 8, 8)
    app.properties._rows["text"][0].set("Greeting")
    app.properties.commit("text")
    assert app.form.design.control("Label1")["text"] == "Greeting"
    assert app.form.surface.controls["Label1"].text == "Greeting"

    app.form.select(FORM)
    app.properties._rows["width"][0].set("480")
    app.properties.commit("width")
    assert app.form.design.width == 480


def test_design_time_immediate_window(app):
    app.immediate_line("? 6 * 7")
    assert "42" in app.immediate.output.get("1.0", "end")


def test_run_and_talk_to_the_program(app):
    app.form.add_control("Label", 8, 8)
    app.run()
    assert app.process is not None
    app.immediate_line("? Label1.text")
    app.immediate_line("form.close()")
    output = wait_for_exit(app)
    assert "Label1\n" in output
    assert "--- Ended (exit code 0) ---" in output


def test_relative_path_is_stored_absolute(tmp_path, monkeypatch):
    from pybasic.ide.app import App

    monkeypatch.chdir(tmp_path)
    root = tk.Tk()
    try:
        app = App(root, Path("projects") / "Hello")
        assert app.project.folder == tmp_path / "projects" / "Hello"
        assert app.form.path == tmp_path / "projects" / "Hello" / "Form1.form"
    finally:
        root.destroy()


def test_forms_and_modules_get_their_own_tabs(app):
    first = app.form
    app.project.add_form("Settings")
    app.project.add_module("helpers")
    app.explorer_refresh()
    assert app.explorer.tree.exists("form:Settings") and app.explorer.tree.exists("module:helpers")

    settings = app.open_form("Settings")
    assert app.form is settings and app.properties.app is settings
    settings.add_control("CheckBox", 8, 8)
    assert first.design.controls == []  # the Toolbox and Properties work on the showing form

    module = app.open_module("helpers")
    assert app.form is None and app.properties.app is None
    module.code.text.insert("end", "\nANSWER = 42\n")
    assert module.title() == "helpers.py*"

    assert app.open_form("Form1") is first and app.properties.app is first
    assert app.save()
    assert "ANSWER = 42" in (app.project.folder / "helpers.py").read_text()
    assert formfile.load(app.project.folder / "Settings.form").controls[0]["name"] == "CheckBox1"

    assert app.close_document(settings)
    assert settings not in app.editors and len(app.documents.tabs()) == 2


def test_renaming_a_form_renames_its_files_and_the_startup(app):
    form = app.form
    assert form.set_property(FORM, "name", "MainForm") == FORM
    assert "class MainForm(Form):" in form.code.get_source()
    assert app.save()
    folder = app.project.folder
    assert sorted(p.name for p in folder.glob("*.*")) == ["MainForm.form", "MainForm.py", "pyproject.toml"]
    assert app.project.startup == "MainForm"
    assert form.name == "MainForm" and app.explorer.tree.exists("form:MainForm")


def test_run_uses_the_startup_form(app):
    app.project.add_form("Settings")
    app.set_startup("Settings")
    assert app.explorer.tree.item("form:Settings", "text") == "Settings  (startup)"
    app.run()
    app.immediate_line("? type(form).__name__")
    app.immediate_line("form.close()")
    output = wait_for_exit(app)
    assert "Settings\n" in output and "--- Ended (exit code 0) ---" in output


def test_frames_rename_and_delete_with_their_contents(app):
    form = app.form
    form.add_control("Frame", 8, 8, 200, 120)
    form.add_control("OptionButton", 8, 8, container="Frame1")
    form.add_control("OptionButton", 8, 40, container="Frame1")
    assert form.surface.controls["OptionButton1"].widget.master is form.surface.controls["Frame1"].inner

    assert form.set_property("Frame1", "name", "fraSize") == "fraSize"
    assert {c["name"]: c.get("container") for c in form.design.controls} == {
        "fraSize": None, "OptionButton1": "fraSize", "OptionButton2": "fraSize"
    }
    assert app.save()
    assert formfile.load(form.path).controls[1]["container"] == "fraSize"

    form.delete_control("fraSize")
    assert form.design.controls == [] and form.surface.controls == {}


def test_list_property_and_timer(app):
    form = app.form
    form.add_control("ListBox", 8, 8)
    assert form.set_property("ListBox1", "items", "one\ntwo\n\n") == "ListBox1"
    assert form.design.control("ListBox1")["items"] == ["one", "two"]
    assert form.surface.controls["ListBox1"].items == ["one", "two"]
    app.properties.update_values()  # as the list editor dialog does after OK
    assert app.properties._rows["items"][0].get() == "one; two"

    form.add_control("Timer", 100, 100, 64, 64)
    assert "width" not in form.design.control("Timer1")
    form.goto_handler("Timer1", "timer")
    assert "def Timer1_timer(self):" in form.code.get_source()


def test_toggling_multiline_rebuilds_the_textbox_in_place(app):
    form = app.form
    form.add_control("TextBox", 8, 8)
    form.add_control("Label", 8, 40)
    original = form.surface.controls["TextBox1"].widget
    form.select("TextBox1")
    assert app.properties._rows["text"][1] is False  # edited inline

    assert form.set_property("TextBox1", "multiline", "True") == "TextBox1"
    textbox = form.surface.controls["TextBox1"]
    assert isinstance(textbox.editor, tk.Text) and not original.winfo_exists()
    # Still stacked below Label1, which was drawn after it.
    stacking = [str(w) for w in form.surface.canvas.winfo_children()]
    assert stacking.index(str(textbox.widget)) < stacking.index(str(form.surface.controls["Label1"].widget))
    assert app.properties._rows["text"][1] is True  # now edited in the dialog

    assert form.set_property("TextBox1", "text", "first\nsecond") == "TextBox1"
    assert textbox.text == "first\nsecond"
    app.properties.update_values()
    assert app.properties._rows["text"][0].get() == "first ⏎ second"

    form.set_property("TextBox1", "multiline", "False")
    assert form.design.control("TextBox1")["text"] == "first second"
    assert isinstance(form.surface.controls["TextBox1"].editor, tk.Entry)


def test_scrollbars_choice_in_the_designer(app):
    form = app.form
    form.add_control("TextBox", 8, 8)
    assert form.choices_for("TextBox1", "scrollbars") == ("none", "horizontal", "vertical", "both")
    assert form.choices_for("TextBox1", "text") is None
    form.set_property("TextBox1", "multiline", "True")
    editor = app.properties.grid_frame.grid_slaves(row=_row(app, "scrollbars"), column=1)[0]
    assert editor.winfo_class() == "TCombobox" and str(editor.cget("state")) == "readonly"

    assert form.set_property("TextBox1", "scrollbars", "both") == "TextBox1"
    control = form.surface.controls["TextBox1"]
    assert len([w for w in control.widget.winfo_children() if w.winfo_class() == "Scrollbar"]) == 2
    # Clicking a scrollbar in the designer selects the TextBox.
    assert all(w in control.design_widgets() for w in control.widget.winfo_children())


def _row(app, prop):
    labels = {w.cget("text"): w for w in app.properties.grid_frame.grid_slaves(column=0)}
    return labels[prop].grid_info()["row"]
