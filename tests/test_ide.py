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


def test_project_runs_with_its_own_venv(app):
    import subprocess
    import sys

    assert app.explorer.tree.item("python", "text").endswith("(IDE)")
    # A real venv; its python can use the base installation's tkinter.
    subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(app.project.folder / ".venv")], check=True)
    app.set_python(None)  # refreshes the Explorer, as choosing would
    label = app.explorer.tree.item("python", "text")
    assert label == "Python %d.%d.%d  (.venv)" % sys.version_info[:3]

    app.run()
    app.immediate_line("? __import__('sys').prefix")
    app.immediate_line("form.close()")
    output = wait_for_exit(app)
    assert "Python: .venv" in output
    assert str(app.project.folder / ".venv") in output
    assert "--- Ended (exit code 0) ---" in output


def test_missing_interpreter_is_reported_not_run(app):
    app.set_python(app.project.folder / "nowhere" / "python")
    assert "can't run it" in app.explorer.tree.item("python", "text")
    app.run()
    assert app.process is None
    assert "doesn't exist" in app.immediate.output.get("1.0", "end")


def make_wheel(folder, name="tinypkg", version="1.0"):
    """A minimal wheel, so pip can install something without the internet."""
    import zipfile

    info = f"{name}-{version}.dist-info"
    files = {
        f"{name}/__init__.py": "VALUE = 42\n",
        f"{info}/METADATA": f"Metadata-Version: 2.1\nName: {name}\nVersion: {version}\n",
        f"{info}/WHEEL": "Wheel-Version: 1.0\nGenerator: test\nRoot-Is-Purelib: true\nTag: py3-none-any\n",
    }
    files[f"{info}/RECORD"] = "".join(f"{n},,\n" for n in [*files, f"{info}/RECORD"])
    folder.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(folder / f"{name}-{version}-py3-none-any.whl", "w") as wheel:
        for n, content in files.items():
            wheel.writestr(n, content)


def wait_until_idle(app, seconds=120):
    deadline = time.time() + seconds
    while app.process is not None and time.time() < deadline:
        app.root.update()
        time.sleep(0.05)
    assert app.process is None, "still busy"
    return app.immediate.output.get("1.0", "end")


def test_create_environment_then_add_a_library(app, tmp_path, monkeypatch):
    import sys

    make_wheel(tmp_path / "wheels")
    monkeypatch.setenv("PIP_NO_INDEX", "1")  # pip reads its options from the environment too
    monkeypatch.setenv("PIP_FIND_LINKS", str(tmp_path / "wheels"))

    app.create_environment(Path(sys.executable))
    output = wait_until_idle(app)
    assert "The environment is ready." in output, output
    assert app.project.python() == app.project.venv_python()
    assert app.explorer.tree.item("python", "text").endswith("(.venv)")

    app.add_library("tinypkg")
    output = wait_until_idle(app)
    assert "Added tinypkg to the project." in output, output
    assert app.project.dependencies == ["tinypkg"]
    libraries = [app.explorer.tree.item(i, "text") for i in app.explorer.tree.get_children("libraries")]
    assert libraries == ["tinypkg"]

    app.run()  # the program can import it
    app.immediate_line("? __import__('tinypkg').VALUE")
    app.immediate_line("form.close()")
    assert "42\n" in wait_for_exit(app)

    # A copy of the project on another machine: creating its environment installs the libraries.
    import shutil

    shutil.rmtree(app.project.folder / ".venv")
    app.create_environment(Path(sys.executable))
    output = wait_until_idle(app)
    assert output.count("--- Installing tinypkg ---") == 2 and output.rstrip().endswith("The environment is ready. ---")


def test_failed_pip_install_changes_nothing(app, tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("PIP_NO_INDEX", "1")
    app.create_environment(Path(sys.executable))
    wait_until_idle(app)
    app.add_library("no-such-package-anywhere")
    assert "nothing was added" in wait_until_idle(app)
    assert app.project.dependencies == []


def test_uv_is_the_fallback_when_venv_fails(app, tmp_path, monkeypatch):
    broken = tmp_path / "broken-python"
    broken.write_text("#!/bin/sh\necho 'No module named venv'\nexit 1\n")
    broken.chmod(0o755)
    fake_uv = tmp_path / "uv"
    fake_uv.write_text(f"#!/bin/sh\necho \"$@\" > {tmp_path / 'uv-args'}\n")
    fake_uv.chmod(0o755)
    monkeypatch.setattr("shutil.which", lambda name: str(fake_uv) if name == "uv" else None)

    app.create_environment(broken)
    output = wait_until_idle(app)
    assert "trying uv instead" in output
    assert (tmp_path / "uv-args").read_text().split() == ["venv", "--seed", "--python", str(broken), str(app.project.folder / ".venv")]


def test_add_library_offers_to_create_an_environment_first(app, monkeypatch):
    from tkinter import messagebox

    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a) or False)
    app.add_library("tinypkg")
    assert asked and app.process is None  # declined, so nothing went into the IDE's Python


def write_code(app, name, code):
    path = app.project.folder / f"{name}.py"
    path.write_text(code)
    for editor in app.editors:  # reload it if it's open
        if editor.path.with_suffix(".py") == path:
            editor.code.set_source(code)
            editor._saved = (formfile.dumps(editor.design), code) if hasattr(editor, "design") else code


def test_run_time_error_is_shown_at_its_line(app):
    app.form.add_control("Button", 8, 8)
    app.save()
    write_code(app, "Form1", "from pybasic import Form\n\n\nclass Form1(Form):\n"
               "    def Button1_click(self):\n        total = 0\n        self.text = str(1 / total)\n")
    app.open_form("Form1", "design")
    app.run()
    app.immediate_line("_ = Button1.widget.invoke()")
    deadline = time.time() + 15
    while "ZeroDivisionError" not in app.form.code.error_bar.cget("text") and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    code = app.form.code
    assert app.form.frame.select() == str(code)  # switched to the code
    assert code.error_bar.cget("text") == "Line 7: ZeroDivisionError: division by zero"
    assert code.text.tag_ranges("error") and str(code.text.tag_ranges("error")[0]) == "7.0"
    assert "--- ZeroDivisionError: division by zero  (Form1.py, line 7) ---" in app.immediate.output.get("1.0", "end")
    app.immediate_line("form.close()")  # the program kept running after the error
    assert "--- Ended (exit code 0) ---" in wait_for_exit(app)

    code.text.insert("7.0", "# ")  # editing clears the highlight
    app.root.update()
    assert not code.text.tag_ranges("error") and not code.error_bar.winfo_ismapped()


def test_startup_errors_in_modules_open_the_module(app):
    app.project.add_module("helpers")
    write_code(app, "helpers", "def greeting():\n    return GREETING\n")
    write_code(app, "Form1", "from pybasic import Form\nimport helpers\n\n\nclass Form1(Form):\n"
               "    def Form_load(self):\n        self.text = helpers.greeting()\n")
    app.run()
    wait_for_exit(app)
    module = next(e for e in app.editors if e.name == "helpers")
    assert app.documents.select() == str(module.frame)
    assert module.code.error_bar.cget("text") == "Line 2: NameError: name 'GREETING' is not defined"


def test_menu_editor_builds_a_menu(app):
    form = app.form
    editor = app.menu_editor()
    editor.add()
    editor.text_var.set("&File")
    assert editor.name_var.get() == "mnuFile"  # named from the text
    editor.add_inside()
    editor.text_var.set("&Open...")
    editor.modifier_vars["Ctrl"].set(True)
    editor.key_var.set("o")
    editor.add_separator()
    editor.add()
    editor.text_var.set("E&xit")
    editor.name_var.set("mnuQuit")  # typed by hand, so it stops following the text
    editor.text_var.set("E&xit Program")
    assert editor.name_var.get() == "mnuQuit"
    editor.tree.selection_set(str(id(editor.items[0])))
    editor.add()
    editor.text_var.set("&Help")
    editor.checked_var.set(True)
    assert editor.ok()

    assert form.design.menu == [
        {"name": "mnuFile", "text": "&File", "items": [
            {"name": "mnuOpen", "text": "&Open...", "shortcut": "Ctrl+O"},
            {"text": "-"},
            {"name": "mnuQuit", "text": "E&xit Program"},
        ]},
        {"name": "mnuHelp", "text": "&Help", "checked": True},
    ]
    assert form.code_objects()[-3:] == ["mnuOpen", "mnuQuit", "mnuHelp"]  # submenus have no click
    menubar = [w.cget("text") for w in form.surface.menubar.winfo_children()]
    assert menubar == ["File", "Help"]
    assert app.save() and formfile.load(form.path).menu == form.design.menu


def test_menu_items_open_their_handlers_and_renames_follow(app):
    form = app.form
    form.set_menu([{"name": "mnuFile", "text": "&File", "items": [{"name": "mnuOpen", "text": "&Open"}]}])
    # Clicking the item in the designer's menu bar opens its handler, as in VB.
    dropdown = form.surface.menubar.winfo_children()[0].nametowidget(form.surface.menubar.winfo_children()[0]["menu"])
    dropdown.invoke(0)
    assert form.frame.select() == str(form.code)
    form.code.text.insert("sel.first", "self.text = 'opened'")
    form.code.text.delete("sel.first", "sel.last")

    editor = app.menu_editor()
    editor.tree.selection_set(str(id(editor.items[0]["items"][0])))
    editor.name_var.set("mnuOpenFile")
    assert editor.ok()
    assert "def mnuOpenFile_click(self):\n        self.text = 'opened'" in form.code.get_source()


@pytest.mark.parametrize("change, message", [
    (lambda e: e.name_var.set("Form"), "reserved"),
    (lambda e: e.key_var.set("Banana"), "isn't a shortcut"),
    (lambda e: e.key_var.set("S"), "needs Ctrl or Alt"),
    (lambda e: e.name_var.set("Button1"), "already a control"),
])
def test_menu_editor_checks_before_ok(app, change, message):
    app.form.add_control("Button", 8, 8)
    editor = app.menu_editor()
    editor.add()
    change(editor)
    with pytest.raises(AssertionError, match=message):  # the error message box, as a test failure
        editor.ok()
    editor.destroy()


def test_shortcut_picker_shows_problems_as_you_go(app):
    editor = app.menu_editor()
    editor.add()
    editor.key_var.set("1")
    assert "needs Ctrl or Alt" in editor.shortcut_error.cget("text")
    editor.modifier_vars["Ctrl"].set(True)
    assert editor.shortcut_error.cget("text") == "" and editor.items[0]["shortcut"] == "Ctrl+1"
    editor.modifier_vars["Shift"].set(True)
    assert "Shift changes which key" in editor.shortcut_error.cget("text")
    editor.key_var.set("f5")
    assert editor.items[0]["shortcut"] == "Ctrl+Shift+F5"  # tidied as it's stored
    assert editor.key_var.get() == "F5"
    assert editor.tree.item(str(id(editor.items[0])), "values")[0] == "Ctrl+Shift+F5"
    editor.key_var.set("")
    assert "shortcut" not in editor.items[0]
    editor.destroy()


def test_undo_and_redo_designer_changes(app):
    form = app.form
    form.add_control("Button", 8, 8)
    form.set_property("Button1", "text", "Go")
    form.geometry_changed("Button1", (40, 48, 96, 28))  # as a drag does when it ends
    assert app.is_dirty()

    form.undo()
    assert form.design.control("Button1")["left"] == 8
    form.undo()
    assert form.design.control("Button1")["text"] == "Button1"
    assert form.surface.controls["Button1"].text == "Button1"  # the designer shows it too
    form.undo()
    assert form.design.controls == [] and form.surface.controls == {}
    assert not app.is_dirty() and not form.can_undo()  # back to how it was saved

    form.redo()
    form.redo()
    assert form.surface.controls["Button1"].text == "Go"
    form.add_control("Label", 8, 48)  # a new change clears what could be redone
    assert not form.can_redo()


def test_undo_brings_back_a_deleted_frame_with_its_contents(app):
    form = app.form
    form.add_control("Frame", 8, 8, 200, 120)
    form.add_control("OptionButton", 8, 8, container="Frame1")
    form.delete_control("Frame1")
    form.undo()
    assert [c["name"] for c in form.design.controls] == ["Frame1", "OptionButton1"]
    assert form.surface.controls["OptionButton1"].widget.master is form.surface.controls["Frame1"].inner


def test_undoing_a_rename_restores_the_code_unless_it_was_edited_since(app):
    form = app.form
    form.add_control("Button", 8, 8)
    form.goto_handler("Button1", "click")
    form.set_property("Button1", "name", "btnGo")
    assert "def btnGo_click" in form.code.get_source()
    form.undo()
    assert form.design.control("Button1") and "def Button1_click" in form.code.get_source()

    form.redo()
    assert form.design.control("btnGo") and "def btnGo_click" in form.code.get_source()
    form.code.text.insert("end", "\n# my own edit\n")
    form.undo()  # the design goes back; the edited code is left alone
    assert form.design.control("Button1") and "# my own edit" in form.code.get_source()


def test_arrow_keys_nudge_and_resize(app):
    form = app.form
    form.add_control("Button", 16, 16)
    for _ in range(3):
        form.nudge(dx=8)
    form.nudge(dy=1)
    form.nudge(dwidth=8)
    spec = form.design.control("Button1")
    assert (spec["left"], spec["top"], spec["width"]) == (40, 17, 104)
    assert form.surface.controls["Button1"].left == 40
    assert app.properties._rows["left"][0].get() == "40"
    form.undo()  # the resize
    form.undo()  # all the moves, as one step
    assert (spec := form.design.control("Button1"))["left"] == 16 and spec["top"] == 16

    form.nudge(dwidth=-500)
    assert form.design.control("Button1")["width"] == 8  # never smaller than a grid step
    form.add_control("Timer", 100, 100)
    form.nudge(dwidth=8)  # a Timer has no size
    assert "width" not in form.design.control("Timer1")


def test_ctrl_z_belongs_to_the_code_editor_while_typing_code(app):
    form = app.form
    form.add_control("Button", 8, 8)
    form.show_code()
    form.code.text.focus_force()
    app.root.update()
    assert app._undo_key(redo=False) is None  # the Text widget's own undo runs
    assert form.design.controls

    form.show_design()
    form.surface.canvas.focus_force()
    app.root.update()
    assert app._undo_key(redo=False) == "break"
    assert form.design.controls == []
