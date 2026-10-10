"""The IDE's link with the programs it runs: the Immediate window, input(), help() and the debugger."""

import tkinter as tk
from tkinter import simpledialog

import pytest
from test_ide import wait_for, wait_for_exit

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    yield app
    app.stop()
    wait_for_exit(app)
    root.destroy()


def output(app):
    return app.immediate.output.get("1.0", "end")


# ----- input() and help() (these used to freeze the IDE) -----

def test_input_is_answered_in_the_immediate_window(app):
    app.run()
    app.immediate_line("name = input('Name? ')")
    assert wait_for(app, lambda: app.session.prompt == "Name? ")
    assert output(app).endswith("Name? \n") and app.immediate.prompt.cget("text") == "input:"
    app.immediate_line("Ada")  # this line answers input(); it isn't run
    assert app.immediate.prompt.cget("text") == ">>>"
    app.immediate_line("? name")
    assert wait_for(app, lambda: "Name? Ada\n" in output(app) and "\nAda\n" in output(app))
    app.immediate_line("form.close()")
    assert "--- Ended (exit code 0) ---" in wait_for_exit(app)


def test_help_writes_its_text(app):
    app.run()
    app.immediate_line("help(len)")
    app.immediate_line("help()")
    app.immediate_line("form.close()")
    text = wait_for_exit(app)
    assert "len(obj, /)" in text
    assert "Type help(something) to read about it" in text


def test_input_and_help_at_design_time(app, monkeypatch):
    monkeypatch.setattr(simpledialog, "askstring", lambda title, prompt, **kw: "Bob")
    app.immediate_line("who = input('Who? ')")
    app.immediate_line("? who")
    assert "Who? Bob\n" in output(app) and output(app).rstrip().endswith("Bob")
    monkeypatch.setattr(simpledialog, "askstring", lambda title, prompt, **kw: None)  # Cancel
    app.immediate_line("input()")
    assert "EOFError" in output(app)
    app.immediate_line("help(len)")
    assert "len(obj, /)" in output(app)
    app.immediate_line("help")
    assert "Type help(something)" in output(app)


# ----- break mode -----

SHOP = """\
from readymade import Form


def add_tax(price):
    tax = price // 10
    return price + tax


class Form1(Form):
    def Form_load(self):
        price = 100
        price = add_tax(price)
        self.text = str(price)

    def Button1_click(self):
        basket = {"tea": 2, "jam": 0}
        per_jar = basket["tea"] / basket["jam"]
        self.text = str(per_jar)
"""
LINES = {text.strip(): n for n, text in enumerate(SHOP.splitlines(), 1) if text.strip()}


@pytest.fixture
def shop(app):
    from test_ide import write_code

    app.form.add_control("Button", 8, 8)
    app.save()
    write_code(app, "Form1", SHOP)
    app.open_form("Form1", "code")
    return app.form.code


def paused_at(app, line):
    return wait_for(app, lambda: app.in_break_mode and app.form.code.paused_line() == line)


def finish(app):
    """Go on, and close the program."""
    if app.in_break_mode:
        app.run()  # F5 continues
        assert wait_for(app, lambda: not app.in_break_mode)
    app.immediate_line("form.close()")
    return wait_for_exit(app)


def test_break_at_an_error(app, shop):
    app.run()
    assert wait_for(app, lambda: app.root.title().endswith("[run]"))
    app.immediate_line("_ = Button1.widget.invoke()")
    error_line = LINES['per_jar = basket["tea"] / basket["jam"]']
    assert paused_at(app, error_line)
    assert app.root.title().endswith("[break]")
    assert shop.error_bar.cget("text") == f"Line {error_line}: ZeroDivisionError: division by zero"
    assert str(app.debug_tabs) in [str(pane) for pane in app.bottom_area.panes()]  # the split layout
    assert app.locals.value_of("basket") == ("{'tea': 2, 'jam': 0}", "dict")
    assert app.locals.value_of("self")[1] == "Form1"
    app.locals.tree.item(app.locals._rows[("basket",)], open=True)
    app.locals.tree.focus(app.locals._rows[("basket",)])
    app.locals.tree.event_generate("<<TreeviewOpen>>")
    assert wait_for(app, lambda: ("basket", "'jam'") in app.locals._rows)
    assert app.locals.value_of("basket", "'jam'") == ("0", "int")
    assert [app.call_stack.tree.item(row, "values")[0] for row in app.call_stack.tree.get_children()] == ["Button1_click"]
    app.immediate_line("? basket['tea'] * 21")  # the paused function's variables
    assert wait_for(app, lambda: "\n42\n" in output(app))
    app.debug_go("next")  # no stepping on from an error
    assert "can't step on" in output(app) and app.in_break_mode
    text = finish(app)  # the rest of the event was skipped; the program went on
    assert "--- Ended (exit code 0) ---" in text
    assert not app.in_break_mode and shop.paused_line() is None and not app.root.title().endswith("]")


def test_no_break_when_the_option_is_off(app, shop):
    from readymade import usersettings

    usersettings.set("break-on-errors", False)
    app.run()
    app.immediate_line("_ = Button1.widget.invoke()")
    assert wait_for(app, lambda: "ZeroDivisionError" in shop.error_bar.cget("text"))
    assert not app.in_break_mode
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_breakpoints_and_stepping(app, shop):
    first = LINES["price = 100"]
    assert shop.toggle_breakpoint(first)
    assert not shop.toggle_breakpoint(LINES["from readymade import Form"] + 1)  # a blank line can't have one
    assert app.project.local_settings()["breakpoints"] == {"Form1.py": [first]}
    app.run()
    assert paused_at(app, first)  # in Form_load, before the window shows
    assert app.session.paused["reason"] == "breakpoint"
    app.debug_go("next")
    assert paused_at(app, LINES["price = add_tax(price)"])
    assert app.locals.value_of("price") == ("100", "int")
    app.debug_go("step")
    assert paused_at(app, LINES["tax = price // 10"])
    stack = [app.call_stack.tree.item(row, "values")[0] for row in app.call_stack.tree.get_children()]
    assert stack == ["add_tax", "Form_load"]  # the latest at the top
    app.call_stack.tree.event_generate("<Return>")  # (the focus is add_tax)
    app.session.choose_frame(0)  # Form_load's place and variables
    assert paused_at(app, LINES["price = add_tax(price)"]) and wait_for(app, lambda: ("self",) in app.locals._rows)
    app.session.choose_frame(1)
    app.debug_go("return")
    assert paused_at(app, LINES["self.text = str(price)"])
    assert app.locals.value_of("price") == ("110", "int")
    app.run_to_cursor()  # (the cursor is on the paused line: nothing to run to, so it goes on)
    assert wait_for(app, lambda: not app.in_break_mode)
    app.immediate_line("? form.text")
    assert wait_for(app, lambda: "\n110\n" in output(app))
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_breakpoints_are_remembered(app, shop):
    shop.toggle_breakpoint(LINES["tax = price // 10"])
    app.close_document(app.form)
    code = app.open_form("Form1", "code").code
    assert code.breakpoint_lines() == [LINES["tax = price // 10"]]
    code.text.insert("1.0", "\n\n")  # they move with the code
    assert code.breakpoint_lines() == [LINES["tax = price // 10"] + 2]
    app.save()
    assert app.project.local_settings()["breakpoints"] == {"Form1.py": [LINES["tax = price // 10"] + 2]}
    app.clear_breakpoints()
    assert code.breakpoint_lines() == [] and "breakpoints" not in app.project.local_settings()


def test_breakpoint_set_while_running_and_pause(app, shop):
    app.run()
    assert wait_for(app, lambda: app.root.title().endswith("[run]"))
    line = LINES['basket = {"tea": 2, "jam": 0}']
    shop.toggle_breakpoint(line)
    app.immediate_line("_ = Button1.widget.invoke()")
    assert paused_at(app, line)
    app.clear_breakpoints()
    app.run()  # continue: to the error
    assert wait_for(app, lambda: app.in_break_mode and app.session.paused and app.session.paused["reason"] == "error")
    app.run()
    assert wait_for(app, lambda: not app.in_break_mode)
    app.pause()  # F6: it breaks as the next event starts
    app.immediate_line("_ = Button1.widget.invoke()")
    assert paused_at(app, line)
    assert app.session.paused["reason"] == "step"
    app.immediate_line("del basket")  # (from 3.13 a paused function's variables can change)
    app.stop()  # Shift+F5 ends it, paused or not
    wait_for_exit(app)
    assert not app.in_break_mode and app.session is None and shop.paused_line() is None


# ----- watches -----

def test_watches(app, shop):
    from readymade.ide import debugging

    shop.text.mark_set("insert", f"{LINES['tax = price // 10']}.5")  # on "price"
    dialog = app.add_watch()
    assert dialog.watch() == {"expression": "tax", "kind": "watch", "file": "Form1.py", "function": "add_tax"}
    assert list(dialog.functions["values"]) == [debugging.ALL_FUNCTIONS, "add_tax", "Button1_click", "Form_load"]
    dialog.expression.set("price * 2")
    dialog.ok()
    dialog = app.add_watch("price")
    dialog.function.set(debugging.ALL_FUNCTIONS)
    dialog.kind.set("changes")
    assert "slows it down" in dialog.note.cget("text")
    dialog.function.set("Form_load")
    assert dialog.note.cget("text") == ""
    dialog.ok()
    assert app.watches() == [
        {"expression": "price * 2", "kind": "watch", "file": "Form1.py", "function": "add_tax"},
        {"expression": "price", "kind": "changes", "file": "Form1.py", "function": "Form_load"},
    ]
    assert [app.watches_panel.tree.item(row, "values")[2] for row in app.watches_panel.tree.get_children()] == [
        "add_tax in Form1.py", "Form_load in Form1.py, breaks when it changes"]

    shop.toggle_breakpoint(LINES["tax = price // 10"])
    app.run()
    assert paused_at(app, LINES["tax = price // 10"])
    assert app.watches_panel.value_of("#watch", 0)[:2] == ("200", "int")
    assert app.watches_panel.value_of("#watch", 1)[0] == "<out of context>"  # only in Form_load
    app.session.choose_frame(0)  # Form_load
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 0)[0] == "<out of context>")
    assert app.watches_panel.value_of("#watch", 1)[:2] == ("100", "int")
    app.delete_watch(0)  # while paused: the program hears at once
    assert wait_for(app, lambda: len(app.watches_panel.tree.get_children()) == 1)
    app.run()
    assert paused_at(app, LINES["self.text = str(price)"])  # the line after price changed
    assert app.session.paused["reason"] == "watch"
    assert "--- Watch: price changed from 100 to 110 ---" in output(app)
    app.quick_watch()  # the word at the cursor, which is on the paused line: "self"
    assert wait_for(app, lambda: any(isinstance(w, debugging.QuickWatch) for w in app.root.winfo_children()))
    quick = next(w for w in app.root.winfo_children() if isinstance(w, debugging.QuickWatch))
    assert "Form1" in quick.value.get("1.0", "end")
    quick.destroy()
    assert "--- Ended (exit code 0) ---" in finish(app)
    assert app.watches_panel.value_of("#watch", 0) == ("", "", "Form_load in Form1.py, breaks when it changes")


def test_watches_while_running(app, shop):
    from readymade import usersettings

    assert str(app.debug_tabs) not in [str(pane) for pane in app.bottom_area.panes()]  # hidden at first
    app.show_debug_window(app.watches_panel)  # View > Watches
    assert str(app.debug_tabs) in [str(pane) for pane in app.bottom_area.panes()]
    assert app.debug_tabs.select() == str(app.watches_panel) and usersettings.get("debug-windows") is True
    app.set_watches([{"expression": "form.text", "kind": "watch", "file": "", "function": ""},
                     {"expression": "len(basket)", "kind": "watch", "file": "Form1.py", "function": "Button1_click"},
                     {"expression": "add_tax(50)", "kind": "watch", "file": "Form1.py", "function": ""},
                     {"expression": "[1, 2]", "kind": "watch", "file": "", "function": ""}])
    app.run()
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 0)[0] == "'110'")  # live, from Form_load
    assert app.watches_panel.value_of("#watch", 1)[0] == "<out of context>"  # only while paused in that function
    assert app.watches_panel.value_of("#watch", 2)[0] == "55"  # the file's own names
    app.immediate_line("form.text = 'Shop'")
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 0)[0] == "'Shop'")
    row = app.watches_panel._rows[("#watch", 3)]
    app.watches_panel.tree.focus(row)
    app.watches_panel.tree.item(row, open=True)
    app.watches_panel.tree.event_generate("<<TreeviewOpen>>")  # opening one while running
    assert wait_for(app, lambda: ("#watch", 3, "[1]") in app.watches_panel._rows)
    assert "--- Ended (exit code 0) ---" in finish(app)
    app.keep_debug_windows.set(False)  # View > Debug Windows, unticked
    app._debug_windows_toggled()
    assert str(app.debug_tabs) not in [str(pane) for pane in app.bottom_area.panes()]
