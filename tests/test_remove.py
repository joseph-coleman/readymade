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
    assert "This deletes Form2.form and Form2.py" in asked[0] and "forms.Form2" in asked[0]

    answer(True)
    assert app.remove_from_project("form", "Form2")
    assert not (app.project.folder / "Form2.form").exists() and not (app.project.folder / "Form2.py").exists()
    assert editor not in app.editors and not app.is_dirty()
    assert app.project.forms() == ["Form1"] and app.project.startup == "Form1"
    assert "form:Form2" not in explorer_rows(app)
    assert app.explorer.tree.item("form:Form1", "text") == "Form1  (startup)"
    assert "Deleted Form2.form and Form2.py." in app.immediate.output.get("1.0", "end")


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
