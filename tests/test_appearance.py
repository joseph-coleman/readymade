"""backcolor, forecolor, font, alignment, valignment and cursor: on controls, forms, in the
designer's Properties panel, and the font dialog."""

import tkinter as tk
from tkinter import colorchooser, messagebox, ttk
from tkinter import font as tkfont

import pytest

from readymade import Form, appearance, dialogs, formfile
from readymade.controls import REGISTRY
from readymade.form import FORM

pytestmark = pytest.mark.usefixtures("display")


# ----- the neutral values -----

def test_colors():
    assert appearance.check_color("#FF8000") == "#ff8000"
    assert appearance.check_color("") == appearance.check_color(None) == ""
    for bad in ("red", "#f80", "ff8000", "#ff80001"):
        with pytest.raises(ValueError, match="isn't a colour"):
            appearance.check_color(bad)
    assert appearance.lighter("#000000", 0.5) == "#80808" + "0"


def test_fonts():
    assert appearance.parse_font("Arial, 12, bold") == ("Arial", 12, ("bold",))
    assert appearance.parse_font(("DejaVu Sans", 14, "underline", "Bold")) == ("DejaVu Sans", 14, ("bold", "underline"))
    assert appearance.parse_font("") == appearance.parse_font(None) == ("", 0, ())
    assert appearance.format_font(("Arial", 12, "italic bold")) == "Arial, 12, bold italic"
    assert appearance.format_font(", 14") == ", 14"
    assert appearance.format_font("Arial, , ") == "Arial"
    assert appearance.format_font(("", "", "")) == ""
    with pytest.raises(ValueError, match="must be a number"):
        appearance.parse_font("Arial, big")
    with pytest.raises(ValueError, match="'heavy' isn't a font style"):
        appearance.parse_font("Arial, 12, heavy")
    usual = {"family": "Usual", "size": 9}
    assert appearance.tk_font(", , bold", usual) == ("Usual", 9, "bold")
    assert appearance.tk_font("Arial, 16", usual) == ("Arial", 16)


def test_anchor():
    assert appearance.anchor("left", "top") == "nw"
    assert appearance.anchor("center", "middle") == "center"
    assert appearance.anchor("right", "middle") == "e"
    assert appearance.anchor("center", "bottom") == "s"


# ----- on controls at run time -----

@pytest.fixture
def make_form(tmp_path):
    forms = []

    def make(*controls, cls=Form, **form_props):
        """controls: (type, name, container or None, props)."""
        design = formfile.FormDesign(name="Form1", width=400, height=300, **form_props)
        for type_name, name, container, props in controls:
            spec = REGISTRY[type_name].new_spec(name, 8, 8, container=container)
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


def test_which_controls_have_which_properties():
    look = ("backcolor", "forecolor", "font", "alignment", "valignment", "cursor")

    def has(type_name):
        return tuple(p for p in look if p in REGISTRY[type_name].prop_defaults())

    assert has("Label") == has("Button") == has("CheckBox") == has("OptionButton") == look
    assert has("TextBox") == has("ComboBox") == has("Frame") == ("backcolor", "forecolor", "font", "alignment", "cursor")
    assert has("ListBox") == ("backcolor", "forecolor", "font", "cursor")
    assert has("Image") == has("Canvas") == ("backcolor", "cursor")
    assert has("Timer") == ()
    assert not hasattr(REGISTRY["Timer"], "backcolor")  # nor in its help, or completion
    assert REGISTRY["Button"].prop_defaults()["alignment"] == "center"
    assert REGISTRY["Canvas"].prop_defaults()["backcolor"] == "#ffffff"
    defaults = list(REGISTRY["Label"].prop_defaults())
    assert defaults[:6] == ["text", "backcolor", "forecolor", "font", "alignment", "valignment"]
    assert defaults[-1] == "cursor"
    assert REGISTRY["Label"].choices("valignment") == ("top", "middle", "bottom")
    assert REGISTRY["ListBox"].choices("alignment") is None


def test_label(make_form):
    form = make_form(("Label", "Label1", None, {
        "backcolor": "#102030", "forecolor": "#ffff00", "font": "DejaVu Sans, 14, bold",
        "alignment": "right", "valignment": "bottom",
    }))
    label = form.Label1
    widget = label.widget
    assert (widget["background"], widget["foreground"]) == ("#102030", "#ffff00")
    assert widget.tk.splitlist(widget["font"]) == ("DejaVu Sans", "14", "bold")  # what Tk is asked for
    assert (str(widget["anchor"]), str(widget["justify"])) == ("se", "right")
    label.font = ("DejaVu Sans", 10, "italic")
    assert label.font == "DejaVu Sans, 10, italic"
    label.font = ""  # back to the usual font
    assert str(widget["font"]) == "TkDefaultFont"
    label.forecolor = ""
    assert widget["foreground"] == label._originals[(str(widget), "foreground")]
    with pytest.raises(ValueError):
        label.alignment = "middle"
    with pytest.raises(ValueError):
        label.backcolor = "blue"


def test_labels_show_their_containers_colour(make_form):
    form = make_form(
        ("Label", "Label1", None, {}),
        ("Frame", "Frame1", None, {}),
        ("CheckBox", "Check1", "Frame1", {}),
        ("Label", "Own", "Frame1", {"backcolor": "#00ff00"}),
        ("TextBox", "Text1", None, {}),
        backcolor="#336699",
    )
    assert form.backcolor == "#336699" and form.root["background"] == "#336699"
    assert form.Label1.widget["background"] == "#336699"  # shows the form's colour
    assert form.Frame1.widget["background"] == form.Frame1.inner["background"] == "#336699"
    assert form.Check1.widget["background"] == "#336699"
    assert form.Text1.widget["background"] != "#336699"  # a text box has its own colour
    form.Frame1.backcolor = "#ffeedd"
    assert form.Check1.widget["background"] == "#ffeedd"  # inside the frame: the frame's colour
    assert form.Own.widget["background"] == "#00ff00"
    form.backcolor = "#000000"
    assert form.Label1.widget["background"] == "#000000"
    assert form.Check1.widget["background"] == "#ffeedd"
    form.Frame1.backcolor = ""
    assert form.Check1.widget["background"] == "#000000"
    form.backcolor = ""
    assert form.Label1.widget["background"] == form.root["background"] != "#000000"


def test_buttons_check_boxes_and_option_buttons(make_form):
    form = make_form(
        ("Button", "Button1", None, {"backcolor": "#000080", "forecolor": "#ffffff", "valignment": "top"}),
        ("CheckBox", "Check1", None, {"forecolor": "#ff0000", "alignment": "center"}),
        ("OptionButton", "Option1", None, {"font": ", 20"}),
    )
    button = form.Button1.widget
    assert (button["background"], button["foreground"], button["activeforeground"]) == ("#000080", "#ffffff", "#ffffff")
    assert button["activebackground"] == appearance.lighter("#000080")  # hovering shows
    assert str(button["anchor"]) == "n"
    assert str(form.Check1.widget["anchor"]) == "center"
    assert form.Check1.widget["foreground"] == "#ff0000"
    assert tkfont.Font(root=button, font=form.Option1.widget["font"]).actual()["size"] == 20


def test_text_boxes(make_form):
    form = make_form(
        ("TextBox", "Single", None, {"backcolor": "#000000", "forecolor": "#00ff00", "alignment": "right"}),
        ("TextBox", "Multi", None, {"multiline": True, "scrollbars": "vertical", "alignment": "center",
                                    "backcolor": "#fffff0"}),
    )
    single = form.Single.editor
    assert (single["background"], single["foreground"], single["insertbackground"]) == ("#000000", "#00ff00", "#00ff00")
    assert str(single["justify"]) == "right"
    multi = form.Multi
    assert multi.editor["background"] == "#fffff0"
    bar = next(w for w in multi.widget.winfo_children() if isinstance(w, tk.Scrollbar))
    assert bar["background"] != "#fffff0"  # scrollbars keep their own look
    multi.text = "one\ntwo"
    assert str(multi.editor.tag_cget("readymade-align", "justify")) == "center"
    assert multi.editor.tag_ranges("readymade-align")[0].string == "1.0"
    multi.editor.insert("1.0", "zero\n")  # typed at the very start: not tagged until the key is released
    multi.editor.focus_force()
    form.root.update()
    multi.editor.event_generate("<KeyRelease>", keysym="a")
    assert "readymade-align" in multi.editor.tag_names("1.0")


def test_combo_and_list_boxes(make_form):
    form = make_form(
        ("ComboBox", "Combo1", None, {"backcolor": "#202020", "forecolor": "#e0e0e0", "font": ", 13",
                                      "alignment": "right", "items": ["a", "b"]}),
        ("ListBox", "List1", None, {"backcolor": "#ffffe0", "forecolor": "#800000"}),
    )
    combo = form.Combo1.widget
    style = combo["style"]
    assert style.endswith(".TCombobox") and style != "TCombobox"
    assert ttk.Style(combo).lookup(style, "fieldbackground") == "#202020"
    assert str(combo["justify"]) == "right"
    popdown = combo.tk.call("ttk::combobox::PopdownWindow", combo) + ".f.l"
    assert combo.tk.call(popdown, "cget", "-background") == "#202020"
    assert "13" in str(combo.tk.call(popdown, "cget", "-font"))
    form.Combo1.backcolor = form.Combo1.forecolor = ""
    assert combo["style"] == "TCombobox"
    assert (form.List1.widget["background"], form.List1.widget["foreground"]) == ("#ffffe0", "#800000")


def test_frames(make_form):
    form = make_form(("Frame", "Frame1", None, {"forecolor": "#ff0000", "alignment": "center"}))
    frame = form.Frame1
    assert str(frame.widget["labelanchor"]) == "n"
    assert frame.widget["foreground"] == "#ff0000"
    frame.enabled = False
    assert frame.widget["foreground"] == "gray50"
    frame.enabled = True
    assert frame.widget["foreground"] == "#ff0000"


def test_cursors(make_form):
    form = make_form(
        ("Button", "Button1", None, {"cursor": "hand"}),
        ("TextBox", "Text1", None, {}),
        cursor="cross",
    )
    assert str(form.Button1.widget["cursor"]) == "hand2"
    assert str(form.Text1.widget["cursor"]) == "xterm"  # "default": a text box keeps its own
    assert str(form.root["cursor"]) == "crosshair"
    form.Button1.cursor = "default"
    assert str(form.Button1.widget["cursor"]) == ""
    with pytest.raises(ValueError, match="cursor must be one of"):
        form.cursor = "pointer"


def test_form_files_only_mention_changed_form_properties(tmp_path):
    design = formfile.FormDesign(name="Form1")
    assert "backcolor" not in formfile.dumps(design) and "cursor" not in formfile.dumps(design)
    design.backcolor, design.cursor = "#123456", "wait"
    loaded = formfile.loads(formfile.dumps(design))
    assert (loaded.backcolor, loaded.cursor) == ("#123456", "wait")


def test_old_designs_without_the_properties_still_load(make_form):
    form = make_form(("Label", "Label1", None, {}))
    spec = formfile.load(form.path).controls[0]
    for prop in ("backcolor", "forecolor", "font", "alignment", "valignment", "cursor"):
        del spec[prop]
    design = formfile.load(form.path)
    design.controls = [spec]
    formfile.save(design, form.path)
    again = Form(form.path)
    try:
        again.load()
        assert (again.Label1.alignment, again.Label1.valignment, again.Label1.cursor) == ("left", "middle", "default")
    finally:
        again.root.destroy()


# ----- the designer -----

@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Colours")
    yield app
    app.stop()
    root.destroy()


def test_designer_colours_fonts_and_alignment(app, monkeypatch):
    editor = app.form
    editor.add_control("Label", 16, 16)
    panel = app.properties
    assert [p for p in ("backcolor", "forecolor", "font", "alignment", "valignment", "cursor") if p in panel._rows] == \
        ["backcolor", "forecolor", "font", "alignment", "valignment", "cursor"]
    assert editor.chooser_for("Label1", "backcolor") == "color"
    assert editor.chooser_for("Label1", "font") == "font"
    assert editor.chooser_for("Label1", "alignment") is None
    assert editor.choices_for("Label1", "alignment") == ("left", "center", "right")

    monkeypatch.setattr(colorchooser, "askcolor", lambda **kw: ((255, 0, 0), "#ff0000"))
    panel._choose("backcolor")
    assert editor.design.control("Label1")["backcolor"] == "#ff0000"
    assert editor.surface.controls["Label1"].widget["background"] == "#ff0000"
    assert panel._swatches["backcolor"]["background"] == "#ff0000"
    monkeypatch.setattr(colorchooser, "askcolor", lambda **kw: (None, None))  # cancelled
    panel._choose("forecolor")
    assert editor.design.control("Label1")["forecolor"] == ""

    asked = {}
    monkeypatch.setattr(dialogs.FontChooser, "ask", classmethod(lambda cls, parent, font, title: asked.update(font=font) or "DejaVu Sans, 18"))
    panel._choose("font")
    assert editor.design.control("Label1")["font"] == "DejaVu Sans, 18"
    assert asked["font"] == ""
    editor.set_property("Label1", "alignment", "right")
    assert str(editor.surface.controls["Label1"].widget["anchor"]) == "e"

    editor.set_property("Label1", "cursor", "hand")
    assert str(editor.surface.controls["Label1"].widget["cursor"]) == "arrow"  # the designer keeps its own

    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **kw: errors.append(message))
    assert editor.set_property("Label1", "font", "DejaVu Sans, huge") is None
    assert "must be a number" in errors[-1]
    assert editor.design.control("Label1")["font"] == "DejaVu Sans, 18"

    editor.undo()  # the cursor
    editor.undo()  # the alignment
    assert str(editor.surface.controls["Label1"].widget["anchor"]) == "w"


def test_designer_form_colour(app, monkeypatch):
    editor = app.form
    editor.add_control("Label", 16, 16)
    editor.add_control("TextBox", 16, 56)
    editor.select(FORM)
    assert app.properties.app.chooser_for(FORM, "backcolor") == "color"
    assert editor.choices_for(FORM, "cursor")[0] == "default"
    editor.set_property(FORM, "backcolor", "#204060")
    assert editor.surface.canvas["background"] == "#204060"
    assert editor.surface.controls["Label1"].widget["background"] == "#204060"
    assert editor.surface.controls["TextBox1"].widget["background"] != "#204060"
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, message, **kw: errors.append(message))
    assert editor.set_property(FORM, "backcolor", "teal") is None
    assert editor.design.backcolor == "#204060"
    assert app.save()
    assert formfile.load(editor.path).backcolor == "#204060"


def test_several_controls_at_once(app):
    editor = app.form
    editor.add_control("Label", 16, 16)
    editor.add_control("Button", 16, 56)
    editor.select_many(["Label1", "Button1"])
    from readymade.ide.editors import MULTIPLE

    assert "forecolor" in dict(editor.props_for(MULTIPLE))
    editor.set_property(MULTIPLE, "forecolor", "#00aa00")
    assert editor.design.control("Label1")["forecolor"] == editor.design.control("Button1")["forecolor"] == "#00aa00"


# ----- the font dialog -----

def test_font_chooser(app):
    family = min(tkfont.families(app.root))  # one this system has
    chooser = dialogs.FontChooser(app.root, f"{family}, 14, bold")
    try:
        assert chooser.value() == f"{family}, 14, bold"
        assert chooser.families.get(chooser.families.curselection()[0]) == family
        chooser.styles["italic"].set(True)
        chooser.size.set("")
        assert chooser.value() == f"{family}, , bold italic"
        chooser.families.selection_clear(0, tk.END)
        chooser.families.selection_set(0)  # (usual font)
        chooser.update()
        chooser.families.event_generate("<<ListboxSelect>>")
        assert chooser.value() == ", , bold italic"
        chooser.size.set("big")
        chooser.ok()  # stays open: the size isn't a number
        assert chooser.winfo_exists() and chooser.result is None
        chooser.size.set("11")
        chooser.ok()
        assert chooser.result == ", 11, bold italic"
    finally:
        if chooser.winfo_exists():
            chooser.destroy()


def test_font_dialog_for_programs(monkeypatch):
    seen = {}
    monkeypatch.setattr(dialogs.FontChooser, "ask", classmethod(lambda cls, parent, font, title: seen.update(font=font, title=title) or "Arial, 12"))
    assert dialogs.font_dialog("Courier, 10") == "Arial, 12"
    assert seen == {"font": "Courier, 10", "title": "Font"}


def test_properties_scroll_when_they_dont_fit(app):
    app.root.geometry("1000x360")
    app.form.add_control("Label", 16, 16)
    app.root.update()
    panel = app.properties
    assert panel._bar.winfo_ismapped()
    assert panel._scroller.yview()[0] == 0
    last = panel._editors["cursor"]
    last.focus_force()  # as if reached with Tab
    app.root.update()
    assert panel._scroller.yview()[0] > 0
    app.root.geometry("1000x900")
    app.root.update()
    assert not panel._bar.winfo_ismapped()
