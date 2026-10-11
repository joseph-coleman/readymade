"""Find and Replace in the code window, and Find in Files."""

import tkinter as tk

import pytest

from readymade.ide.find import OPTIONS, compile_search, matches

pytestmark = pytest.mark.usefixtures("display")

CODE = """def total(prices):
    count = 0
    for price in prices:
        count += price
    return count  # Count it
"""


def test_searches():
    found = matches(compile_search("count"), CODE)
    assert len(found) == 4 and CODE[found[-1][0]:found[-1][1]] == "Count"  # (any case, to start with)
    assert len(matches(compile_search("count", case=True), CODE)) == 3
    assert len(matches(compile_search("price", word=True), CODE)) == 2  # not "prices"
    assert len(matches(compile_search(r"pric\w+", regex=True), CODE)) == 4
    assert compile_search("") is None
    with pytest.raises(Exception):
        compile_search("(", regex=True)
    assert len(matches(compile_search("(", regex=False), CODE)) == 1  # plain text: ( is just (


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    app.project.add_module("tools")
    module = app.open_module("tools")
    module.code.set_source(CODE)
    yield app, module.code
    app.runner.stop()
    root.destroy()


def test_the_find_bar(app):
    app, code = app
    code.text.mark_set("insert", "1.0")
    app.find()  # Ctrl+F
    bar = code.find_bar
    bar.find.set("count")
    assert bar.count.cget("text") == "1 of 4" and code.text.get("sel.first", "sel.last") == "count"
    assert len(code.text.tag_ranges("found")) == 8  # every match marked
    app.find_next(1)  # F3
    assert bar.count.cget("text") == "2 of 4" and str(code.text.index("sel.first")) == "4.8"
    app.find_next(-1)  # Shift+F3
    app.find_next(-1)  # around to the last
    assert bar.count.cget("text") == "4 of 4"
    bar.case.set(True)
    bar.search()
    assert bar.count.cget("text").endswith("3")
    bar.find.set("nothing like it")
    assert bar.count.cget("text") == "No results"
    bar.regex.set(True)
    bar.find.set("(")
    assert bar.count.cget("text").startswith("Can't read that")
    bar.close()
    assert not code.text.tag_ranges("found") and not bar.is_open()


def test_replacing(app):
    app, code = app
    code.text.mark_set("insert", "1.0")
    app.find(replace=True)  # Ctrl+H
    bar = code.find_bar
    assert bar.replace_row.winfo_manager() == "pack"
    bar.case.set(True)
    bar.find.set("count")
    bar.replace.set("total")
    bar.replace_one()  # the first, then on to the next
    assert code.get_source().count("total") == 2 and bar.count.cget("text") == "1 of 2"
    bar.replace_all()
    assert bar.count.cget("text") == "Replaced 2" and "count" not in code.get_source() and "Count it" in code.get_source()
    code.text.edit_undo()  # Replace All is one undo step
    assert code.get_source().count("count") == 2
    bar.regex.set(True)
    bar.find.set(r"for (\w+) in (\w+)")
    bar.replace.set(r"for \2 in \1")
    bar.replace_all()
    assert "for prices in price:" in code.get_source()


def test_find_in_files(app):
    app, code = app
    folder = app.project.folder
    (folder / "README.md").write_text("Count the prices.\n")
    (folder / "data").mkdir()
    (folder / "data" / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n\0count")
    code.text.insert("1.0", "# count me too (unsaved)\n")
    app.find_in_files()
    panel = app.find_panel
    assert app.bottom.select() == str(panel)
    panel.find.set("count")
    panel.search()
    tree = panel.tree
    files = {tree.item(row, "text"): len(tree.get_children(row)) for row in tree.get_children()}
    assert files == {"README.md": 1, "tools.py": 5}  # the open file as it is in its tab; no pictures
    assert panel.status.cget("text") == "6 in 2 files"
    readme = tree.get_children(tree.get_children()[0])[0]
    panel._open(readme)
    editor = app.current_editor()
    assert editor.path == folder / "README.md" and editor.code.text.get("sel.first", "sel.last") == "Count"


def test_line_starts_and_ends():
    assert len(matches(compile_search(r"^\s+return", regex=True), CODE)) == 1  # ^: each line's start
    assert len(matches(compile_search(r"prices\):$", regex=True), CODE)) == 1


def test_the_buttons_say_what_they_do(app):
    from readymade.ide import helptext, tooltips

    app, code = app
    app.find()
    bar = code.find_bar
    assert [tooltips.text_of(box) for box in bar.option_boxes] == [said for _, said in OPTIONS]
    assert "Match case" in tooltips.text_of(bar.option_boxes[0])
    assert all(tooltips.text_of(box) for box in app.find_panel.option_boxes)
    bar.find_entry.focus_force()
    app.root.update()
    app.show_help()  # F1 in the find bar: help on finding
    assert app.help.title.cget("text") == "Find and Replace"
    assert "Whole word" in helptext.finding().text
