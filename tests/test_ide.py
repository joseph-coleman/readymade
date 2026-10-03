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
    app.properties._rows["text"].set("Greeting")
    app.properties.commit("text")
    assert app.design.control("Label1")["text"] == "Greeting"
    assert app.surface.controls["Label1"].text == "Greeting"

    app.select(FORM)
    app.properties._rows["width"].set("480")
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
