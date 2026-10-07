"""Loading pictures for the Image and Canvas controls, and drawing on them.

Tk shows PNG, GIF and PPM files itself. With Pillow installed in the project's
environment, any format Pillow reads works (JPEG, BMP, ...), and scaled pictures
are smooth; without it, scaling is in whole steps (x2, 1/2, ...). Drawing on an
Image's pixels always needs Pillow, whose ImageDraw does the work.
"""

from __future__ import annotations

import functools
import math
import os
import shutil
import subprocess
import sys
import tkinter as tk
from fractions import Fraction

from readymade import appearance

try:
    from PIL import Image as _PILImage
    from PIL import ImageColor as _ImageColor
    from PIL import ImageFont as _ImageFont
    from PIL import ImageTk as _ImageTk
except ImportError:  # optional
    _PILImage = _ImageColor = _ImageFont = _ImageTk = None

FILE_TYPES = {"Pictures": "*.png *.gif *.jpg *.jpeg *.bmp *.ppm *.webp", "All files": "*"}


def have_pillow():
    return _PILImage is not None


def need_pillow(what):
    if not have_pillow():
        raise ModuleNotFoundError(
            f"{what} needs the Pillow library. Add it to the project with Project > Add Library: pillow",
            name="PIL")


def load(path, size=None, keep_shape=False, master=None):
    """(Tk image, the picture's own size) for the picture at path, scaled to size (width,
    height) if given; with keep_shape, scaled to fit inside size instead. Raises OSError
    (or tk.TclError) if it can't be read."""
    if have_pillow():
        with _PILImage.open(path) as picture:
            picture.load()
            return to_photo(picture, size, keep_shape, master), picture.size
    photo = tk.PhotoImage(master=master, file=str(path))
    natural = (photo.width(), photo.height())
    if size:
        photo = _scale(photo, size, keep_shape)
    return photo, natural


def to_photo(picture, size=None, keep_shape=False, master=None):
    """A Tk image of a Pillow image, scaled as for load."""
    if size:
        if keep_shape:
            size = fit(picture.size, size)
        if size != picture.size:
            picture = picture.resize(size, _PILImage.Resampling.LANCZOS)
    return _ImageTk.PhotoImage(picture, master=master)


def fit(natural, box):
    """The largest size inside box with the shape of natural."""
    scale = min(box[0] / max(1, natural[0]), box[1] / max(1, natural[1]))
    return max(1, round(natural[0] * scale)), max(1, round(natural[1] * scale))


def _scale(photo, size, keep_shape=False):
    """Tk alone can only zoom and shrink by whole numbers, so get as close as that allows."""
    have = (photo.width(), photo.height())
    if keep_shape:
        # One ratio for both directions, the largest that fits (Tk rounds shrunk sizes up).
        scale = min(Fraction(want, max(1, n)) for want, n in zip(size, have))
        ratio = Fraction(0)
        for d in range(1, 9):
            n = int(scale * d)
            while n and any(math.ceil(h * n / d) > want for want, h in zip(size, have)):
                n -= 1
            ratio = max(ratio, Fraction(n, d))
        if ratio == 0:  # smaller than 1/8: shrink by a whole number
            ratio = Fraction(1, math.ceil(1 / scale))
        factors = [(ratio.numerator, ratio.denominator)] * 2
    else:
        factors = []
        for want, n in zip(size, have):
            ratio = Fraction(want, max(1, n)).limit_denominator(8)
            factors.append((max(1, ratio.numerator), max(1, ratio.denominator)))
    (zx, sx), (zy, sy) = factors
    if zx > 1 or zy > 1:
        photo = photo.zoom(zx, zy)
    if sx > 1 or sy > 1:
        photo = photo.subsample(sx, sy)
    return photo


# ----- drawing (Pillow only) -----

def open_for_drawing(path):
    """A Pillow image of the file, ready to draw on."""
    with _PILImage.open(path) as picture:
        return picture.convert("RGBA")


def blank(size, background="#ffffff"):
    return _PILImage.new("RGBA", size, rgba(background))


def drawer(picture):
    from PIL import ImageDraw

    return ImageDraw.Draw(picture)


def save(picture, path):
    """Save a Pillow image; the file name's extension chooses the format."""
    if os.path.splitext(str(path))[1].lower() in (".jpg", ".jpeg", ".bmp"):  # no transparency: put it on white
        flat = blank(picture.size)
        flat.alpha_composite(picture)
        picture = flat.convert("RGB")
    picture.save(path)


@functools.lru_cache(maxsize=256)
def rgba(color):
    """(r, g, b, a) for "#rrggbb" (or a color name); "" is transparent."""
    if not color:
        return (0, 0, 0, 0)
    try:
        return _ImageColor.getcolor(color, "RGBA")
    except ValueError:
        raise ValueError(f"{color!r} isn't a color; use \"#rrggbb\", like \"#ff0000\" for red") from None


def to_hex(value):
    """"#rrggbb" for a pixel; "" for a transparent one."""
    if len(value) == 4 and value[3] == 0:
        return ""
    return "#{:02x}{:02x}{:02x}".format(*value[:3])


@functools.lru_cache(maxsize=64)
def font(spec=None, pixels_per_point=1.0):
    """A Pillow font for a font like ("Arial", 12, "bold"): a family name or a font file,
    a size in points, and optionally "bold" and/or "italic". A family that isn't found
    gets Pillow's own font, at the size asked for."""
    family, size, styles = _font_parts(spec)
    size = max(1, round(size * pixels_per_point))
    path = _font_file(family, styles) if family else None
    if path:
        try:
            return _ImageFont.truetype(path, size)
        except OSError:
            pass
    if family:
        print(f"Font {family!r} wasn't found, so Pillow's own font is used instead.", file=sys.stderr)
    return _ImageFont.load_default(size)


def _font_parts(spec):
    family, size, styles = appearance.parse_font(spec)
    return family or None, size or 12, frozenset(styles) & {"bold", "italic"}


def _font_file(family, styles):
    """The file for a font family in a style, found the way each system does it."""
    if os.path.isfile(family):
        return family
    style = " ".join(s.capitalize() for s in sorted(styles)) or "Regular"
    if shutil.which("fc-match"):  # Linux, and wherever fontconfig is installed
        found = subprocess.run(["fc-match", "-f", "%{file}\n%{family}", f"{family}:style={style}"],
                               capture_output=True, text=True, check=False).stdout.splitlines()
        # fc-match always answers with something; only take it if it's the family asked for.
        if len(found) == 2 and family.lower() in found[1].lower():
            return found[0]
    if sys.platform == "win32":
        import winreg

        names = [f"{family} {style} (TrueType)", f"{family} {style} (OpenType)"] if styles else []
        names += [f"{family} (TrueType)", f"{family} (OpenType)"]
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts") as key:
                for name in names:
                    try:
                        return winreg.QueryValueEx(key, name)[0]  # Pillow finds it in the Fonts folder
                    except OSError:
                        continue
        except OSError:
            pass
    # Pillow looks for file names in the system's font folders (macOS: "Arial Bold.ttf").
    for name in (f"{family} {style}.ttf", f"{family}.ttf", f"{family}.ttc"):
        try:
            _ImageFont.truetype(name, 12)
            return name
        except OSError:
            continue
    return None
