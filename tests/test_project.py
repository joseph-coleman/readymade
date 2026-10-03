"""Projects: the pyproject.toml-based project model, and running multi-form programs."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from pybasic import forms, formfile
from pybasic.controls import REGISTRY
from pybasic.project import Project, ProjectError, set_startup

ROOT = Path(__file__).parent.parent


def test_create(tmp_path):
    project = Project.create(tmp_path / "My Inventory")
    assert project.name == "my-inventory"
    assert project.forms() == ["Form1"] and project.modules() == []
    assert project.startup == "Form1"
    assert 'startup = "Form1"' in project.pyproject.read_text()
    with pytest.raises(ProjectError, match="isn't empty"):
        Project.create(project.folder)


def test_forms_and_modules_are_found_in_the_folder(tmp_path):
    project = Project.create(tmp_path / "p")
    project.add_form("Settings")
    project.add_module("helpers")
    (project.folder / "notes.txt").write_text("not code")
    assert project.forms() == ["Form1", "Settings"]
    assert project.modules() == ["helpers"]
    assert Project.find(project.folder / "Settings.form").folder == project.folder


@pytest.mark.parametrize(
    "name, message",
    [("2fast", "valid Python name"), ("class", "valid Python name"), ("random", "hide Python's own"),
     ("form1", "already has"), ("Helpers", "already has")],
)
def test_bad_names(tmp_path, name, message):
    project = Project.create(tmp_path / "p")
    project.add_module("helpers")
    with pytest.raises(ProjectError, match=message):
        project.add_form(name)


def test_startup_falls_back_to_the_first_form(tmp_path):
    (tmp_path / "B.form").write_text(formfile.dumps(formfile.FormDesign(name="B")))
    (tmp_path / "A.form").write_text(formfile.dumps(formfile.FormDesign(name="A")))
    assert Project(tmp_path).startup == "A"  # no pyproject.toml at all
    Project(tmp_path).set_startup("B")  # creates one
    assert Project(tmp_path).startup == "B"


@pytest.mark.parametrize(
    "before, after",
    [
        ('[project]\nname = "x"\n', '[project]\nname = "x"\n\n[tool.pybasic]\nstartup = "Main"\n'),
        ('[tool.pybasic]\n\n[tool.other]\na = 1\n', '[tool.pybasic]\nstartup = "Main"\n\n[tool.other]\na = 1\n'),
        ('[tool.pybasic]\nstartup = "Old"  # comment\ntheme = "x"\n', '[tool.pybasic]\nstartup = "Main"\ntheme = "x"\n'),
        ('[tool.pybasic]\nstartup="Old"\n[[tool.pybasic.plugins]]\nname = "p"\n',
         '[tool.pybasic]\nstartup = "Main"\n[[tool.pybasic.plugins]]\nname = "p"\n'),
    ],
)
def test_set_startup_edits_only_that_line(before, after):
    assert set_startup(before, "Main") == after


def make_two_form_project(folder):
    project = Project.create(folder, first_form="Main")
    project.add_form("Dialog")
    for name, controls in (("Main", [("Button", "Ask"), ("Label", "Answer")]), ("Dialog", [("Button", "OK")])):
        design = formfile.load(project.folder / f"{name}.form")
        design.controls += [REGISTRY[t].new_spec(n, 8, 8 + 32 * i) for i, (t, n) in enumerate(controls)]
        formfile.save(design, project.folder / f"{name}.form")
    (project.folder / "Main.py").write_text(
        "from pybasic import Form, forms\n\n\nclass Main(Form):\n"
        "    def Ask_click(self):\n"
        "        forms.Dialog.show(modal=True)\n"
        "        self.Answer.text = f'result: {forms.Dialog.result}'\n"
    )
    (project.folder / "Dialog.py").write_text(
        "from pybasic import Form\n\n\nclass Dialog(Form):\n"
        "    def Form_load(self):\n        self.result = None\n\n"
        "    def OK_click(self):\n        self.result = 'ok'\n        self.close()\n"
    )
    return project


@pytest.mark.usefixtures("display")
def test_modal_dialog_and_ending_when_the_last_form_closes(tmp_path):
    project = make_two_form_project(tmp_path / "p")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        [sys.executable, "-m", "pybasic.run", "--immediate", str(project.folder)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    lines = [
        "_ = form.root.after(0, Ask.widget.invoke)",  # a modal dialog blocks, so start it from the event loop
        "print('dialog:', forms.Dialog.root.state())",
        "_ = forms.Dialog.OK.widget.invoke()",
        "print(Answer.text)",
        "forms.Dialog.show()",
        "form.close()",
        "print('still running with', [f for f, x in forms.loaded().items() if x.loaded])",
        "forms.Dialog.close()",
    ]
    for line in lines:
        process.stdin.write(line + "\n")
        process.stdin.flush()
        time.sleep(0.4)
    try:
        out, err = process.communicate(timeout=15)
    finally:
        process.kill()
    assert process.returncode == 0, err
    assert out.splitlines() == ["dialog: normal", "result: ok", "still running with ['Dialog']"]


@pytest.mark.usefixtures("display")
def test_default_and_explicit_instances(tmp_path, monkeypatch):
    project = make_two_form_project(tmp_path / "p")
    monkeypatch.syspath_prepend(str(project.folder))
    forms.reset()
    made = []
    try:
        from Dialog import Dialog

        first, second = Dialog(), Dialog()
        made += [first, second, forms.Dialog]
        assert first is not second and forms.Dialog is forms.Dialog
        assert forms.Dialog is not first
        first.root.after(50, first.OK.widget.invoke)
        first.show(modal=True)  # returns when OK closes it
        assert (first.loaded, first.result, second.result) == (False, "ok", None)
        first.show()  # showing a closed form loads it again
        assert first.loaded and first.result is None
        with pytest.raises(AttributeError, match="no form named 'Nope'"):
            forms.Nope
    finally:
        for form in made:
            if form.loaded:
                form.root.destroy()
        forms.reset()
        sys.modules.pop("Dialog", None)
