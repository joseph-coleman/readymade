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


def numbers(code):
    code.update()
    items = code.gutter.find_all()
    return [code.gutter.itemcget(i, "text") for i in items], {code.gutter.itemcget(i, "text"): code.gutter.itemcget(i, "fill") for i in items}


def test_line_numbers_follow_the_code(code):
    shown, colors = numbers(code)
    assert shown == ["1", "2", "3", "4", "5", "6"]  # SOURCE's five lines, and the empty one after its last newline
    code.text.mark_set("insert", "4.0")
    code.text.event_generate("<KeyRelease>")
    _, colors = numbers(code)
    assert colors["4"] != colors["1"]  # the current line's number stands out

    code.text.insert("1.0", "import os\n" * 200)
    shown, _ = numbers(code)
    assert shown[0] == "1" and shown[-1] != "206"  # only the lines in view
    wide = int(code.gutter.cget("width"))
    code.text.yview_moveto(1.0)
    shown, _ = numbers(code)
    assert shown[-1] == "206" and shown[0] != "1"  # scrolling moves them
    code.set_source("x = 1\n")
    numbers(code)
    assert int(code.gutter.cget("width")) < wide  # narrower again with fewer digits


def test_toggle_comment(code):
    select(code, "4.0", "5.end")  # "    if x:" and "        y = 2"
    assert code.toggle_comment() == "break"
    assert code.get_source().splitlines()[3:] == ["    # if x:", "    #     y = 2"]  # lined up at the shallowest indent
    assert code.text.get("sel.first", "sel.last") == "    # if x:\n    #     y = 2\n"
    code.toggle_comment()
    assert code.get_source() == SOURCE
    code.toggle_comment()
    code.text.edit_undo()
    assert code.get_source() == SOURCE  # one undo step


def test_toggle_comment_on_mixed_and_blank_lines(code):
    code.set_source("a = 1\n\n# b = 2\n#c = 3\n")
    select(code, "1.0", "4.end")
    code.toggle_comment()  # not all commented: comment them all
    assert code.get_source() == "# a = 1\n\n# # b = 2\n# #c = 3\n"
    code.set_source("# a = 1\n\n# b = 2\n#c = 3\n")
    select(code, "1.0", "4.end")
    code.toggle_comment()  # all commented: uncomment ("# " or just "#")
    assert code.get_source() == "a = 1\n\nb = 2\nc = 3\n"
    code.text.tag_remove("sel", "1.0", "end")
    code.text.mark_set("insert", "3.2")
    code.toggle_comment()  # no selection: the current line
    assert code.get_source().splitlines()[2] == "# b = 2"
    assert "<Control-Key-slash>" in code.text.bind()


def type_text(code, text):
    """Type into the code window as a person would, through its key bindings."""
    keysyms = {"(": "parenleft", ")": "parenright", "[": "bracketleft", "]": "bracketright", "{": "braceleft",
               "}": "braceright", '"': "quotedbl", "'": "apostrophe", " ": "space", "=": "equal", ",": "comma",
               ".": "period", ":": "colon", "#": "numbersign", "\n": "Return"}
    code.text.focus_force()
    code.update()
    for char in text:
        code.text.event_generate(f"<KeyPress-{keysyms.get(char, char)}>")
    code.update()


def typed(code, text, start=""):
    code.set_source(start)
    code.text.mark_set("insert", "end-1c")
    type_text(code, text)
    return code.get_source(), code.text.index("insert")


def test_brackets_close_themselves_and_are_stepped_over(code):
    assert typed(code, "print(") == ("print()", "1.6")  # the cursor between the pair
    assert typed(code, "print(x)") == ("print(x)", "1.8")  # typing ) steps over the one the editor added
    assert typed(code, "f(g(1))") == ("f(g(1))", "1.7")
    assert typed(code, "d = {a[0]}") == ("d = {a[0]}", "1.10")


def test_brackets_dont_close_before_a_word(code):
    code.set_source("value")
    code.text.mark_set("insert", "1.0")
    type_text(code, "(")
    assert code.get_source() == "(value"


def test_a_closer_you_typed_isnt_stepped_over(code):
    code.set_source("()")
    code.text.mark_set("insert", "1.1")
    type_text(code, ")")
    assert code.get_source() == "())"


def test_quotes(code):
    assert typed(code, 'x = "hi"') == ('x = "hi"', "1.8")
    assert typed(code, "# don't") == ("# don't", "1.7")  # no pair after a letter
    assert typed(code, 'f"{x}"')[0] == 'f"{x}"'  # string prefixes still pair up
    assert typed(code, 'rb"')[0] == 'rb""'
    assert typed(code, '"""') == ('""""""', "1.3")  # a docstring: """|"""


def test_backspace_removes_a_pair_the_editor_made(code):
    typed(code, "print(")
    code._backspace(None)
    assert code.get_source() == "print"
    typed(code, 'x = "')
    code._backspace(None)
    assert code.get_source() == "x = "
    code.set_source("()")  # typed by hand: Backspace removes just the opener
    code.text.mark_set("insert", "1.1")
    assert code._backspace(None) is None


def test_typing_a_bracket_or_quote_wraps_the_selection(code):
    code.set_source("x = name\ny = other\n")
    select(code, "1.4", "1.8")
    type_text(code, "(")
    assert code.get_source().splitlines()[0] == "x = (name)" and code.text.get("sel.first", "sel.last") == "name"
    select(code, "1.4", "2.5")  # across lines
    type_text(code, '"')
    assert code.get_source() == 'x = "(name)\ny = o"ther\n'
    assert code.text.get("sel.first", "sel.last") == "(name)\ny = o"
    code.text.edit_undo()
    assert code.get_source() == "x = (name)\ny = other\n"  # each wrap is one undo step


def test_moving_away_forgets_which_closers_were_added(code):
    typed(code, "print(")
    code.text.event_generate("<ButtonRelease-1>")
    code.update()
    type_text(code, ")")
    assert code.get_source() == "print())"


def enter_at_end(code, source):
    """Press Enter at the end of source; return the new line's text before the cursor, and the whole text."""
    code.set_source(source)
    code.text.mark_set("insert", "end-1c")
    type_text(code, "\n")
    return code.text.get("insert linestart", "insert"), code.get_source()


@pytest.mark.parametrize("source, indent", [
    ("    x = 1", "    "),                      # keeps the indentation
    ("def f(x):", "    "),                      # a block starts
    ("    if x:  # the usual case", "        "),  # a comment after the colon
    ("x = 1  # note:", ""),                     # a colon in a comment isn't a block
    ('s = "if x:"', ""),                        # nor is one in a string
    ("        return x", "    "),              # the block is done
    ("        pass", "    "),
    ("    raise ValueError(x)", ""),
    ("        return_value = 1", "        "),  # only the keyword itself
    ("result = compute(a,", " " * 17),          # line up after the open bracket
    ("    items = [", "        "),               # a bracket ending the line: one level in
    ('print("(")', ""),                         # a bracket in a string doesn't count
])
def test_enter_indents_to_suit(code, source, indent):
    assert enter_at_end(code, source)[0] == indent


def test_enter_between_a_pair_opens_it_up(code):
    code.set_source("    x = ")
    code.text.mark_set("insert", "end-1c")
    type_text(code, "[\n")
    assert code.get_source() == "    x = [\n        \n    ]"
    assert code.text.index("insert") == "2.8"  # on the indented line between
    code.text.edit_undo()
    assert code.get_source() == "    x = []"  # one undo step


def test_enter_tidies_whitespace(code):
    code.set_source("    \n")
    code.text.mark_set("insert", "1.4")
    type_text(code, "\n")
    assert code.get_source() == "\n    \n"  # the line of only spaces is left empty
    code.set_source("    a = 1;    b = 2")
    code.text.mark_set("insert", "1.10")
    type_text(code, "\n")
    assert code.get_source() == "    a = 1;\n    b = 2"  # the rest starts at the indent


def test_replacing_all_the_code_is_one_undo_step(code):
    code.replace_source("something else\n")
    code.text.edit_undo()
    assert code.get_source() == SOURCE
