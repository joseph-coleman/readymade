"""Runtime behavior of each control type."""

import time

import pytest

from readymade import Form, formfile
from readymade.controls import REGISTRY

pytestmark = pytest.mark.usefixtures("display")


def make_form(tmp_path, *controls, cls=Form):
    """controls: (type, name, container or None, extra props)."""
    design = formfile.FormDesign(name="Form1")
    for type_name, name, container, props in controls:
        spec = REGISTRY[type_name].new_spec(name, 8, 8, container=container)
        spec.update(props)
        design.controls.append(spec)
    path = tmp_path / "Form1.form"
    formfile.save(design, path)
    form = cls(path)
    form.show()
    return form


def pump(form, seconds):
    end = time.time() + seconds
    while time.time() < end:
        form.root.update()
        time.sleep(0.005)


@pytest.fixture
def closing():
    forms = []
    yield forms.append
    for form in forms:
        form.root.destroy()


def test_checkbox(tmp_path, closing):
    clicks = []

    class Form1(Form):
        def CheckBox1_click(self):
            clicks.append(self.CheckBox1.value)

    form = make_form(tmp_path, ("CheckBox", "CheckBox1", None, {"value": True}), cls=Form1)
    closing(form)
    assert form.CheckBox1.value is True
    form.CheckBox1.widget.invoke()
    assert clicks == [False]


def test_option_buttons_are_grouped_by_container(tmp_path, closing):
    form = make_form(
        tmp_path,
        ("OptionButton", "optA", None, {"value": True}),
        ("OptionButton", "optB", None, {}),
        ("Frame", "Frame1", None, {}),
        ("OptionButton", "optC", "Frame1", {"value": True}),
        ("OptionButton", "optD", "Frame1", {}),
    )
    closing(form)
    assert [form.controls[n].value for n in ("optA", "optB", "optC", "optD")] == [True, False, True, False]
    form.optB.value = True  # selecting B deselects A, but not the frame's group
    form.optD.widget.invoke()
    assert [form.controls[n].value for n in ("optA", "optB", "optC", "optD")] == [False, True, False, True]
    assert form.optA.widget.cget("tristatevalue") != form.optA._group.get()  # not drawn "mixed"


def test_frame_holds_its_controls(tmp_path, closing):
    form = make_form(tmp_path, ("Frame", "Frame1", None, {"left": 40, "top": 40}), ("Label", "Label1", "Frame1", {}))
    closing(form)
    assert form.Label1.widget.master is form.Frame1.inner
    form.Frame1.text = "Options"
    assert form.Frame1.widget.cget("text") == "Options"


def test_listbox(tmp_path, closing):
    clicks = []

    class Form1(Form):
        def ListBox1_click(self):
            clicks.append(self.ListBox1.text)

    form = make_form(tmp_path, ("ListBox", "ListBox1", None, {"items": ["red", "green"]}), cls=Form1)
    closing(form)
    box = form.ListBox1
    box.add_item("blue")
    box.add_item("black", 0)
    assert box.items == ["black", "red", "green", "blue"]
    assert (box.list_index, box.text, box.list_count) == (-1, "", 4)
    box.list_index = 2
    assert box.text == "green"
    pump(form, 0.05)  # Tk drops events for windows that aren't on screen yet
    box.widget.event_generate("<<ListboxSelect>>")
    pump(form, 0.05)
    assert clicks == ["green"]
    box.remove_item(0)
    assert box.items == ["red", "green", "blue"]
    box.clear()
    assert box.items == []


def test_combobox(tmp_path, closing):
    changes = []

    class Form1(Form):
        def ComboBox1_change(self):
            changes.append(self.ComboBox1.text)

    form = make_form(tmp_path, ("ComboBox", "ComboBox1", None, {"items": ["S", "M", "L"], "text": ""}), cls=Form1)
    closing(form)
    combo = form.ComboBox1
    assert combo.items == ["S", "M", "L"]
    combo.list_index = 1
    assert (combo.text, combo.list_index) == ("M", 1)
    assert changes == ["M"]
    combo.editable = False
    assert str(combo.widget.cget("state")) == "readonly"
    combo.enabled = False
    assert str(combo.widget.cget("state")) == "disabled"
    combo.enabled = True
    assert str(combo.widget.cget("state")) == "readonly"


def test_timer_ticks_until_disabled(tmp_path, closing):
    ticks = []

    class Form1(Form):
        def Timer1_timer(self):
            ticks.append(1)
            if len(ticks) == 3:
                self.Timer1.enabled = False

    form = make_form(tmp_path, ("Timer", "Timer1", None, {"interval": 10}), cls=Form1)
    closing(form)
    assert not form.Timer1.widget.winfo_manager()  # never shown at runtime
    pump(form, 0.3)
    assert len(ticks) == 3


def test_timer_spec_has_no_size():
    spec = REGISTRY["Timer"].new_spec("Timer1", 8, 8, 100, 100)
    assert "width" not in spec and "height" not in spec
    formfile.loads(formfile.dumps(formfile.FormDesign(controls=[spec])))


def test_list_defaults_are_not_shared():
    a = REGISTRY["ListBox"].new_spec("List1", 0, 0)
    b = REGISTRY["ListBox"].new_spec("List2", 0, 0)
    a["items"].append("x")
    assert b["items"] == []


def test_multiline_textbox(tmp_path, closing):
    changes = []

    class Form1(Form):
        def TextBox1_change(self):
            changes.append(self.TextBox1.text)

    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "text": "one\ntwo"}), cls=Form1)
    closing(form)
    box = form.TextBox1
    assert isinstance(box.editor, __import__("tkinter").Text)
    assert box.text == "one\ntwo"
    pump(form, 0.05)
    assert changes == []  # the initial text isn't a change

    box.text = "a\nb\nc"
    pump(form, 0.05)
    assert changes == ["a\nb\nc"]  # one event per assignment

    box.editor.insert("end", "!")  # as if typed
    pump(form, 0.05)
    assert changes[-1] == "a\nb\nc!"

    box.enabled = False
    box.text = "set while disabled"
    assert box.text == "set while disabled"

    with pytest.raises(AttributeError, match="designer"):
        box.multiline = False


def test_single_line_textbox_is_still_an_entry(tmp_path, closing):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {}))
    closing(form)
    assert isinstance(form.TextBox1.widget, __import__("tkinter").Entry)
    assert form.TextBox1.multiline is False


@pytest.mark.parametrize(
    "scrollbars, orients, wrap",
    [("none", [], "word"), ("vertical", ["vertical"], "word"),
     ("horizontal", ["horizontal"], "none"), ("both", ["vertical", "horizontal"], "none")],
)
def test_scrollbars(tmp_path, closing, scrollbars, orients, wrap):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "scrollbars": scrollbars}))
    closing(form)
    box = form.TextBox1
    bars = [w for w in box.widget.winfo_children() if w.winfo_class() == "Scrollbar"]
    assert [str(b.cget("orient")) for b in bars] == orients
    assert str(box.editor.cget("wrap")) == wrap
    assert box.scrollbars == scrollbars
    with pytest.raises(AttributeError, match="designer"):
        box.scrollbars = "none" if scrollbars != "none" else "both"


def test_vertical_scrollbar_follows_the_text(tmp_path, closing):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "scrollbars": "vertical", "height": 48}))
    closing(form)
    box = form.TextBox1
    box.text = "\n".join(f"line {i}" for i in range(50))
    pump(form, 0.1)
    bar = next(w for w in box.widget.winfo_children() if w.winfo_class() == "Scrollbar")
    assert bar.get()[1] < 1.0  # the thumb shows only part of the text


def test_scrollbars_are_ignored_on_single_line_boxes(tmp_path, closing):
    form = make_form(tmp_path, ("TextBox", "TextBox1", None, {"scrollbars": "both"}))
    closing(form)
    assert form.TextBox1.widget is form.TextBox1.editor
    assert form.TextBox1.editor.winfo_class() == "Entry"


def test_unknown_scrollbars_value_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="none, horizontal, vertical, both"):
        make_form(tmp_path, ("TextBox", "TextBox1", None, {"multiline": True, "scrollbars": "sideways"}))


# ----- ScrollBar, Slider, UpDown, ProgressBar: a whole number from min to max -----

@pytest.mark.parametrize("type_name", ["ScrollBar", "Slider", "UpDown", "ProgressBar"])
def test_ranged_values(tmp_path, closing, type_name):
    form = make_form(tmp_path, (type_name, "It", None, {"min": 10, "max": 20, "value": 15}))
    closing(form)
    it = form.It
    assert (it.min, it.max, it.value) == (10, 20, 15)
    it.value = 20.0  # (a whole number, even as a float)
    assert it.value == 20 and isinstance(it.value, int)
    for bad in (21, 9, 12.5, "lots", True):
        with pytest.raises(ValueError):
            it.value = bad
    it.max = 12  # the value comes along
    assert it.value == 12
    it.min = 12
    with pytest.raises(ValueError, match="min can't be more than max"):
        it.min = 13
    with pytest.raises(ValueError, match="max can't be less than min"):
        it.max = 11


def test_change_runs_for_code_and_users(tmp_path, closing):
    changes = []

    class Form1(Form):
        def ScrollBar1_change(self):
            changes.append(("scroll", self.ScrollBar1.value))

        def Slider1_change(self):
            changes.append(("slide", self.Slider1.value))

        def UpDown1_change(self):
            changes.append(("updown", self.UpDown1.value))

    form = make_form(tmp_path, ("ScrollBar", "ScrollBar1", None, {"max": 50, "smallchange": 2, "largechange": 10}),
                     ("Slider", "Slider1", None, {"max": 10}), ("UpDown", "UpDown1", None, {"max": 5, "increment": 2}),
                     cls=Form1)
    closing(form)
    form.ScrollBar1.value = 3
    form.ScrollBar1.value = 3  # (no change, so no event)
    bar = form.ScrollBar1.widget
    pump(form, 0.05)
    x = next(x for x in range(bar.winfo_width() - 1, 0, -1) if "rightarrow" in bar.identify(x, 8))
    bar.event_generate("<ButtonPress-1>", x=x, y=8)  # its right arrow, clicked
    bar.event_generate("<ButtonRelease-1>", x=x, y=8)
    form.ScrollBar1._scrolled("scroll", -1, "pages")  # a click beside the thumb
    form.ScrollBar1._scrolled("moveto", "0.5")  # the thumb dragged halfway: of 0..50 plus a page of 10
    assert [v for kind, v in changes if kind == "scroll"] == [3, 5, 0, 30]
    form.Slider1.widget.set(6.4)  # the knob dragged: to the nearest whole number
    assert form.Slider1.value == 6 and float(form.Slider1.widget.get()) == 6
    form.UpDown1.widget.event_generate("<<Increment>>")  # its up arrow
    pump(form, 0.05)
    assert form.UpDown1.value == 2 and form.UpDown1.widget.get() == "2"
    form.UpDown1.widget.delete(0, "end")
    form.UpDown1.widget.insert(0, "4")  # typed
    assert form.UpDown1.value == 4
    form.UpDown1.widget.insert("end", "9")  # "49": out of range, so the value stays
    assert form.UpDown1.value == 4
    assert ("slide", 6) in changes and [v for kind, v in changes if kind == "updown"] == [2, 4]


def test_slider_keys(tmp_path, closing):
    form = make_form(tmp_path, ("Slider", "Slider1", None, {"max": 20, "value": 10, "smallchange": 2,
                                                             "largechange": 5}))
    closing(form)
    slider = form.Slider1
    slider.widget.focus_force()
    pump(form, 0.05)
    for key, expected in (("Right", 12), ("Left", 10), ("Next", 15), ("Prior", 10), ("End", 20), ("Home", 0)):
        slider.widget.event_generate(f"<KeyPress-{key}>")
        assert slider.value == expected, key
    slider.enabled = False
    slider.widget.event_generate("<KeyPress-End>")
    assert slider.value == 0 and slider.widget.instate(["disabled"])


def test_updown_wraps_and_shows_its_value_after_typing(tmp_path, closing):
    form = make_form(tmp_path, ("UpDown", "UpDown1", None, {"min": 1, "max": 3, "value": 3, "wrap": True}),
                     ("TextBox", "TextBox1", None, {}))
    closing(form)
    updown = form.UpDown1
    updown.widget.event_generate("<<Increment>>")
    assert updown.value == 1  # round to min
    updown.widget.focus_force()
    pump(form, 0.05)
    updown.widget.delete(0, "end")
    updown.widget.insert(0, "x")
    form.TextBox1.editor.focus_force()
    pump(form, 0.05)
    assert updown.widget.get() == "1"  # leaving puts back the value


def test_progressbar(tmp_path, closing):
    form = make_form(tmp_path, ("ProgressBar", "ProgressBar1", None, {"min": 100, "max": 300, "value": 150}))
    closing(form)
    bar = form.ProgressBar1
    assert (float(bar.widget.cget("maximum")), float(bar.widget.cget("value"))) == (200, 50)
    bar.marquee = True
    assert str(bar.widget.cget("mode")) == "indeterminate"
    bar.marquee = False
    assert str(bar.widget.cget("mode")) == "determinate" and float(bar.widget.cget("value")) == 50


def test_orientation_is_set_in_the_designer(tmp_path, closing):
    form = make_form(tmp_path, ("Slider", "Slider1", None, {"orientation": "vertical", "width": 24, "height": 160}),
                     ("ProgressBar", "ProgressBar1", None, {"orientation": "vertical"}))
    closing(form)
    assert str(form.Slider1.widget.cget("orient")) == "vertical"
    assert str(form.ProgressBar1.widget.cget("orient")) == "vertical"
    form.Slider1.orientation = "vertical"  # (no change)
    with pytest.raises(AttributeError, match="designer"):
        form.Slider1.orientation = "horizontal"


# ----- TabStrip, TreeView, ListView -----

def test_tabstrip_pages(tmp_path, closing):
    picked = []

    class Form1(Form):
        def TabStrip1_click(self):
            picked.append(self.TabStrip1.tab)

    form = make_form(tmp_path, ("TabStrip", "TabStrip1", None, {"tabs": ["One", "Two"]}),
                     ("Button", "Button1", "TabStrip1", {"page": 0}), ("Label", "Label1", "TabStrip1", {"page": 1}),
                     ("Label", "Label2", "TabStrip1", {"page": 7}),  # (past its tabs: on the last page)
                     cls=Form1)
    closing(form)
    strip = form.TabStrip1
    pump(form, 0.05)
    assert strip.tabs == ["One", "Two"] and strip.tab == 0
    assert form.Button1.widget.winfo_viewable() and not form.Label1.widget.winfo_viewable()
    assert form.Label2.widget.master is form.Label1.widget.master
    strip.tab = 1  # code changes it: click runs too
    pump(form, 0.05)
    assert form.Label1.widget.winfo_viewable() and not form.Button1.widget.winfo_viewable()
    strip.widget.select(0)  # the user picks the first tab
    pump(form, 0.05)
    assert strip.tab == 0 and picked == [1, 0]
    with pytest.raises(ValueError, match="tab must be from 0 to 1"):
        strip.tab = 2
    strip.enabled = False
    assert str(strip.widget.tab(0, "state")) == "disabled"
    strip.tabs = ["Only"]  # its other page keeps its controls, out of sight
    assert strip.tabs == ["Only"] and strip.tab == 0 and str(strip.widget.tab(1, "state")) == "hidden"


def test_treeview(tmp_path, closing):
    chosen = []

    class Form1(Form):
        def TreeView1_nodeclick(self, node):
            chosen.append(node.text)

    form = make_form(tmp_path, ("TreeView", "TreeView1", None, {"items": ["Fruit", "  Apple", "  Pear", "Veg"]}),
                     cls=Form1)
    closing(form)
    tree = form.TreeView1
    fruit, veg = tree.nodes
    assert [n.text for n in fruit.children] == ["Apple", "Pear"] and fruit.children[0].parent is fruit
    leek = veg.add("Leek", key="leek")
    assert tree.node("leek") is leek and leek.parent is veg and leek.key == "leek"
    assert tree.items == ["Fruit", "  Apple", "  Pear", "Veg", "  Leek"]
    with pytest.raises(ValueError, match="already has a node 'leek'"):
        tree.add("Leek", key="leek")
    with pytest.raises(ValueError, match="no node 'nope'"):
        tree.add("x", parent="nope")
    tree.selected = leek
    pump(form, 0.05)
    assert tree.selected is leek and chosen == ["Leek"] and veg.expanded  # (opened to show it)
    leek.text = "Leeks"
    veg.remove()
    assert tree.node("leek") is None and [n.text for n in tree.nodes] == ["Fruit"] and tree.selected is None
    tree.items = ["One", "    Two"]  # (in too far: just under the one before)
    assert tree.items == ["One", "  Two"]
    tree.clear()
    assert tree.nodes == []


def test_listview(tmp_path, closing):
    log = []

    class Form1(Form):
        def ListView1_itemclick(self, item):
            log.append(("item", item.text))

        def ListView1_columnclick(self, column):
            log.append(("column", column))

    form = make_form(tmp_path, ("ListView", "ListView1", None, {"columns": ["Name", "Size"]}), cls=Form1)
    closing(form)
    view = form.ListView1
    for name, size in (("b.txt", "10"), ("A.txt", "9"), ("c.txt", "1,000")):
        view.add(name, size)
    view.sort(1)  # numbers as numbers
    assert [i.text for i in view.items] == ["A.txt", "b.txt", "c.txt"]
    view._header_clicked(0)  # (a click on the Name header: sorts, as text)
    view._header_clicked(0)  # again: the other way
    assert [i.text for i in view.items] == ["c.txt", "b.txt", "A.txt"] and view.widget.heading("c0", "text") == "Name ▼"
    assert ("column", 0) in log
    row = view.items[1]
    view.selected = row
    pump(form, 0.05)
    assert view.selected is row and ("item", "b.txt") in log
    row.values = ["bee.txt", "11"]
    assert row.text == "bee.txt" and row.index == 1
    view.add("x", key="k")
    with pytest.raises(ValueError, match="already has an item 'k'"):
        view.add("y", key="k")
    view.item("k").remove()
    assert view.item("k") is None and len(view.items) == 3
    view.multiselect = True
    view.widget.selection_set([i.key for i in view.items[:2]])
    assert [i.text for i in view.selected_items] == ["c.txt", "bee.txt"]
    view.sortable = False
    view._header_clicked(1)
    assert [i.text for i in view.items] == ["c.txt", "bee.txt", "A.txt"]  # (not sorted)
    view.columns = ["Name", "Size", "Kind"]
    assert view.items[0].values == ["c.txt", "1,000", ""]


def test_tree_colors_fill_the_empty_space_too(tmp_path, closing):
    """Windows' and macOS's themes draw a Treeview's empty space themselves (ignoring its
    color), so a colored TreeView or ListView uses ttk's plain field there."""
    from tkinter import ttk

    form = make_form(tmp_path, ("TreeView", "TreeView1", None, {"backcolor": "#a080b0"}),
                     ("ListView", "ListView1", None, {"font": "DejaVu Sans, 12"}))
    closing(form)
    style = ttk.Style(form.root)
    tree = form.TreeView1.widget

    def field(widget):
        return style.layout(widget.cget("style"))[0][0]

    assert field(tree) == "Readymade.field" and style.lookup(tree.cget("style"), "fieldbackground") == "#a080b0"
    assert field(form.ListView1.widget) == "Treeview.field"  # (just a font: the theme's own field)
    form.TreeView1.backcolor = ""
    assert tree.cget("style") == "Treeview"


def test_tabstrip_pages_are_the_same_size_in_every_theme(tmp_path, closing):
    """macOS's theme sets a notebook's pages in by about 18 points a side (8 and 17 above and
    below); a TabStrip's page fills it below its tabs, as in the designer, whatever the theme."""
    from tkinter import ttk

    def page_size():
        form = make_form(tmp_path, ("TabStrip", "TabStrip1", None, {"width": 300, "height": 200}))
        closing(form)
        pump(form, 0.05)
        return form.TabStrip1.inner.winfo_width(), form.TabStrip1.inner.winfo_height()

    usual = page_size()
    style = ttk.Style()
    style.configure("TNotebook", padding=(18, 8, 18, 17))  # (as macOS's theme has it)
    try:
        assert page_size() == usual
    finally:
        style.configure("TNotebook", padding="")
    assert usual[0] >= 296  # (just the page's own border, if the theme draws one)


# ----- a toolbar's parts: flat buttons, a borderless Frame, toggles that look like buttons -----

def test_toolbar_parts(tmp_path, closing):
    from tkinter import ttk

    form = make_form(tmp_path, ("Frame", "Bar", None, {"border": False, "dock": "top", "height": 36}),
                     ("Button", "New", "Bar", {"flat": True, "dock": "left", "width": 32, "font": "DejaVu Sans, 12"}),
                     ("CheckBox", "Bold", "Bar", {"appearance": "button", "flat": True, "dock": "left", "width": 32,
                                                   "forecolor": "#0000c0"}),
                     ("OptionButton", "Left", "Bar", {"appearance": "button", "dock": "left", "width": 32}),
                     ("OptionButton", "Right", "Bar", {"appearance": "button", "dock": "left", "width": 32}),
                     ("CheckBox", "Plain", None, {"top": 60}))
    closing(form)
    assert int(form.Bar.widget.cget("borderwidth")) == 0
    # Flat: ttk's Toolbutton style, which each system draws as its toolbars' buttons.
    new, bold = form.New.widget, form.Bold.widget
    assert (new.winfo_class(), bold.winfo_class()) == ("TButton", "TCheckbutton")
    assert str(new.cget("style")).endswith(".Toolbutton") and str(bold.cget("style")).endswith(".Toolbutton")
    style = ttk.Style(form.root)
    assert "12" in str(style.lookup(new.cget("style"), "font"))  # (a ttk widget's font is its style's)
    assert style.lookup(bold.cget("style"), "foreground") == "#0000c0"
    form.Bold.value = True
    assert bold.instate(["selected"])
    assert style.lookup(bold.cget("style"), "foreground", ["selected"]) != "#0000c0"  # (on: the theme's own)
    # A button look that isn't flat: Tk's classic toggle, without its box (except on macOS: see below).
    assert form.Left.widget.winfo_class() == "Radiobutton" and not int(form.Left.widget.cget("indicatoron"))
    assert int(form.Plain.widget.cget("indicatoron"))
    form.Left.value = True
    form.Right.value = True  # (one group: Left / Center / Right)
    assert not form.Left.value
    for control, prop, value in ((form.New, "flat", False), (form.Bold, "appearance", "normal")):
        with pytest.raises(AttributeError, match="designer"):
            setattr(control, prop, value)
    form.Bar.border = True
    assert int(form.Bar.widget.cget("borderwidth")) > 0
    assert REGISTRY["CheckBox"].choices("appearance") == ("normal", "button")
    assert "picture" in REGISTRY["OptionButton"].prop_defaults() and "flat" not in REGISTRY["Label"].prop_defaults()


def test_on_macos_a_button_look_is_always_a_toolbutton():
    """macOS's classic toggle shows "on" in a maroon of Tk's; its Toolbutton, in the system's accent color."""
    from types import SimpleNamespace

    from readymade.controls.buttons import _Appearance

    def wants(appearance, flat, system):
        toggle = SimpleNamespace(_appearance=appearance, _flat=flat)
        parent = SimpleNamespace(tk=SimpleNamespace(call=lambda *args: system))
        return _Appearance._wants_toolbutton(toggle, parent)

    assert wants("button", False, "aqua") and wants("button", True, "x11") and wants("button", True, "win32")
    assert not wants("button", False, "x11") and not wants("button", False, "win32")
    assert not wants("normal", True, "aqua") and not wants("normal", False, "aqua")


def test_a_borderless_frame_is_outlined_in_the_designer(tmp_path):
    import tkinter as tk

    from readymade.controls import create

    root = tk.Tk()
    try:
        spec = {**REGISTRY["Frame"].new_spec("Frame1", 8, 8), "border": False}
        designed = create(root, spec, design=True)
        running = create(root, {**spec, "name": "Frame2"})
        assert int(designed.widget.cget("highlightthickness")) == 1  # (so it can be found and clicked)
        assert int(running.widget.cget("highlightthickness")) == 0 and int(running.widget.cget("borderwidth")) == 0
    finally:
        root.destroy()
