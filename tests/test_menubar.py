"""The IDE's menu bar and shortcuts, made from one table (readymade.ide.menubar)."""

import importlib
import sys
import tkinter as tk

import pytest

from readymade import menus
from readymade.ide import menubar


@pytest.fixture
def table_for(monkeypatch):
    """The table as it's made on another system (the keys differ on a Mac)."""
    def make(platform):
        monkeypatch.setattr(sys, "platform", platform)
        return importlib.reload(menubar)

    yield make
    monkeypatch.undo()
    importlib.reload(menubar)


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_no_key_does_two_things(table_for, platform):
    table = table_for(platform)
    twice = {key: [item.label for item in items] for key, items in table.bound_keys().items() if len(items) > 1}
    assert twice == {}
    for key in table.bound_keys():
        menus.shortcut_sequence(key, platform)  # (a real shortcut, or ValueError)


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_every_key_shown_works(table_for, platform):
    table = table_for(platform)
    shown = {item.key for item in table.walk() if getattr(item, "key", "")}
    # Del and Ctrl+/ are the code editor's and the designer's own keys; the rest are bound by the table.
    assert shown - set(table.bound_keys()) == {"Del", "Ctrl+/"}
    labels = [item.label for item in table.walk()]
    assert len(labels) == len(set(labels)) + 1  # (only "Make Equal" twice: Horizontal and Vertical Spacing)


@pytest.mark.parametrize("platform", ["win32", "linux", "darwin"])
def test_each_systems_usual_keys_work_everywhere(table_for, platform):
    """Step Into, Redo and Find Next show each system's usual key, and the others' work too."""
    table = table_for(platform)
    assert {"F11", "Ctrl+F11", "Ctrl+Y", "Ctrl+Shift+Z", "F3", "Shift+F3"} <= set(table.bound_keys())
    step_into = next(item for item in table.walk() if item.label == "Step Into")
    assert step_into.key == ("Ctrl+F11" if platform == "darwin" else "F11")  # (macOS keeps F11 for Show Desktop)


@pytest.mark.usefixtures("display")
def test_the_menus_and_keys_are_made_from_it(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    try:
        bar = root.nametowidget(root["menu"])
        menus_by_label = {bar.entrycget(i, "label"): bar.nametowidget(bar.entrycget(i, "menu"))
                          for i in range(bar.index("end") + 1) if bar.type(i) == "cascade"}
        assert list(menus_by_label) == [m.label for m in menubar.MENUS]
        file_menu = menus_by_label["File"]
        assert file_menu.entrycget(2, "label") == "Save All"
        assert file_menu.entrycget(2, "accelerator") == menus.accelerator("Ctrl+S")
        for key in menubar.bound_keys():  # each bound on the window, and not also in the code
            assert root.bind(menus.shortcut_sequence(key))
            assert menus.shortcut_sequence(key) not in app.form.code.text.bind()

        def states(menu):
            menu.tk.eval(menu.cget("postcommand"))  # as when it opens
            return {menu.entrycget(i, "label"): str(menu.entrycget(i, "state")) for i in range(menu.index("end") + 1)
                    if menu.type(i) != "separator"}

        edit, debug, format_menu = menus_by_label["Edit"], menus_by_label["Debug"], menus_by_label["Format"]
        form = app.form
        form.show_design()
        assert states(edit)["Toggle Comment"] == "disabled" and states(edit)["Cut"] == "disabled"
        assert states(format_menu)["Align"] == "disabled" and states(format_menu)["Tab Order"] == "normal"
        form.add_control("Button", 8, 8)
        assert states(edit)["Cut"] == "normal" and states(edit)["Undo"] == "normal"
        assert states(format_menu)["Align"] == "normal" and states(format_menu)["Make Same Size"] == "disabled"
        form.show_code()
        assert states(edit)["Toggle Comment"] == "normal" and states(format_menu)["Tab Order"] == "disabled"
        debug_states = states(debug)
        assert debug_states["Continue"] == debug_states["Step Out"] == debug_states["Pause"] == "disabled"
        assert debug_states["Step Over"] == "normal"  # (with nothing running, F10 starts it)
    finally:
        app.runner.stop()
        root.destroy()


@pytest.mark.usefixtures("display")
def test_checks_show_their_state(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    try:
        bar = root.nametowidget(root["menu"])
        format_menu = next(bar.nametowidget(bar.entrycget(i, "menu")) for i in range(bar.index("end") + 1)
                           if bar.type(i) == "cascade" and bar.entrycget(i, "label") == "Format")
        tab_order = format_menu.index("Tab Order")
        variable = format_menu.entrycget(tab_order, "variable")
        app.form.add_control("Button", 8, 8)
        app.form.show_design()
        app.toggle_tab_order()
        format_menu.tk.eval(format_menu.cget("postcommand"))
        assert root.getvar(variable) in (1, True, "1")
        app.toggle_tab_order()
        format_menu.tk.eval(format_menu.cget("postcommand"))
        assert root.getvar(variable) in (0, False, "0")
    finally:
        app.runner.stop()
        root.destroy()
