"""The Problems tab: every lint problem in the project, open files or not."""

import tkinter as tk
from tkinter import messagebox

import pytest

# The fake linter flags lines with "bad" in them.
from test_ide import add_fake_linters, wait_for

from readymade import lint

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")  # a new project, with Form1 open
    add_fake_linters(app, tmp_path)
    folder = app.project.folder
    (folder / "helpers.py").write_text("x = 1\ny = 'bad'\n\n\ndef f():\n    return 'bad too'\n", encoding="utf-8")
    app.project.add_form("Form2")
    code = (folder / "Form2.py").read_text(encoding="utf-8")
    (folder / "Form2.py").write_text(code.replace("pass", "pass  # bad", 1), encoding="utf-8")
    yield app
    app.runner.stop()
    root.destroy()


def rows(app):
    tree = app.problems.tree
    return [tuple(str(v) for v in tree.item(row, "values")) for row in tree.get_children()]


def settled(app):
    return not app.linter.busy


def test_problems_in_files_that_arent_open(app):
    assert app.problems.status.cget("text").startswith("Linting is off")
    lint.set_choices(app.project, ["typing-check"], ["save-check"])
    app.linter.check_all()
    assert wait_for(app, lambda: settled(app) and len(rows(app)) == 6)
    form2 = (app.project.folder / "Form2.py").read_text(encoding="utf-8").splitlines()
    bad = str(next(n for n, line in enumerate(form2, 1) if "bad" in line))
    assert rows(app) == [
        ("Form2.py", bad, "X100 found bad  (save-check)"),
        ("Form2.py", bad, "X100 found bad  (typing-check)"),
        ("helpers.py", "2", "X100 found bad  (save-check)"),
        ("helpers.py", "2", "X100 found bad  (typing-check)"),
        ("helpers.py", "6", "X100 found bad  (save-check)"),
        ("helpers.py", "6", "X100 found bad  (typing-check)"),
    ]
    assert app.problems.status.cget("text") == "6 problems in 2 files"
    assert app.bottom.tab(app.problems, "text") == "Problems (6)"


def test_open_files_update_as_you_type(app, monkeypatch):
    lint.set_choices(app.project, ["typing-check"], [])
    app.linter.check_all()
    assert wait_for(app, lambda: settled(app) and len(rows(app)) == 3)
    code = app.form.code
    code.text.insert("end", "\n# bad idea\n")
    app.linter.check(app.form)  # (typing does this after a pause)
    assert wait_for(app, lambda: settled(app) and any(row[0] == "Form1.py" for row in rows(app)))
    # Closing it without saving: its problems are the saved file's again.
    monkeypatch.setattr(messagebox, "askyesnocancel", lambda *a, **kw: False)
    app.close_document(app.form)
    assert wait_for(app, lambda: settled(app) and not any(row[0] == "Form1.py" for row in rows(app)))


def test_clicking_a_problem_goes_there(app):
    lint.set_choices(app.project, ["typing-check"], [])
    app.linter.check_all()
    assert wait_for(app, lambda: settled(app) and len(rows(app)) == 3)
    tree = app.problems.tree
    target = next(row for row in tree.get_children() if tree.item(row, "values")[0] == "helpers.py"
                  and str(tree.item(row, "values")[1]) == "6")
    app.bottom.select(app.problems)  # the tab is showing, as when someone clicks in it
    app.root.update()
    tree.focus_force()
    tree.focus(target)
    app.root.update()
    tree.event_generate("<Return>")
    module = next(e for e in app.editors if e.name == "helpers")
    assert app.documents.select() == str(module.frame)
    assert module.code.text.index("insert") == "6.12"  # line 6, where "bad" starts in "    return 'bad too'"
    # Now open, helpers.py is checked from its editor; its problems stay listed.
    assert wait_for(app, lambda: settled(app) and sum(row[0] == "helpers.py" for row in rows(app)) == 2)


def test_removed_files_and_tools_leave_the_list(app, monkeypatch):
    lint.set_choices(app.project, ["typing-check"], [])
    app.linter.check_all()
    assert wait_for(app, lambda: settled(app) and len(rows(app)) == 3)
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **kw: True)
    app.files.remove_from_project("module", "helpers")
    assert wait_for(app, lambda: settled(app) and [row[0] for row in rows(app)] == ["Form2.py"])
    lint.set_choices(app.project, [], [])
    app.linter.check_all()
    assert wait_for(app, lambda: settled(app) and rows(app) == [])
    assert app.problems.status.cget("text").startswith("Linting is off")
    assert app.bottom.tab(app.problems, "text") == "Problems"


def test_saving_checks_the_other_files_again(app):
    lint.set_choices(app.project, ["save-check"], [])
    app.linter.check_all()
    assert wait_for(app, lambda: settled(app) and len(rows(app)) == 3)
    (app.project.folder / "helpers.py").write_text("x = 1\n", encoding="utf-8")  # fixed elsewhere
    app.form.add_control("Button", 16, 16)  # something to save
    assert app.save()
    assert wait_for(app, lambda: settled(app) and [row[0] for row in rows(app)] == ["Form2.py"])
