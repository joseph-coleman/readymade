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

    def checked_price(self, text):
        try:
            return float(text)
        except ValueError:
            return 0.0
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
    assert list(dialog.functions["values"]) == [debugging.ALL_FUNCTIONS, "add_tax", "Button1_click", "checked_price",
                                              "Form_load"]
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
    assert paused_at(app, LINES["price = add_tax(price)"])  # price didn't exist, then it did
    assert app.session.paused["message"] == f"price was set to 100 on line {LINES['price = 100']}"
    assert app.watches_panel.value_of("#watch", 0)[0] == "<out of context>"  # add_tax hasn't run
    app.run()
    assert paused_at(app, LINES["tax = price // 10"])
    assert app.watches_panel.value_of("#watch", 0)[:2] == ("200", "int")
    assert app.watches_panel.value_of("#watch", 1)[0] == "100  (in Form_load)"  # (waiting for add_tax)
    app.session.choose_frame(0)  # Form_load
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 0)[0] == "200  (in add_tax)")
    assert app.watches_panel.value_of("#watch", 1)[:2] == ("100", "int")
    app.delete_watch(0)  # while paused: the program hears at once
    assert wait_for(app, lambda: len(app.watches_panel.tree.get_children()) == 1)
    app.run()
    assert paused_at(app, LINES["self.text = str(price)"])  # the line after price changed
    assert app.session.paused["reason"] == "watch"
    changed = LINES["price = add_tax(price)"]
    assert f"--- Watch: price changed from 100 to 110 on line {changed} ---" in output(app)
    assert str(shop.text.tag_ranges("changed")[0]) == f"{changed}.0"  # the line that changed it is marked
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
    assert app.watches_panel.value_of("#watch", 1)[0] == "<out of context>"  # Button1_click hasn't run
    assert app.watches_panel.value_of("#watch", 2)[0] == "55"  # the file's own names
    app.immediate_line("form.text = 'Shop'")
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 0)[0] == "'Shop'")
    app.immediate_line("_ = Button1.widget.invoke()")  # (it fails, and pauses at the error)
    assert wait_for(app, lambda: app.in_break_mode)
    app.run()
    assert wait_for(app, lambda: app.watches_panel.value_of("#watch", 1)[0] == "2  (as Button1_click left it)")
    row = app.watches_panel._rows[("#watch", 3)]
    app.watches_panel.tree.focus(row)
    app.watches_panel.tree.item(row, open=True)
    app.watches_panel.tree.event_generate("<<TreeviewOpen>>")  # opening one while running
    assert wait_for(app, lambda: ("#watch", 3, "[1]") in app.watches_panel._rows)
    assert "--- Ended (exit code 0) ---" in finish(app)
    app.keep_debug_windows.set(False)  # View > Debug Windows, unticked
    app._debug_windows_toggled()
    assert str(app.debug_tabs) not in [str(pane) for pane in app.bottom_area.panes()]


# ----- starting errors, stepping from the start, Set Next Statement, breakpoint conditions -----

def test_an_error_as_the_program_starts(app):
    from test_ide import write_code

    app.project.add_module("prices")
    write_code(app, "prices", "TAX = 10\nRATE = TAX / MISSING\n")
    write_code(app, "Form1", "from readymade import Form\nimport prices\n\n\nclass Form1(Form):\n    pass\n")
    app.run()
    assert wait_for(app, lambda: app.in_break_mode)
    module = next(e for e in app.editors if e.name == "prices")
    assert module.code.paused_line() == 2
    assert app.locals.value_of("TAX") == ("10", "int")  # the module's own names
    assert "it can't go on: Continue or End ends it" in output(app)
    app.run()
    assert "--- Ended (exit code 1) ---" in wait_for_exit(app)


def test_f11_starts_stepping(app, shop):
    app.debug_go("step")  # F11, with nothing running
    assert paused_at(app, LINES["price = 100"])  # Form_load's first line
    app.debug_go("next")
    assert paused_at(app, LINES["price = add_tax(price)"])
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_set_next_statement(app, shop):
    shop.toggle_breakpoint(LINES["price = 100"])
    app.run()
    assert paused_at(app, LINES["price = 100"])
    shop.text.mark_set("insert", f"{LINES['tax = price // 10']}.0")  # in another function: refused
    app.set_next_statement()
    assert wait_for(app, lambda: "Can't go on from line" in output(app))
    shop.text.mark_set("insert", f"{LINES['self.text = str(price)']}.0")
    app.set_next_statement()  # skip the rest: price is never set
    assert paused_at(app, LINES["self.text = str(price)"])
    assert app.in_break_mode and app.session.paused is not None
    app.run()
    assert wait_for(app, lambda: not app.in_break_mode)
    app.immediate_line("? form.text")
    assert wait_for(app, lambda: "\nNone\n" in output(app))  # (Python 3.13: a variable skipped over is None)
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_breakpoint_conditions(app, shop):
    from readymade.ide import debugging

    line = LINES["tax = price // 10"]
    dialog = app.breakpoint_condition(app.form, line)
    dialog.condition.set("price >")
    dialog.ok()
    assert "isn't an expression" in dialog.note.cget("text") and shop.breakpoint_settings(line) is None
    dialog.condition.set("price > 50")
    dialog.mode.set(dict(debugging.HIT_MODES)[">="])
    dialog.hits.set("1")
    dialog.ok()
    assert shop.breakpoints() == [{"line": line, "condition": "price > 50", "hit_mode": ">=", "hits": 1}]
    assert app.project.local_settings()["breakpoints"] == {"Form1.py": shop.breakpoints()}
    app.root.update()
    assert len(shop.gutter.find_withtag("breakpoint")) == 3  # a dot with a + (two lines)
    menu = app._gutter_menu(app.form, line, type("Click", (), {"x_root": 0, "y_root": 0})())
    menu.unpost()
    assert menu.entrycget(0, "label") == "Remove Breakpoint"
    app.run()
    assert paused_at(app, line)
    assert app.session.paused["message"] == "price > 50 is true, hit 1 time"
    menu = app._gutter_menu(app.form, line, type("Click", (), {"x_root": 0, "y_root": 0})())
    menu.unpost()
    labels = [menu.entrycget(i, "label") for i in range(menu.index("end") + 1) if menu.type(i) != "separator"]
    assert labels == ["Remove Breakpoint", "Switch Breakpoint Off", "Breakpoint Condition...", "Run to Here",
                      "Set Next Statement"]
    assert "--- Ended (exit code 0) ---" in finish(app)
    app.close_document(app.form)
    code = app.open_form("Form1", "code").code  # remembered, condition and all
    assert code.breakpoints() == [{"line": line, "condition": "price > 50", "hit_mode": ">=", "hits": 1}]


def test_step_into_has_a_key_a_mac_leaves_alone(app):
    from readymade import menus

    for shortcut in ("F11", "Ctrl+F11"):  # macOS takes F11 for Show Desktop; Ctrl is ⌘ there
        assert app.root.bind(menus.shortcut_sequence(shortcut))
    assert menus.accelerator("Ctrl+F11", platform="darwin") == "Command-F11"


# ----- edits during a run, values under the mouse, the Breakpoints tab -----

def test_a_note_when_code_changes_during_a_run(app, shop):
    shop.text.insert("end", "\n# a change\n")
    app.root.update()
    assert not shop.note_bar.winfo_ismapped()  # (not running: nothing to say)
    app.run()
    assert wait_for(app, lambda: app.session is not None and app.root.title().endswith("[run]"))
    shop.text.insert("end", "# another\n")
    assert wait_for(app, lambda: shop.note_bar.winfo_ismapped())
    assert "changes take effect the next time it runs" in shop.note_bar.cget("text")
    assert "--- Ended (exit code 0) ---" in finish(app)
    app.root.update()
    assert not shop.note_bar.winfo_ismapped()


def test_the_name_under_the_mouse(app, shop):
    def at(line_text, word, offset=1):
        line = LINES[line_text]
        column = shop.text.get(f"{line}.0", f"{line}.end").index(word) + offset
        shop.text.see(f"{line}.{column}")
        app.root.update()
        x, y, w, h = shop.text.bbox(f"{line}.{column}")
        return shop.expression_at(x + 1, y + h // 2)

    assert at("price = add_tax(price)", "add_tax") == "add_tax"
    assert at("self.text = str(price)", "text") == "self.text"  # with the dotted names before it
    assert at("self.text = str(per_jar)", "self") == "self"
    assert at('per_jar = basket["tea"] / basket["jam"]', '"tea"') == ""  # in a string
    assert at("def Form_load(self):", "def") == ""  # a keyword
    assert at("tax = price // 10", "10") == ""  # a number


def test_values_under_the_mouse_while_paused(app, shop):
    shop.toggle_breakpoint(LINES["tax = price // 10"])
    app.run()
    assert paused_at(app, LINES["tax = price // 10"])
    app._hovered(shop, "price", 100, 100)
    assert wait_for(app, lambda: shop._tip is not None)
    label = shop._tip[0].winfo_children()[0]
    assert label.cget("text") == "price = 100"
    app._hovered(shop, "not_a_name_here", 100, 100)  # nothing shows for a name the function hasn't got
    app.root.update()
    assert wait_for(app, lambda: app.session._tip is None) and shop._tip[1] == "price"
    app.run()
    assert wait_for(app, lambda: not app.in_break_mode) and shop._tip is None  # going on hides it
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_the_breakpoints_tab(app, shop):
    from readymade.ide.panels import BreakpointsPanel

    first, second = LINES["tax = price // 10"], LINES["price = add_tax(price)"]
    shop.toggle_breakpoint(first)
    shop.set_breakpoint_settings(second, {"condition": "price > 1000", "hit_mode": ">=", "hits": 2})

    def rows():
        tree = app.breakpoints_panel.tree
        return [tuple(tree.item(row, "values")) for row in tree.get_children()]

    assert rows() == [
        (BreakpointsPanel.ON, "Form1.py", str(first), "tax = price // 10", ""),
        (BreakpointsPanel.ON, "Form1.py", str(second), "price = add_tax(price)", "when price > 1000, from hit 2 on"),
    ]
    app.switch_breakpoint("Form1.py", first)  # the box: off
    assert rows()[0][0] == BreakpointsPanel.OFF
    assert shop.breakpoint_settings(first) == {"disabled": True} and shop.breakpoint_lines() == [first, second]
    assert app._breakpoint_files() == {str(app.project.folder / "Form1.py"): [
        {"line": second, "condition": "price > 1000", "hit_mode": ">=", "hits": 2}]}  # (the program never sees it)
    app.run()
    app.immediate_line("? form.text")  # it ran through: no stop at the switched-off breakpoint
    assert wait_for(app, lambda: "\n110\n" in output(app))
    assert "--- Ended (exit code 0) ---" in finish(app)

    shop.text.insert("1.0", "# moved\n")  # rows follow the code as it moves
    shop._changed()
    assert [row[2] for row in rows()] == [str(first + 1), str(second + 1)]
    app.save()
    app.close_document(app.form)  # a file that isn't open is changed where it's remembered
    app.switch_breakpoint("Form1.py", first + 1)
    app._change_breakpoint("Form1.py", second + 1, None)
    assert app.project.local_settings()["breakpoints"] == {"Form1.py": [first + 1]}
    assert rows() == [(BreakpointsPanel.ON, "Form1.py", str(first + 1), "tax = price // 10", "")]
    app.go_to_breakpoint("Form1.py", first + 1)  # opens the code there
    assert app.form.code.text.index("insert") == f"{first + 1}.0"


def test_breakpoints_stay_with_the_saved_code_when_changes_are_thrown_away(app, shop):
    line = LINES["tax = price // 10"]
    shop.toggle_breakpoint(line)
    shop.text.insert("1.0", "\n\n")  # not saved
    app.close_document(app.form, ask=False)  # (thrown away)
    assert app.project.local_settings()["breakpoints"] == {"Form1.py": [line]}


# ----- logpoints, breaking where errors are raised, changing values, dragging the arrow -----

def test_a_logpoint(app, shop):
    from readymade.ide import debugging

    line = LINES["tax = price // 10"]
    dialog = app.breakpoint_condition(app.form, line)
    dialog.logs.set(True)
    dialog._logs_chosen()
    dialog.log.set("price is {price")
    dialog.ok()
    assert "can't read" in dialog.note.cget("text")
    dialog.log.set("price is {price}, tax will be {price // 10}")
    dialog.ok()
    assert shop.breakpoints() == [{"line": line, "log": "price is {price}, tax will be {price // 10}"}]
    app.root.update()
    assert app.breakpoints_panel.tree.item(app.breakpoints_panel.tree.get_children()[0], "values")[4] == (
        "writes: price is {price}, tax will be {price // 10}")
    app.run()
    assert wait_for(app, lambda: "\u00bb price is 100, tax will be 10\n" in output(app))
    assert not app.in_break_mode
    assert "--- Ended (exit code 0) ---" in finish(app)
    assert isinstance(dialog, debugging.BreakpointDialog)


def test_breaking_where_an_error_is_raised(app, shop):
    from readymade import usersettings

    usersettings.set("break-on-all-errors", True)
    app.run()
    assert wait_for(app, lambda: app.root.title().endswith("[run]"))
    app.immediate_line("? form.checked_price('free')")  # a try catches it
    assert paused_at(app, LINES["return float(text)"])
    assert app.session.paused["reason"] == "raised" and app.session.can_step()
    assert "was raised here" in output(app)
    app.debug_go("next")  # F10: on to the except
    assert paused_at(app, LINES["except ValueError:"])
    app.run()
    assert wait_for(app, lambda: "\n0.0\n" in output(app))
    app.immediate_line("_ = Button1.widget.invoke()")  # not caught: it pauses where raised, and only there
    assert paused_at(app, LINES['per_jar = basket["tea"] / basket["jam"]'])
    app.run()
    assert wait_for(app, lambda: not app.in_break_mode and "ZeroDivisionError" in output(app))
    app.root.after(300)
    wait_for(app, lambda: False, seconds=0.5)
    assert not app.in_break_mode  # (no second pause as the error ended the event)
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_changing_a_value_in_locals(app, shop):
    import sys

    shop.toggle_breakpoint(LINES["tax = price // 10"])
    app.run()
    assert paused_at(app, LINES["tax = price // 10"])
    row = app.locals._rows[("price",)]
    app.locals.edit_value(row)
    editor = app.locals.value_editor
    assert editor is not None and editor.get() == "100"
    editor.delete(0, "end")
    editor.insert(0, "200")
    editor.focus_force()
    app.root.update()
    editor.event_generate("<Return>")
    if sys.version_info >= (3, 13):
        assert wait_for(app, lambda: app.locals.value_of("price") == ("200", "int")), (
            app.locals.value_editor, output(app)[-300:])
        app.run()
        app.immediate_line("? form.text")
        assert wait_for(app, lambda: "\n220\n" in output(app))
    else:
        assert wait_for(app, lambda: "before Python 3.13" in output(app))
    assert "--- Ended (exit code 0) ---" in finish(app)


def test_dragging_the_arrow(app, shop):
    from types import SimpleNamespace

    start, target = LINES["price = add_tax(price)"], LINES["self.text = str(price)"]
    shop.toggle_breakpoint(start)
    app.run()
    assert paused_at(app, start)

    def y_of(line):
        app.root.update()
        _, y, _, height, _ = shop.text.dlineinfo(f"{line}.0")
        return y + height // 2

    shop._gutter_press(SimpleNamespace(x=7, y=y_of(start)))
    shop._gutter_drag(SimpleNamespace(x=7, y=y_of(target)))
    assert shop._drag_to == target
    shop._gutter_release(SimpleNamespace(x=7, y=y_of(target)))
    assert paused_at(app, target)  # add_tax never ran
    assert shop.breakpoint_lines() == [start]  # (a drag isn't a click)
    shop._gutter_press(SimpleNamespace(x=7, y=y_of(target)))
    shop._gutter_release(SimpleNamespace(x=7, y=y_of(target)))  # a click on the arrow's line: a breakpoint
    assert shop.breakpoint_lines() == [start, target]
    app.run()
    app.immediate_line("? form.text")
    assert wait_for(app, lambda: "\n100\n" in output(app))  # no tax added
    assert "--- Ended (exit code 0) ---" in finish(app)
