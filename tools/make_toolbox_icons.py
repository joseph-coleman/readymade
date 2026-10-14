"""Draw the Toolbox's icons: readymade/ide/icons/{light,dark}/{Tool}-{size}.png.

Each icon is drawn on a 16 x 16 grid, at 10 times that size, then shrunk (for smooth edges)
to 20 pixels, and 40 for high-DPI screens. The light set is for the Light theme's gray
buttons, the dark set for Dark's. Run it after changing a drawing (it needs Pillow; the IDE
doesn't):

    python tools/make_toolbox_icons.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "readymade" / "ide" / "icons"
SIZES = (20, 40)
GRID = 16
SCALE = 10  # drawing pixels per grid unit
WIDTH = 1.2  # outline width, in grid units

PALETTES = {
    "light": {"line": "#2b2b2b", "field": "#ffffff", "face": "#c9c9c9", "accent": "#2f6fd0", "soft": "#8c8c8c",
              "green": "#3a9a4a", "sun": "#e0a820", "red": "#d04040"},
    "dark": {"line": "#e4e4e4", "field": "#1e1e1e", "face": "#5c5c5c", "accent": "#6ea8fe", "soft": "#a8a8a8",
             "green": "#5cbf6a", "sun": "#f0c040", "red": "#f07070"},
}


class Pen:
    """Drawing in grid units."""

    def __init__(self, draw, colors):
        self.draw, self.c = draw, colors

    @staticmethod
    def _xy(points):
        return [(x * SCALE, y * SCALE) for x, y in points]

    def _width(self, width):
        return round((width or WIDTH) * SCALE)

    def rect(self, x0, y0, x1, y1, fill=None, line="line", width=None, radius=0):
        box = (x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE)
        self.draw.rounded_rectangle(box, radius * SCALE, fill=self.c.get(fill), outline=self.c.get(line),
                                    width=self._width(width) if line else 0)

    def oval(self, x0, y0, x1, y1, fill=None, line="line", width=None):
        self.draw.ellipse((x0 * SCALE, y0 * SCALE, x1 * SCALE, y1 * SCALE), fill=self.c.get(fill),
                          outline=self.c.get(line), width=self._width(width) if line else 0)

    def lines(self, *points, color="line", width=None):
        self.draw.line(self._xy(points), fill=self.c[color], width=self._width(width), joint="curve")

    def shape(self, *points, fill="line", line=None, width=None):
        self.draw.polygon(self._xy(points), fill=self.c.get(fill), outline=self.c.get(line),
                          width=self._width(width) if line else 0)


def pointer(p):
    p.shape((4, 1.5), (4, 13), (6.8, 10.4), (8.8, 14.5), (10.6, 13.6), (8.6, 9.6), (12.2, 9.6),
            fill="field", line="line")


def label(p):
    p.lines((3, 14), (8, 2), (13, 14), width=1.8)
    p.lines((5.2, 9.6), (10.8, 9.6), width=1.6)


def textbox(p):
    p.rect(1, 4, 15, 12, fill="field")
    p.lines((3.2, 8), (7.8, 8), color="soft", width=1.6)
    p.lines((10.5, 5.6), (10.5, 10.4), color="accent", width=1.3)
    p.lines((9.4, 5.6), (11.6, 5.6), color="accent", width=1)
    p.lines((9.4, 10.4), (11.6, 10.4), color="accent", width=1)


def frame(p):
    p.lines((3, 3.5), (1.5, 3.5), (1.5, 14), (14.5, 14), (14.5, 3.5), (9.6, 3.5))
    p.lines((4, 3.5), (8.6, 3.5), color="accent", width=1.8)


def tabstrip(p):
    p.rect(1.5, 5, 14.5, 14.5, fill="field")
    p.rect(1.5, 1.8, 6.2, 5.6, fill="field", radius=0.6)  # the tab in front
    p.rect(6.2, 2.8, 10.6, 5, fill="face", width=1)  # one behind
    p.lines((2.4, 5), (5.3, 5), color="field", width=1.4)  # (the front tab opens into its page)
    p.lines((4, 9), (12, 9), color="soft", width=1.2)
    p.lines((4, 11.6), (10, 11.6), color="soft", width=1.2)


def button(p):
    p.rect(1, 4.5, 15, 11.5, fill="face", radius=1.6)
    p.lines((5, 8), (11, 8), color="line", width=1.4)


def checkbox(p):
    p.rect(2.5, 2.5, 13.5, 13.5, fill="field")
    p.lines((5, 8.2), (7.3, 10.8), (11.4, 5.2), color="accent", width=2)


def optionbutton(p):
    p.oval(2.5, 2.5, 13.5, 13.5, fill="field")
    p.oval(5.6, 5.6, 10.4, 10.4, fill="accent", line=None)


def combobox(p):
    p.rect(1, 4.5, 15, 11.5, fill="field")
    p.rect(10, 4.5, 15, 11.5, fill="face")
    p.shape((10.9, 6.8), (14.1, 6.8), (12.5, 9.8))
    p.lines((2.8, 8), (7.6, 8), color="soft", width=1.4)


def listbox(p):
    p.rect(2, 1.5, 14, 14.5, fill="field")
    p.rect(2.6, 6.3, 13.4, 8.9, fill="accent", line=None)
    for y in (4.2, 11, 13):
        p.lines((4, y), (11.5, y), color="soft", width=1.1)


def treeview(p):
    p.lines((3.5, 4.5), (3.5, 12.5), color="soft", width=1)
    p.lines((3.5, 8.5), (6.5, 8.5), color="soft", width=1)
    p.lines((3.5, 12.5), (6.5, 12.5), color="soft", width=1)
    p.rect(1.5, 1.5, 6, 4.8, fill="accent", line=None)
    p.rect(6.5, 7, 11, 10, fill="field", width=1)
    p.rect(6.5, 11, 14.5, 14, fill="field", width=1)


def listview(p):
    p.rect(1, 2, 15, 14, fill="field")
    p.rect(1, 2, 15, 5, fill="face")
    p.lines((7.5, 2), (7.5, 14), width=1)
    p.rect(1.6, 8, 14.4, 10.2, fill="accent", line=None)
    for y in (6.8, 11.8):
        p.lines((2.6, y), (6, y), color="soft", width=1)
        p.lines((9, y), (13.4, y), color="soft", width=1)


def datatable(p):
    p.rect(1, 2, 15, 14, fill="field")
    p.rect(1, 2, 15, 5, fill="face")
    for x in (6, 10.5):
        p.lines((x, 2), (x, 14), width=1)
    for y in (8, 11):
        p.lines((1, y), (15, y), width=1)
    p.rect(6, 8, 10.5, 11, fill=None, line="accent", width=1.4)  # the cell cursor


def calendar(p):
    p.rect(1.5, 2.5, 14.5, 14, fill="field")
    p.rect(1.5, 2.5, 14.5, 5.5, fill="accent")  # the month's band
    for x in (4.5, 11.5):
        p.lines((x, 1), (x, 4), width=1.3)  # the rings
    for row, y in enumerate((7.6, 10, 12.4)):
        for column, x in enumerate((4, 6.7, 9.4, 12)):
            if (row, column) == (1, 2):
                p.oval(x - 1.1, y - 1.1, x + 1.1, y + 1.1, fill="accent", line=None)  # the chosen day
            else:
                p.rect(x - 0.6, y - 0.5, x + 0.6, y + 0.5, fill="soft", line=None)


def datepicker(p):
    p.rect(1, 4.5, 15, 11.5, fill="field")
    p.lines((2.6, 8), (6.8, 8), color="soft", width=1.4)
    p.rect(8.6, 4.5, 15, 11.5, fill="face")  # the drop-down button, as a ComboBox's...
    p.rect(9.8, 5.7, 13.8, 10.5, fill="field", width=0.8)  # ...with a calendar on it
    p.rect(9.8, 5.7, 13.8, 7.4, fill="accent", line=None)
    p.rect(9.8, 5.7, 13.8, 10.5, fill=None, width=0.8)


def scrollbar(p):
    p.rect(1, 4.5, 15, 11.5, fill="face")
    p.shape((4.6, 5.8), (4.6, 10.2), (1.9, 8))
    p.shape((11.4, 5.8), (11.4, 10.2), (14.1, 8))
    p.rect(6.2, 6, 9.8, 10, fill="field", width=1)


def slider(p):
    p.rect(1.5, 7, 14.5, 9, fill="soft", line=None)
    p.shape((6, 3.4), (10, 3.4), (10, 9.6), (8, 11.8), (6, 9.6), fill="accent", line="line", width=1)
    for x in (2, 8, 14):
        p.lines((x, 13), (x, 14.8), width=1.1)


def updown(p):
    p.rect(1.2, 2.5, 10.4, 13.5, fill="field")
    p.lines((3, 8), (7.6, 8), color="soft", width=1.4)
    p.rect(10.4, 2.5, 15, 13.5, fill="face")
    p.shape((11.2, 7.2), (14.2, 7.2), (12.7, 4.2))
    p.shape((11.2, 8.8), (14.2, 8.8), (12.7, 11.8))


def progressbar(p):
    p.rect(1, 5, 15, 11, fill="field")
    p.rect(2.2, 6.2, 10, 9.8, fill="accent", line=None)


def image(p):
    p.rect(1.5, 2.5, 14.5, 13.5, fill="field")
    p.shape((2.4, 12.6), (6.4, 6.8), (9, 10), (11, 7.8), (13.6, 12.6), fill="green")
    p.oval(9.6, 3.8, 12.4, 6.6, fill="sun", line=None)


def canvas(p):
    p.rect(1.5, 1.5, 14.5, 14.5, fill="field")
    p.oval(3.3, 3.3, 8.9, 8.9, line="accent", width=1.3)
    p.shape((7, 12.8), (13.2, 12.8), (10.1, 7.4), fill=None, line="red", width=1.3)


def grid(p):
    p.rect(1.5, 1.5, 14.5, 14.5, fill="field")
    p.rect(5.8, 5.8, 10.2, 10.2, fill="accent", line=None)
    for at in (5.8, 10.2):
        p.lines((at, 1.5), (at, 14.5), width=1)
        p.lines((1.5, at), (14.5, at), width=1)


def timer(p):
    p.oval(1.5, 1.5, 14.5, 14.5, fill="field")
    p.lines((8, 8), (8, 4), width=1.5)
    p.lines((8, 8), (11, 8), width=1.5)
    p.oval(7.2, 7.2, 8.8, 8.8, fill="line", line=None)


def unknown(p):
    """A control type without its own icon (one from a library, say)."""
    p.rect(2, 4, 14, 12, fill="face", radius=1)
    for x in (5, 8, 11):
        p.oval(x - 0.8, 7.2, x + 0.8, 8.8, fill="line", line=None)


ICONS = {"Pointer": pointer, "Label": label, "TextBox": textbox, "Frame": frame, "TabStrip": tabstrip, "Button": button,
         "CheckBox": checkbox, "OptionButton": optionbutton, "ComboBox": combobox, "ListBox": listbox, "TreeView": treeview, "ListView": listview, "DataTable": datatable, "Calendar": calendar, "DatePicker": datepicker,
         "ScrollBar": scrollbar, "Slider": slider, "UpDown": updown, "ProgressBar": progressbar, "Image": image,
         "Canvas": canvas, "Grid": grid, "Timer": timer, "Unknown": unknown}


def main():
    for theme, colors in PALETTES.items():
        folder = OUT / theme
        folder.mkdir(parents=True, exist_ok=True)
        for name, drawing in ICONS.items():
            big = Image.new("RGBA", (GRID * SCALE, GRID * SCALE), (0, 0, 0, 0))
            drawing(Pen(ImageDraw.Draw(big), colors))
            for size in SIZES:
                big.resize((size, size), Image.Resampling.LANCZOS).save(folder / f"{name}-{size}.png", optimize=True)
    print(f"{len(ICONS) * len(PALETTES) * len(SIZES)} icons in {OUT}")


if __name__ == "__main__":
    main()
