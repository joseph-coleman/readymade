"""Menus: the text and shortcut formats, the .form file, and menus at runtime."""

import time
import tkinter as tk

import pytest

from readymade import Form, formfile, menus
from readymade.menus import KEYS, names, normalize_shortcut, parse_text, shortcut_sequence

MENU = [
    {"name": "mnuFile", "text": "&File", "items": [
        {"name": "mnuOpen", "text": "&Open...", "shortcut": "Ctrl+O"},
        {"text": "-"},
        {"name": "mnuRecent", "text": "&Recent", "items": [{"name": "mnuRecent1", "text": "notes.txt"}]},
        {"name": "mnuExit", "text": "E&xit"},
    ]},
    {"name": "mnuView", "text": "&View", "items": [
        {"name": "mnuWrap", "text": "&Word Wrap", "checked": True},
        {"name": "mnuZoom", "text": "Zoom", "shortcut": "Ctrl+Shift+Z", "enabled": False},
    ]},
]


@pytest.mark.parametrize("text, expected", [
    ("&File", ("File", 0)), ("E&xit", ("Exit", 1)), ("Save && Exit", ("Save & Exit", -1)),
    ("&Save && E&xit", ("Save & Exit", 0)), ("Plain", ("Plain", -1)),
])
def test_parse_text(text, expected):
    assert parse_text(text) == expected


@pytest.mark.parametrize("shortcut, sequence", [
    ("Ctrl+S", "<Control-KeyPress-s>"), ("Ctrl+Shift+S", "<Control-KeyPress-S>"), ("F5", "<KeyPress-F5>"),
    ("Shift+F5", "<Shift-KeyPress-F5>"), ("Ctrl+1", "<Control-KeyPress-1>"), ("Del", "<KeyPress-Delete>"),
    ("Alt+Enter", "<Alt-KeyPress-Return>"), ("ctrl + o", "<Control-KeyPress-o>"),
    ("Ctrl+,", "<Control-KeyPress-comma>"), ("Ctrl+Alt+Del", "<Control-Alt-KeyPress-Delete>"),
    ("Ctrl+PgDn", "<Control-KeyPress-Next>"), ("Shift+Up", "<Shift-KeyPress-Up>"), ("Ctrl+Shift+F12", "<Control-Shift-KeyPress-F12>"),
])
def test_shortcut_sequence(shortcut, sequence):
    assert shortcut_sequence(shortcut) == sequence


@pytest.mark.parametrize("shortcut, message", [
    ("Ctrl+", "isn't a shortcut"), ("Hyper+S", "isn't a shortcut"), ("Ctrl+Banana", "isn't a shortcut"), ("", "isn't a shortcut"),
    ("S", "needs Ctrl or Alt"), ("Shift+S", "needs Ctrl or Alt"), ("/", "needs Ctrl or Alt"),
    ("Ctrl+Shift+1", "Shift changes which key"), ("Alt+Shift+,", "Shift changes which key"),
])
def test_bad_shortcuts(shortcut, message):
    with pytest.raises(ValueError, match=message):
        shortcut_sequence(shortcut)


@pytest.mark.parametrize("written, normal", [
    ("ctrl + shift + s", "Ctrl+Shift+S"), ("shift+ctrl+f5", "Ctrl+Shift+F5"), ("Control+o", "Ctrl+O"),
    ("delete", "Del"), ("Ctrl+PageUp", "Ctrl+PgUp"), ("alt+escape", "Alt+Esc"), ("Ctrl+\\", "Ctrl+\\"),
])
def test_normalize_shortcut(written, normal):
    assert normalize_shortcut(written) == normal


def test_every_listed_key_works_with_ctrl():
    assert len(KEYS) == len(set(KEYS)) == 26 + 10 + 24 + 15 + 11
    for key in KEYS:
        assert normalize_shortcut(f"Ctrl+{key}") == f"Ctrl+{key}"
        shortcut_sequence(f"Ctrl+{key}")


def test_menu_in_the_form_file():
    plain = formfile.FormDesign()
    assert "menu" not in formfile.dumps(plain)  # forms without menus don't change
    design = formfile.FormDesign(menu=MENU)
    loaded = formfile.loads(formfile.dumps(design))
    assert loaded.menu == MENU
    assert names(loaded.menu) == ["mnuFile", "mnuOpen", "mnuRecent", "mnuRecent1", "mnuExit", "mnuView", "mnuWrap", "mnuZoom"]


@pytest.mark.parametrize("menu, message", [
    ([{"name": "Label1", "text": "x"}], "more than one"),
    ([{"text": "Open"}], "needs a 'name'"),
    ([{"name": "a", "text": "A", "items": [{"name": "a", "text": "again"}]}], "more than one"),
])
def test_bad_menus(menu, message):
    design = formfile.FormDesign(controls=[{"type": "Label", "name": "Label1", "left": 0, "top": 0}], menu=menu)
    with pytest.raises(formfile.FormFileError, match=message):
        formfile.loads(formfile.dumps(design))


@pytest.mark.usefixtures("display")
def test_menus_at_runtime(tmp_path):
    calls = []

    class Form1(Form):
        def mnuOpen_click(self):
            calls.append("open")

        def mnuWrap_click(self):
            calls.append(("wrap", self.mnuWrap.checked))
            self.mnuWrap.checked = not self.mnuWrap.checked

        def mnuZoom_click(self):
            calls.append("zoom")

    formfile.save(formfile.FormDesign(name="Form1", menu=MENU), tmp_path / "Form1.form")
    form = Form1(tmp_path / "Form1.form")
    try:
        form.show()
        menubar = form.root.nametowidget(form.root["menu"])
        assert [menubar.entrycget(i, "label") for i in range(2)] == ["File", "View"]
        assert menubar.entrycget(0, "underline") == 0
        file_menu = menubar.nametowidget(menubar.entrycget(0, "menu"))
        assert file_menu.entrycget(0, "accelerator") == "Ctrl+O"
        assert file_menu.type(1) == "separator"

        file_menu.invoke(0)
        assert calls == []  # menu commands run once the menu has closed (see menus.later)
        form.root.update_idletasks()
        assert calls == ["open"]
        # Clicking doesn't toggle the check mark by itself, as in VB; the handler does it.
        view_menu = menubar.nametowidget(menubar.entrycget(1, "menu"))
        view_menu.invoke(0)
        form.root.update_idletasks()
        assert calls[-1] == ("wrap", True) and form.mnuWrap.checked is False
        view_menu.invoke(1)  # disabled
        form.root.update_idletasks()
        assert calls[-1] != "zoom" and form.mnuZoom.enabled is False

        form.mnuZoom.enabled = True
        form.mnuOpen.text = "&Open File..."
        assert file_menu.entrycget(0, "label") == "Open File..."
        assert set(form.menus) >= {"mnuFile", "mnuRecent1", "mnuZoom"}

        # Shortcuts work anywhere in the form.
        form.root.focus_force()
        for sequence in ("<Control-KeyPress-o>", "<Control-KeyPress-Z>"):
            form.root.event_generate(sequence)
        end = time.time() + 1
        while len(calls) < 4 and time.time() < end:
            form.root.update()
        assert calls[-2:] == ["open", "zoom"]
    finally:
        form.root.destroy()


def test_defer_commands_runs_them_after_the_menu_closes():
    """On macOS a dialog opened from inside a menu bar command freezes unpainted, so menu
    commands run just after: from an idle callback, once the menu has closed."""
    root = tk.Tk()
    try:
        ran = []
        bar = tk.Menu(root)
        file_menu = tk.Menu(bar, tearoff=False)
        recent = tk.Menu(file_menu, tearoff=False)
        recent.add_command(label="a.txt", command=lambda: ran.append("a.txt"))
        file_menu.add_command(label="Open", command=lambda: ran.append("open"))
        file_menu.add_cascade(label="Recent", menu=recent)
        file_menu.add_separator()
        wrap = tk.BooleanVar(root, False)
        file_menu.add_checkbutton(label="Wrap", variable=wrap, command=lambda: ran.append(("wrap", wrap.get())))
        bar.add_cascade(label="File", menu=file_menu)
        menus.defer_commands(bar)
        for menu, index in ((file_menu, 0), (recent, 0), (file_menu, 3)):
            menu.invoke(index)
        assert ran == []  # nothing yet: the menu is still "open"
        root.update_idletasks()
        assert ran == ["open", "a.txt", ("wrap", True)]
    finally:
        root.destroy()


@pytest.mark.usefixtures("display")
def test_every_ide_menu_command_is_deferred(tmp_path, monkeypatch):
    from tkinter import simpledialog

    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    try:
        asked = []
        monkeypatch.setattr(simpledialog, "askstring", lambda *a, **kw: asked.append(a[0]))
        bar = root.nametowidget(root["menu"])
        project_menu = next(bar.nametowidget(bar.entrycget(i, "menu")) for i in range(bar.index("end") + 1)
                            if bar.type(i) == "cascade" and bar.entrycget(i, "label") == "Project")
        project_menu.invoke("Add Form...")
        assert asked == []  # the dialog waits for the menu to close
        root.update_idletasks()
        assert asked == ["Add Form"]
        explorer = app.explorer.libraries_menu
        explorer.invoke("Add Library...")
        root.update_idletasks()
        assert asked == ["Add Form", "Add Library"]
    finally:
        app.stop()
        root.destroy()


def test_context_clicks():
    class FakeTk:
        def __init__(self, system):
            self.system = system

        def call(self, *args):
            assert args == ("tk", "windowingsystem")
            return self.system

    class Widget:
        def __init__(self, system):
            self.tk = FakeTk(system)

    # On a Mac, Tk 8.6 calls the right button 2 (Tk 9: 3), and Control+click is a right click too.
    assert menus.context_clicks(Widget("aqua")) == ("<Button-2>", "<Button-3>", "<Control-Button-1>")
    # Elsewhere button 2 is the middle button.
    assert menus.context_clicks(Widget("x11")) == menus.context_clicks(Widget("win32")) == ("<Button-3>",)


@pytest.mark.usefixtures("display")
def test_project_explorer_opens_its_menu_on_a_right_click(tmp_path, monkeypatch):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    try:
        tree = app.explorer.tree
        assert tree.bind("<Button-3>") and not tree.bind("<Button-2>")  # this isn't a Mac
        shown = []
        monkeypatch.setattr(tk.Menu, "tk_popup", lambda menu, x, y, entry="": shown.append(menu))
        root.update()
        x, y, w, h = tree.bbox("form:Form1")
        tree.event_generate("<Button-3>", x=x + 5, y=y + h // 2)
        assert shown == [app.explorer.menu] and tree.focus() == "form:Form1"
    finally:
        app.stop()
        root.destroy()


# ----- shortcuts on each system: on a Mac, Ctrl is ⌘ and Alt is Option -----

@pytest.mark.parametrize("shortcut, linux, mac", [
    ("Ctrl+S", "<Control-KeyPress-s>", "<Command-KeyPress-s>"),
    ("Ctrl+Shift+Z", "<Control-KeyPress-Z>", "<Command-KeyPress-Z>"),
    ("Ctrl+/", "<Control-KeyPress-slash>", "<Command-KeyPress-slash>"),
    ("Shift+F7", "<Shift-KeyPress-F7>", "<Shift-KeyPress-F7>"),
    ("F5", "<KeyPress-F5>", "<KeyPress-F5>"),
])
def test_shortcut_sequences(shortcut, linux, mac):
    assert shortcut_sequence(shortcut, platform="linux") == shortcut_sequence(shortcut, platform="win32") == linux
    assert shortcut_sequence(shortcut, platform="darwin") == mac


@pytest.mark.parametrize("shortcut, linux, mac_label, mac_text", [
    # Tk on a Mac draws "Command-S" as ⌘S, "Shift-Command-Z" as ⇧⌘Z (checked on a real Mac).
    ("Ctrl+S", "Ctrl+S", "Command-S", "⌘S"),
    ("Ctrl+Shift+Z", "Ctrl+Shift+Z", "Shift-Command-Z", "⇧⌘Z"),
    ("Shift+Alt+F", "Alt+Shift+F", "Option-Shift-F", "⌥⇧F"),
    ("Ctrl+/", "Ctrl+/", "Command-/", "⌘/"),
    ("F5", "F5", "F5", "F5"),
])
def test_how_shortcuts_are_shown(shortcut, linux, mac_label, mac_text):
    assert menus.accelerator(shortcut, platform="linux") == linux
    assert menus.accelerator(shortcut, platform="darwin") == mac_label
    assert menus.display(shortcut, platform="darwin") == mac_text
    assert menus.display(shortcut, platform="win32") == linux


def test_modifier_names_and_masks():
    assert menus.tk_modifier("Ctrl", "darwin") == "Command" and menus.tk_modifier("Ctrl", "linux") == "Control"
    assert menus.tk_modifier("Alt", "darwin") == "Option" and menus.tk_modifier("Alt", "win32") == "Alt"
    assert menus.primary_mask("darwin") == 0x8 and menus.primary_mask("linux") == 0x4
    assert menus.modifier_label("Ctrl", "darwin") == "Ctrl (⌘)" and menus.modifier_label("Ctrl", "linux") == "Ctrl"


@pytest.mark.usefixtures("display")
def test_bind_shortcut():
    root = tk.Tk()
    try:
        fired = []
        entry = tk.Entry(root)
        entry.pack()
        root.update()
        menus.bind_shortcut(root, "Ctrl+S", lambda e: fired.append("save"), platform="linux")
        # On a Mac, Option+Shift+F types "Ï", so Alt shortcuts go by the key's position (F is 3).
        menus.bind_shortcut(root, "Shift+Alt+F", lambda e: fired.append("format"), platform="darwin")
        entry.focus_force()
        root.update()
        entry.event_generate("<Control-KeyPress-s>")
        entry.event_generate("<KeyPress>", keysym="Idiaeresis", keycode=(3 << 24) | 0xCF, state=0x11)
        entry.event_generate("<KeyPress>", keysym="ssharp", keycode=(1 << 24) | 0xDF, state=0x11)  # another key
        entry.event_generate("<KeyPress>", keysym="Idiaeresis", keycode=(3 << 24) | 0xCF, state=0x19)  # with ⌘ too
        root.update()
        assert fired == ["save", "format"]
    finally:
        root.destroy()


def test_help_overview_on_a_mac():
    from readymade.ide import helptext

    mac, linux = helptext.home("darwin").text, helptext.home("linux").text
    assert "⌘-click goes to a definition" in mac and "⌃Space completes a name" in mac
    assert "⌘Z / ⇧⌘Z undo and redo" in mac and "⌥⇧F formats the code" in mac
    assert "Ctrl+click goes to a definition" in linux and "Ctrl+Z / Ctrl+Y undo and redo" in linux
