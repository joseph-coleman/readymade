"""The Image control, picture loading (with and without Pillow), app_path, bundling pictures
and other files into Make EXE, and choosing a picture in the designer."""

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

import pytest

from readymade import Form, app_path, formfile, package, pictures
from readymade import form as form_module
from readymade.controls import REGISTRY
from readymade.ide.editors import bring_in
from readymade.project import Project

pytestmark = pytest.mark.usefixtures("display")


def write_png(path, width=20, height=10, colour="#ff0000"):
    root = tk.Tk()
    try:
        photo = tk.PhotoImage(master=root, width=width, height=height)
        photo.put(colour, to=(0, 0, width, height))
        path.parent.mkdir(parents=True, exist_ok=True)
        photo.write(str(path), format="png")
    finally:
        root.destroy()
    return path


@pytest.fixture(params=["pillow", "tk"])
def loader(request, monkeypatch):
    """Run the test with Pillow (when installed) and with Tk alone."""
    if request.param == "tk":
        monkeypatch.setattr(pictures, "_PILImage", None)
    elif pictures._PILImage is None:
        pytest.skip("Pillow isn't installed")
    return request.param


def make_form(folder, **props):
    design = formfile.FormDesign(name="Form1")
    spec = REGISTRY["Image"].new_spec("Image1", 8, 8)
    spec.update(props)
    design.controls.append(spec)
    formfile.save(design, folder / "Form1.form")
    form = Form(folder / "Form1.form")
    form.show()
    form.root.update()
    return form


def shown_size(image):
    photo = image._photo
    return (photo.width(), photo.height()) if photo else None


def test_picture_relative_to_the_programs_folder(tmp_path, loader):
    write_png(tmp_path / "images" / "logo.png")
    form = make_form(tmp_path, picture="images/logo.png")
    try:
        assert shown_size(form.Image1) == (20, 10)
        assert form.Image1.widget["text"] == ""
    finally:
        form.root.destroy()


def test_autosize_gives_the_control_the_pictures_size(tmp_path, loader):
    write_png(tmp_path / "small.png", 20, 10)
    write_png(tmp_path / "big.png", 60, 30)
    form = make_form(tmp_path, picture="small.png", width=96, height=96)
    image = form.Image1
    try:
        assert image.sizing == "autosize"
        assert (image.width, image.height) == (20, 10)
        form.root.update()
        assert (image.widget.winfo_width(), image.widget.winfo_height()) == (20, 10)
        image.width = 200  # the picture decides
        assert image.width == 20
        image.picture = "big.png"
        assert (image.width, image.height) == (60, 30)
        image.border = True
        assert (image.width, image.height) == (62, 32)
        image.picture = "missing.png"  # keeps its size
        assert (image.width, image.height) == (62, 32)
    finally:
        form.root.destroy()


@pytest.mark.parametrize("sizing, anchor", [("normal", "nw"), ("center", "center")])
def test_own_size_in_a_fixed_control(tmp_path, loader, sizing, anchor):
    write_png(tmp_path / "logo.png")
    form = make_form(tmp_path, picture="logo.png", sizing=sizing, width=96, height=50)
    try:
        assert (form.Image1.width, form.Image1.height) == (96, 50)
        assert shown_size(form.Image1) == (20, 10)
        assert str(form.Image1.widget["anchor"]) == anchor
    finally:
        form.root.destroy()


def test_stretch_follows_the_controls_size(tmp_path, loader):
    write_png(tmp_path / "logo.png")
    form = make_form(tmp_path, picture="logo.png", sizing="stretch", width=40, height=40)
    try:
        assert shown_size(form.Image1) == (40, 40)
        form.Image1.width, form.Image1.height = 60, 20
        assert shown_size(form.Image1) == (60, 20)
        form.Image1.border = True
        assert shown_size(form.Image1) == (58, 18)
        form.Image1.sizing = "normal"
        assert shown_size(form.Image1) == (20, 10)
        with pytest.raises(ValueError, match="sizing must be one of"):
            form.Image1.sizing = "fill"
    finally:
        form.root.destroy()


def test_zoom_keeps_the_pictures_shape(tmp_path, loader):
    write_png(tmp_path / "logo.png", 20, 10)
    form = make_form(tmp_path, picture="logo.png", sizing="zoom", width=40, height=40)
    try:
        assert shown_size(form.Image1) == (40, 20)
        assert str(form.Image1.widget["anchor"]) == "center"
        form.Image1.width, form.Image1.height = 100, 15
        assert shown_size(form.Image1) == (30, 15)
    finally:
        form.root.destroy()


def test_tk_alone_scales_in_whole_steps(tmp_path, monkeypatch):
    monkeypatch.setattr(pictures, "_PILImage", None)
    write_png(tmp_path / "logo.png", 20, 20)
    form = make_form(tmp_path, picture="logo.png", sizing="stretch", width=50, height=10)
    try:
        assert shown_size(form.Image1) == (50, 10)  # 5/2 across, 1/2 down
        form.Image1.sizing = "zoom"
        assert shown_size(form.Image1) == (10, 10)  # 1/2: as big as fits
        form.Image1.width, form.Image1.height = 33, 33
        assert shown_size(form.Image1) == (33, 33)  # 13/8 (eighths at most)
        form.Image1.width, form.Image1.height = 34, 34
        assert shown_size(form.Image1) == (34, 34)  # 5/3, which Tk rounds up from 33.3
        form.Image1.width, form.Image1.height = 33, 33
        assert shown_size(form.Image1) == (33, 33)  # so here 5/3 would be too big: 13/8
        form.Image1.width, form.Image1.height = 1, 1
        assert shown_size(form.Image1) == (1, 1)  # 1/20
    finally:
        form.root.destroy()


def test_fit():
    assert pictures.fit((20, 10), (40, 40)) == (40, 20)
    assert pictures.fit((300, 600), (100, 100)) == (50, 100)


def test_code_can_show_any_file_and_none(tmp_path, loader):
    elsewhere = write_png(tmp_path / "elsewhere" / "photo.png", 30, 15)
    program = tmp_path / "program"
    program.mkdir()
    form = make_form(program)
    try:
        assert shown_size(form.Image1) is None
        form.Image1.picture = elsewhere  # a full path (a Path works too), never copied
        assert shown_size(form.Image1) == (30, 15)
        assert form.Image1.picture == str(elsewhere)
        assert not (program / "images").exists()
        form.Image1.picture = ""
        assert shown_size(form.Image1) is None
    finally:
        form.root.destroy()


def test_a_missing_picture_is_reported_not_fatal(tmp_path, capsys):
    form = make_form(tmp_path, picture="nope.png")
    try:
        assert shown_size(form.Image1) is None
        assert "Image1: can't show the picture 'nope.png'" in capsys.readouterr().err
    finally:
        form.root.destroy()


def test_app_path(tmp_path, monkeypatch):
    monkeypatch.setattr(form_module, "_folder", None)
    monkeypatch.setattr(sys, "argv", [str(tmp_path / "Form1.py")])
    assert app_path() == tmp_path
    assert app_path("data", "prices.csv") == tmp_path / "data" / "prices.csv"
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path / "bundle"), raising=False)
    assert app_path("x") == tmp_path / "bundle" / "x"
    form_module.set_app_path(tmp_path / "project")
    assert app_path() == tmp_path / "project"


def test_running_a_project_sets_app_path(tmp_path):
    project = Project.create(tmp_path / "Shop")
    (project.folder / "Form1.py").write_text(
        "from readymade import Form, app_path\n\n\nclass Form1(Form):\n"
        "    def Form_load(self):\n        print('APP', app_path())\n        self.close()\n",
        encoding="utf-8")
    root = Path(__file__).parent.parent
    env = dict(os.environ, PYTHONPATH=str(root))
    done = subprocess.run([sys.executable, "-m", "readymade.run", str(project.folder)], cwd=tmp_path,
                          env=env, capture_output=True, text=True, timeout=30, check=False)
    assert f"APP {project.folder}" in done.stdout, done.stderr


def test_make_exe_bundles_pictures_and_included_files(tmp_path):
    project = Project.create(tmp_path / "Shop", first_form="Main")
    write_png(project.folder / "images" / "logo.png")
    (project.folder / "data").mkdir()
    (project.folder / "data" / "prices.csv").write_text("x\n")
    (project.folder / "sounds").mkdir()
    for name in ("a.wav", "b.wav", "c.txt"):
        (project.folder / "sounds" / name).write_text("")
    (project.folder / "readme.txt").write_text("")
    design = formfile.load(project.folder / "Main.form")
    for name, picture in [("Logo", "images/logo.png"), ("Again", "images/logo.png"), ("Gone", "images/gone.png")]:
        design.controls.append({**REGISTRY["Image"].new_spec(name, 0, 0), "picture": picture})
    formfile.save(design, project.folder / "Main.form")
    project.set_setting("include", ["data", "sounds/*.wav", "readme.txt", "nothing/*.x"])

    files, missing = package.bundled_files(project)
    folder = project.folder
    assert files == [
        (folder / "Main.form", "."),
        (folder / "images" / "logo.png", "images"),  # once, though two controls show it
        (folder / "data", "data"),
        (folder / "sounds" / "a.wav", "sounds"),
        (folder / "sounds" / "b.wav", "sounds"),
        (folder / "readme.txt", "."),
    ]
    assert missing == ["Main.Gone.picture: images/gone.png", "include: nothing/*.x"]
    launcher = package.write_launcher(project, "Main")
    args = package.pyinstaller_args(project, launcher, "/opt/readymade")
    assert f"{folder / 'images' / 'logo.png'}{os.pathsep}images" in args


def test_bring_in_copies_outside_files_into_images(tmp_path):
    project = tmp_path / "project"
    inside = write_png(project / "art" / "a.png")
    assert bring_in(project, inside) == "art/a.png"
    outside = write_png(tmp_path / "Downloads" / "a.png", colour="#00ff00")
    assert bring_in(project, outside) == "images/a.png"
    assert (project / "images" / "a.png").read_bytes() == outside.read_bytes()
    assert bring_in(project, outside) == "images/a.png"  # the same file again: no second copy
    other = write_png(tmp_path / "Desktop" / "a.png", colour="#0000ff")
    assert bring_in(project, other) == "images/a-2.png"
    assert sorted(p.name for p in (project / "images").iterdir()) == ["a-2.png", "a.png"]


def test_choosing_a_picture_in_the_designer(tmp_path, monkeypatch):
    from readymade.ide.app import App

    picture = write_png(tmp_path / "Pictures" / "cat.png", 16, 16)
    root = tk.Tk()
    app = App(root, tmp_path / "Pets")
    try:
        editor = app.form
        editor.add_control("Image", 16, 16)
        app.root.update()
        name = editor.selected
        assert editor.surface.controls[name].widget["text"] == "(no picture)"
        panel = app.properties
        assert panel.app.file_types_for(name, "picture") == pictures.FILE_TYPES
        asked = {}
        monkeypatch.setattr(filedialog, "askopenfilename", lambda **kw: asked.update(kw) or str(picture))
        panel._choose("picture")
        assert Path(asked["initialdir"]) == app.project.folder
        assert editor._spec(name)["picture"] == "images/cat.png"
        assert panel._rows["picture"][0].get() == "images/cat.png"
        assert (app.project.folder / "images" / "cat.png").exists()
        control = editor.surface.controls[name]
        assert control._photo is not None and control.widget["text"] == ""
        # Autosized: the design takes the picture's size, and there's nothing to resize.
        assert (editor._spec(name)["width"], editor._spec(name)["height"]) == (16, 16)
        assert panel._rows["width"][0].get() == "16"
        assert not control.resizable
        editor.set_property(name, "sizing", "stretch")
        control = editor.surface.controls[name]
        assert control.resizable
        editor.set_property(name, "width", "64")
        assert editor.surface.controls[name]._photo.width() == 64
        editor.undo()
        editor.undo()
        editor.undo()
        assert editor._spec(name)["picture"] == ""
    finally:
        app.stop()
        root.destroy()
