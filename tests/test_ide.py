"""Drive the IDE: projects, documents, and the core loop of draw, double-click to code, rename, save, run."""

import sys
import time
import tkinter as tk
import types
from pathlib import Path
from tkinter import messagebox

import pytest

from readymade import formfile
from readymade.form import FORM
from readymade.ide.editors import MULTIPLE

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Hello")  # a new project
    yield app
    app.runner.stop()
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
    app.runner.immediate_line("? 6 * 7")
    assert "42" in app.immediate.output.get("1.0", "end")


def test_run_and_talk_to_the_program(app):
    app.form.add_control("Label", 8, 8)
    app.runner.run()
    assert app.process is not None
    app.runner.immediate_line("? Label1.text")
    app.runner.immediate_line("form.close()")
    output = wait_for_exit(app)
    assert "Label1\n" in output
    assert "--- Ended (exit code 0) ---" in output


def test_relative_path_is_stored_absolute(tmp_path, monkeypatch):
    from readymade.ide.app import App

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
    app.runner.run()
    app.runner.immediate_line("? type(form).__name__")
    app.runner.immediate_line("form.close()")
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
    app.envs.set_python(None)  # refreshes the Explorer, as choosing would
    label = app.explorer.tree.item("python", "text")
    assert label == "Python %d.%d.%d  (.venv)" % sys.version_info[:3]

    app.runner.run()
    app.runner.immediate_line("? __import__('sys').prefix")
    app.runner.immediate_line("form.close()")
    output = wait_for_exit(app)
    assert "Python: .venv" in output
    assert str(app.project.folder / ".venv") in output
    assert "--- Ended (exit code 0) ---" in output


def test_missing_interpreter_is_reported_not_run(app):
    app.envs.set_python(app.project.folder / "nowhere" / "python")
    assert "can't run it" in app.explorer.tree.item("python", "text")
    app.runner.run()
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

    app.envs.create_environment(Path(sys.executable))
    output = wait_until_idle(app)
    assert "The environment is ready." in output, output
    assert app.project.python() == app.project.venv_python()
    assert app.explorer.tree.item("python", "text").endswith("(.venv)")

    app.envs.add_library("tinypkg")
    output = wait_until_idle(app)
    assert "Added tinypkg to the project." in output, output
    assert app.project.dependencies == ["tinypkg"]
    libraries = [app.explorer.tree.item(i, "text") for i in app.explorer.tree.get_children("libraries")]
    assert libraries == ["tinypkg"]

    app.runner.run()  # the program can import it
    app.runner.immediate_line("? __import__('tinypkg').VALUE")
    app.runner.immediate_line("form.close()")
    assert "42\n" in wait_for_exit(app)

    # A copy of the project on another machine: creating its environment installs the libraries.
    import shutil

    shutil.rmtree(app.project.folder / ".venv")
    app.envs.create_environment(Path(sys.executable))
    output = wait_until_idle(app)
    assert output.count("--- Installing tinypkg ---") == 2 and output.rstrip().endswith("The environment is ready. ---")

    # Removing it takes it out of the list and uninstalls it from the project's environment.
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **kw: True)
    assert app.files.remove_from_project("library", "tinypkg")
    output = wait_until_idle(app)
    assert "Removed tinypkg from the project." in output, output
    assert app.project.dependencies == []
    assert app.explorer.tree.get_children("libraries") == ()
    import subprocess

    still_there = subprocess.run([str(app.project.python()), "-c", "import tinypkg"], capture_output=True, check=False)
    assert still_there.returncode != 0


def test_failed_pip_install_changes_nothing(app, tmp_path, monkeypatch):
    import sys

    monkeypatch.setenv("PIP_NO_INDEX", "1")
    app.envs.create_environment(Path(sys.executable))
    wait_until_idle(app)
    app.envs.add_library("no-such-package-anywhere")
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

    app.envs.create_environment(broken)
    output = wait_until_idle(app)
    assert "trying uv instead" in output
    assert (tmp_path / "uv-args").read_text().split() == ["venv", "--seed", "--python", str(broken), str(app.project.folder / ".venv")]


def test_add_library_offers_to_create_an_environment_first(app, monkeypatch):
    from tkinter import messagebox

    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a) or False)
    app.envs.add_library("tinypkg")
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
    write_code(app, "Form1", "from readymade import Form\n\n\nclass Form1(Form):\n"
               "    def Button1_click(self):\n        total = 0\n        self.text = str(1 / total)\n")
    app.open_form("Form1", "design")
    app.runner.run()
    app.runner.immediate_line("_ = Button1.widget.invoke()")
    deadline = time.time() + 15
    while "ZeroDivisionError" not in app.form.code.error_bar.cget("text") and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    code = app.form.code
    assert app.form.frame.select() == str(code)  # switched to the code
    assert code.error_bar.cget("text") == "Line 7: ZeroDivisionError: division by zero"
    assert code.text.tag_ranges("error") and str(code.text.tag_ranges("error")[0]) == "7.0"
    assert "--- ZeroDivisionError: division by zero  (Form1.py, line 7) ---" in app.immediate.output.get("1.0", "end")
    assert wait_for(app, lambda: app.in_break_mode)  # paused at the error (see test_debugging.py)
    app.runner.run()  # continue: the program goes on without the rest of the event
    assert wait_for(app, lambda: not app.in_break_mode)
    app.runner.immediate_line("form.close()")
    assert "--- Ended (exit code 0) ---" in wait_for_exit(app)

    code.text.insert("7.0", "# ")  # editing clears the highlight
    app.root.update()
    assert not code.text.tag_ranges("error") and not code.error_bar.winfo_ismapped()


def test_startup_errors_in_modules_open_the_module(app):
    app.project.add_module("helpers")
    write_code(app, "helpers", "def greeting():\n    return GREETING\n")
    write_code(app, "Form1", "from readymade import Form\nimport helpers\n\n\nclass Form1(Form):\n"
               "    def Form_load(self):\n        self.text = helpers.greeting()\n")
    app.runner.run()
    assert wait_for(app, lambda: app.in_break_mode)  # paused at the error in Form_load (see test_debugging.py)
    module = next(e for e in app.editors if e.name == "helpers")
    assert app.documents.select() == str(module.frame)
    assert module.code.error_bar.cget("text") == "Line 2: NameError: name 'GREETING' is not defined"
    app.runner.run()  # continue: the rest of Form_load is skipped
    assert wait_for(app, lambda: not app.in_break_mode)
    app.runner.immediate_line("form.close()")
    assert "--- Ended (exit code 0) ---" in wait_for_exit(app)


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
    app.root.update_idletasks()  # menu commands run once the menu has closed
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


def test_dialogs_are_built_alike(app, monkeypatch):
    from readymade.ide import environments
    from readymade.ide.dialog import Dialog

    def opened():
        return next(w for w in app.root.winfo_children() if isinstance(w, Dialog) and w.winfo_exists())

    def buttons(dialog):  # the row at the bottom, under the body
        row = next(w for w in dialog.winfo_children() if w is not dialog.body)
        return sorted(b.cget("text") for b in row.winfo_children()[0].winfo_children())

    editor = app.menu_editor()
    assert buttons(editor) == ["Cancel", "OK"]
    assert editor.bind("<Escape>") and not editor.bind("<Return>")  # Enter types in its fields
    editor.cancel()

    app.form.add_control("ListBox", 8, 8)
    app.properties._edit_lines("items")
    lines = opened()
    assert lines.title() == "ListBox1.items" and buttons(lines) == ["Cancel", "OK"]
    next(w for w in lines.body.winfo_children() if isinstance(w, tk.Text)).insert("1.0", "Apples\nPears")
    lines.ok()
    assert app.form.design.control("ListBox1")["items"] == ["Apples", "Pears"]
    assert not lines.winfo_exists()

    based_on = []
    monkeypatch.setattr(environments, "find_pythons", lambda: [Path(sys.executable)])
    monkeypatch.setattr(environments, "describe_python", lambda python: "3.x")
    monkeypatch.setattr(app.envs, "create_environment", lambda base, then=None: based_on.append(base))
    app.envs.ask_create_environment()
    create = opened()
    assert buttons(create) == ["Cancel", "Create"] and create.bind("<Return>")
    create.ok()
    assert based_on == [Path(sys.executable)] and not create.winfo_exists()


@pytest.mark.parametrize("theme", ["Light", "Dark"])
def test_asking_for_a_name(app, theme):
    from tkinter import ttk

    from readymade import usersettings
    from readymade.ide import options
    from readymade.ide.dialog import AskString, ask_string

    usersettings.set("theme", theme.lower())
    options.apply(app)
    seen = {}

    def answer(typed):
        asker = next(w for w in app.root.winfo_children() if isinstance(w, AskString) and w.winfo_exists())
        try:
            entry = asker.entry
            seen["selected"] = entry.get()[entry.index("sel.first"):entry.index("sel.last")]
            seen["colors"] = {str(asker.cget("background")), str(ttk.Style(asker).lookup("TFrame", "background"))}
            if typed is not None:
                entry.delete(0, tk.END)
                entry.insert(0, typed)
                asker.ok()
        finally:
            asker.cancel()  # (if it's still open: a failure here mustn't leave the test waiting)

    app.root.after(100, answer, "Shop")
    assert ask_string(app, "Add Module", "Module name:", "Module1") == "Shop"
    assert seen["selected"] == "Module1"  # typing replaces the suggestion
    assert len(seen["colors"]) == 1  # the window and what's in it look alike
    app.root.after(100, answer, None)
    assert ask_string(app, "Add Module", "Module name:") is None


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
    assert app.undo_key(redo=False) is None  # the Text widget's own undo runs
    assert form.design.controls

    form.show_design()
    form.surface.canvas.focus_force()
    app.root.update()
    assert app.undo_key(redo=False) == "break"
    assert form.design.controls == []


def test_selecting_several_controls(app):
    form = app.form
    for top in (8, 48, 88):
        form.add_control("Button", 16, top)
    form.add_control("Frame", 160, 8, 120, 100)
    form.add_control("Label", 8, 8, container="Frame1")

    form.toggle_selected("Button1")  # Ctrl+click
    form.toggle_selected("Button2")
    assert form.selection == ["Button1", "Button2"] and form.selected == "Button2"
    assert app.properties.current == MULTIPLE
    form.toggle_selected("Label1")  # in another container: starts a new selection
    assert form.selection == ["Label1"]
    form.select_many(["Button1", "Button3", "Label1"])  # e.g. a selection box; one container only
    assert form.selection == ["Label1"]
    form.select_many(["Button1", "Button3"])
    form.toggle_selected("Button1")
    assert form.selection == ["Button3"]

    # A selection box on the form selects the controls it touches.
    form.select(FORM)
    app.root.update()
    canvas = form.surface.canvas
    x, y = canvas.winfo_rootx(), canvas.winfo_rooty()
    form.surface._lasso_release(types.SimpleNamespace(x_root=x + 100, y_root=y + 60, state=0),
                                (x, y, False, None, None))
    assert form.selection == ["Button1", "Button2"]
    corners = [m for m in form.surface.canvas.winfo_children() if m in form.surface._markers]
    assert len(corners) == 8  # four corners each

    # Ctrl+drag inside a Frame boxes the controls in it; a Ctrl+click on it (no drag) adds the Frame.
    form.add_control("Label", 8, 48, container="Frame1")
    app.root.update()
    frame = form.surface.controls["Frame1"]
    inner = frame.inner
    x, y = inner.winfo_rootx(), inner.winfo_rooty()
    form.surface._lasso_release(types.SimpleNamespace(x_root=x + 100, y_root=y + 80, state=0),
                                (x + 2, y + 2, False, frame, "Frame1"))
    assert form.selection == ["Label1", "Label2"]
    form.select("Button1")
    form.surface._lasso_release(types.SimpleNamespace(x_root=x + 3, y_root=y + 3, state=0),
                                (x + 2, y + 2, False, frame, "Frame1"))
    assert form.selection == ["Button1", "Frame1"]


def test_moving_editing_and_deleting_a_selection(app):
    form = app.form
    form.add_control("Button", 16, 8)
    form.add_control("CheckBox", 16, 48)
    form.select_many(["Button1", "CheckBox1"])

    form.nudge(dx=8)
    assert [form.design.control(n)["left"] for n in ("Button1", "CheckBox1")] == [24, 24]

    rows = dict(form.props_for(MULTIPLE))
    assert "value" not in rows and rows["left"] == 24 and rows["top"] == ""  # shared props; blank where they differ
    assert form.choices_for(MULTIPLE, "enabled") == ("True", "False")
    assert form.set_property(MULTIPLE, "enabled", "False") == MULTIPLE
    assert [form.design.control(n)["enabled"] for n in ("Button1", "CheckBox1")] == [False, False]
    form.undo()  # one step for both
    assert [form.design.control(n)["enabled"] for n in ("Button1", "CheckBox1")] == [True, True]
    assert form.selection == ["Button1", "CheckBox1"]  # undo keeps the selection

    form.delete_selection()
    assert form.design.controls == []
    form.undo()
    assert [c["name"] for c in form.design.controls] == ["Button1", "CheckBox1"]


def test_format_menu(app):
    form = app.form
    form.add_control("Button", 13, 8, 96, 32)
    form.add_control("Button", 40, 56, 64, 24)
    form.add_control("Button", 80, 120, 80, 24)
    form.add_control("Timer", 200, 200)
    form.select_many(["Button2", "Button3", "Timer1", "Button1"])  # Button1 is the reference

    form.align("lefts")
    assert {form.design.control(n)["left"] for n in ("Button1", "Button2", "Button3", "Timer1")} == {13}
    form.make_same_size()
    assert [(form.design.control(n)["width"], form.design.control(n)["height"]) for n in ("Button2", "Button3")] == [(96, 32)] * 2
    assert "width" not in form.design.control("Timer1")
    form.align_to_grid()
    assert form.design.control("Button1")["left"] == 16
    form.space_evenly("y")
    tops = sorted(form.design.control(n)["top"] for n in ("Button1", "Button2", "Button3", "Timer1"))
    assert tops == [8, 72, 136, 200]  # the ends stay, the gaps even out
    form.center_in_container("x")
    assert form.design.control("Button1")["left"] == (400 - 96) // 2

    form.select("Button1")
    form.change_order(to_front=True)
    assert [c["name"] for c in form.design.controls][-1] == "Button1"
    form.change_order(to_front=False)
    assert [c["name"] for c in form.design.controls][0] == "Button1"
    assert form.surface.canvas.winfo_children().index(form.surface.controls["Button1"].widget) < \
        form.surface.canvas.winfo_children().index(form.surface.controls["Button2"].widget)


def test_send_to_back_keeps_frames_before_their_contents(app):
    form = app.form
    form.add_control("Label", 8, 8)
    form.add_control("Frame", 100, 8, 160, 120)
    form.add_control("Button", 8, 8, container="Frame1")
    form.add_control("CheckBox", 8, 48, container="Frame1")
    form.select("CheckBox1")
    form.change_order(to_front=False)
    assert [c["name"] for c in form.design.controls] == ["Label1", "Frame1", "CheckBox1", "Button1"]
    form.select("Frame1")
    form.change_order(to_front=False)  # the Frame takes its contents with it
    assert [c["name"] for c in form.design.controls] == ["Frame1", "CheckBox1", "Button1", "Label1"]
    assert app.save() and formfile.load(form.path)  # still a valid .form file


def specs_of(form, *names):
    return [{k: form.design.control(n)[k] for k in ("left", "top", "text") if k in form.design.control(n)} for n in names]


def test_copy_and_paste_in_the_same_form(app):
    form = app.form
    form.add_control("Button", 16, 16)
    form.set_property("Button1", "text", "Go")
    form.select("Button1")
    app.edit("copy")
    app.edit("paste")
    assert form.selection == ["Button2"]  # the copy is selected, ready to move
    assert specs_of(form, "Button2") == [{"left": 32, "top": 32, "text": "Go"}]  # offset, so it doesn't hide the original
    app.edit("paste")
    assert specs_of(form, "Button3") == [{"left": 48, "top": 48, "text": "Go"}]  # repeated pastes cascade
    form.undo()
    assert form.design.control("Button3") is None and form.design.control("Button2")


def test_copying_a_frame_copies_its_contents(app):
    form = app.form
    form.add_control("Frame", 8, 8, 160, 100)
    form.add_control("OptionButton", 8, 8, container="Frame1")
    form.add_control("OptionButton", 8, 40, container="Frame1")
    form.select("Frame1")
    app.edit("copy")
    form.select(FORM)
    added = form.paste(app.clipboard)
    assert added == ["Frame2", "OptionButton3", "OptionButton4"]
    assert [form.design.control(n).get("container") for n in added] == [None, "Frame2", "Frame2"]
    assert form.surface.controls["OptionButton3"].widget.master is form.surface.controls["Frame2"].inner

    form.select("Frame1")  # with one Frame selected, a paste goes inside it
    form.add_control("Label", 200, 200)
    form.select("Label1")
    app.edit("copy")
    form.select("Frame1")
    app.edit("paste")
    assert form.design.control("Label2")["container"] == "Frame1"


def test_cut_and_paste_keeps_names_and_places(app):
    form = app.form
    form.add_control("Button", 16, 16)
    form.add_control("CheckBox", 16, 56)
    form.select_many(["Button1", "CheckBox1"])
    app.edit("cut")
    assert form.design.controls == []
    app.edit("paste")
    assert [c["name"] for c in form.design.controls] == ["Button1", "CheckBox1"]
    assert specs_of(form, "Button1", "CheckBox1")[0]["left"] == 16  # nothing in the way, so no offset
    assert form.selection == ["Button1", "CheckBox1"]


def test_paste_into_another_form(app):
    form1 = app.form
    form1.add_control("TextBox", 8, 8)
    form1.select("TextBox1")
    app.edit("copy")
    app.project.add_form("Settings")
    settings = app.open_form("Settings")
    app.edit("paste")
    assert [c["name"] for c in settings.design.controls] == ["TextBox1"]
    assert specs_of(settings, "TextBox1")[0]["left"] == 8
    assert form1.design.control("TextBox1")  # the original is untouched


def test_clipboard_keys_leave_text_boxes_alone(app):
    form = app.form
    form.add_control("Button", 8, 8)
    form.surface.canvas.focus_force()
    app.root.update()
    assert app.clipboard_key("copy") == "break" and app.clipboard
    app.clipboard = []
    entry = next(w for w in app.properties.grid_frame.grid_slaves(column=1) if w.winfo_class() == "TEntry")
    entry.focus_force()
    app.root.update()
    assert app.clipboard_key("copy") is None and app.clipboard == []  # the entry copies its own text


def test_clicking_one_control_of_a_selection_selects_just_it(app):
    form = app.form
    form.add_control("Button", 16, 16)
    form.add_control("Button", 16, 56)
    form.select_many(["Button1", "Button2"])
    surface = form.surface
    press = types.SimpleNamespace(x_root=0, y_root=0, state=0)
    surface._control_press(press, surface.controls["Button1"])
    assert form.selection == ["Button1", "Button2"]  # kept while the mouse is down, so the group can be dragged
    surface._release(press)  # released without moving
    assert form.selection == ["Button1"]


def fake_python(folder, pyinstaller_installed=False, build_fails=False):
    """A stand-in for the project's python that plays pip and PyInstaller, recording its calls."""
    folder.mkdir(parents=True, exist_ok=True)
    if pyinstaller_installed:
        (folder / "installed").touch()
    script = folder / "python"
    script.write_text(
        "#!/bin/sh\n"
        f'echo "$@" >> "{folder}/calls"\n'
        'case "$1 $2" in\n'
        f'  "-c "*) [ -f "{folder}/installed" ]; exit $? ;;\n'
        f'  "-m pip") touch "{folder}/installed"; echo "Successfully installed pyinstaller" ;;\n'
        f'  "-m PyInstaller") echo "INFO: Build {"failed" if build_fails else "complete!"}"; exit {1 if build_fails else 0} ;;\n'
        "esac\n"
    )
    script.chmod(0o755)
    return script


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in python is a shell script")
def test_make_exe_installs_pyinstaller_then_builds(app, tmp_path):
    fake = fake_python(tmp_path / "fake")
    app.envs.set_python(fake)
    (tmp_path / "fake" / "calls").unlink()  # the Explorer asked it for its version; not part of this
    app.envs.make_exe(ask=False)
    output = wait_until_idle(app)
    calls = (tmp_path / "fake" / "calls").read_text().splitlines()
    assert [c.split()[:2] for c in calls] == [["-c", "import"], ["-m", "pip"], ["-m", "PyInstaller"],
                                              ["-m", "readymade.notices"]]
    assert "pyinstaller" in calls[1]
    assert "--- Installing pyinstaller ---" in output and "INFO: Build complete!" in output
    assert (f"--- Done: {app.project.folder / 'dist' / 'hello'}, with its license notices in LICENSES.txt ---"
            in output)
    assert calls[3].split()[2:] == [str(app.project.folder / "dist" / "LICENSES.txt"), "hello"]
    assert (app.project.folder / "build" / "readymade" / "_readymade_launcher.py").exists()
    assert app.project.dependencies == []  # a build tool, not something the program needs


@pytest.mark.skipif(sys.platform == "win32", reason="the stand-in python is a shell script")
def test_make_exe_reports_a_failed_build(app, tmp_path):
    app.envs.set_python(fake_python(tmp_path / "fake", pyinstaller_installed=True, build_fails=True))
    app.envs.make_exe(ask=False)
    output = wait_until_idle(app)
    assert "--- Installing" not in output
    assert "PyInstaller couldn't make the program; its messages are above." in output


def test_make_exe_offers_an_environment_first(app, monkeypatch):
    from tkinter import messagebox

    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a) or False)
    app.envs.make_exe(ask=False)
    assert asked and app.process is None  # declined: nothing runs in the IDE's own Python


def test_make_exe_stops_when_the_projects_python_is_missing(app):
    app.envs.set_python("D:/miniforge3/envs/app/python.exe")  # chosen on another machine
    app.envs.make_exe(ask=False)
    output = wait_until_idle(app)
    assert "doesn't exist. Choose another in the Project menu." in output
    assert "Installing" not in output and app.process is None


FAKE_LINTER = """import sys
source = sys.stdin.read() if "--stdin" in sys.argv else open(sys.argv[-1]).read()
for n, line in enumerate(source.splitlines(), 1):
    if "bad" in line:
        print(f"{sys.argv[-1]}:{n}:{line.index('bad') + 1}: X100 found bad")
"""


def add_fake_linters(app, tmp_path):
    (tmp_path / "fake_linter.py").write_text(FAKE_LINTER)
    script = str(tmp_path / "fake_linter.py").replace("\\\\", "/")
    pyproject = app.project.pyproject
    pyproject.write_text(pyproject.read_text() + (
        "\n[tool.readymade.lint-tools.typing-check]\n"
        f'command = ["{{python}}", "{script}", "--stdin", "{{file}}"]\nstdin = true\n'
        "\n[tool.readymade.lint-tools.save-check]\n"
        f'command = ["{{python}}", "{script}", "{{file}}"]\n'
    ))


def wait_for(app, condition, seconds=15):
    deadline = time.time() + seconds
    while not condition() and time.time() < deadline:
        app.root.update()
        time.sleep(0.02)
    return condition()


def test_problems_show_while_typing_and_after_saving(app, tmp_path):
    from readymade import lint

    add_fake_linters(app, tmp_path)
    lint.set_choices(app.project, ["typing-check"], ["save-check"])
    app.linter.check_all()
    app.form.show_code()  # on screen, so the line numbers are drawn
    code = app.form.code
    code.text.insert("end", "\nvalue = bad_name\n")
    code.text.event_generate("<<Modified>>")
    assert wait_for(app, lambda: [p.tool for p in code.problems()] == ["typing-check"])  # unsaved: the stdin tool only
    problem = code.problems()[0]
    tag = next(iter(code._problem_tags))
    assert code.text.get(f"{tag}.first", f"{tag}.last") == "bad_name"  # the word is underlined
    code.text.see(f"{problem.line}.0")
    code.text.mark_set("insert", f"{problem.line}.0")
    app.root.update()
    code._draw_numbers()
    assert code.gutter.find_withtag("problem")  # marked next to its line number
    assert code.problem_bar.cget("text") == "typing-check: X100 found bad"  # the message, for the cursor's line

    assert app.save()
    assert wait_for(app, lambda: sorted(p.tool for p in code.problems()) == ["save-check", "typing-check"])

    lint.set_choices(app.project, [], [])  # turned off: the marks go
    app.linter.check_all()
    assert wait_for(app, lambda: code.problems() == [] and not code._problem_tags)


def test_a_missing_tool_is_reported_once(app):
    from readymade import lint

    lint.set_choices(app.project, ["mypy"], [])  # not installed for the tests
    app.linter.check_all()
    app.open_form("Form1")
    assert wait_for(app, lambda: "mypy isn't installed" in app.immediate.output.get("1.0", "end"))
    app.linter.check_all()
    wait_for(app, lambda: False, seconds=1)
    assert app.immediate.output.get("1.0", "end").count("mypy isn't installed") == 1


def test_the_linting_dialog(app, tmp_path):
    from readymade import lint
    from readymade.ide.tooldialog import linting_dialog

    add_fake_linters(app, tmp_path)
    dialog = linting_dialog(app)
    assert set(dialog.tools) >= {"pyflakes", "ruff", "flake8", "pylint", "mypy", "typing-check", "save-check"}
    statuses = {name: [w.cget("text") for w in frame.winfo_children()] for name, frame in dialog.status.items()}
    assert statuses["ruff"] == ["not installed"]  # and no Install button: there's no environment yet
    assert "create an environment" in dialog.where.cget("text")
    dialog.shared["ruff"].set(True)
    dialog.mine["typing-check"].set(True)
    dialog.ok()
    assert lint.choices(app.project) == (["ruff"], ["typing-check"])


FAKE_FORMATTER = """import re, sys
source = sys.stdin.read()
if "def f(:" in source:
    sys.stderr.write("error: cannot parse\\n")
    sys.exit(123)
sys.stdout.write(re.sub(r"(\\w)=(\\w)", r"\\1 = \\2", source))  # spaces around =
"""


def add_fake_formatter(app, tmp_path):
    (tmp_path / "fake_formatter.py").write_text(FAKE_FORMATTER)
    script = str(tmp_path / "fake_formatter.py").replace("\\\\", "/")
    pyproject = app.project.pyproject
    pyproject.write_text(pyproject.read_text() + (
        f'\n[tool.readymade.format-tools.spacer]\ncommand = ["{{python}}", "{script}"]\n'))


def test_format_document(app, tmp_path):
    from readymade import formatting

    add_fake_formatter(app, tmp_path)
    form = app.form
    form.show_code()
    form.code.text.insert("end", "\nx=1\ny=2\n")
    line = form.code.text.search("y=2", "1.0").split(".")[0]
    form.code.text.mark_set("insert", f"{line}.2")
    app.format_document()
    assert "No formatter is chosen" in app.immediate.output.get("1.0", "end")
    formatting.set_choices(app.project, [], ["spacer"])  # my default, as the project hasn't chosen
    before = form.code.get_source()
    app.format_document()
    assert form.code.get_source().endswith("\nx = 1\ny = 2\n")
    assert form.code.text.index("insert") == f"{line}.2"  # the cursor stays put
    form.code.text.edit_undo()
    assert form.code.get_source() == before  # one undo step

    form.code.text.insert("end", "def f(:\n")
    broken = form.code.get_source()
    assert app.format_code(form) is False
    assert form.code.get_source() == broken  # left as it was
    assert "spacer couldn't format Form1.py: error: cannot parse" in app.immediate.output.get("1.0", "end")


def test_the_projects_formatter_wins_and_format_on_save(app, tmp_path):
    from readymade import formatting

    add_fake_formatter(app, tmp_path)
    formatting.set_choices(app.project, ["spacer"], ["black"])
    assert [t.name for t in formatting.tools_for(app.project)] == ["spacer"]  # not combined: the project's choice
    formatting.set_choices(app.project, [], ["black", "isort"])
    assert [t.name for t in formatting.tools_for(app.project)] == ["isort", "black"]  # my default, imports first

    formatting.set_choices(app.project, ["spacer"], [])
    formatting.set_on_save(app.project, False, True)  # my default: on
    assert formatting.format_on_save(app.project)
    form = app.form
    form.code.text.insert("end", "\nx=1\n")
    assert app.save()
    assert (app.project.folder / "Form1.py").read_text().endswith("\nx = 1\n")  # formatted, then saved
    form.code.text.insert("end", "def f(:\n")
    assert app.save()  # a formatter that can't still lets the save go ahead
    assert (app.project.folder / "Form1.py").read_text().endswith("def f(:\n")


def test_the_formatting_dialog(app):
    from readymade import formatting
    from readymade.ide.tooldialog import formatting_dialog

    dialog = formatting_dialog(app)
    assert list(dialog.tools)[:5] == ["isort", "autopep8", "yapf", "black", "ruff"]  # the order they run in
    dialog.shared["black"].set(True)
    dialog.mine["ruff"].set(True)
    dialog.switch[0].set(True)  # format when saving, for the project
    dialog.ok()
    assert formatting.choices(app.project) == (["black"], ["ruff"])
    assert formatting.on_save_choices(app.project) == (True, False)
    assert "format-on-save = true" in app.project.pyproject.read_text()


def test_format_document_has_its_shortcut(app):
    assert app.root.bind("<Alt-KeyPress-F>")


needs_jedi = pytest.mark.skipif(not __import__("readymade.ide.assist", fromlist=["AVAILABLE"]).AVAILABLE,
                                reason="needs Jedi (pip install -e '.[ide]')")


def form_with_code(app, code):
    form = app.form
    form.add_control("Label", 8, 8)
    form.add_control("Button", 8, 40)
    form.show_code()
    form.code.set_source(code)
    return form


@needs_jedi
def test_completion_list_while_typing(app):
    from test_codeview import type_text

    form = form_with_code(app, "from readymade import Form\n\n\nclass Form1(Form):\n    def Button1_click(self):\n        \n")
    code = form.code
    code.text.mark_set("insert", "6.8")
    type_text(code, "self.")
    assert wait_for(app, code.completions.is_open)
    shown = [c.name for c in code.completions.shown]
    assert "Label1" in shown and "Button1" in shown
    type_text(code, "Lab")  # narrows the list
    assert [c.name for c in code.completions.shown] == ["Label1"]
    code._newline(None)  # Enter accepts
    assert code.text.get("6.0", "6.end") == "        self.Label1" and not code.completions.is_open()

    type_text(code, ".")
    assert wait_for(app, code.completions.is_open)
    code.completions.move(1)
    code._up_down(-1)  # Up/Down move through the list rather than the code
    assert code.completions.listbox.curselection() == (0,)
    code._up_down(1)
    code.text.event_generate("<KeyRelease-Down>")  # releasing the key mustn't reset the choice
    code.update()
    assert code.completions.listbox.curselection() == (1,)
    code.text.event_generate("<Escape>")
    assert not code.completions.is_open()


@needs_jedi
def test_go_to_definition(app):
    form = form_with_code(app, "from readymade import Form\n\n\nclass Form1(Form):\n"
                               "    def Button1_click(self):\n        self.Label1.text = self.greeting()\n\n"
                               "    def greeting(self):\n        return 'hi'\n")
    app.go_to_definition(form, "6.14")  # self.Label1
    assert form.frame.select() == str(form.surface) and form.selected == "Label1"  # shown in the designer

    app.go_to_definition(form, "6.35")  # self.greeting
    assert form.frame.select() == str(form.code)
    assert form.code.text.index("insert") == "8.8" and form.code.text.get("sel.first", "sel.last") == "greeting"

    app.go_to_definition(form, f"1.{len('from readymade import ') + 1}")  # Form, in readymade itself: read-only
    viewer = app.current_editor()
    assert viewer.title() == "form.py (read-only)" and str(viewer.code.text.cget("state")) == "disabled"
    assert viewer.code.text.get("insert linestart", "insert lineend").startswith("class Form")
    assert viewer.code.on_change is None  # never linted


def test_completion_says_when_jedi_is_missing(app, monkeypatch):
    monkeypatch.setattr(app, "assistant", None)
    app.go_to_definition()
    assert "need Jedi" in app.immediate.output.get("1.0", "end")


def test_programs_and_tools_run_without_color(app, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "3")  # as some terminals set it
    env = app.runner.environment()
    assert "FORCE_COLOR" not in env and env["PYTHON_COLORS"] == "0" and env["NO_COLOR"] == "1"
    app.form.add_control("Label", 8, 8)
    write_code(app, "Form1", "from readymade import Form\n\n\nclass Form1(Form):\n"
               "    def Form_load(self):\n        print('\\x1b[31mred\\x1b[0m')\n        self.close()\n")
    app.runner.run()
    output = wait_for_exit(app)
    assert "red\n" in output and "\x1b" not in output  # color a program prints itself is dropped too


def test_every_designer_property_and_event_has_help():
    import inspect

    from readymade.controls import REGISTRY
    from readymade.ide import helptext

    for type_name, cls in REGISTRY.items():
        assert inspect.getdoc(cls), type_name
        for prop in cls.prop_defaults():
            assert inspect.getdoc(getattr(cls, prop)), f"{type_name}.{prop} has no docstring for F1"
        for event in cls.events:
            assert event.name in helptext.EVENTS, f"{type_name}'s {event.name} event isn't described"


def test_f1_in_the_designer_and_properties(app):
    form = app.form
    form.add_control("ListBox", 8, 8)
    form.select("ListBox1")
    form.show_design()
    form.surface.canvas.focus_force()
    app.root.update()
    app.show_help()
    assert app.bottom.select() == str(app.help)
    assert app.help.title.cget("text") == "ListBox1"
    help_text = app.help.text.get("1.0", "end")
    assert "add_item" in help_text and "list_index" in help_text and "ListBox1_click(self)" in help_text

    items = app.properties._editors["width"]
    items.focus_force()
    app.root.update()
    app.show_help()
    assert app.help.title.cget("text") == "width" and "Width, in pixels" in app.help.text.get("1.0", "end")

    form.select(FORM)
    form.surface.canvas.focus_force()
    app.root.update()
    app.show_help()
    assert app.help.title.cget("text") == "Form1" and "Form_load(self)" in app.help.text.get("1.0", "end")


def test_running_shows_the_immediate_window_again(app):
    app.show_topic(__import__("readymade.ide.helptext", fromlist=["home"]).home())
    assert app.bottom.select() == str(app.help)
    app.runner.run()
    assert app.bottom.select() == str(app.immediate)
    app.runner.immediate_line("form.close()")
    wait_for_exit(app)


@needs_jedi
def test_f1_in_code(app):
    form = form_with_code(app, "from readymade import Form, msgbox\n\n\nclass Form1(Form):\n"
                               "    def Button1_click(self):\n        self.Label1.text = 'x'\n        msgbox('hi')\n")
    form.code.text.mark_set("insert", "6.14")  # self.Label1
    form.code.text.focus_force()
    app.root.update()
    app.show_help()
    assert app.help.title.cget("text") == "Label1" and "Label1_click(self)" in app.help.text.get("1.0", "end")
    form.code.text.mark_set("insert", "7.10")  # msgbox
    app.show_help()
    assert app.help.title.cget("text") == "readymade.dialogs.msgbox"


def test_paste_with_code(app):
    form = app.form
    form.add_control("Button", 8, 8)
    form.add_control("Label", 8, 48)
    write_code(app, "Form1", """from readymade import Form


class Form1(Form):
    def Button1_click(self):
        self.Label1.text = "clicked"  # the label pasted with it

        self.Button1.enabled = False

    def Button1_mousedown(self, x, y):
        print(x, y)

    def Other_click(self):
        pass
""")
    form.select_many(["Button1", "Label1"])
    app.form.surface.canvas.focus_set()
    app.edit("copy")
    assert [method for _, method, _ in app.clipboard_handlers] == ["Button1_click", "Button1_mousedown"]
    app.edit("paste")  # plain paste: the controls only
    assert form.design.control("Button2") is not None and "Button2_click" not in form.code.get_source()
    form.undo()
    app.edit("paste_code")
    source = form.code.get_source()
    assert '''    def Button2_click(self):
        self.Label2.text = "clicked"  # the label pasted with it

        self.Button2.enabled = False
''' in source
    assert "    def Button2_mousedown(self, x, y):\n        print(x, y)\n" in source
    assert source.count("def Button1_click") == 1 and "def Other_click" in source
    form.undo()  # one step takes away the controls and their code
    assert "Button2" not in form.code.get_source() and form.design.control("Button2") is None

    app.project.add_form("Second")
    other = app.open_form("Second")
    app.edit("paste_code")  # another form: the names are free, so they're kept
    assert "def Button1_click(self):" in other.code.get_source()
    app.edit("paste_code")  # again: renamed controls, renamed code
    assert "def Button2_click(self):" in other.code.get_source()



def test_the_make_exe_dialog(app, monkeypatch):
    from readymade import package
    from readymade.ide.makeexe import MakeExeDialog

    made = []
    real = app.envs.make_exe
    monkeypatch.setattr(app.envs, "make_exe", lambda ask=True: real() if ask else made.append("made"))  # (no build)
    dialog = real()
    assert isinstance(dialog, MakeExeDialog) and dialog.fields["name"].get() == "hello"
    assert dialog.fields["version"].get() == "0.1.0" and dialog.notices.get() is True
    dialog.fields["name"].set("Hello/World")
    dialog.make()
    assert "it can't have / in it" in dialog.note.cget("text") and made == []
    for key, value in (("name", "Hello World"), ("version", "1.2.0"), ("company", "Tea & Co"),
                       ("description", "Says hello"), ("copyright", "(c) 2026 Tea & Co")):
        dialog.fields[key].set(value)
    dialog.one_folder.set(True)
    dialog.notices.set(False)
    dialog.make()
    assert made == ["made"]  # then it makes the program
    details = package.details(app.project)
    assert details == {"name": "Hello World", "version": "1.2.0", "company": "Tea & Co", "description": "Says hello",
                       "copyright": "(c) 2026 Tea & Co", "one_folder": True, "notices": False}
    text = (app.project.folder / "pyproject.toml").read_text()
    assert 'version = "1.2.0"' in text and "one-folder = true" in text and "notices = false" in text
    assert package.exe_path(app.project, "win32") == app.project.folder / "dist" / "Hello World" / "Hello World.exe"
    assert package.exe_path(app.project, "darwin") == app.project.folder / "dist" / "Hello World.app"
    assert package.notices_path(app.project, "linux") == app.project.folder / "dist" / "Hello World" / "LICENSES.txt"
    dialog = real()  # the choices come back next time
    assert dialog.fields["company"].get() == "Tea & Co" and dialog.one_folder.get() is True
    dialog.destroy()
