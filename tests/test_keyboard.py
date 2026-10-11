"""Key names for keypress, Tab order, and Enter and Esc pressing a form's default and cancel buttons."""

import tkinter as tk

import pytest

from readymade import Form, formfile, keys
from readymade.controls import REGISTRY
from readymade.form import FORM

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
    # Checked on a real Mac (Tk 8.6.13): fn is Super_L with state bit 0x40, which arrow, Delete
    # and F keys also carry (arrows add 0x20 too); neither changes the names.
    ("", "Super_L", 0x40, "Fn"),
    ("", "Delete", 0x40, "Del"),  # fn+Delete
    ("", "F5", 0x40, "F5"),
    ("", "Left", 0x68, "Ctrl+Left"),  # Cmd+Left
    ("", "Left", 0x70, "Alt+Left"),  # Option+Left
    ("´", "acute", OPTION, "´"),  # Option+E: the dead key's accent, then "é" with the next key
    ("é", "eacute", 0, "é"),
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
    from readymade.controls import control_of

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
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Keys")
    yield app
    app.runner.stop()
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
    # New controls go last. A Label has a place too (Tab passes it by; its access key uses it).
    assert tab_indexes(editor) == {"TextBox1": 0, "Label1": 1, "Button1": 2, "CheckBox1": 3}
    editor.set_property("CheckBox1", "tabindex", "0")  # the others make room
    assert tab_indexes(editor) == {"CheckBox1": 0, "TextBox1": 1, "Label1": 2, "Button1": 3}
    assert editor.surface.controls["Button1"].tabindex == 3
    assert app.properties._rows["tabindex"][0].get() == "0"
    editor.set_property("CheckBox1", "tabindex", "99")
    assert tab_indexes(editor)["CheckBox1"] == 3
    editor.delete_control("TextBox1")
    assert tab_indexes(editor) == {"Label1": 0, "Button1": 1, "CheckBox1": 2}
    editor.select("Button1")
    editor.paste(editor.copy_selection())
    assert tab_indexes(editor) == {"Label1": 0, "Button1": 1, "CheckBox1": 2, "Button2": 3}


def test_tab_order_mode(app):
    editor = app.form
    for type_name in ("TextBox", "Button", "Label", "CheckBox"):
        editor.add_control(type_name, 16, 16)
    editor.show_design()
    app.toggle_tab_order()
    surface = editor.surface
    assert surface.tab_order_next == 0
    assert sorted(b.cget("text") for b in surface._badges) == ["0", "1", "2", "3"]
    surface._control_press(None, surface.controls["CheckBox1"])
    surface._control_press(None, surface.controls["Label1"])  # a Label gets its place too, as in VB
    surface._control_press(None, surface.controls["Button1"])
    assert tab_indexes(editor) == {"CheckBox1": 0, "Label1": 1, "Button1": 2, "TextBox1": 3}
    assert editor.selected == "CheckBox1"  # still the last control added: clicks number, they don't select
    greens = sorted(b.cget("text") for b in surface._badges if b.cget("bg") == "#208020")
    assert greens == ["0", "1", "2"]
    editor.undo()
    assert tab_indexes(editor) == {"CheckBox1": 0, "Label1": 1, "TextBox1": 2, "Button1": 3}
    assert len(surface._badges) == 4  # still numbered after undo rebuilt the form
    surface.canvas.focus_force()
    surface.canvas.update()
    surface.canvas.event_generate("<Escape>")
    assert surface.tab_order_next is None and surface._badges == []


# ----- access keys: & in a caption -----

def test_access_keys(make_form):
    clicks = []

    class Form1(Form):
        def Save_click(self):
            clicks.append("Save")

    form = make_form(
        ("Label", "lblName", {"text": "&Name:"}),
        ("TextBox", "Name", {"tabindex": 0}),
        ("TextBox", "Notes", {"tabindex": 1}),
        ("CheckBox", "Gift", {"text": "&Gift wrap", "tabindex": 2}),
        ("OptionButton", "Post", {"text": "By &post", "tabindex": 3}),
        ("Button", "Save", {"text": "&Save && close", "tabindex": 4}),
        ("Label", "lblQA", {"text": "Q&A", "accesskey": False}),
        cls=Form1,
    )
    assert form.Save.text == "&Save && close"  # as written; it shows without the &s, with S underlined
    assert (form.Save.widget["text"], form.Save.widget["underline"]) == ("Save & close", 0)
    assert (form.lblQA.widget["text"], form.lblQA.access_key) == ("Q&A", "")  # accesskey off: an & is an &
    assert [form.lblName.access_key, form.Gift.access_key, form.Post.access_key] == ["N", "G", "P"]
    form.Notes.widget.focus_force()
    press(form, "<Alt-KeyPress-s>")
    assert clicks == ["Save"]
    press(form, "<Alt-KeyPress-g>")
    assert form.Gift.value is True and focused(form) == "Gift"
    press(form, "<Alt-KeyPress-p>")
    assert form.Post.value is True
    press(form, "<Alt-KeyPress-n>")  # a Label goes to the control after it
    assert focused(form) == "Name"
    form.Save.enabled = False
    press(form, "<Alt-KeyPress-s>")
    assert clicks == ["Save"]  # (not when it's disabled)


def test_a_frames_access_key_goes_inside_it(make_form):
    form = make_form(
        ("TextBox", "Before", {"tabindex": 0}),
        ("Frame", "fraSize", {"text": "&Size", "width": 200, "height": 120}),
        ("OptionButton", "Small", {"container": "fraSize", "tabindex": 2, "top": 8}),
        ("OptionButton", "Large", {"container": "fraSize", "tabindex": 1, "top": 40}),
    )
    press(form, "<Alt-KeyPress-s>")
    assert focused(form) == "Large"  # its first in Tab order
    assert form.fraSize.widget["text"] == "Size"


def test_mac_access_keys_go_by_the_keys_place(monkeypatch):
    from readymade import form as form_module

    monkeypatch.setattr(form_module.sys, "platform", "darwin")
    event = type("Key", (), {"keycode": 1 << 24, "keysym": "ß"})()  # Option+S types ß; the key is S's
    assert form_module._access_letter(event) == "S"


def test_a_labels_access_key_follows_the_tab_order(make_form):
    form = make_form(
        ("TextBox", "Name", {"tabindex": 3}),
        ("TextBox", "Email", {"tabindex": 1}),
        ("Label", "lblEmail", {"text": "&Email:", "tabindex": 0}),  # drawn last, but first in the order
        ("Label", "lblName", {"text": "&Name:", "tabindex": 2}),
    )
    assert [c.name for c in form._tab_order()] == ["Email", "Name"]  # Tab passes Labels by
    press(form, "<Alt-KeyPress-n>")
    assert focused(form) == "Name"
    press(form, "<Alt-KeyPress-e>")
    assert focused(form) == "Email"
    form.lblEmail.tabindex = 2  # (it reads the order as it is then)
    form.lblName.tabindex = 0
    press(form, "<Alt-KeyPress-e>")
    assert focused(form) == "Name"


def test_forms_from_before_labels_had_a_tab_index():
    from readymade.controls import tab_numbers

    specs = [{"type": "Label", "name": "lblName"}, {"type": "TextBox", "name": "Name", "tabindex": 1},
             {"type": "Button", "name": "OK", "tabindex": 0}, {"type": "Label", "name": "lblNotes"},
             {"type": "Frame", "name": "fraSize"}, {"type": "TextBox", "name": "Notes", "tabindex": 2},
             {"type": "Image", "name": "Image1"}]
    # Each goes just before the next numbered control drawn after it: where its access key went before.
    assert tab_numbers(specs) == {"OK": 0, "lblName": 1, "Name": 2, "lblNotes": 3, "fraSize": 4, "Notes": 5}
    assert tab_numbers([{"type": "TextBox", "name": "T", "tabindex": 0}, {"type": "Label", "name": "L"}]) == {
        "T": 0, "L": 1}  # (nothing after it: at the end)
    assert tab_numbers([{"type": "Label", "name": "L", "tabindex": 0}]) is None  # (all numbered already)


# ----- tabstop, OptionButton groups, keydown and keyup -----

def test_tabstop_false_is_passed_by(make_form):
    form = make_form(
        ("TextBox", "First", {"tabindex": 0}),
        ("Button", "Help", {"tabindex": 1, "tabstop": False, "text": "&Help"}),
        ("TextBox", "Last", {"tabindex": 2}),
    )
    form.First.widget.focus_force()
    press(form, "<Tab>")
    assert focused(form) == "Last"
    press(form, "<Tab>")
    assert focused(form) == "First"
    assert form.Help.tabindex == 1 and form.Help.widget["takefocus"] == 0
    form.Help.tabstop = True
    press(form, "<Tab>")
    assert focused(form) == "Help"


def test_arrow_keys_choose_between_option_buttons(make_form):
    chosen = []

    class Form1(Form):
        def Medium_click(self):
            chosen.append("Medium")

    form = make_form(
        ("TextBox", "Name", {"tabindex": 0}),
        ("OptionButton", "Small", {"tabindex": 1}),
        ("OptionButton", "Medium", {"tabindex": 2}),
        ("OptionButton", "Large", {"tabindex": 3}),
        ("Button", "OK", {"tabindex": 4}),
        cls=Form1,
    )
    assert [c.name for c in form._tab_order()] == ["Name", "Small", "OK"]  # none chosen: the group's first
    form.Name.widget.focus_force()
    press(form, "<Tab>")
    assert focused(form) == "Small"
    press(form, "<Down>")  # the next one, chosen (with its click event), as in Windows
    assert focused(form) == "Medium" and form.Medium.value and chosen == ["Medium"]
    press(form, "<Right>")
    press(form, "<Right>")  # around to the first again
    assert focused(form) == "Small" and form.Small.value
    press(form, "<Up>")
    assert focused(form) == "Large" and form.Large.value
    assert [c.name for c in form._tab_order()] == ["Name", "Large", "OK"]  # only the chosen one stops
    press(form, "<Tab>")
    assert focused(form) == "OK"
    press(form, "<Shift-Tab>")
    assert focused(form) == "Large"
    form.Name.widget.focus_force()
    press(form, "<Down>")  # arrows elsewhere are left alone
    assert focused(form) == "Name"


def test_keydown_and_keyup_once_per_press(make_form):
    seen = []

    class Form1(Form):
        def Form_keydown(self, key):
            seen.append(("down", key))

        def Form_keyup(self, key):
            seen.append(("up", key))

    form = make_form(("TextBox", "Name", {}), cls=Form1)
    press(form, "<KeyPress-Left>")
    press(form, "<KeyRelease-Left>")  # X11 repeats a held key as release and press together
    press(form, "<KeyPress-Left>")
    press(form, "<KeyPress-Left>")  # (Windows and macOS: just more presses)
    press(form, "<KeyPress-exclam>", state=0x1)  # Shift+1: the key is "1"
    press(form, "<KeyRelease-1>")
    press(form, "<KeyRelease-Left>")
    form.root.after(60)
    form.root.update()
    assert seen == [("down", "Left"), ("down", "1"), ("up", "1"), ("up", "Left")]


def test_key_names_for_keydown():
    assert [keys.key_name(k, "linux") for k in ("a", "A", "exclam", "KP_7", "space", "Shift_L", "Left", "F5")] == [
        "A", "A", "1", "7", "Space", "Shift", "Left", "F5"]
    assert keys.key_name("Meta_L", "darwin") == "Ctrl"  # Command, as everywhere in readymade
