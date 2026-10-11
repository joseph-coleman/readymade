"""Removing forms, modules and libraries from a project, in the project and in the IDE."""

import tkinter as tk
from tkinter import messagebox

import pytest

from readymade import project as project_module
from readymade.project import Project

# ----- the project -----

@pytest.mark.parametrize("before, after", [
    ('[project]\ndependencies = ["rich", "requests>=2"]\n', '[project]\ndependencies = [\n    "requests>=2",\n]\n'),
    ('[project]\ndependencies = ["Rich[jupyter]>=13"]\n', '[project]\ndependencies = []\n'),  # by package name
    ('[project]\ndependencies = ["requests"]\n', '[project]\ndependencies = ["requests"]\n'),  # not there: unchanged
    ('[project]\nname = "x"\n', '[project]\nname = "x"\n'),  # no list at all
    ('[tool.x]\na = 1\n', '[tool.x]\na = 1\n'),  # no [project]
])
def test_remove_dependency(before, after):
    assert project_module.remove_dependency(before, "rich") == after


def test_remove_form_and_module(tmp_path):
    project = Project.create(tmp_path / "Shop", first_form="Main")
    project.add_form("Settings")
    project.add_module("helpers")
    project.set_startup("Main")
    project.remove_form("Main")
    assert project.forms() == ["Settings"]
    assert not (project.folder / "Main.form").exists() and not (project.folder / "Main.py").exists()
    assert project.setting("startup") is None and project.startup == "Settings"  # the first form left
    project.remove_module("helpers")
    assert project.modules() == []
    project.remove_dependency("anything")  # nothing to remove: fine


# ----- the IDE -----

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")  # a new project, with Form1
    yield app
    app.stop()
    root.destroy()


@pytest.fixture
def answer(monkeypatch):
    """Answer the confirmation: answer(True) or answer(False). Returns the questions asked."""
    asked = []

    def set_answer(value):
        monkeypatch.setattr(messagebox, "askyesno", lambda title, message, **kw: asked.append(message) or value)
        return asked

    return set_answer


def explorer_rows(app):
    tree = app.explorer.tree
    rows = []
    for top in tree.get_children(""):
        for group in tree.get_children(top):
            rows += tree.get_children(group)
    return rows


def test_removing_a_form_closes_it_and_deletes_its_files(app, answer):
    app.project.add_form("Form2")
    app.set_startup("Form2")
    app.explorer_refresh()
    editor = app.open_form("Form2")
    editor.add_control("Button", 16, 16)  # unsaved: no question about saving, as it's being deleted
    assert app.is_dirty()

    asked = answer(False)
    assert not app.remove_from_project("form", "Form2")
    assert (app.project.folder / "Form2.form").exists() and editor in app.editors
    assert "This moves Form2.form and Form2.py to the Trash" in asked[0].replace("Recycle Bin", "Trash") and "forms.Form2" in asked[0]

    answer(True)
    assert app.remove_from_project("form", "Form2")
    assert not (app.project.folder / "Form2.form").exists() and not (app.project.folder / "Form2.py").exists()
    assert editor not in app.editors and not app.is_dirty()
    assert app.project.forms() == ["Form1"] and app.project.startup == "Form1"
    assert "form:Form2" not in explorer_rows(app)
    assert app.explorer.tree.item("form:Form1", "text") == "Form1  (startup)"
    assert "Moved Form2.form and Form2.py to the " in app.immediate.output.get("1.0", "end")


def test_removing_a_module(app, answer):
    app.project.add_module("helpers")
    app.explorer_refresh()
    app.open_module("helpers")
    asked = answer(True)
    assert app.remove_from_project("module", "helpers")
    assert "import helpers" in asked[0]
    assert app.project.modules() == [] and not any(e.name == "helpers" for e in app.editors)
    assert "module:helpers" not in explorer_rows(app)


def test_removing_a_library_without_a_project_environment(app, answer, monkeypatch):
    app.project.add_dependency("tinypkg>=1")
    app.explorer_refresh()
    started = []
    monkeypatch.setattr(app, "_start", lambda *a, **kw: started.append(a))
    asked = answer(True)
    assert app.remove_from_project("library", "tinypkg>=1")
    assert "stays installed there" in asked[0]  # never uninstalled from the IDE's own Python
    assert started == []
    assert app.project.dependencies == []
    assert "Removed tinypkg>=1 from the project." in app.immediate.output.get("1.0", "end")


def test_removing_a_library_uninstalls_it_from_the_project_environment(app, answer, monkeypatch):
    python = app.project.venv_python()
    python.parent.mkdir(parents=True)
    python.write_text("")  # as if there were a .venv
    app.project.add_dependency("Tiny_Pkg>=1")
    started = []

    def start(args, on_exit=None, **kw):
        started.append(args)
        on_exit(0)

    monkeypatch.setattr(app, "_start", start)
    asked = answer(True)
    assert app.remove_from_project("library", "Tiny_Pkg>=1")
    assert "uninstalled from the project's environment" in asked[0]
    assert started == [[str(python), "-m", "pip", "uninstall", "-y", "--disable-pip-version-check", "tiny-pkg"]]
    assert app.project.dependencies == []


def test_explorer_menu_and_delete_key(app, answer):
    app.project.add_module("helpers")
    app.project.add_dependency("rich")
    app.explorer_refresh()
    tree = app.explorer.tree
    assert "library:rich" in tree.get_children("libraries")

    asked = answer(False)
    tree.focus_force()
    tree.focus("module:helpers")
    tree.update()
    tree.event_generate("<Delete>")
    assert len(asked) == 1 and "helpers" in asked[0]  # Delete asks to remove the selected item
    tree.focus("libraries")
    tree.event_generate("<Delete>")
    assert len(asked) == 1  # the Libraries heading itself can't be removed

    explorer = app.explorer

    def enabled(row, label):
        return str(explorer.menu_for(row).entrycget(label, "state")) == "normal"

    assert enabled("form:Form1", "Remove...") and enabled("form:Form1", "Set as Startup")
    assert enabled("module:helpers", "Remove...") and not enabled("module:helpers", "Set as Startup")
    top = tree.get_children("")[0]
    assert not enabled(top, "Remove...")  # the project itself
    assert enabled("library:rich", "Remove Library...")
    assert not enabled("libraries", "Remove Library...")
    assert explorer.menu_for("python") is explorer.python_menu


def test_renaming_imports_of_a_module():
    from readymade.project import rename_imports

    source = """import helpers
import os, helpers
from helpers import greeting
import helpers as h
import helpers_extra

print(helpers.greeting(), h.x, my_helpers.y, helpers_extra.z)
"""
    assert rename_imports(source, "helpers", "tools") == """import tools
import os, tools
from tools import greeting
import tools as h
import helpers_extra

print(tools.greeting(), h.x, my_helpers.y, helpers_extra.z)
"""
    assert rename_imports("from helpers import x\nhelpers.y\n", "helpers", "tools") == (
        "from tools import x\nhelpers.y\n")  # (only `import helpers` makes helpers.y the module)


def test_renaming_a_module(app):
    from test_ide import write_code

    app.project.add_module("helpers")
    write_code(app, "helpers", "def greeting():\n    return 'hi'\n")
    write_code(app, "Form1", "from readymade import Form\nimport helpers\n\n\nclass Form1(Form):\n"
               "    def Form_load(self):\n        self.text = helpers.greeting()\n")
    app.project.add_module("other")
    (app.project.folder / "other.py").write_text("from helpers import greeting\n")
    form = app.open_form("Form1", "code")
    module = app.open_module("helpers")
    module.code.toggle_breakpoint(2)
    assert app.rename_module("helpers", "tools")
    assert not (app.project.folder / "helpers.py").exists() and (app.project.folder / "tools.py").exists()
    assert module.path.name == "tools.py" and app.documents.tab(module.frame, "text") == "tools.py"
    form_code = form.code.get_source()  # open: changed there, to be saved
    assert "import tools\n" in form_code and "tools.greeting()" in form_code and form.is_dirty()
    assert (app.project.folder / "other.py").read_text() == "from tools import greeting\n"  # not open: saved
    assert app.project.local_settings()["breakpoints"] == {"tools.py": [2]}
    assert app.explorer.tree.exists("module:tools") and not app.explorer.tree.exists("module:helpers")
    assert "Renamed helpers.py to tools.py, and its imports in Form1.py, other.py." in app.immediate.output.get(
        "1.0", "end")
    with pytest.raises(AssertionError, match="unexpected dialog"):  # (an error message: a name that's taken)
        app.rename_module("tools", "other")


def test_the_projects_other_files(app, monkeypatch, answer):
    from readymade.ide.editors import FileEditor

    folder = app.project.folder
    (folder / "README.md").write_text("# Shop\n\nNotes: (draft)\n")
    (folder / "data").mkdir()
    (folder / "data" / "prices.csv").write_text("tea,3.50\n")
    (folder / "data" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0\0\0")
    (folder / "pkg").mkdir()
    (folder / "pkg" / "tools.py").write_text("def f():\n    return 1\n")
    app.explorer_refresh()
    tree = app.explorer.tree
    assert [tree.item(row, "text") for row in tree.get_children("files")] == ["data/", "pkg/", "pyproject.toml",
                                                                               "README.md"]
    assert tree.get_children("file:data") == ("waiting:data",)  # filled when opened
    tree.focus("file:data")
    tree.item("file:data", open=True)
    tree.event_generate("<<TreeviewOpen>>")
    assert [tree.item(row, "text") for row in tree.get_children("file:data")] == ["logo.png", "prices.csv"]

    readme = app.open_file("README.md")  # text: a tab, as plain text
    assert isinstance(readme, FileEditor) and readme.plain and app.documents.tab(readme.frame, "text") == "README.md"
    readme.code.text.insert("end", "More (notes")
    app.root.update()
    assert not readme.code.text.tag_ranges("keyword") and "More (notes\n" in readme.code.get_source() + "\n"
    assert app.save() and (folder / "README.md").read_text().endswith("More (notes")
    assert not app.open_file("pkg/tools.py").plain  # Python in a folder: code
    opened = []
    monkeypatch.setattr(app, "open_with_system", opened.append)
    assert app.open_file("data/logo.png") is None and opened == [folder / "data" / "logo.png"]  # not text

    menu = app.explorer.menu_for("file:data/prices.csv")  # bundling with Make EXE
    assert menu is app.explorer.files_menu and app.explorer.bundled.get() is False
    app.set_bundled("data", True)
    assert app.project.include() == ["data"]
    assert tree.item("file:data", "text") == "data/  (bundled)" and tree.item("file:data", "open")  # (still open)
    assert tree.item("file:data/prices.csv", "text") == "prices.csv  (bundled)"
    app.explorer.menu_for("file:data/prices.csv")
    assert app.explorer.bundled.get() is True  # with its folder,
    assert app.explorer.files_menu.entrycget("Bundle with Make EXE", "state") == "disabled"  # so not by itself

    asked = answer(True)
    assert app.remove_from_project("file", "data")  # (the trash is a test one: see conftest)
    assert asked[-1].startswith("Move the data folder and everything in it to the ")
    assert not (folder / "data").exists() and app.project.include() == []
    assert not tree.exists("file:data")


def test_new_and_renamed_files(app, monkeypatch):
    from readymade.ide.editors import FileEditor

    folder = app.project.folder
    (folder / ".gitignore").write_text(".venv/\n")
    (folder / ".hidden").mkdir()
    assert app.new_folder("", "docs") == "docs" and (folder / "docs").is_dir()
    notes = app.new_file("docs", "notes.txt")  # opened, to type in
    assert notes == "docs/notes.txt" and isinstance(app._current_editor(), FileEditor)
    tree = app.explorer.tree
    assert tree.exists("file:.gitignore") and not tree.exists("file:.hidden")  # dot-files show; hidden folders don't
    assert tree.focus() == "file:docs/notes.txt"
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **kw: errors.append(message))
    assert app.new_file("docs", "notes.txt") is None and "already" in errors[-1]
    assert app.new_file("", "a/b") is None and "isn't a name" in errors[-1]

    app.set_bundled("docs", True)
    editor = app._current_editor()
    assert app.rename_file("docs", "guide") == "guide"  # a folder: what's in it follows
    assert editor.path == folder / "guide" / "notes.txt" and app.project.include() == ["guide"]
    assert app.rename_file("guide/notes.txt", "help.txt") == "guide/help.txt"
    assert editor.path == folder / "guide" / "help.txt" and app.documents.tab(editor.frame, "text") == "help.txt"
    assert app.rename_file("guide/help.txt", "../x") is None and "isn't a name" in errors[-1]


def test_files_changed_outside_the_ide(app):
    folder = app.project.folder
    (folder / "README.md").write_text("first\n")
    (folder / "notes.txt").write_text("notes\n")
    app.explorer_refresh()
    app.check_outside_changes()  # (what's there now counts as seen)
    readme = app.open_file("README.md")
    notes = app.open_file("notes.txt")
    import os
    import time

    def touch(path, text):
        path.write_text(text)
        later = time.time() + 5
        os.utime(path, (later, later))  # (a different time, even on file systems that round it)

    (folder / "added.csv").write_text("x\n")
    touch(folder / "README.md", "changed outside\n")
    notes.code.text.insert("1.0", "mine ")
    touch(folder / "notes.txt", "theirs\n")
    app.check_outside_changes()
    assert app.explorer.tree.exists("file:added.csv")  # the Explorer noticed
    assert readme.code.get_source() == "changed outside\n" and not readme.is_dirty()  # not edited here: shown
    assert notes.code.get_source().startswith("mine notes") and notes.is_dirty()  # edited here: kept,
    assert "notes.txt was changed outside readymade. Your changes here are kept" in app.immediate.output.get(
        "1.0", "end")  # and said once
    app.immediate.output.configure(state="normal")
    app.immediate.output.delete("1.0", "end")
    app.check_outside_changes()
    assert "changed outside" not in app.immediate.output.get("1.0", "end")


def test_a_chosen_picture_shows_in_the_files_list(app, tmp_path, monkeypatch):
    from tkinter import filedialog

    outside = tmp_path / "elsewhere"
    outside.mkdir()
    tk.PhotoImage(master=app.root, width=4, height=4).write(str(outside / "logo.png"), format="png")
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kw: str(outside / "logo.png"))
    form = app.form
    form.add_control("Image", 8, 8)
    form.choose_file("Image1", "picture")  # copied into images/
    tree = app.explorer.tree
    assert tree.exists("file:images")
    tree.focus("file:images")
    tree.item("file:images", open=True)
    tree.event_generate("<<TreeviewOpen>>")
    assert tree.item("file:images/logo.png", "text") == "logo.png"
    app.save()
    assert tree.item("file:images/logo.png", "text") == "logo.png  (bundled)"  # a form shows it
