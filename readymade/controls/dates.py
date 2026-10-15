"""The date controls: a Calendar (a month to choose a day in, as VB's MonthView) and a
DatePicker (a date field whose month drops down, as VB's DTPicker). Their values are
datetime.date; a DatePicker's can be None, if allow_empty.

The month is drawn on a Canvas (MonthGrid), so it looks alike everywhere. Dropped down, it's
placed inside the form's own window (DropMonth), not in a window of its own: a separate
window takes the keyboard differently on each system (a Mac's hardly at all).
"""

from __future__ import annotations

import calendar
import datetime
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from readymade import appearance, keys
from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip

FIRST_DAYS = ("sunday", "monday")
ISO = "%Y-%m-%d"  # 2026-10-14: a date's usual look, and what a CSV file holds
_ACCENT = "#2f6fd0"  # the chosen day, if the theme has no highlight color
_DIM = "#9a9a9a"  # days of the months either side
_OUT = "#cfcfcf"  # days that can't be chosen (before min, after max)


def to_date(value, name="value"):
    """value as a datetime.date (None for None or ""): a date, a datetime, or a string like
    "2026-10-14". ValueError if it isn't one."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    try:
        return datetime.date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValueError(f"{name}: {value!r} isn't a date (year-month-day: 2026-10-14)") from None


def read_date(text, format=ISO, name="value"):
    """A typed date: in format (strftime's codes), as year-month-day, or as people write them:
    Oct 18, 2026; October 18 2026; 18 Oct 2026; Sun Oct 18 (this year); 10/18/2026, 10-18-26
    and 10/18 (month first, unless format puts the day first: then 18/10/2026); today,
    tomorrow, yesterday. ValueError if it isn't one."""
    text = text.strip()
    try:
        return datetime.datetime.strptime(text, _for_reading(format)).date()
    except ValueError:
        pass
    try:
        return datetime.date.fromisoformat(text)
    except ValueError:
        pass
    day = _read_loosely(text, day_first=_day_first(format))
    if day is None:
        examples = dict.fromkeys([show(datetime.date(2026, 10, 14), format), "Oct 14, 2026", "10/14/2026"])
        raise ValueError(f"{name}: {text!r} isn't a date (as {', or '.join(examples)})")
    return day


_WORDS = {"today": 0, "tomorrow": 1, "yesterday": -1}
_ENGLISH_MONTHS = ("january february march april may june july august september october november "
                   "december").split()


def _month_named(word):
    """The month a word names (October, Oct, Oct.: the locale's names, or English), or None."""
    word = word.lower().rstrip(".")
    if len(word) < 3:
        return None
    for number in range(1, 13):
        names = (calendar.month_name[number].lower(), calendar.month_abbr[number].lower(), _ENGLISH_MONTHS[number - 1])
        if any(name.startswith(word) for name in names if name):  # (Oct, Octo, October; not Octember)
            return number
    return None


def _day_first(format):
    """Whether format writes the day before the month (18/10/2026: as most of the world does)."""
    day, month = re.search(r"%[-#]?[de]", format), re.search(r"%[-#]?[mbB]", format)
    return bool(day and month and day.start() < month.start())


def _year(text):
    year = int(text)
    if len(text) <= 2:  # (26: 2026; 99: 1999, as strftime's %y reads them)
        year += 2000 if year < 69 else 1900
    return year


def _read_loosely(text, day_first=False):
    """A date as people write them (see read_date), or None."""
    words = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text.lower().replace(",", " ")).split()
    if len(words) == 1 and words[0] in _WORDS:
        return datetime.date.today() + datetime.timedelta(days=_WORDS[words[0]])
    weekdays = {name.lower() for name in (*calendar.day_name, *calendar.day_abbr)} | {
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
        "mon", "tue", "tues", "wed", "thu", "thur", "thurs", "fri", "sat", "sun"}
    if words and words[0].rstrip(".") in weekdays:  # ("Sun Oct 18": the day's name is left out)
        words = words[1:]
    year, month, day = datetime.date.today().year, None, None
    try:
        if len(words) in (2, 3) and _month_named(words[0]) and words[1].isdigit():  # Oct 18 (2026)
            month, day = _month_named(words[0]), int(words[1])
            year = _year(words[2]) if len(words) == 3 else year
        elif len(words) in (2, 3) and words[0].isdigit() and _month_named(words[1]):  # 18 Oct (2026)
            month, day = _month_named(words[1]), int(words[0])
            year = _year(words[2]) if len(words) == 3 else year
        elif len(words) == 1:
            parts = re.split(r"[/.-]", words[0])
            if 2 <= len(parts) <= 3 and all(part.isdigit() for part in parts):
                if len(parts[0]) == 4:  # 2026/10/18
                    year, month, day = int(parts[0]), int(parts[1]), int(parts[2]) if len(parts) == 3 else 1
                else:  # 10/18/2026 (or 18/10/2026, day first; or month first, if that can't be)
                    first, second = int(parts[0]), int(parts[1])
                    month, day = (second, first) if day_first else (first, second)
                    if month > 12 >= day:
                        month, day = day, month
                    year = _year(parts[2]) if len(parts) == 3 else year
        if month is None:
            return None
        return datetime.date(year, month, day)
    except ValueError:  # (October 32nd, and the like)
        return None


TIME_FORMAT = "%-I:%M %p"  # 9:30 PM (%-I: the hour without a leading zero, as on every system here)
DATETIME_FORMAT = "%Y-%m-%d %-I:%M %p"  # 2026-10-14 9:30 PM
_NO_PAD = re.compile(r"%[-#]([dmHIMSjUW])")  # %-d (Linux's and macOS's way) or %#d (Windows'): no leading zero
_TIME_CODES = re.compile(r"%[-#]?[HIMSpXcTR]")
_TIME = re.compile(r"^(\d{1,2})(?:[:.h]?(\d{2}))?(?:[:.](\d{2}))?\s*([ap])\.?\s*(?:m\.?)?$", re.IGNORECASE)
_TIME_24 = re.compile(r"^(\d{1,2})(?:[:.h]?(\d{2}))?(?:[:.](\d{2}))?$")


def show(value, format):
    """value (a date, time or datetime) in format, strftime's codes; %-d, %-I and the like
    leave out the leading zero (5, not 05) on every system, not only where strftime does."""
    def unpadded(match):
        return value.strftime("%" + match.group(1)).lstrip("0") or "0"
    return value.strftime(_NO_PAD.sub(unpadded, format))


def _for_reading(format):
    """format as strptime takes it (it reads 5 or 05 for %d anyway)."""
    return _NO_PAD.sub(r"%\1", format)


def has_time(format):
    """Whether format shows a time (%H, %I, %M, %p...)."""
    return bool(_TIME_CODES.search(format))


def _now():
    now = datetime.datetime.now()
    return datetime.time(now.hour, now.minute)


def read_time(text, format=TIME_FORMAT, name="value"):
    """A typed time: in format, or as people write them: 9:30 PM, 9:30pm, 9.30 p.m., 9 pm,
    21:30, 2130, 9 (9:00). ValueError if it isn't one."""
    text = text.strip()
    try:
        return datetime.datetime.strptime(text, _for_reading(format)).time()
    except ValueError:
        pass
    for pattern in (_TIME, _TIME_24):
        match = pattern.match(text)
        if not match:
            continue
        hour, minute, second = int(match.group(1)), int(match.group(2) or 0), int(match.group(3) or 0)
        if pattern is _TIME:
            if not 1 <= hour <= 12:
                break
            hour = hour % 12 + (12 if match.group(4).lower() == "p" else 0)
        try:
            return datetime.time(hour, minute, second)
        except ValueError:
            break
    example = show(datetime.time(21, 30), format)
    raise ValueError(f"{name}: {text!r} isn't a time (as {example})") from None


def read_datetime(text, format=DATETIME_FORMAT, name="value"):
    """A typed date and time: in format, or year-month-day and a time (2026-10-14 21:30, or
    2026-10-14 9:30 PM). ValueError if it isn't one."""
    text = text.strip()
    try:
        return datetime.datetime.strptime(text, _for_reading(format))
    except ValueError:
        pass
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        pass
    date_format = format[:_TIME_CODES.search(format).start()].strip() if has_time(format) else format
    words = text.split()
    for cut in range(len(words) - 1, 0, -1):  # (the date first, then the time: "14 Oct 2026" "9pm")
        try:
            return datetime.datetime.combine(read_date(" ".join(words[:cut]), date_format or ISO),
                                             read_time(" ".join(words[cut:])))
        except ValueError:
            continue
    example = show(datetime.datetime(2026, 10, 14, 21, 30), format)
    raise ValueError(f"{name}: {text!r} isn't a date and time (as {example})")


def to_time(value, name="value"):
    """value as a datetime.time (None for None or ""): a time, a datetime's, or text like
    "21:30" or "9:30 PM". ValueError if it isn't one."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime.datetime):
        return value.time()
    if isinstance(value, datetime.time):
        return value
    if isinstance(value, str):
        return read_time(value, name=name)
    raise ValueError(f"{name}: {value!r} isn't a time (21:30, or 9:30 PM)")


def to_datetime(value, name="value"):
    """value as a datetime.datetime (None for None or ""): a datetime, a date (its midnight), or
    text like "2026-10-14 21:30". ValueError if it isn't one."""
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time())
    if isinstance(value, str):
        return read_datetime(value, name=name)
    raise ValueError(f"{name}: {value!r} isn't a date and time (2026-10-14 21:30)")


def times_between(step, first=None, last=None):
    """The times every step minutes through the day (from midnight), from first to last."""
    times = [datetime.time(minutes // 60, minutes % 60) for minutes in range(0, 24 * 60, max(1, step))]
    return [t for t in times if (first is None or t >= first) and (last is None or t <= last)]


def _nearest(times, time):
    if not times:
        return None
    minutes = time.hour * 60 + time.minute
    return min(range(len(times)), key=lambda i: abs(times[i].hour * 60 + times[i].minute - minutes))


def _check_format(format):
    try:
        shown = show(datetime.datetime(2026, 10, 14, 21, 30), format)
    except (ValueError, TypeError):
        raise ValueError(f"format: {format!r} isn't a date format (strftime's codes: %Y-%m-%d)") from None
    if not shown.strip():
        raise ValueError(f"format: {format!r} shows nothing of a date")
    return format


def _add_months(day, months):
    """day, months later (or earlier), on the same day of the month if it has one (else its last)."""
    year, month = divmod(day.year * 12 + day.month - 1 + months, 12)
    return day.replace(year=year, month=month + 1, day=min(day.day, calendar.monthrange(year, month + 1)[1]))


def _theme_colors(widget):
    """The theme's highlight and the text on it (a chosen row's colors), for the chosen day."""
    style = ttk.Style(widget)
    colors = []
    for option, fallback in (("background", _ACCENT), ("foreground", "#ffffff")):
        color = style.lookup("Treeview", option, ("selected",))
        try:
            widget.winfo_rgb(color)
        except tk.TclError:
            color = ""
        colors.append(color or fallback)
    return colors


# ----- the month, drawn -----

class MonthGrid:
    """A month to choose a day in, drawn on a Canvas: the month and year between arrows to the
    months either side, the days' initials, and six weeks of days. value is the chosen day.
    The arrow keys move it (Page Up/Down: a month; Home/End: the month's first and last day),
    and on_move(day) is told; a click, Enter or Space chooses it: on_choose(day, how), how
    being "click" or "key".

    A click on the month's name shows the year's months, to go to one; on the year, a decade
    of years (the arrows then step a decade). Picking a year shows its months, picking a month
    its days. Arrows and Enter work there too, and Esc goes back to the days."""

    def __init__(self, parent, design=False, on_move=None, on_choose=None):
        self.canvas = tk.Canvas(parent, highlightthickness=1, bd=0, takefocus=0 if design else 1)
        self.value = datetime.date.today()
        self.shown = (self.value.year, self.value.month)
        self.view = "days"  # "days" (a month's), "months" (a year's) or "years" (a decade's, and one either side)
        self.design = design
        self.min = self.max = None
        self.firstday = "sunday"
        self.enabled = True
        self.back, self.fore = "#ffffff", "#000000"
        self.accent, self.accent_text = _theme_colors(self.canvas)
        self.set_font("")
        self.on_move, self.on_choose = on_move, on_choose
        canvas = self.canvas
        canvas.bind("<Configure>", lambda e: self.draw(), add="+")
        if not design:
            canvas.bind("<ButtonPress-1>", self._click, add="+")
            canvas.bind("<KeyPress>", self._key, add="+")
        self.paint(None, None)

    # ----- how it looks -----

    def set_font(self, font):
        """font as readymade writes it ("" for the usual): the days in it, the month in bold."""
        usual = tkfont.nametofont("TkDefaultFont", root=self.canvas).actual()
        spec = appearance.tk_font(font, usual) if font else (usual["family"], usual["size"])
        self.font = tkfont.Font(root=self.canvas, font=spec)
        self.bold = tkfont.Font(root=self.canvas, font=spec)
        self.bold.configure(weight="bold")
        self.draw()

    def paint(self, back, fore):
        self.back, self.fore = back or "#ffffff", fore or "#000000"
        self.canvas.configure(background=self.back, highlightbackground=self.back, highlightcolor=self.accent)
        self.draw()

    def size(self):
        """Its natural size: a day as wide as "28" and some, as tall as a line and some."""
        cell_w, cell_h = max(28, self.font.measure("28") + 14), self.font.metrics("linespace") + 8
        return 7 * cell_w + 2, self._head() + self._names() + 6 * cell_h + 2

    def _head(self):
        return self.bold.metrics("linespace") + 10

    def _names(self):
        return self.font.metrics("linespace") + 6

    def _calendar(self):
        return calendar.Calendar(6 if self.firstday == "sunday" else 0)

    def _weeks(self):
        """The six weeks shown: the month's, then the next month's days to fill them."""
        weeks = self._calendar().monthdatescalendar(*self.shown)
        while len(weeks) < 6:
            weeks.append([day + datetime.timedelta(days=7) for day in weeks[-1]])
        return weeks

    def _choosable(self, day):
        return self.enabled and (self.min is None or day >= self.min) and (self.max is None or day <= self.max)

    def _layout(self):
        canvas = self.canvas
        width, height = canvas.winfo_width(), canvas.winfo_height()
        if width <= 1:
            width, height = int(canvas.cget("width")), int(canvas.cget("height"))
        top = self._head() + self._names()
        return width, height, top, width / 7, max(1, (height - top) / 6)

    def draw(self):
        canvas = self.canvas
        canvas.delete("all")
        width, height, top, cell_w, cell_h = self._layout()
        year, month = self.shown
        gray = self.fore if self.enabled else _DIM
        head = self._head()
        if self.view == "days":
            title = [(calendar.month_name[month], "zoom-months"), (str(year), "zoom-years")]
        elif self.view == "months":
            title = [(str(year), "zoom-years")]
        else:
            start = year - year % 10
            title = [(f"{start}-{start + 9}", "")]
        self._draw_title(title, width, head, gray)
        # The arrows to the months (years, decades) either side: drawn, as an arrow character
        # isn't in every font.
        size = max(4, min(head, cell_w) * 0.22)
        for x, step in ((cell_w / 2, -1), (width - cell_w / 2, 1)):
            reachable = self.enabled and self._can_turn(step)
            canvas.create_polygon(x + step * size * 0.6, head / 2, x - step * size * 0.6, head / 2 - size,
                                  x - step * size * 0.6, head / 2 + size, fill=gray if reachable else _OUT)
        if self.view == "days":
            self._draw_days(top, cell_w, cell_h, gray)
        else:
            self._draw_picks(width, height, head, gray)

    def _draw_title(self, parts, width, head, color):
        """The month and year, side by side; each a click away from choosing another."""
        gap = self.bold.measure(" ")
        x = width / 2 - (sum(self.bold.measure(text) for text, _ in parts) + gap * (len(parts) - 1)) / 2
        for text, tag in parts:
            self.canvas.create_text(x, head / 2, text=text, font=self.bold, fill=color, anchor="w",
                                    tags=(tag,) if tag else ())
            if tag and self.enabled and not self.design:  # (a hand over it: it can be clicked)
                self.canvas.tag_bind(tag, "<Enter>", lambda e: self.canvas.configure(cursor="hand2"))
                self.canvas.tag_bind(tag, "<Leave>", lambda e: self.canvas.configure(cursor=""))
            x += self.bold.measure(text) + gap

    def _draw_days(self, top, cell_w, cell_h, gray):
        canvas, (_, month) = self.canvas, self.shown
        head = self._head()
        for column, weekday in enumerate(self._calendar().iterweekdays()):
            canvas.create_text((column + 0.5) * cell_w, head + self._names() / 2,
                               text=calendar.day_abbr[weekday][:2], font=self.font, fill=_DIM)
        today = datetime.date.today()
        radius = max(4, min(cell_w, cell_h) / 2 - 1)
        for row, week in enumerate(self._weeks()):
            for column, day in enumerate(week):
                x, y = (column + 0.5) * cell_w, top + (row + 0.5) * cell_h
                color = gray if day.month == month else _DIM
                if not self._choosable(day):
                    color = _OUT
                if day == self.value:
                    canvas.create_oval(x - radius, y - radius, x + radius, y + radius, fill=self.accent, width=0)
                    color = self.accent_text
                elif day == today:
                    canvas.create_oval(x - radius, y - radius, x + radius, y + radius, outline=self.accent, width=1)
                canvas.create_text(x, y, text=str(day.day), font=self.font, fill=color)

    def _picks(self):
        """The months or years view's twelve: [(label, (year, month) or year, choosable, in the
        decade)], four across and three down."""
        year, month = self.shown
        if self.view == "months":
            return [(calendar.month_abbr[m], (year, m), self._reachable(datetime.date(year, m, 1), 1), True)
                    for m in range(1, 13)]
        start = year - year % 10
        return [(str(y), y, 1 <= y <= 9999 and self._reachable(datetime.date(y, 1, 1), 12), start <= y <= start + 9)
                for y in range(start - 1, start + 11)]

    def _pick_cells(self, width, height, head):
        return width / 4, max(1, (height - head) / 3)

    def _draw_picks(self, width, height, head, gray):
        canvas = self.canvas
        cell_w, cell_h = self._pick_cells(width, height, head)
        year, month = self.shown
        current = (year, month) if self.view == "months" else year  # (the keyboard's, shown ringed)
        if self.value is None:
            chosen = None
        else:
            chosen = (self.value.year, self.value.month) if self.view == "months" else self.value.year
        for index, (label, key, choosable, inside) in enumerate(self._picks()):
            row, column = divmod(index, 4)
            x0, y0 = column * cell_w + 3, head + row * cell_h + 3
            x1, y1 = x0 + cell_w - 6, y0 + cell_h - 6
            color = (gray if inside else _DIM) if choosable else _OUT
            if key == chosen:
                canvas.create_rectangle(x0, y0, x1, y1, fill=self.accent, width=0)
                color = self.accent_text
            if key == current:
                canvas.create_rectangle(x0, y0, x1, y1, outline=self.accent, width=1)
            canvas.create_text((x0 + x1) / 2, (y0 + y1) / 2, text=label, font=self.font, fill=color)

    def _reachable(self, first, months):
        """Whether any day of the months from first (a month's first day) can be chosen."""
        last = _add_months(first, months) - datetime.timedelta(days=1)
        return (self.min is None or last >= self.min) and (self.max is None or first <= self.max)

    def _span(self):
        """The view's first day, and its length in months (a month, a year, a decade and two)."""
        year, month = self.shown
        if self.view == "days":
            return datetime.date(year, month, 1), 1
        if self.view == "months":
            return datetime.date(year, 1, 1), 12
        return datetime.date(max(1, year - year % 10 - 1), 1, 1), 144

    def _step(self):
        return {"days": 1, "months": 12, "years": 120}[self.view]

    def _can_turn(self, step):
        first, months = self._span()
        try:
            target = _add_months(first, step * self._step())
        except ValueError:  # (before year 1 or after 9999)
            return False
        return self._reachable(target, months)

    # ----- choosing -----

    def show(self, day):
        """Show day's month (and draw)."""
        if day is not None:
            self.shown = (day.year, day.month)
        self.view = "days"
        self.draw()

    def zoom_in(self):
        """Back to the days (from the months or years shown). Whether it wasn't already there."""
        if self.view == "days":
            return False
        self.view = "days"
        self.draw()
        return True

    def _clamped(self, day):
        if self.min is not None and day < self.min:
            return self.min
        if self.max is not None and day > self.max:
            return self.max
        return day

    def _move_to(self, day):
        day = self._clamped(day)
        if day != self.value:
            self.value = day
            if self.on_move:
                self.on_move(day)
        self.show(day)

    def turn(self, step):
        """Show the next month (year, decade) on, or before: step 1 or -1. The chosen day stays."""
        if self._can_turn(step):
            year, month = self.shown
            moved = _add_months(datetime.date(year, month, 1), step * self._step())
            self.shown = (moved.year, moved.month)
            self.draw()

    def _go(self, key):
        """A month or year picked (clicked, or Enter): its days, or its months."""
        if self.view == "months":
            self.shown, self.view = key, "days"
        else:
            self.shown, self.view = (key, self.shown[1]), "months"
        self.draw()

    def _click(self, e):  # (not "break": the window's own click watcher sees it too)
        self.canvas.focus_set()
        if not self.enabled:
            return None
        width, height, top, cell_w, cell_h = self._layout()
        head = self._head()
        if e.y < head:
            hit = {tag for item in self.canvas.find_overlapping(e.x, e.y, e.x, e.y) for tag in self.canvas.gettags(item)}
            if "zoom-months" in hit or "zoom-years" in hit:
                self.view = "months" if "zoom-months" in hit else "years"
                self.canvas.configure(cursor="")
                self.draw()
            elif e.x < cell_w:
                self.turn(-1)
            elif e.x > width - cell_w:
                self.turn(1)
            return None
        if self.view != "days":
            pick_w, pick_h = self._pick_cells(width, height, head)
            row, column = int((e.y - head) // pick_h), int(e.x // pick_w)
            if 0 <= row < 3 and 0 <= column < 4:
                _, key, choosable, _ = self._picks()[row * 4 + column]
                if choosable:
                    self._go(key)
            return None
        if e.y < top:
            return None
        row, column = int((e.y - top) // cell_h), int(e.x // cell_w)
        if 0 <= row < 6 and 0 <= column < 7:
            day = self._weeks()[row][column]
            if self._choosable(day):
                self._move_to(day)
                if self.on_choose:
                    self.on_choose(day, "click")
        return None

    def _key(self, e):
        if not self.enabled:
            return None
        name = keys.name(e.char, e.keysym, e.state)
        if self.view != "days":
            return self._pick_key(name)
        day = self.value or datetime.date.today()
        days = {"Left": -1, "Right": 1, "Up": -7, "Down": 7}
        if name in days:
            self._move_to(day + datetime.timedelta(days=days[name]))
        elif name in ("PgUp", "PgDn", "Shift+PgUp", "Shift+PgDn"):  # a month (Shift: a year)
            months = (12 if name.startswith("Shift") else 1) * (-1 if name.endswith("PgUp") else 1)
            self._move_to(_add_months(day, months))
        elif name == "Home":
            self._move_to(day.replace(day=1))
        elif name == "End":
            self._move_to(day.replace(day=calendar.monthrange(day.year, day.month)[1]))
        elif name in ("Enter", " "):
            if self.value is not None and self.on_choose:
                self.on_choose(self.value, "key")
        else:
            return None  # (Tab and the like: the form's)
        return "break"

    def _pick_key(self, name):
        """Keys among the months or years: the arrows move, Enter goes there, Esc back to the days."""
        steps = {"Left": -1, "Right": 1, "Up": -4, "Down": 4}
        year, month = self.shown
        if name in steps:
            if self.view == "months":
                moved = _add_months(datetime.date(year, month, 1), steps[name])
                if self._reachable(moved, 1):
                    self.shown = (moved.year, moved.month)
            elif 1 <= year + steps[name] <= 9999 and self._reachable(datetime.date(year + steps[name], 1, 1), 12):
                self.shown = (year + steps[name], month)
            self.draw()
        elif name in ("PgUp", "PgDn"):
            self.turn(-1 if name == "PgUp" else 1)
        elif name in ("Enter", " "):
            self._go(self.shown if self.view == "months" else year)
        elif name == "Esc":
            self.zoom_in()
        else:
            return None
        return "break"


# ----- the month, dropped down -----

class Dropped:
    """Something dropped down under a field (a picker's, a DataTable cell's), placed in the
    field's own window, over what's there: a month, or a list of times. Choosing calls
    on_choose(value, how), how being "click" or "key"; Esc, a click elsewhere or the keyboard
    leaving closes it, on_close(). Typing closes it too, and on_type(character) is given what
    was typed, for the field to take: a date or time can be typed while it's down."""

    current = None  # the one dropped down now (of either kind)

    def __init__(self, field, on_choose, on_close=None, on_type=None):
        if Dropped.current is not None:
            Dropped.current.close()
        Dropped.current = self
        self.field, self.on_choose, self.on_close, self.on_type = field, on_choose, on_close, on_type
        self.window = field.winfo_toplevel()

    def _show(self, widget, keyboard, width, height, below):
        """Place widget (keyboard: what in it takes the keys) under below, or above if there's
        no room under it; below is a widget, or (widget, x, y, width, height) for part of one."""
        self.widget, self.keyboard = widget, keyboard
        x, y, field_h = self._where(below)
        window_w, window_h = self.window.winfo_width(), self.window.winfo_height()
        if y + field_h + height > window_h and y - height >= 0:  # (no room below: above)
            y -= height
        else:
            y += field_h
        x = max(0, min(x, window_w - width))
        widget.place(x=x, y=y, width=width, height=height)
        tk.Misc.lift(widget)  # (over the others; a Canvas's own lift() raises its items)
        keyboard.focus_set()
        keyboard.bind("<FocusOut>", lambda e: self.window.after_idle(self._focus_left), add="+")
        keyboard.bind("<KeyPress>", self._typed, add="+")
        _watch_clicks(self.window)

    def _typed(self, e):
        """A character typed while it's down: closed, and the field given it to start typing with."""
        if self.on_type is None or not e.char or e.char == " " or keys.name(e.char, e.keysym, e.state) != e.char:
            return None  # (not a character: an arrow, Enter, a shortcut; Space chooses)
        self.close(chosen=True)  # (the field takes the keyboard as it takes the character)
        self.on_type(e.char)
        return "break"

    def _where(self, field):
        if isinstance(field, tuple):
            widget, x, y, _, height = field
        else:
            widget, x, y, height = field, 0, 0, field.winfo_height()
        return (widget.winfo_rootx() + x - self.window.winfo_rootx(),
                widget.winfo_rooty() + y - self.window.winfo_rooty(), height)

    def _focus_left(self):
        try:
            focus = self.window.focus_get()
        except KeyError:  # (a widget tkinter doesn't know: not this one's)
            focus = None
        if Dropped.current is self and focus is not self.keyboard:
            self.close()

    def contains(self, x_root, y_root):
        widget = self.widget
        return (widget.winfo_rootx() <= x_root < widget.winfo_rootx() + widget.winfo_width()
                and widget.winfo_rooty() <= y_root < widget.winfo_rooty() + widget.winfo_height())

    def _chose(self, value, how):
        self.close(chosen=True, refocus=True)
        self.on_choose(value, how)

    def close(self, chosen=False, refocus=False):
        """Close it; refocus: the keyboard back to the field (chosen, or Esc), not left where
        the user went (a click elsewhere)."""
        if Dropped.current is not self:
            return
        Dropped.current = None
        self.widget.destroy()
        if refocus:
            try:
                self.field.focus_set()
            except tk.TclError:  # (the field's gone)
                pass
        if not chosen and self.on_close:
            self.on_close()


class DropMonth(Dropped):
    """A month dropped down under a field (a DatePicker's, a DataTable's date cell): a click,
    Enter or Space chooses a day."""

    def __init__(self, field, value, on_choose, on_close=None, minimum=None, maximum=None, firstday="sunday",
                 font="", below=None, on_type=None):
        super().__init__(field, on_choose, on_close, on_type)
        month = self.month = MonthGrid(self.window, on_choose=self._chose)
        month.min, month.max, month.firstday = minimum, maximum, firstday
        month.set_font(font)
        month.value = value
        month.shown = ((value or datetime.date.today()).year, (value or datetime.date.today()).month)
        month.canvas.configure(highlightthickness=1, highlightbackground=_DIM, highlightcolor=_DIM)
        width, height = month.size()
        month.canvas.configure(width=width, height=height)
        self._show(month.canvas, month.canvas, width, height, below or field)
        month.draw()
        month.canvas.bind("<Escape>", lambda e: (month.zoom_in() or self.close(refocus=True), "break")[1])


class DropTimes(Dropped):
    """A list of times dropped down under a field (a TimePicker's, a DataTable's time cell):
    every step minutes from minimum to maximum, the one nearest value chosen and in sight. A
    click, or Enter, chooses one."""

    ROWS = 8  # times in sight at once

    def __init__(self, field, value, on_choose, on_close=None, step=30, minimum=None, maximum=None,
                 format=TIME_FORMAT, font="", below=None, on_type=None):
        super().__init__(field, on_choose, on_close, on_type)
        self.times = times_between(step, minimum, maximum)
        frame = tk.Frame(self.window, highlightthickness=1, highlightbackground=_DIM, bd=0)
        usual = tkfont.nametofont("TkDefaultFont", root=frame).actual()
        shown_font = tkfont.Font(root=frame, font=appearance.tk_font(font, usual) if font else
                                 (usual["family"], usual["size"]))
        accent, accent_text = _theme_colors(frame)
        box = self.list = tk.Listbox(frame, selectmode="browse", activestyle="none", exportselection=False,
                                     bd=0, highlightthickness=0, font=shown_font, height=self.ROWS,
                                     selectbackground=accent, selectforeground=accent_text)
        bar = ttk.Scrollbar(frame, command=box.yview)
        box.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        box.pack(side="left", fill="both", expand=True)
        for time in self.times:
            box.insert("end", show(time, format))
        nearest = _nearest(self.times, value or _now())
        if nearest is not None:
            box.selection_set(nearest)
            box.activate(nearest)
            box.see(nearest)
        widest = max((shown_font.measure(box.get(i)) for i in range(box.size())), default=40)
        width = widest + 16 + bar.winfo_reqwidth()
        frame.update_idletasks()
        height = frame.winfo_reqheight()  # (as tall as its rows, whatever the font)
        self._show(frame, box, width, height, below or field)
        box.yview(max(0, (nearest or 0) - 2))  # (the time nearest in sight, two earlier ones above it)
        box.bind("<ButtonRelease-1>", lambda e: self._pick("click"))
        for key in ("<Return>", "<KP_Enter>", "<space>"):
            box.bind(key, lambda e: (self._pick("key"), "break")[1])
        box.bind("<Escape>", lambda e: (self.close(refocus=True), "break")[1])

    def _pick(self, how):
        chosen = self.list.curselection()
        if chosen:
            self._chose(self.times[chosen[0]], how)


_watched = set()


def _watch_clicks(window):
    """A click anywhere in window, outside the dropped-down month, closes it (bound once a window)."""
    if str(window) in _watched:
        return
    _watched.add(str(window))

    def pressed(e):
        dropped = Dropped.current
        if dropped is not None and dropped.window is window and not dropped.contains(e.x_root, e.y_root):
            dropped.close()

    window.bind("<ButtonPress>", pressed, add="+")
    window.bind("<Destroy>", lambda e: e.widget is window and _watched.discard(str(window)), add="+")


# ----- shared by the controls -----

class _Changes:
    """A value, and change, run as it changes (by the user or by code)."""

    _value = None

    def _set_value(self, value):
        changed = value != self._value
        self._value = value
        self._show()
        if changed and self._ready:
            for handler in self._on_change:
                handler()

    def bind_event(self, event, handler):
        if event == "change":
            self._on_change.append(handler)
        else:
            super().bind_event(event, handler)


def _day_of(value):
    return value.date() if isinstance(value, datetime.datetime) else value


class _Dated(_Changes):
    """min, max and firstday, and the value they bound: a date (or a date and time, whose
    day is what they bound)."""

    _min = _max = None

    @classmethod
    def designer_changed(cls, spec, prop):
        super().designer_changed(spec, prop)
        low, high = (to_date(spec.get(p, ""), p) for p in ("min", "max"))
        if low and high and low > high:
            raise ValueError(f"min ({low}) can't be after max ({high})")
        if "format" in spec:
            _check_format(spec["format"])
        timed = has_time(spec.get("format", ISO))
        day = _day_of((to_datetime if timed else to_date)(spec.get("value", ""), "value"))
        if day and ((low and day < low) or (high and day > high)):
            raise ValueError(f"value ({day}) must be from min to max")
        if spec.get("firstday", "sunday") not in FIRST_DAYS:
            raise ValueError(f"firstday must be one of: {', '.join(FIRST_DAYS)}")

    @property
    def min(self):
        """The first day that can be chosen (a datetime.date), or None for no limit. Set a date
        or "2026-01-31"."""
        return self._min

    @min.setter
    def min(self, value):
        day = to_date(value, "min")
        if day and self._max and day > self._max:
            raise ValueError(f"min ({day}) can't be after max ({self._max})")
        self._min = day
        self._bounds_changed()

    @property
    def max(self):
        """The last day that can be chosen, or None for no limit."""
        return self._max

    @max.setter
    def max(self, value):
        day = to_date(value, "max")
        if day and self._min and day < self._min:
            raise ValueError(f"max ({day}) can't be before min ({self._min})")
        self._max = day
        self._bounds_changed()

    @property
    def firstday(self):
        """The day weeks start on: "sunday" or "monday"."""
        return self._firstday

    @firstday.setter
    def firstday(self, value):
        if value not in FIRST_DAYS:
            raise ValueError(f"firstday must be one of: {', '.join(FIRST_DAYS)}")
        self._firstday = value
        self._show()

    def _within(self, value):
        """value, its day moved within min and max (a date and time keeping its time)."""
        day = _day_of(value)
        limit = self._min if self._min and day < self._min else self._max if self._max and day > self._max else None
        if limit is None:
            return value
        return datetime.datetime.combine(limit, value.time()) if isinstance(value, datetime.datetime) else limit

    def _check(self, value):
        day = _day_of(value)
        if day is not None and ((self._min and day < self._min) or (self._max and day > self._max)):
            raise ValueError(f"{day} is outside {self.name}'s min to max ({self._min or '...'} to {self._max or '...'})")

    def _bounds_changed(self):
        if self._value is not None:
            self._set_value(self._within(self._value))
        self._show()


class _Field:
    """A picker's field: a ttk Combobox to type in, whose button (or F4, or Alt+Down) drops
    something down instead of a list. Up and Down step the value; what's typed counts once
    Enter is pressed or the keyboard leaves. format is how the value shows; allow_empty lets
    it be None, the field empty."""

    _allow_empty = False

    def _make_field(self, parent):
        self._on_change, self._enabled = [], True
        self._text = tk.StringVar(parent)
        field = ttk.Combobox(parent, textvariable=self._text, values=())
        if not self.design:
            field.bind("<ButtonPress-1>", self._pressed)  # (before the Combobox's own: its button drops ours)
            field.bind("<KeyPress>", self._key)
            field.bind("<FocusOut>", lambda e: self._typed(), add="+")
        return field

    @property
    def format(self):
        return self._format

    @format.setter
    def format(self, value):
        self._format = _check_format(value)
        self._format_changed()
        self._show()

    def _format_changed(self):
        pass

    @property
    def allow_empty(self):
        """Whether it can be left empty: the field blank, value None (a database's NULL)."""
        return self._allow_empty

    @allow_empty.setter
    def allow_empty(self, value):
        self._allow_empty = bool(value)
        if not self._allow_empty and self._value is None:
            self._set_value(self._within(self._usual()))

    def _show(self):
        self._text.set(show(self._value, self._format) if self._value is not None else "")

    def _typed(self):
        """What's typed becomes the value, if it reads as one within min and max; else the
        value's put back."""
        text = self._text.get().strip()
        if text == (show(self._value, self._format) if self._value is not None else ""):
            return
        if not text and self._allow_empty:
            self._set_value(None)
            return
        try:
            value = self._read(text) if text else None
        except ValueError:
            value = None
        if value is None or value != self._within(value):
            self.widget.bell()
            self._show()
            return
        self._set_value(value)

    def _pressed(self, e):
        element = str(self.widget.identify(e.x, e.y))
        on_button = "arrow" in element or "button" in element or e.x >= self.widget.winfo_width() - self.widget.winfo_height()
        if on_button and self._enabled:
            self.widget.focus_set()
            self.drop()
            return "break"
        return None

    def _key(self, e):
        if not self._enabled:
            return None
        name = keys.name(e.char, e.keysym, e.state)
        if name in ("F4", "Alt+Down"):
            self.drop()
            return "break"
        if name in ("Up", "Down"):
            self._typed()
            self._set_value(self._within(self._stepped(self._value, 1 if name == "Down" else -1)))
            self.widget.icursor("end")
            return "break"
        if name == "Enter":
            self._typed()
        return None  # (Enter goes on to the form: a default button, say)

    def drop(self):
        """Drop down what chooses its value, under the field."""
        if self.design or not self._enabled:
            return
        self._typed()
        self._dropped(self._font if isinstance(self._font, str) else "")

    def _chosen(self, value, how):
        self._set_value(value)
        self.widget.icursor("end")

    def _type_in(self, character):
        """Typed while the month (or times) was down: the field, starting with it."""
        self._text.set(character)
        self.widget.focus_set()
        self.widget.icursor("end")

    @property
    def enabled(self):
        """Whether the user can change it."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self.widget.state(["!disabled"] if self._enabled else ["disabled"])

    def _paint(self):
        # A ttk field takes its colors from a style, so a colored one gets its own.
        if not self._ready:
            return
        bg, fg = self._background(), self._foreground()
        if bg or fg:
            name = f"readymade{id(self)}.TCombobox"
            ttk.Style(self.widget).configure(name, **{k: v for k, v in (("fieldbackground", bg), ("foreground", fg))
                                                     if v})
            self.widget["style"] = name
        else:
            self.widget["style"] = "Preview.TCombobox" if self.design else "TCombobox"


# ----- the controls -----

@register
class Calendar(_Dated, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A month to choose a day in, as VB's MonthView. value is the chosen day, a datetime.date
    (today, at first). The arrows beside the month show the months either side, and a click
    on the month or year chooses another; the arrow keys move the day, Page Up and Down a
    month. min and max limit the days that can be chosen; firstday is the day weeks start on.
    change runs as the day changes."""

    type_name = "Calendar"
    default_size = (224, 184)
    default_event = "change"
    events = (Event("change"), *_FOCUS_EVENTS)
    extra_props = {"min": "", "max": "", "firstday": "sunday", "value": ""}
    prop_choices = {"firstday": FIRST_DAYS}

    def create_widget(self, parent):
        self._on_change, self._enabled, self._firstday = [], True, "sunday"
        self._value = datetime.date.today()
        self._month = MonthGrid(parent, design=self.design, on_move=self._set_value,
                                on_choose=lambda day, how: self._set_value(day))
        return self._month.canvas

    @property
    def value(self):
        """The chosen day, a datetime.date. Set a date, or "2026-10-14" ("": today, kept within
        min and max)."""
        return self._value

    @value.setter
    def value(self, value):
        day = to_date(value)
        if day is None:
            day = self._within(datetime.date.today())
        self._check(day)
        self._set_value(day)
        self._month.show(day)

    def _show(self):
        month = self._month
        month.value, month.min, month.max, month.firstday = self._value, self._min, self._max, self._firstday
        month.draw()

    @property
    def enabled(self):
        """Whether the user can choose a day (grayed, if not)."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = self._month.enabled = bool(value)
        self._month.draw()

    def _paint(self):
        if self._ready:
            self._month.paint(self._background(), self._foreground())

    def _apply_font(self):
        if self._ready:
            self._month.set_font(self._font)


@register
class DatePicker(_Field, _Dated, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A date field whose month drops down, as VB's DTPicker: its button (or F4, or Alt+Down)
    shows the month to choose a day in; a date can be typed too, as format shows it (or
    year-month-day), and Up and Down step it a day. value is a datetime.date (today, at
    first); with allow_empty it can be None, the field empty. format is in strftime's codes:
    "%Y-%m-%d" (2026-10-14), "%m/%d/%Y", "%-d %b %Y" (5 Oct 2026). A format with a time in it
    ("%Y-%m-%d %-I:%M %p") makes value a datetime.datetime: the month chooses its day, and its
    time is typed. change runs as the value changes."""

    type_name = "DatePicker"
    default_size = (128, 24)
    default_event = "change"
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"format": ISO, "allow_empty": False, "min": "", "max": "", "firstday": "sunday", "value": ""}
    prop_choices = {"firstday": FIRST_DAYS}

    def create_widget(self, parent):
        self._firstday, self._format, self._timed = "sunday", ISO, False
        self._value = datetime.date.today()
        return self._make_field(parent)

    @property
    def value(self):
        """The date, a datetime.date (a datetime.datetime, if format has a time); None if the
        field's empty (with allow_empty). Set a date, or "2026-10-14" (with a time: "2026-10-14
        21:30"); "" is today (now), or empty with allow_empty."""
        return self._value

    @value.setter
    def value(self, value):
        value = (to_datetime if self._timed else to_date)(value)
        if isinstance(value, datetime.datetime) and not self._timed:
            value = value.date()
        if value is None and not self._allow_empty:
            value = self._within(self._usual())
        self._check(value)
        self._set_value(value)

    format = property(_Field.format.fget, _Field.format.fset, doc="""How the date shows (and is
        typed), in strftime's codes: "%Y-%m-%d" (2026-10-14, the usual), "%m/%d/%Y"
        (10/14/2026), "%-d %b %Y" (5 Oct 2026: %-d, no leading zero), "%x" (the locale's own).
        With a time in it, value is a date and time: "%Y-%m-%d %-I:%M %p" (2026-10-14 9:30 PM).""")

    def _format_changed(self):
        timed, self._timed = self._timed, has_time(self._format)
        if self._value is not None and timed != self._timed:  # (a time part, or none now)
            self._value = to_datetime(self._value) if self._timed else self._value.date()

    def _usual(self):
        if self._timed:
            return datetime.datetime.combine(datetime.date.today(), _now())
        return datetime.date.today()

    def _read(self, text):
        return read_datetime(text, self._format) if self._timed else read_date(text, self._format)

    def _stepped(self, value, step):
        return (value or self._usual()) + datetime.timedelta(days=step)

    def _dropped(self, font):
        value = self._value or self._within(self._usual())
        DropMonth(self.widget, _day_of(value), self._day_chosen, minimum=self._min, maximum=self._max,
                  firstday=self._firstday, font=font, on_type=self._type_in)

    def _day_chosen(self, day, how):
        if self._timed:  # (the day chosen, the time as it was)
            day = datetime.datetime.combine(day, (self._value or self._usual()).time())
        self._chosen(day, how)


@register
class TimePicker(_Field, _Changes, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A time field whose times drop down: its button (or F4, or Alt+Down) shows the times
    every step minutes (30: 9:00, 9:30, 10:00...) to choose one; any time can be typed too
    (9:30 PM, 9:30pm, 21:30, 2130, 9 pm), and Up and Down step it to the next step. value is
    a datetime.time (now, at first); with allow_empty it can be None, the field empty. format
    is in strftime's codes: "%-I:%M %p" (9:30 PM, the usual), "%H:%M" (21:30). min and max
    limit the times. change runs as the time changes."""

    type_name = "TimePicker"
    default_size = (104, 24)
    default_event = "change"
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"format": TIME_FORMAT, "step": 30, "allow_empty": False, "min": "", "max": "", "value": ""}

    _min = _max = None

    def create_widget(self, parent):
        self._format, self._step = TIME_FORMAT, 30
        self._value = _now()
        return self._make_field(parent)

    @classmethod
    def designer_changed(cls, spec, prop):
        super().designer_changed(spec, prop)
        _check_format(spec.get("format", TIME_FORMAT))
        low, high, value = (to_time(spec.get(p, ""), p) for p in ("min", "max", "value"))
        if low and high and low > high:
            raise ValueError(f"min ({show(low, TIME_FORMAT)}) can't be after max ({show(high, TIME_FORMAT)})")
        if value and ((low and value < low) or (high and value > high)):
            raise ValueError("value must be from min to max")
        if not 1 <= int(spec.get("step", 30)) <= 720:
            raise ValueError("step must be from 1 to 720 minutes")

    @property
    def value(self):
        """The time, a datetime.time; None if the field's empty (with allow_empty). Set a time,
        or "21:30" or "9:30 PM" ("": now, or empty with allow_empty)."""
        return self._value

    @value.setter
    def value(self, value):
        value = to_time(value)
        if value is None and not self._allow_empty:
            value = self._within(_now())
        if value is not None and value != self._within(value):
            raise ValueError(f"{show(value, self._format)} is outside {self.name}'s min to max")
        self._set_value(value)

    format = property(_Field.format.fget, _Field.format.fset, doc="""How the time shows (and is
        typed), in strftime's codes: "%-I:%M %p" (9:30 PM, the usual: %-I, no leading zero),
        "%H:%M" (21:30), "%-I:%M:%S %p" (with seconds).""")

    @property
    def step(self):
        """The minutes between the times dropped down (and that Up and Down step): 30, say, or 15."""
        return self._step

    @step.setter
    def step(self, value):
        value = int(value)
        if not 1 <= value <= 720:
            raise ValueError("step must be from 1 to 720 minutes")
        self._step = value

    @property
    def min(self):
        """The earliest time that can be chosen (a datetime.time), or None. Set a time or "8:00"."""
        return self._min

    @min.setter
    def min(self, value):
        time = to_time(value, "min")
        if time and self._max and time > self._max:
            raise ValueError("min can't be after max")
        self._min = time
        if self._value is not None:
            self._set_value(self._within(self._value))

    @property
    def max(self):
        """The latest time that can be chosen, or None."""
        return self._max

    @max.setter
    def max(self, value):
        time = to_time(value, "max")
        if time and self._min and time < self._min:
            raise ValueError("max can't be before min")
        self._max = time
        if self._value is not None:
            self._set_value(self._within(self._value))

    def _within(self, time):
        if self._min and time < self._min:
            return self._min
        if self._max and time > self._max:
            return self._max
        return time

    def _usual(self):
        return _now()

    def _read(self, text):
        return read_time(text, self._format)

    def _stepped(self, value, step):
        """The time step minutes on (or back) from value, on the step's grid: 9:47, Up a 30
        step, is 9:30; Down, 10:00."""
        minutes = (value or _now()).hour * 60 + (value or _now()).minute
        on_grid = minutes % self._step == 0
        if step > 0:
            minutes = (minutes // self._step + 1) * self._step
        else:
            minutes = (minutes // self._step - (1 if on_grid else 0)) * self._step
        minutes = max(0, min(minutes, 24 * 60 - 1))
        return datetime.time(minutes // 60, minutes % 60)

    def _dropped(self, font):
        DropTimes(self.widget, self._value, self._chosen, step=self._step, minimum=self._min, maximum=self._max,
                  format=self._format, font=font, on_type=self._type_in)
