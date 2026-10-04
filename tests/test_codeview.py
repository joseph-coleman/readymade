"""Editing keys in the code window: Tab, Shift+Tab and Backspace for indentation."""

import tkinter as tk
import types

import pytest

from pybasic.ide.codeview import CodeView

pytestmark = pytest.mark.usefixtures("display")

SOURCE = "def f():\n    x = 1\n\n    if x:\n        y = 2\n"


@pytest.fixture
def code():
    root = tk.Tk()
    view = CodeView(root, types.SimpleNamespace(update_title=lambda: None, code_objects=lambda: [], events_for=lambda o: ()))
    view.pack()
    view.set_source(SOURCE)
    yield view
    root.destroy()


def select(code, start, end):
    code.text.tag_remove("sel", "1.0", "end")
    code.text.tag_add("sel", start, end)
    code.text.mark_set("insert", end)


def press(code, handler):
    return getattr(code, handler)(None)


def test_tab_indents_selected_lines(code):
    select(code, "2.3", "4.2")  # partly into lines 2 and 4
    assert press(code, "_tab") == "break"
    assert code.get_source() == "def f():\n        x = 1\n\n        if x:\n        y = 2\n"  # the blank line stays empty
    assert code.text.get("sel.first", "sel.last") == "        x = 1\n\n        if x:\n"  # still selected, ready for another Tab
    code.text.edit_undo()
    assert code.get_source() == SOURCE  # one undo step


def test_a_selection_ending_at_a_line_start_leaves_that_line_alone(code):
    select(code, "2.0", "3.0")  # the whole of line 2, as when selecting lines with Shift+Down
    press(code, "_tab")
    assert code.get_source().splitlines()[1:4] == ["        x = 1", "", "    if x:"]


def test_shift_tab_dedents(code):
    select(code, "4.0", "5.end")
    assert press(code, "_dedent") == "break"
    assert code.get_source().splitlines()[3:] == ["if x:", "    y = 2"]
    code.text.tag_remove("sel", "1.0", "end")
    code.text.mark_set("insert", "5.3")
    press(code, "_dedent")  # no selection: the current line
    assert code.get_source().splitlines()[4] == "y = 2"
    press(code, "_dedent")  # nothing left to remove
    assert code.get_source().splitlines()[4] == "y = 2"


def test_dedent_removes_partial_indentation_and_tabs(code):
    code.set_source("  a\n\tb\n      c\n")
    select(code, "1.0", "3.end")
    press(code, "_dedent")
    assert code.get_source() == "a\nb\n  c\n"


def test_tab_without_a_selection_goes_to_the_next_tab_stop(code):
    code.text.mark_set("insert", "1.2")
    press(code, "_tab")
    assert code.get_source().startswith("de  f f():")  # two spaces, to column 4
    select(code, "1.0", "1.2")  # part of one line: replaced, as in other editors
    press(code, "_tab")
    assert code.get_source().startswith("      f f():")  # four spaces from column 0, where "de" was


def test_backspace_in_indentation_goes_back_a_tab_stop(code):
    code.text.mark_set("insert", "5.8")
    assert press(code, "_backspace") == "break"
    assert code.get_source().splitlines()[4] == "    y = 2"
    code.text.mark_set("insert", "5.6")  # inside the text: an ordinary Backspace
    assert press(code, "_backspace") is None
    code.set_source("      z\n")
    code.text.mark_set("insert", "1.6")  # 6 spaces: back to column 4
    press(code, "_backspace")
    assert code.get_source() == "    z\n"


def test_the_keys_are_bound(code):
    bound = code.text.bind()
    assert "<Key-Tab>" in bound and "<Key-BackSpace>" in bound
    assert "<Shift-Key-Tab>" in bound or "<Key-ISO_Left_Tab>" in bound
