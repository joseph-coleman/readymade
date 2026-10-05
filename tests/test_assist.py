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
    assert prepared.added[6] == ("control", "Label1", "Label") and prepared.added[8] == ("menu", "mnuOpen", "MenuItem")


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


@needs_jedi
def test_help_on_code(tmp_path):
    source = ('import os\nfrom pybasic import Form, msgbox\n\n\nclass Form1(Form):\n    def Form_load(self):\n'
              '        self.Label1.text = os.path.join("a", "b").upper()\n        msgbox(len("x"))\n')
    prepared = assist.prepare(source, "Form1", [("Label", "Label1")])
    assistant = assist.Assistant(Path(__file__).parent.parent)

    def help_at(line, column):
        return assistant.help(prepared, line, column, tmp_path / "Form1.py", tmp_path, None)

    assert help_at(7, 14) == ("control", "Label1", "Label")  # the IDE shows the control's own help
    text = help_at(7, 21)  # .text: a pybasic property; Jedi doesn't read property docstrings, so pybasic does
    assert text.title.endswith(".text") and "The text it shows" in text.text
    join = help_at(7, 36)
    assert join.title == "os.path.join" and join.docs_url == "https://docs.python.org/3/library/os.path.html#os.path.join"
    assert help_at(7, 51).docs_url == "https://docs.python.org/3/library/stdtypes.html#str.upper"
    assert help_at(8, 15).docs_url == "https://docs.python.org/3/library/functions.html#len"
    msgbox = help_at(8, 10)
    assert msgbox.title == "pybasic.dialogs.msgbox" and "Show a message" in msgbox.text and msgbox.docs_url == ""
