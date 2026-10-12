"""Tips on the IDE's marks and notes, and F1 in each of its windows and dialogs."""

import tkinter as tk

import pytest

from readymade.ide import tooltips

pytestmark = pytest.mark.usefixtures("display")

CODE = """from readymade import Form


class Form1(Form):
    def Form_load(self):
        total = 0
        total += 1

        self.text = str(total)
"""


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    app.form.code.set_source(CODE)
    app.form.show_code()
    root.update()
    yield app
    app.runner.stop()
    root.destroy()


def test_what_the_line_numbers_marks_say(app):
    code = app.form.code

    def tip(line, x=7):
        app.root.update()
        _, y, _, height, _ = code.text.dlineinfo(f"{line}.0")
        return code.gutter_tip(x, y + height // 2)

    assert tip(6).startswith("Click to set a breakpoint")
    assert tip(8) == ""  # a blank line can't have one
    code.toggle_breakpoint(6)
    assert tip(6).startswith("A breakpoint: the program pauses before this line runs.")
    code.set_breakpoint_settings(7, {"condition": "total > 1", "log": "total is {total}"})
    assert 'A logpoint: instead of pausing, it writes "total is {total}"' in tip(7)
    assert "only when total > 1" in tip(7)
    app.debug.switch_breakpoint("Form1.py", 6)
    assert tip(6).startswith("A breakpoint, switched off (hollow)")
    assert tip(6, x=200) == ""  # (over the numbers themselves: nothing)


def test_what_the_lists_notes_say(app, tmp_path):
    explorer = app.explorer
    assert explorer.tip_for("form:Form1").startswith("The startup form")
    assert explorer.tip_for("python").startswith("The Python that runs the program")
    (app.project.folder / "data").mkdir()
    (app.project.folder / "data" / "prices.csv").write_text("tea\n")
    app.files.set_bundled("data", True)
    explorer.tree.item("file:data", open=True)
    explorer.fill_folder("file:data")
    assert "as you chose" in explorer.tip_for("file:data")
    assert "with the folder it's in" in explorer.tip_for("file:data/prices.csv")

    app.debug.set_watches([{"expression": "total", "kind": "changes", "file": "Form1.py", "function": "Form_load"},
                     {"expression": "total", "kind": "watch", "file": "", "function": ""}])
    app.debug.show_debug_window(app.watches_panel)
    app.root.update()
    tree = app.watches_panel.tree
    x, y, _, h = tree.bbox(tree.get_children()[0], "#0")
    assert app.watches_panel.tip_at(x + 5, y + h // 2).startswith("Δ This watch pauses the program")
    x, y, _, h = tree.bbox(tree.get_children()[1], "#0")
    assert app.watches_panel.tip_at(x + 5, y + h // 2) == ""  # (a plain watch has no mark)

    app.form.code.toggle_breakpoint(6)
    app.debug.show_debug_window(app.breakpoints_panel)
    app.root.update()
    tree = app.breakpoints_panel.tree
    rows = tree.get_children()
    x, y, _, h = tree.bbox(rows[0], "#1")
    assert app.breakpoints_panel.tip_at(x + 3, y + h // 2).startswith("On: the program pauses here")
    x, y, _, h = tree.bbox(rows[1], "#1")
    assert app.breakpoints_panel.tip_at(x + 3, y + h // 2).startswith("A watch that pauses the program")

    tools = app.toolbox.buttons
    assert all(tooltips.text_of(w) for w in tools.values())
    assert tooltips.text_of(tools["Label"]).startswith("Label: Text on a form")  # (an icon: so its name first)


@pytest.mark.parametrize("panel, title", [
    ("immediate", "Immediate window"), ("problems", "Problems"), ("explorer", "Project Explorer"),
    ("locals", "Locals"), ("watches_panel", "Watches"), ("call_stack", "Call Stack"),
    ("breakpoints_panel", "Breakpoints"), ("toolbox", "Toolbox"),
])
def test_f1_in_each_window(app, panel, title):
    app.debug.show_debug_window(app.locals)
    widget = getattr(app, panel)
    if panel == "immediate":
        target = widget.entry
    elif panel == "toolbox":
        target = widget.buttons[""]  # (the pointer)
    else:
        target = widget.tree
    if panel in ("watches_panel", "call_stack", "breakpoints_panel"):
        app.debug_tabs.select(widget)
    if panel in ("problems",):
        app.bottom.select(widget)
    app.root.update()
    target.focus_force()
    app.root.update()
    app.show_help()
    assert app.help.title.cget("text") == title


def test_f1_on_a_tab_strip_is_its_tab(app):
    app.bottom.select(app.problems)
    app.bottom.focus_force()
    app.root.update()
    app.show_help()
    assert app.help.title.cget("text") == "Problems"


def test_the_dialogs_help(app):
    from readymade.ide import options
    from readymade.ide.makeexe import MakeExeDialog

    for dialog, title in ((app.debug.add_watch(), "Add Watch"), (app.debug.breakpoint_condition(app.form, 6), "Breakpoint Condition"),
                          (options.OptionsDialog(app), "Options"), (MakeExeDialog(app, lambda: None), "Make EXE")):
        app.help.title.configure(text="")
        dialog.focus_force()
        app.root.update()
        dialog.event_generate("<F1>")
        assert app.help.title.cget("text") == title
        assert "Help" in [w.cget("text") for w in _widgets(dialog) if w.winfo_class() == "TButton"]
        dialog.destroy()


def _widgets(widget):
    for child in widget.winfo_children():
        yield child
        yield from _widgets(child)
