"""Menus: the text and shortcut formats, the .form file, and menus at runtime."""

import time

import pytest

from readymade import Form, formfile
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
        assert calls == ["open"]
        # Clicking doesn't toggle the check mark by itself, as in VB; the handler does it.
        view_menu = menubar.nametowidget(menubar.entrycget(1, "menu"))
        view_menu.invoke(0)
        assert calls[-1] == ("wrap", True) and form.mnuWrap.checked is False
        view_menu.invoke(1)  # disabled
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
