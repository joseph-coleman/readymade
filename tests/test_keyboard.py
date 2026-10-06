"""Key names for keypress, Tab order, and Enter and Esc pressing a form's default and cancel buttons."""

import tkinter as tk

import pytest

from pybasic import Form, formfile, keys
from pybasic.controls import REGISTRY
from pybasic.form import FORM

pytestmark = pytest.mark.usefixtures("display")

SHIFT, CTRL, ALT, NUMLOCK = 0x1, 0x4, 0x8, 0x10  # X11's state bits


# ----- key names -----

@pytest.mark.parametrize("char, keysym, state, expected", [
    ("a", "a", 0, "a"),
    ("A", "A", SHIFT, "A"),
    ("!", "exclam", SHIFT, "!"),
    (" ", "space", 0, " "),
    ("7", "KP_7", NUMLOCK, "7"),
    ("\r", "Return", 0, "Enter"),
    ("\r", "KP_Enter", 0, "Enter"),
    ("\x1b", "Escape", 0, "Esc"),
    ("\t", "Tab", 0, "Tab"),
    ("", "ISO_Left_Tab", SHIFT, "Shift+Tab"),
    ("\x08", "BackSpace", 0, "Backspace"),
    ("\x7f", "Delete", 0, "Del"),
    ("", "Prior", 0, "PgUp"),
    ("", "Next", 0, "PgDn"),
    ("", "Left", SHIFT, "Shift+Left"),
    ("", "F1", 0, "F1"),
    ("", "F4", ALT, "Alt+F4"),
    ("\x13", "s", CTRL, "Ctrl+S"),
    ("\x1a", "Z", CTRL | SHIFT, "Ctrl+Shift+Z"),
    ("s", "s", ALT, "Alt+S"),
    ("", "comma", CTRL, "Ctrl+,"),
    ("\x00", "space", CTRL, "Ctrl+Space"),
    ("", "Shift_L", 0, "Shift"),
    ("", "Control_R", CTRL, "Ctrl"),
    ("", "Caps_Lock", 0, "CapsLock"),
])
def test_key_names(char, keysym, state, expected):
    assert keys.name(char, keysym, state, platform="linux") == expected


def test_altgr_on_windows_types_characters():
    win_ctrl, win_alt = 0x4, 0x20000
    assert keys.name("@", "q", win_ctrl | win_alt, platform="win32") == "@"  # AltGr is Ctrl+Alt on Windows
    assert keys.name("\x13", "s", win_ctrl, platform="win32") == "Ctrl+S"
    assert keys.name("s", "s", win_alt, platform="win32") == "Alt+S"


MAC_CONTROL, COMMAND, OPTION = 0x4, 0x8, 0x10  # Tk's state bits on macOS


@pytest.mark.parametrize("char, keysym, state, expected", [
    ("s", "s", COMMAND, "Ctrl+S"),  # Cmd+S: the same save shortcut as Ctrl+S elsewhere
    ("z", "Z", COMMAND | SHIFT, "Ctrl+Shift+Z"),
    ("\x13", "s", MAC_CONTROL, "MacCtrl+S"),  # the Mac's own Control key
    ("ß", "ssharp", OPTION, "ß"),  # Option types characters
    ("é", "eacute", OPTION, "é"),
    ("", "Left", OPTION, "Alt+Left"),  # but with a named key it's Alt
    ("", "F4", COMMAND | OPTION, "Ctrl+Alt+F4"),
    ("s", "s", COMMAND | OPTION, "Ctrl+Alt+S"),
    ("\r", "Return", 0, "Enter"),
    ("", "Meta_L", COMMAND, "Ctrl"),  # Command on its own
    ("", "Control_L", MAC_CONTROL, "MacCtrl"),
    ("", "Option_L", OPTION, "Alt"),
])
def test_mac_key_names(char, keysym, state, expected):
    assert keys.name(char, keysym, state, platform="darwin") == expected


# ----- forms -----

@pytest.fixture
def make_form(tmp_path):
    forms = []

    def make(*controls, cls=Form, **form_props):
        """controls: (type, name, props)."""
        design = formfile.FormDesign(name="Form1", width=400, height=300, **form_props)
        for i, (type_name, name, props) in enumerate(controls):
            spec = REGISTRY[type_name].new_spec(name, 8, 8 + 32 * i)
            spec.update(props)
            design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = cls(tmp_path / "Form1.form")
        form.show()
        form.root.update()
        forms.append(form)
        return form

    yield make
    for form in forms:
        form.root.destroy()


def press(form, sequence, **options):
    """Press a key in whatever has the focus, as the keyboard would."""
    widget = form.root.focus_lastfor()
    widget.focus_force()  # the program has the keyboard (with no window manager, nothing gives it)
    form.root.update()
    widget.event_generate(sequence, **options)
    form.root.update()


def focused(form):
    """The control with the focus: the one the form gives keys to when it has the keyboard."""
    from pybasic.controls import control_of

    return control_of(form.root.focus_lastfor()).name


def test_keypress_gets_the_names(make_form):
    seen = []

    class Form1(Form):
        def TextBox1_keypress(self, key):
            seen.append(key)

    form = make_form(("TextBox", "TextBox1", {}), cls=Form1)
    form.TextBox1.editor.focus_force()
    form.root.update()
    press(form, "<KeyPress>", keysym="Return")
    press(form, "<KeyPress>", keysym="a")
    press(form, "<KeyPress>", keysym="F2")
    assert seen == ["Enter", "a", "F2"]


def test_tab_order(make_form):
    form = make_form(
        ("TextBox", "Name", {"tabindex": 2}),
        ("Label", "Caption", {}),  # never reached by Tab
        ("Button", "OK", {"tabindex": 0}),
        ("CheckBox", "Remember", {"tabindex": 1}),
        ("TextBox", "Notes", {"tabindex": 3, "multiline": True}),
    )
    assert focused(form) == "OK"  # the first in the tab order starts with the focus
    visits = []
    for _ in range(5):
        press(form, "<Tab>")
        visits.append(focused(form))
    assert visits == ["Remember", "Name", "Notes", "OK", "Remember"]  # Tab leaves the multi-line box too
    press(form, "<Shift-Tab>")
    assert focused(form) == "OK"
    press(form, "<Shift-Tab>")
    assert focused(form) == "Notes"
    press(form, "<Shift-Tab>")  # Shift+Tab leaves a multi-line box backwards
    assert focused(form) == "Name"
    assert "\t" not in form.Notes.text  # no tab characters were typed

    form.Remember.enabled = False
    form.Name.visible = False
    form.OK.widget.focus_force()
    form.root.update()
    press(form, "<Tab>")
    assert focused(form) == "Notes"  # disabled and hidden controls are skipped
    form.Name.tabindex = 0  # code can change the order too
    form.Name.visible = True
    form.root.update()
    form.OK.widget.focus_force()
    form.root.update()
    press(form, "<Shift-Tab>")
    assert focused(form) == "Name"


def test_without_tab_indexes_the_order_is_the_designed_order(make_form):
    form = make_form(("Button", "B", {}), ("Button", "A", {}), ("TextBox", "C", {}))  # all tabindex 0
    assert focused(form) == "B"
    press(form, "<Tab>")
    assert focused(form) == "A"


def test_enter_and_esc(make_form):
    clicks = []

    class Form1(Form):
        def OK_click(self):
            clicks.append("OK")

        def Cancel_click(self):
            clicks.append("Cancel")

    form = make_form(
        ("TextBox", "Name", {"tabindex": 0}),
        ("TextBox", "Notes", {"tabindex": 1, "multiline": True}),
        ("Button", "OK", {"tabindex": 2}),
        ("Button", "Cancel", {"tabindex": 3}),
        cls=Form1, default_button="OK", cancel_button="Cancel",
    )
    assert form.default_button is form.OK and form.cancel_button is form.Cancel
    assert str(form.OK.widget["default"]) == "active" and str(form.Cancel.widget["default"]) == "disabled"
    press(form, "<Return>")
    assert clicks == ["OK"]
    press(form, "<Escape>")
    assert clicks == ["OK", "Cancel"]
    form.Notes.editor.focus_force()
    form.root.update()
    press(form, "<Return>")  # a new line, not OK
    assert clicks == ["OK", "Cancel"]
    form.Cancel.widget.focus_force()
    form.root.update()
    press(form, "<Return>")  # Enter on a button presses that button
    assert clicks == ["OK", "Cancel", "Cancel"]

    form.OK.enabled = False
    form.Name.editor.focus_force()
    form.root.update()
    press(form, "<Return>")
    assert clicks == ["OK", "Cancel", "Cancel"]  # a disabled default button can't be pressed
    form.default_button = form.Cancel
    assert str(form.OK.widget["default"]) == "disabled" and str(form.Cancel.widget["default"]) == "active"
    form.default_button = None
    press(form, "<Return>")
    assert clicks == ["OK", "Cancel", "Cancel"]
    with pytest.raises(ValueError, match="must be one of the form's Buttons"):
        form.cancel_button = "Name"


def test_form_files_only_mention_default_and_cancel_buttons_when_set():
    design = formfile.FormDesign()
    assert "default_button" not in formfile.dumps(design)
    design.default_button, design.cancel_button = "OK", "Cancel"
    again = formfile.loads(formfile.dumps(design))
    assert (again.default_button, again.cancel_button) == ("OK", "Cancel")


# ----- the designer -----

@pytest.fixture
def app(tmp_path):
    from pybasic.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Keys")
    yield app
    app.stop()
    root.destroy()


def tab_indexes(editor):
    return {s["name"]: s["tabindex"] for s in editor.design.controls if "tabindex" in s}


def test_designer_default_and_cancel_buttons(app):
    editor = app.form
    editor.add_control("Button", 16, 16)
    editor.add_control("Button", 16, 56)
    editor.add_control("TextBox", 16, 96)
    editor.select(FORM)
    assert editor.choices_for(FORM, "default_button") == ("", "Button1", "Button2")
    editor.set_property(FORM, "default_button", "Button1")
    editor.set_property(FORM, "cancel_button", "Button2")
    assert str(editor.surface.controls["Button1"].widget["default"]) == "active"
    editor.set_property("Button1", "name", "OK")
    assert editor.design.default_button == "OK"
    editor.undo()
    assert editor.design.default_button == "Button1"
    assert str(editor.surface.controls["Button1"].widget["default"]) == "active"  # after rebuilding
    editor.delete_control("Button2")
    assert editor.design.cancel_button == ""
    assert app.save()
    assert formfile.load(editor.path).default_button == "Button1"


def test_designer_tab_indexes(app):
    editor = app.form
    for type_name in ("TextBox", "Label", "Button", "CheckBox"):
        editor.add_control(type_name, 16, 16)
    assert tab_indexes(editor) == {"TextBox1": 0, "Button1": 1, "CheckBox1": 2}  # new controls go last
    editor.set_property("CheckBox1", "tabindex", "0")  # the others make room
    assert tab_indexes(editor) == {"CheckBox1": 0, "TextBox1": 1, "Button1": 2}
    assert editor.surface.controls["Button1"].tabindex == 2
    assert app.properties._rows["tabindex"][0].get() == "0"
    editor.set_property("CheckBox1", "tabindex", "99")
    assert tab_indexes(editor)["CheckBox1"] == 2
    editor.delete_control("TextBox1")
    assert tab_indexes(editor) == {"Button1": 0, "CheckBox1": 1}
    editor.select("Button1")
    editor.paste(editor.copy_selection())
    assert tab_indexes(editor) == {"Button1": 0, "CheckBox1": 1, "Button2": 2}


def test_tab_order_mode(app):
    editor = app.form
    for type_name in ("TextBox", "Button", "Label", "CheckBox"):
        editor.add_control(type_name, 16, 16)
    editor.show_design()
    app.toggle_tab_order()
    surface = editor.surface
    assert surface.tab_order_next == 0
    assert sorted(b.cget("text") for b in surface._badges) == ["0", "1", "2"]
    surface._control_press(None, surface.controls["CheckBox1"])
    surface._control_press(None, surface.controls["Label1"])  # not a tab stop: just a beep
    surface._control_press(None, surface.controls["Button1"])
    assert tab_indexes(editor) == {"CheckBox1": 0, "Button1": 1, "TextBox1": 2}
    assert editor.selected == "CheckBox1"  # still the last control added: clicks number, they don't select
    greens = sorted(b.cget("text") for b in surface._badges if b.cget("bg") == "#208020")
    assert greens == ["0", "1"]
    editor.undo()
    assert tab_indexes(editor) == {"CheckBox1": 0, "TextBox1": 1, "Button1": 2}
    assert len(surface._badges) == 3  # still numbered after undo rebuilt the form
    surface.canvas.focus_force()
    surface.canvas.update()
    surface.canvas.event_generate("<Escape>")
    assert surface.tab_order_next is None and surface._badges == []
