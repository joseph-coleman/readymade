"""Tools > Options: the code font, indent width and color theme, which are each person's own."""

import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

import pytest

from readymade import codegen, dialogs, usersettings
from readymade.ide import codeview, options, themes

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    yield app
    app.runner.stop()
    root.destroy()
    codeview.set_indent(4)  # the editor's indent is shared by every editor: put it back


def test_defaults_and_bad_values():
    assert (options.code_font(), options.indent_width(), options.theme()) == ("", 4, themes.LIGHT)
    usersettings.set("indent-width", 3)
    usersettings.set("theme", "purple")
    usersettings.set("code-font", "Mono, huge")
    assert (options.code_font(), options.indent_width(), options.theme()) == ("", 4, themes.LIGHT)


def test_the_options_dialog(app, monkeypatch):
    family = min(tkfont.families(app.root))  # one this system has
    dialog = options.OptionsDialog(app)
    monkeypatch.setattr(dialogs.FontChooser, "ask", classmethod(lambda cls, parent, font, title: f"{family}, 15"))
    dialog._choose_font()
    dialog.indent.set("2")
    dialog.theme.set("dark")
    dialog.ok()
    assert usersettings.get("code-font") == f"{family}, 15"
    assert (usersettings.get("indent-width"), usersettings.get("theme")) == (2, "dark")

    # The font: every place code shows changes at once.
    code_font = tkfont.nametofont(options.CODE_FONT, root=app.root)
    assert code_font.cget("family") == family and code_font.cget("size") == 15
    code = app.form.code
    assert str(code.text.cget("font")) == options.CODE_FONT
    assert str(app.immediate.output.cget("font")) == options.CODE_FONT

    # The theme: the open editor, and the Immediate, Help and Problems tabs.
    assert code.text.cget("background") == themes.DARK.background
    assert code.text.tag_cget("keyword", "foreground") == themes.DARK.tokens["keyword"]
    assert code.gutter.cget("background") == themes.DARK.gutter
    assert app.immediate.output.cget("background") == themes.DARK.background
    assert app.help.text.cget("background") == themes.DARK.background
    assert ttk.Style(app.root).lookup("Problems.Treeview", "background") == themes.DARK.background
    app.project.add_module("helpers")
    module = app.open_module("helpers")  # opened later: dark too
    assert module.code.text.cget("background") == themes.DARK.background

    # The indent: Tab in the editor goes two spaces; generated handlers still use four (PEP 8).
    module.code.text.delete("1.0", "end")
    module.code.text.mark_set("insert", "1.0")
    module.code.text.focus_force()
    app.root.update()
    module.code.text.event_generate("<Tab>")
    assert module.code.get_source().startswith("  ") and not module.code.get_source().startswith("   ")
    assert codegen.INDENT == "    "


def test_dark_is_the_whole_ide_except_the_form(app):
    app.form.add_control("ComboBox", 16, 16)
    light_ttk = ttk.Style(app.root).theme_use()
    def padding(style):  # the same sizes come back as text or as a tuple, by theme
        value = style.lookup("TNotebook.Tab", "padding")
        return " ".join(map(str, value)) if isinstance(value, tuple) else str(value)

    light_tab_padding = padding(ttk.Style(app.root))
    usersettings.set("theme", "dark")
    options.apply(app)
    style = ttk.Style(app.root)
    chrome = themes.DARK.chrome
    assert style.theme_use() == options.DARK_TTK
    assert style.lookup(".", "background") == chrome.window and app.root.cget("background") == chrome.window
    assert style.lookup("Treeview", "background") == chrome.field  # the Project Explorer
    assert padding(style) == light_tab_padding  # the light theme's sizes carry over
    button = next(w for w in app.toolbox.winfo_children() if isinstance(w, tk.Radiobutton))
    assert button.cget("background") == chrome.button
    assert app.form.surface.cget("background") == chrome.workspace
    assert app.properties._scroller.cget("background") == chrome.window
    assert style.lookup("Note.TLabel", "foreground") == chrome.note
    # The form being designed keeps the program's look: its ComboBox is in the light preview style.
    combo = app.form.surface.controls["ComboBox1"].widget
    assert combo.cget("style") == "Preview.TCombobox"
    assert style.lookup("Preview.TCombobox", "fieldbackground") != chrome.field

    usersettings.set("theme", "light")
    options.apply(app)
    assert ttk.Style(app.root).theme_use() == light_ttk
    assert button.cget("background") != chrome.button
    assert app.form.surface.cget("background") != chrome.workspace


def test_cancel_changes_nothing(app):
    dialog = options.OptionsDialog(app)
    dialog.theme.set("dark")
    dialog.indent.set("8")
    dialog.destroy()  # Cancel
    assert usersettings.get("theme") is None and codeview.INDENT == "    "
    assert app.form.code.text.cget("background") == themes.LIGHT.background


def test_usual_font_and_starting_with_saved_options(tmp_path):
    from readymade.ide.app import App

    usersettings.set("theme", "dark")
    usersettings.set("indent-width", 8)
    root = tk.Tk()
    try:
        app = App(root, tmp_path / "Shop")  # starts with the saved options
        assert app.form.code.text.cget("background") == themes.DARK.background
        assert codeview.INDENT == " " * 8
        dialog = options.OptionsDialog(app)
        dialog.font.set("Something, 30")
        dialog.font.set("")  # the Usual button
        dialog.ok()
        usual = tkfont.nametofont("TkFixedFont", root=root).actual()
        assert tkfont.nametofont(options.CODE_FONT, root=root).actual("size") == usual["size"]
        app.runner.stop()
    finally:
        root.destroy()
        codeview.set_indent(4)


def test_tools_menu_opens_options(app):
    bar = app.root.nametowidget(app.root["menu"])
    tools = next(bar.nametowidget(bar.entrycget(i, "menu")) for i in range(bar.index("end") + 1)
                 if bar.type(i) == "cascade" and bar.entrycget(i, "label") == "Tools")
    tools.invoke("Options...")
    app.root.update_idletasks()
    dialogs_open = [w for w in app.root.winfo_children() if isinstance(w, options.OptionsDialog)]
    assert len(dialogs_open) == 1
    dialogs_open[0].destroy()
