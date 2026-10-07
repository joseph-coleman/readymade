"""Drawing on an Image's pixels (needs Pillow)."""

import time
import tkinter as tk

import pytest

from readymade import Form, formfile, pictures
from readymade.controls import REGISTRY

pytestmark = [
    pytest.mark.usefixtures("display"),
    pytest.mark.skipif(not pictures.have_pillow(), reason="drawing needs Pillow"),
]

RED, GREEN, BLUE, WHITE, BLACK = "#ff0000", "#00ff00", "#0000ff", "#ffffff", "#000000"


@pytest.fixture
def make_form(tmp_path):
    forms = []

    def make(cls=Form, **props):
        design = formfile.FormDesign(name="Form1", width=400, height=300)
        spec = REGISTRY["Image"].new_spec("Image1", 0, 0, 100, 80)
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


def write_png(path, width, height, color):
    root = tk.Tk()
    photo = tk.PhotoImage(master=root, width=width, height=height)
    photo.put(color, to=(0, 0, width, height))
    photo.write(str(path), format="png")
    root.destroy()
    return path


def test_new_picture_and_shapes(make_form):
    form = make_form()
    image = form.Image1
    image.new(60, 40)
    assert image.picture_size == (60, 40)
    assert (image.width, image.height) == (60, 40)  # autosized
    assert image.pixel(0, 0) == WHITE
    image.rectangle(10, 10, 5, 4, color=RED, fill=GREEN)
    assert [image.pixel(x, 10) for x in (9, 10, 14, 15)] == [WHITE, RED, RED, WHITE]  # 5 pixels across
    assert image.pixel(12, 11) == GREEN
    assert image.pixel(12, 13) == RED and image.pixel(12, 14) == WHITE  # 4 down
    image.line(0, 39, 59, 39, color=BLUE)
    assert image.pixel(30, 39) == BLUE
    image.circle(45, 15, 5, fill=BLACK)
    assert image.pixel(45, 15) == BLACK
    image.point(1, 1, color=RED)
    assert image.pixel(1, 1) == RED
    image.polygon((20, 20), (30, 20), (25, 30), fill=BLUE, color="")
    assert image.pixel(25, 23) == BLUE
    image.clear("")
    assert image.pixel(25, 23) == ""  # transparent


def test_arc_angles_go_counter_clockwise_from_three_oclock(make_form):
    image = make_form().Image1
    image.new(100, 100)
    image.arc(0, 0, 100, 100, 0, 90, fill=RED, color="")  # the top right quarter
    assert image.pixel(70, 30) == RED
    assert image.pixel(70, 70) == WHITE and image.pixel(30, 30) == WHITE
    image.arc(0, 0, 100, 100, 0, -90, fill=BLUE, color="")  # clockwise: the bottom right
    assert image.pixel(70, 70) == BLUE
    image.arc(0, 0, 100, 100, 90, 90, style="chord", fill=GREEN, color="")  # top left
    assert image.pixel(20, 20) == GREEN and image.pixel(45, 45) == WHITE  # a chord, not a slice
    with pytest.raises(ValueError, match="style must be one of"):
        image.arc(0, 0, 10, 10, 0, 90, style="wedge")


def test_text(make_form, capsys):
    image = make_form().Image1
    image.new(200, 60)
    image.text(100, 30, "Hi", color=BLACK, font=("DejaVu Sans", 14, "bold"), anchor="center")
    image.text(0, 0, "x", font=("No Such Font", 10))
    assert "'No Such Font' wasn't found" in capsys.readouterr().err
    left = [x for x in range(200) if any(image.pixel(x, y) != WHITE for y in range(15, 45))]
    assert left and 80 < min(left) < 100 < max(left) < 120  # centered on 100
    with pytest.raises(ValueError, match="anchor must be one of"):
        image.text(0, 0, "x", anchor="middle")


def test_drawing_on_a_picture_from_a_file(make_form, tmp_path):
    write_png(tmp_path / "red.png", 20, 10, RED)
    image = make_form(picture="red.png").Image1
    assert image.picture_size == (20, 10)
    assert image.pixel(5, 5) == RED
    image.point(5, 5, color=BLUE)
    assert image.pixel(5, 5) == BLUE
    assert pictures.open_for_drawing(tmp_path / "red.png").getpixel((5, 5))[:3] == (255, 0, 0)  # the file is untouched
    image.picture = "red.png"  # loading it again drops the drawing
    assert image.pixel(5, 5) == RED


def test_drawing_with_no_picture_starts_blank_at_the_controls_size(make_form):
    image = make_form(sizing="normal", width=50, height=30).Image1
    image.point(2, 2, color=RED)
    assert image.picture_size == (50, 30)
    assert (image.pixel(0, 0), image.pixel(2, 2)) == (WHITE, RED)
    with pytest.raises(IndexError, match=r"\(50, 0\) is outside the picture, which is 50 x 30"):
        image.pixel(50, 0)


def test_the_screen_catches_up_once_per_handler(make_form, monkeypatch):
    form = make_form()
    image = form.Image1
    image.new(100, 100)
    form.root.update()
    shown = []
    real_show = type(image)._show
    monkeypatch.setattr(type(image), "_show", lambda self: (shown.append(1), real_show(self)))
    start = time.perf_counter()
    for i in range(20000):
        image.point(i % 100, i // 200, color=RED)
    elapsed = time.perf_counter() - start
    assert shown == []  # nothing yet: the handler hasn't finished
    form.root.update()
    assert len(shown) == 1
    assert elapsed < 5
    image.point(0, 99, color=BLUE)
    form.root.update()
    assert len(shown) == 2


def test_scaled_drawing(make_form):
    form = make_form(sizing="zoom", width=100, height=100)
    image = form.Image1
    image.new(50, 25)
    form.root.update()
    assert (image._photo.width(), image._photo.height()) == (100, 50)
    assert (image.width, image.height) == (100, 100)


def test_paste_and_save(make_form, tmp_path):
    write_png(tmp_path / "blue.png", 4, 4, BLUE)
    image = make_form().Image1
    image.new(20, 20)
    image.paste(10, 10, "blue.png", anchor="center")
    assert [image.pixel(x, 10) for x in (7, 8, 11, 12)] == [WHITE, BLUE, BLUE, WHITE]
    image.paste(20, 20, "blue.png", anchor="se")
    assert image.pixel(19, 19) == BLUE and image.pixel(15, 15) == WHITE
    image.save("out.png")  # in the program's folder
    image.save(tmp_path / "out.jpg")
    assert pictures.open_for_drawing(tmp_path / "out.png").getpixel((10, 10))[:3] == (0, 0, 255)
    assert pictures.open_for_drawing(tmp_path / "out.jpg").size == (20, 20)


def test_bad_colors(make_form):
    image = make_form().Image1
    image.new(10, 10)
    with pytest.raises(ValueError, match="isn't a color"):
        image.line(0, 0, 5, 5, color="bluish")


def test_without_pillow_drawing_says_what_to_install(make_form, monkeypatch):
    image = make_form().Image1
    monkeypatch.setattr(pictures, "_PILImage", None)
    with pytest.raises(ModuleNotFoundError, match=r"needs the Pillow library.*Add Library: pillow"):
        image.line(0, 0, 5, 5)


def test_drag_on_an_image(make_form):
    seen = []

    class Form1(Form):
        def Image1_drag(self, x, y):
            seen.append(("drag", x, y))

        def Image1_mousemove(self, x, y):
            seen.append(("move", x, y))

    form = make_form(Form1, sizing="normal")
    widget = form.Image1.widget
    widget.event_generate("<Motion>", x=3, y=4)
    widget.event_generate("<ButtonPress-1>", x=5, y=5)
    widget.event_generate("<B1-Motion>", x=8, y=9)
    widget.event_generate("<ButtonRelease-1>", x=8, y=9)
    for _ in range(5):
        form.root.update()
    assert ("move", 3, 4) in seen and ("drag", 8, 9) in seen
