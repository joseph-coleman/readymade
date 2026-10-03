import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path

import pytest

from pybasic import Form, formfile
from pybasic.controls import REGISTRY
from pybasic.form import check_name
from pybasic.run import load_form_class

ROOT = Path(__file__).parent.parent
EXAMPLE = ROOT / "examples" / "hello" / "Form1.form"


needs_display = pytest.mark.usefixtures("display")


@pytest.fixture
def form_path(tmp_path):
    design = formfile.FormDesign(name="Form1")
    for type_name, name in (("Button", "Button1"), ("TextBox", "TextBox1"), ("Label", "Label1")):
        design.controls.append(REGISTRY[type_name].new_spec(name, 8, 8))
    path = tmp_path / "Form1.form"
    formfile.save(design, path)
    return path


@needs_display
def test_handlers_are_connected_by_name(form_path):
    calls = []

    class Form1(Form):
        def Form_load(self):
            calls.append("load")

        def Button1_click(self):
            calls.append("click")

        def TextBox1_change(self):
            calls.append(f"change {self.TextBox1.text}")

    form = Form1(form_path)
    try:
        form.Button1.widget.invoke()
        form.TextBox1.text = "hi"
        assert calls == ["load", "click", "change hi"]
    finally:
        form.root.destroy()


@needs_display
def test_control_properties(form_path):
    form = Form(form_path)
    try:
        label = form.Label1
        assert label.text == "Label1"
        label.text = "Changed"
        label.left, label.width = 40, 200
        assert (label.widget.cget("text"), label.left, label.width) == ("Changed", 40, 200)
        label.visible = False
        assert not label.widget.winfo_manager()
        form.Button1.enabled = False
        assert form.Button1.widget.cget("state") == tk.DISABLED
    finally:
        form.root.destroy()


@needs_display
def test_unload_can_cancel_closing(form_path):
    class Form1(Form):
        def Form_unload(self):
            return True

    form = Form1(form_path)
    form.close()
    assert form.root.winfo_exists()
    form.root.destroy()


def test_example_class_loads():
    assert load_form_class(EXAMPLE).__name__ == "Form1"


@pytest.mark.parametrize("name", ["Form", "text", "close", "root", "1abc", "class"])
def test_reserved_and_invalid_names(name):
    with pytest.raises(ValueError):
        check_name(name)


@needs_display
def test_run_with_immediate_window():
    """The IDE's Immediate window: lines on stdin run inside the live program."""
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    result = subprocess.run(
        [sys.executable, "-m", "pybasic.run", "--immediate", str(EXAMPLE)],
        input="TextBox1.text = 'Ada'\n_ = Button1.widget.invoke()\nprint(Label2.text)\nform.close()\n",
        capture_output=True, text=True, env=env, timeout=20,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Hello, Ada!"
