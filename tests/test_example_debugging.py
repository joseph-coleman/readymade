"""examples/debugging: what its README.md walks through really happens (run on a copy)."""

import shutil
import tkinter as tk
from pathlib import Path

import pytest
from test_ide import wait_for, wait_for_exit

pytestmark = pytest.mark.usefixtures("display")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "debugging"
# As published: not the breakpoints and watches of whoever last tried it on this machine.
AS_PUBLISHED = shutil.ignore_patterns(".readymade", "__pycache__")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    shutil.copytree(EXAMPLE, tmp_path / "debugging", ignore=AS_PUBLISHED)
    root = tk.Tk()
    app = App(root, tmp_path / "debugging")
    app.open_form("Form1", "code")
    yield app
    app.runner.stop()
    wait_for_exit(app)
    root.destroy()


def line_of(app, file, text):
    """The line of a file's code that has text in it."""
    lines = (app.project.folder / file).read_text(encoding="utf-8").splitlines()
    return next(n for n, line in enumerate(lines, 1) if text in line)


def code_of(app, name):
    editor = app.open_form("Form1", "code") if name == "Form1" else app.open_module(name)
    return editor.code


def paused_in(app, file, text):
    line = line_of(app, file, text)
    return wait_for(app, lambda: app.in_break_mode and app.session.paused is not None
                    and app.session.where()["line"] == line and app.session.where()["file"].endswith(file))


def click(app, button):
    app.runner.immediate_line(f"_ = {button}.widget.invoke()")


def label(app):
    app.runner.immediate_line("print('label:', lblTotal.text)")
    wait_for(app, lambda: "label: " in output(app).split(">>> print('label:', lblTotal.text)")[-1])
    return output(app).split(">>> print('label:', lblTotal.text)")[-1].split("label: ")[1].splitlines()[0]


def output(app):
    return app.immediate.output.get("1.0", "end")


def go_on(app):
    app.runner.run()  # F5
    assert wait_for(app, lambda: not app.in_break_mode)


def test_1_an_error_pauses_the_program(app):
    app.runner.run()
    click(app, "btnClear")
    click(app, "btnAverage")
    assert paused_in(app, "Form1.py", "average = sum(prices) / len(prices)")
    assert app.locals.value_of("prices") == ("[]", "list")
    go_on(app)
    assert label(app) == "Total: 0.00  (0 items)"  # it carried on


def test_2_breakpoints_and_stepping(app):
    code_of(app, "Form1").toggle_breakpoint(line_of(app, "Form1.py", "total = pricing.total(self.basket)"))
    app.runner.run()
    assert paused_in(app, "Form1.py", "total = pricing.total(self.basket)")  # from Form_load
    app.debug.debug_go("step")  # F11
    assert paused_in(app, "pricing.py", "subtotal = 0")
    stack = [app.call_stack.tree.item(row, "values")[0] for row in app.call_stack.tree.get_children()]
    assert stack == ["total", "show_total", "Form_load"]
    app.debug.debug_go("next")
    assert paused_in(app, "pricing.py", "for item in basket:")
    app.debug.debug_go("return")  # Shift+F11
    assert paused_in(app, "Form1.py", "self.lblTotal.text = f\"Total:")
    go_on(app)


def test_3_a_breakpoint_with_a_condition_and_a_hit_count(app):
    pricing = code_of(app, "pricing")
    line = line_of(app, "pricing.py", "cost = line_total(item)")
    pricing.set_breakpoint_settings(line, {"condition": 'item["name"] == "jam"'})
    app.runner.run()
    assert paused_in(app, "pricing.py", "cost = line_total(item)")
    assert "'jam'" in app.locals.value_of("item")[0]
    go_on(app)
    app.runner.stop()
    wait_for_exit(app)
    pricing.set_breakpoint_settings(line, {"hit_mode": "=", "hits": 3})
    app.runner.run()
    assert paused_in(app, "pricing.py", "cost = line_total(item)")
    assert "'bread'" in app.locals.value_of("item")[0]  # the third
    go_on(app)


def test_4_set_next_statement(app):
    code_of(app, "pricing").toggle_breakpoint(line_of(app, "pricing.py", "discount = 5"))
    app.runner.run()
    app.runner.immediate_line("txtItem.text = 'cheese'; txtPrice.text = '9.50'")
    click(app, "btnAdd")
    assert paused_in(app, "pricing.py", "discount = 5")
    app.debug.set_next_statement(app.open_module("pricing"), line_of(app, "pricing.py", "taxed = "))
    assert paused_in(app, "pricing.py", "taxed = ")
    go_on(app)
    assert label(app) == "Total: 44.27  (5 items)"  # no discount (it would be 38.87)


def test_5_watches(app):
    app.debug.set_watches([
        {"expression": "self.seconds_open", "kind": "watch", "file": "", "function": ""},
        {"expression": "TAX_RATE", "kind": "watch", "file": "pricing.py", "function": ""},
        {"expression": "subtotal", "kind": "watch", "file": "pricing.py", "function": "total"},
    ])
    app.runner.run()
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 0)[0] not in ("", "0"))  # ticking
    assert app.watches_panel.value_of("#watch", 1)[0] == "0.08"
    subtotal = app.watches_panel.value_of("#watch", 2)[0]  # (31.490000000000002: floating point adding up)
    assert subtotal.startswith("31.49") and subtotal.endswith("  (as total left it)")
    app.debug.set_watches([*app.debug.breakpoints.watches(), {"expression": "len(self.basket)", "kind": "changes", "file": "Form1.py",
                                      "function": ""}])
    app.runner.immediate_line("txtItem.text = 'cheese'; txtPrice.text = '9.50'")
    click(app, "btnAdd")
    assert paused_in(app, "Form1.py", "self.lstBasket.add_item(")  # the line after the change
    changed = line_of(app, "Form1.py", "self.basket.append(item)")
    assert app.session.paused["message"] == f"len(self.basket) changed from 4 to 5 on line {changed}"
    go_on(app)


def test_6_pause_and_7_starting_by_stepping(app):
    app.debug.debug_go("step")  # F11, stopped
    assert paused_in(app, "Form1.py", "self.basket = []")
    go_on(app)
    app.debug.pause()  # F6
    assert paused_in(app, "Form1.py", "self.seconds_open += 1")
    go_on(app)


def test_8_an_error_as_the_program_starts(app):
    path = app.project.folder / "pricing.py"
    path.write_text(path.read_text(encoding="utf-8").replace("# FREE_DELIVERY", "FREE_DELIVERY"), encoding="utf-8")
    app.runner.run()
    assert paused_in(app, "pricing.py", "FREE_DELIVERY = BIG_ORDER / 0")
    assert app.locals.value_of("BIG_ORDER") == ("40", "int")
    app.runner.run()
    assert "--- Ended (exit code 1) ---" in wait_for_exit(app)


def test_9_the_bug_to_find(app):
    app.runner.run()
    app.runner.immediate_line("lstBasket.list_index = 0")  # 2 x tea
    click(app, "btnRemove")
    app.runner.immediate_line("print('left:', [item['name'] for item in form.basket])")
    assert wait_for(app, lambda: "left: ['tea', 'jam', 'bread']" in output(app))  # the coffee went instead
