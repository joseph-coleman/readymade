"""TextBox readonly, password and maxlength; tooltips; tag; and the program's icon."""

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import pytest

from readymade import Form, formfile, package
from readymade import form as form_module
from readymade.controls import REGISTRY, _tip
from readymade.project import Project

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def make_form(tmp_path):
    forms = []

    def make(*controls, cls=Form, folder=None):
        """controls: (type, name, props)."""
        folder = folder or tmp_path
        design = formfile.FormDesign(name="Form1", width=400, height=300)
        for i, (type_name, name, props) in enumerate(controls):
            spec = REGISTRY[type_name].new_spec(name, 8, 8 + 40 * i)
            spec.update(props)
            design.controls.append(spec)
        formfile.save(design, folder / "Form1.form")
        form = cls(folder / "Form1.form")
        form.show()
        form.root.update()
        forms.append(form)
        return form

    yield make
    for form in forms:
        form.root.destroy()


def write_png(path, size=16):
    root = tk.Tk()
    photo = tk.PhotoImage(master=root, width=size, height=size)
    photo.put("#3060c0", to=(0, 0, size, size))
    path.parent.mkdir(parents=True, exist_ok=True)
    photo.write(str(path), format="png")
    root.destroy()
    return path


def type_keys(form, widget, keysyms):
    widget.focus_force()
    form.root.update()
    for keysym in keysyms:
        widget.event_generate("<KeyPress>", keysym=keysym)
        form.root.update()


# ----- TextBox -----

def test_textbox_properties_are_designable():
    defaults = REGISTRY["TextBox"].prop_defaults()
    assert (defaults["readonly"], defaults["password"], defaults["maxlength"]) == (False, False, 0)


def test_readonly(make_form):
    form = make_form(("TextBox", "Single", {"text": "fixed", "readonly": True, "backcolor": "#ffffe0"}),
                     ("TextBox", "Multi", {"text": "fixed", "readonly": True, "multiline": True}))
    single, multi = form.Single, form.Multi
    assert str(single.editor["state"]) == "readonly"
    assert single.editor["readonlybackground"] == "#ffffe0"  # read-only looks like any other text box
    type_keys(form, single.editor, ["a"])
    type_keys(form, multi.editor, ["a"])
    assert (single.text, multi.text) == ("fixed", "fixed")
    single.text = multi.text = "set by code"  # code can still change it
    assert (single.text, multi.text) == ("set by code", "set by code")
    single.enabled = False
    assert str(single.editor["state"]) == "disabled"
    single.enabled = True
    assert str(single.editor["state"]) == "readonly"
    single.readonly = False
    type_keys(form, single.editor, ["End", "x"])
    assert single.text == "set by codex"


def test_password(make_form):
    form = make_form(("TextBox", "Secret", {"text": "hunter2", "password": True}),
                     ("TextBox", "Notes", {"password": True, "multiline": True}))
    assert form.Secret.editor["show"] == "•"
    assert form.Secret.text == "hunter2"  # code still sees the real text
    form.Secret.password = False
    assert form.Secret.editor["show"] == ""
    assert form.Notes.password  # remembered, but a multi-line box shows its text


def test_maxlength_single_line(make_form):
    form = make_form(("TextBox", "Code", {"text": "", "maxlength": 3}))
    box = form.Code
    type_keys(form, box.editor, ["a", "b", "c", "d", "e"])
    assert box.text == "abc"
    box.text = "longer, from code"
    assert box.text == "longer, from code"
    with pytest.raises(ValueError, match="can't be negative"):
        box.maxlength = -1


def test_maxlength_multi_line(make_form):
    form = make_form(("TextBox", "Notes", {"text": "", "multiline": True, "maxlength": 5}))
    box = form.Notes
    type_keys(form, box.editor, ["a", "b", "Return", "c", "d", "e", "f"])
    assert box.text == "ab\ncd"
    box.text = "ab"
    box.editor.clipboard_clear()
    box.editor.clipboard_append("123456")
    box.editor.mark_set("insert", "end")
    box.editor.event_generate("<<Paste>>")
    form.root.update()
    assert box.text == "ab123"  # as much as fits
    box.editor.tag_add("sel", "1.0", "1.2")  # replacing a selection makes room
    box.editor.event_generate("<<Paste>>")
    form.root.update()
    assert box.text == "12312"


# ----- tooltips and tag -----

def test_tooltips(make_form, monkeypatch):
    monkeypatch.setattr(type(_tip), "DELAY", 10)
    form = make_form(("Button", "Save", {"tooltip": "Save the file (Ctrl+S)"}), ("Label", "Plain", {}))
    widget = form.Save.widget
    widget.event_generate("<Enter>", x=5, y=5)
    for _ in range(20):
        form.root.update()
        form.root.after(10)
    assert _tip.window is not None
    label = _tip.window.winfo_children()[0]
    assert label.cget("text") == "Save the file (Ctrl+S)"
    widget.event_generate("<Leave>")
    form.root.update()
    assert _tip.window is None
    form.Plain.widget.event_generate("<Enter>", x=5, y=5)  # no tooltip: nothing shows
    for _ in range(5):
        form.root.update()
        form.root.after(10)
    assert _tip.window is None
    form.Plain.tooltip = "Added by code"
    assert form.Plain.tooltip == "Added by code"


def test_no_tooltips_in_the_designer():
    root = tk.Tk()
    try:
        spec = REGISTRY["Button"].new_spec("Button1", 0, 0)
        spec["tooltip"] = "hello"
        control = REGISTRY["Button"](root, spec, design=True)
        assert not getattr(control, "_tooltip_connected", False)
    finally:
        root.destroy()


def test_tag(make_form):
    form = make_form(("Label", "Label1", {"tag": "customer name"}), ("Timer", "Timer1", {}))
    assert form.Label1.tag == "customer name"
    assert form.Timer1.tag == ""
    form.Timer1.tag = 42
    assert form.Timer1.tag == "42"
    assert list(REGISTRY["Label"].prop_defaults())[-1] == "tag"
    assert "tag" in REGISTRY["Timer"].prop_defaults()


# ----- the program's icon -----

def test_set_app_icon(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(form_module, "_icon", None)
    assert form_module.set_app_icon(write_png(tmp_path / "icon.png"))
    assert form_module._icon is not None
    assert not form_module.set_app_icon(tmp_path / "missing.png")
    assert "Can't use" in capsys.readouterr().err


def test_project_icon_is_found_beside_the_form(tmp_path):
    project = Project.create(tmp_path / "Shop")
    assert form_module._project_icon(project.folder) is None
    project.set_setting("icon", "images/icon.png")
    assert form_module._project_icon(project.folder) == project.folder / "images" / "icon.png"
    assert form_module._project_icon(tmp_path) is None  # not a project


def test_running_a_project_uses_its_icon(tmp_path):
    project = Project.create(tmp_path / "Shop")
    write_png(project.folder / "images" / "icon.png")
    project.set_setting("icon", "images/icon.png")
    (project.folder / "Form1.py").write_text(
        "from readymade import Form\nfrom readymade import form as f\n\n\nclass Form1(Form):\n"
        "    def Form_load(self):\n        print('ICON', f._icon is not None)\n        self.close()\n\n\n"
        "if __name__ == '__main__':\n    Form1.run()\n",
        encoding="utf-8")
    root = Path(__file__).parent.parent
    env = dict(os.environ, PYTHONPATH=str(root))
    for args in (["-m", "readymade.run", str(project.folder)], [str(project.folder / "Form1.py")]):
        done = subprocess.run([sys.executable, *args], cwd=tmp_path, env=env, capture_output=True,
                              text=True, timeout=30, check=False)
        assert "ICON True" in done.stdout, (args, done.stderr)


@pytest.mark.parametrize("platform, icon, ide_has_pillow, needs", [
    ("win32", "images/icon.png", True, False),  # the IDE converts it
    ("win32", "images/icon.png", False, True),  # PyInstaller does, with Pillow in the project
    ("win32", "images/icon.ico", False, False),  # already Windows' own format
    ("darwin", "images/icon.png", False, True),
    ("darwin", "images/icon.icns", False, False),
    ("linux", "images/icon.png", False, False),  # Linux programs have no icon of their own
    ("win32", None, False, False),
])
def test_icon_needs_pillow(tmp_path, monkeypatch, platform, icon, ide_has_pillow, needs):
    from readymade import pictures

    if not ide_has_pillow:
        monkeypatch.setattr(pictures, "_PILImage", None)
    elif not pictures.have_pillow():
        pytest.skip("Pillow isn't installed")
    project = Project.create(tmp_path / "Shop")
    if icon:
        project.set_setting("icon", icon)
    assert package.icon_needs_pillow(project, platform=platform) is needs


def test_make_exe_uses_the_icon(tmp_path, monkeypatch):
    from PIL import Image

    from readymade import pictures

    project = Project.create(tmp_path / "Shop", first_form="Main")
    icon = write_png(project.folder / "images" / "icon.png", size=20)
    project.set_setting("icon", "images/icon.png")
    source = package.launcher_source(project, "Main")
    assert "set_app_icon(app_path('images/icon.png'))\nforms.Main.show()" in source
    compile(source, "launcher", "exec")
    assert (icon, "images") in package.bundled_files(project)[0]  # for the windows' icon
    launcher = package.write_launcher(project, "Main")

    def icon_arg(platform):
        args = package.pyinstaller_args(project, launcher, "/opt/readymade", platform=platform)
        return Path(args[args.index("--icon") + 1]) if "--icon" in args else None

    # The IDE has Pillow, so it converts the PNG: square, at every size Windows shows.
    ico = icon_arg("win32")
    assert ico == project.folder / "build" / "readymade" / "icon.ico"
    with Image.open(ico) as converted:
        assert converted.format == "ICO" and (256, 256) in converted.info["sizes"] and (16, 16) in converted.info["sizes"]
    icns = icon_arg("darwin")
    with Image.open(icns) as converted:
        assert converted.format == "ICNS"
    assert icon_arg("linux") is None
    monkeypatch.setattr(pictures, "_PILImage", None)  # without Pillow here, PyInstaller gets the PNG
    assert icon_arg("win32") == icon
    icon.unlink()
    assert package.bundled_files(project)[1] == ["icon: images/icon.png"]
    assert icon_arg("win32") is None


def test_an_icon_that_isnt_a_picture(tmp_path):
    project = Project.create(tmp_path / "Shop", first_form="Main")
    (project.folder / "icon.png").write_text("not a picture")
    project.set_setting("icon", "icon.png")
    with pytest.raises(OSError):
        package.program_icon(project, platform="win32")


# ----- the IDE -----

@pytest.fixture
def app(tmp_path):
    from readymade.ide.app import App

    root = tk.Tk()
    app = App(root, tmp_path / "Shop")
    yield app
    app.stop()
    root.destroy()


def test_choosing_the_program_icon(app, tmp_path, monkeypatch):
    chosen = write_png(tmp_path / "Downloads" / "logo.png")
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kw: str(chosen))
    app.choose_icon()
    assert app.project.setting("icon") == "images/logo.png"
    assert (app.project.folder / "images" / "logo.png").exists()
    app.set_icon("images/app.ico")
    assert "need the Pillow library" in app.immediate.output.get("1.0", "end")
    app.set_icon(None)
    assert app.project.setting("icon") is None
    monkeypatch.setattr(filedialog, "askopenfilename", lambda **kw: "")  # canceled: no change
    app.choose_icon()
    assert app.project.setting("icon") is None


def test_textbox_rows_in_the_properties_panel(app):
    app.form.add_control("TextBox", 16, 16)
    rows = app.properties._rows
    assert all(p in rows for p in ("readonly", "password", "maxlength", "tooltip", "tag"))
    app.form.set_property("TextBox1", "maxlength", "8")
    assert app.form.design.control("TextBox1")["maxlength"] == 8


def test_renaming_outside_the_panel_keeps_the_panel_on_the_control(app):
    form = app.form
    form.add_control("Button", 352, 40, 152, 28)
    form.set_property(form.selected, "name", "btnFirst")  # not through the panel's rows
    assert app.properties.current == "btnFirst"
    form.add_control("Button", 352, 76, 152, 28)  # gets the free name Button1
    assert (form.design.control("Button1")["top"], form.design.control("btnFirst")["top"]) == (76, 40)
