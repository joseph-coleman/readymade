"""examples/arrays: controls made while the program runs, as its README.md says (run on a copy)."""

import importlib.util
import shutil
import sys
import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("display")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "arrays"
AS_PUBLISHED = shutil.ignore_patterns(".readymade", "__pycache__")  # (not this machine's settings for it)


@pytest.fixture
def form(tmp_path, monkeypatch):
    folder = shutil.copytree(EXAMPLE, tmp_path / "arrays", ignore=AS_PUBLISHED)
    monkeypatch.syspath_prepend(str(folder))
    monkeypatch.chdir(folder)
    monkeypatch.delitem(sys.modules, "helpers", raising=False)
    spec = importlib.util.spec_from_file_location("arrays_form1", folder / "Form1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    form = module.Form1("Form1.form")
    form.show()
    settle(form)
    yield form
    form.root.destroy()
    sys.modules.pop("helpers", None)


def settle(form):
    for _ in range(10):
        form.root.update()
        time.sleep(0.005)


def test_adding_to_a_designed_control_array(form):
    form.Button1[0].widget.invoke()
    form.Button1[1].widget.invoke()  # (an added one can add too: they share the handler)
    settle(form)
    assert form.Button1.indexes == [0, 1, 2] and form.Button1[2].text == "2" and form.Button1[2].visible
    assert form.Status.text == "Button1[1] made Button1[2]"
    assert form.Button1[2].widget.master is form.Frame1.inner


def test_making_buttons_from_nothing(form):
    form.UpDown1.value = 3
    settle(form)
    assert form.B2.indexes == [0, 1, 2] and form.B2[2].text == "Button 2"
    assert all(b.widget.master is form.Frame2.inner and b.dock == "top" for b in form.B2)
    form.B2[1].widget.invoke()  # B2_click, attached as it was made
    assert form.Status.text == "Button 1 was clicked (B2[1])"
    form.UpDown1.value = 1  # last time's go
    settle(form)
    assert form.B2.indexes == [0] and "B2[2]" not in form.controls


def test_clear_is_made_in_code_with_its_handler_attached(form):
    assert form.Clear.form is form and form.Clear.widget.master is form.Frame2.inner
    form.UpDown1.value = 2
    form.Clear.widget.invoke()  # clear_all(form), from helpers.py: given the form by on()
    settle(form)
    assert form.UpDown1.value == 0 and form.B2.indexes == [] and form.Status.text == "Cleared"
