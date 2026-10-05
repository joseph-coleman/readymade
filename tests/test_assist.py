"""Completion and Go to Definition: the form declarations (always), and Jedi's answers (if installed)."""

from pathlib import Path

import pytest

from pybasic.ide import assist

FORM_CODE = '''from pybasic import Form


class Form1(Form):
    def Button1_click(self):
        self.Label1.te
        self.helper()

    def helper(self):
        pass
'''


def test_forms_declare_their_controls_and_menu_items_for_jedi():
    prepared = assist.prepare(FORM_CODE, "Form1", [("Label", "Label1"), ("Button", "Button1")], ["mnuOpen"])
    lines = prepared.source.split("\n")
    assert lines[3] == "class Form1(Form):"
    assert lines[4].strip().startswith("from pybasic import controls as _pybasic_controls")
    assert lines[5:8] == ["    Label1: _pybasic_controls.Label", "    Button1: _pybasic_controls.Button",
                          "    mnuOpen: _pybasic_menus.MenuItem"]
    assert prepared.to_jedi(1) == 1 and prepared.to_jedi(6) == 10  # lines below the class move down 4
    assert prepared.from_jedi(10) == 6 and prepared.from_jedi(6) is None  # an added line isn't in the editor
    assert prepared.added[6] == ("control", "Label1") and prepared.added[8] == ("menu", "mnuOpen")


def test_code_without_the_form_class_is_left_alone():
    assert assist.prepare("x = 1\n").source == "x = 1\n"
    assert assist.prepare(FORM_CODE, "Renamed", [("Label", "Label1")]).source == FORM_CODE


needs_jedi = pytest.mark.skipif(not assist.AVAILABLE, reason="needs Jedi (pip install -e '.[ide]')")


@pytest.fixture
def ask(tmp_path):
    assistant = assist.Assistant(Path(__file__).parent.parent)
    prepared = assist.prepare(FORM_CODE, "Form1", [("Label", "Label1"), ("Button", "Button1")], ["mnuOpen"])
    path = tmp_path / "Form1.py"

    def ask(kind, line, column):
        method = assistant.complete if kind == "complete" else assistant.definition
        return method(prepared, line, column, path, tmp_path, None)

    ask.path = path
    return ask


@needs_jedi
def test_completion_knows_the_controls(ask):
    assert [c.name for c in ask("complete", 6, 22)] == ["text"]  # self.Label1.te|
    names = [c.name for c in ask("complete", 7, 13)]  # self.|helper()
    assert {"Label1", "Button1", "mnuOpen", "helper", "close", "show"} <= set(names)
    assert not [n for n in names if n.startswith("_pybasic")]  # the added lines stay hidden


@needs_jedi
def test_definitions(ask):
    assert ask("definition", 6, 14) == assist.Definition("control", "Label1")
    helper = ask("definition", 7, 15)
    assert (helper.kind, helper.path, helper.line, helper.column) == ("file", ask.path, 9, 8)  # its real line
    form = ask("definition", 1, 20)
    assert form.kind == "file" and form.path.name == "form.py" and form.name == "Form"
