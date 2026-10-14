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
    """A typed date: in format (strftime's codes), or as year-month-day. ValueError if neither."""
    text = text.strip()
    try:
        return datetime.datetime.strptime(text, format).date()
    except ValueError:
        try:
            return datetime.date.fromisoformat(text)
        except ValueError:
            example = datetime.date(2026, 10, 14).strftime(format)
            raise ValueError(f"{name}: {text!r} isn't a date (as {example})") from None


def _check_format(format):
    try:
        shown = datetime.date(2026, 10, 14).strftime(format)
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

class DropMonth:
    """A month dropped down under a field (a DatePicker's, a DataTable's date cell), placed
    in the field's own window, over what's there: a click, Enter or Space chooses a day,
    on_choose(day, how); Esc, a click elsewhere or the keyboard leaving closes it, on_close()."""

    current = None  # the one dropped down now

    def __init__(self, field, value, on_choose, on_close=None, minimum=None, maximum=None, firstday="sunday",
                 font="", below=None):
        if DropMonth.current is not None:
            DropMonth.current.close()
        DropMonth.current = self
        self.field, self.on_choose, self.on_close = field, on_choose, on_close
        self.window = field.winfo_toplevel()
        month = self.month = MonthGrid(self.window, on_choose=self._chose)
        month.min, month.max, month.firstday = minimum, maximum, firstday
        month.set_font(font)
        month.value = value
        month.shown = ((value or datetime.date.today()).year, (value or datetime.date.today()).month)
        month.canvas.configure(highlightthickness=1, highlightbackground=_DIM, highlightcolor=_DIM)
        width, height = month.size()
        month.canvas.configure(width=width, height=height)
        x, y, field_h = self._where(below or field)
        window_w, window_h = self.window.winfo_width(), self.window.winfo_height()
        if y + field_h + height > window_h and y - height >= 0:  # (no room below: above)
            y -= height
        else:
            y += field_h
        x = max(0, min(x, window_w - width))
        month.canvas.place(x=x, y=y, width=width, height=height)
        tk.Misc.lift(month.canvas)  # (the widget over the others: a Canvas's own lift() raises its items)
        month.draw()
        month.canvas.focus_set()
        month.canvas.bind("<Escape>", lambda e: (month.zoom_in() or self.close(refocus=True), "break")[1])
        month.canvas.bind("<FocusOut>", lambda e: self.window.after_idle(self._focus_left), add="+")
        _watch_clicks(self.window)

    def _where(self, field):
        """field's place in the window: (x, y, height); field is a widget, or (widget, x, y, w, h)."""
        if isinstance(field, tuple):
            widget, x, y, _, height = field
        else:
            widget, x, y, height = field, 0, 0, field.winfo_height()
        return (widget.winfo_rootx() + x - self.window.winfo_rootx(),
                widget.winfo_rooty() + y - self.window.winfo_rooty(), height)

    def _focus_left(self):
        try:
            focus = self.window.focus_get()
        except KeyError:  # (a widget tkinter doesn't know: not the month's)
            focus = None
        if DropMonth.current is self and focus is not self.month.canvas:
            self.close()

    def contains(self, x_root, y_root):
        canvas = self.month.canvas
        return (canvas.winfo_rootx() <= x_root < canvas.winfo_rootx() + canvas.winfo_width()
                and canvas.winfo_rooty() <= y_root < canvas.winfo_rooty() + canvas.winfo_height())

    def _chose(self, day, how):
        self.close(chosen=True, refocus=True)
        self.on_choose(day, how)

    def close(self, chosen=False, refocus=False):
        """Close it; refocus: the keyboard back to the field (a day chosen, or Esc), not left
        where the user went (a click elsewhere)."""
        if DropMonth.current is not self:
            return
        DropMonth.current = None
        self.month.canvas.destroy()
        if refocus:
            try:
                self.field.focus_set()
            except tk.TclError:  # (the field's gone)
                pass
        if not chosen and self.on_close:
            self.on_close()


_watched = set()


def _watch_clicks(window):
    """A click anywhere in window, outside the dropped-down month, closes it (bound once a window)."""
    if str(window) in _watched:
        return
    _watched.add(str(window))

    def pressed(e):
        dropped = DropMonth.current
        if dropped is not None and dropped.window is window and not dropped.contains(e.x_root, e.y_root):
            dropped.close()

    window.bind("<ButtonPress>", pressed, add="+")
    window.bind("<Destroy>", lambda e: e.widget is window and _watched.discard(str(window)), add="+")


# ----- shared by both controls -----

class _Dated:
    """min, max and firstday, and the value they bound."""

    _value = None
    _min = _max = None

    @classmethod
    def designer_changed(cls, spec, prop):
        super().designer_changed(spec, prop)
        low, high = (to_date(spec.get(p, ""), p) for p in ("min", "max"))
        if low and high and low > high:
            raise ValueError(f"min ({low}) can't be after max ({high})")
        day = to_date(spec.get("value", ""), "value")
        if day and ((low and day < low) or (high and day > high)):
            raise ValueError(f"value ({day}) must be from min to max")
        if spec.get("firstday", "sunday") not in FIRST_DAYS:
            raise ValueError(f"firstday must be one of: {', '.join(FIRST_DAYS)}")
        if "format" in spec:
            _check_format(spec["format"])

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

    def _within(self, day):
        """day, within min and max."""
        if self._min and day < self._min:
            return self._min
        if self._max and day > self._max:
            return self._max
        return day

    def _check(self, day):
        if day is not None and ((self._min and day < self._min) or (self._max and day > self._max)):
            raise ValueError(f"{day} is outside {self.name}'s min to max ({self._min or '...'} to {self._max or '...'})")

    def _bounds_changed(self):
        if self._value is not None:
            self._set_day(self._within(self._value))
        self._show()

    def _set_day(self, day):
        changed = day != self._value
        self._value = day
        self._show()
        if changed and self._ready:
            for handler in self._on_change:
                handler()

    def bind_event(self, event, handler):
        if event == "change":
            self._on_change.append(handler)
        else:
            super().bind_event(event, handler)


# ----- the controls -----

@register
class Calendar(_Dated, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A month to choose a day in, as VB's MonthView. value is the chosen day, a datetime.date
    (today, at first). The arrows beside the month show the months either side; the arrow
    keys move the day, Page Up and Down a month. min and max limit the days that can be
    chosen; firstday is the day weeks start on. change runs as the day changes."""

    type_name = "Calendar"
    default_size = (224, 184)
    default_event = "change"
    events = (Event("change"), *_FOCUS_EVENTS)
    extra_props = {"min": "", "max": "", "firstday": "sunday", "value": ""}
    prop_choices = {"firstday": FIRST_DAYS}

    def create_widget(self, parent):
        self._on_change, self._enabled, self._firstday = [], True, "sunday"
        self._value = datetime.date.today()
        self._month = MonthGrid(parent, design=self.design, on_move=self._set_day, on_choose=lambda day, how: self._set_day(day))
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
        self._set_day(day)
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
class DatePicker(_Dated, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A date field whose month drops down, as VB's DTPicker: its button (or F4, or Alt+Down)
    shows the month to choose a day in; a date can be typed too, as format shows it (or
    year-month-day), and Up and Down step it a day. value is a datetime.date (today, at
    first); with allow_empty it can be None, the field empty. format is in strftime's codes:
    "%Y-%m-%d" (2026-10-14), "%m/%d/%Y", "%d %b %Y". change runs as the date changes."""

    type_name = "DatePicker"
    default_size = (128, 24)
    default_event = "change"
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"format": ISO, "allow_empty": False, "min": "", "max": "", "firstday": "sunday", "value": ""}
    prop_choices = {"firstday": FIRST_DAYS}

    def create_widget(self, parent):
        self._on_change, self._enabled, self._firstday = [], True, "sunday"
        self._value, self._format, self._allow_empty = datetime.date.today(), ISO, False
        self._text = tk.StringVar(parent)
        field = ttk.Combobox(parent, textvariable=self._text, values=())
        if not self.design:
            field.bind("<ButtonPress-1>", self._pressed)  # (before the Combobox's own: its button drops the month)
            field.bind("<KeyPress>", self._key)
            field.bind("<FocusOut>", lambda e: self._typed(), add="+")
        return field

    @property
    def value(self):
        """The date, a datetime.date; None if the field's empty (with allow_empty). Set a date,
        or "2026-10-14" ("": today, or empty with allow_empty)."""
        return self._value

    @value.setter
    def value(self, value):
        day = to_date(value)
        if day is None and not self._allow_empty:
            day = self._within(datetime.date.today())
        self._check(day)
        self._set_day(day)

    @property
    def format(self):
        """How the date shows (and is typed), in strftime's codes: "%Y-%m-%d" (2026-10-14, the
        usual), "%m/%d/%Y" (10/14/2026), "%d %b %Y" (14 Oct 2026), "%x" (the locale's own)."""
        return self._format

    @format.setter
    def format(self, value):
        self._format = _check_format(value)
        self._show()

    @property
    def allow_empty(self):
        """Whether the date can be left out: the field empty, value None (a database's NULL)."""
        return self._allow_empty

    @allow_empty.setter
    def allow_empty(self, value):
        self._allow_empty = bool(value)
        if not self._allow_empty and self._value is None:
            self._set_day(self._within(datetime.date.today()))

    def _show(self):
        self._text.set(self._value.strftime(self._format) if self._value else "")

    def _typed(self):
        """What's typed becomes the value, if it's a date within min and max; else it's put back."""
        text = self._text.get().strip()
        if text == (self._value.strftime(self._format) if self._value else ""):
            return
        if not text:
            if self._allow_empty:
                self._set_day(None)
                return
            day = None
        else:
            try:
                day = read_date(text, self._format)
            except ValueError:
                day = None
        if day is None or day != self._within(day):
            self.widget.bell()
            self._show()
            return
        self._set_day(day)

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
        if name in ("Up", "Down"):  # a day, either way
            self._typed()
            day = self._value or datetime.date.today()
            self._set_day(self._within(day + datetime.timedelta(days=1 if name == "Down" else -1)))
            self.widget.icursor("end")
            return "break"
        if name == "Enter":
            self._typed()
            return None  # (and on to the form: a default button, say)
        return None

    def drop(self):
        """Show the month, dropped down under the field, to choose a day in."""
        if self.design or not self._enabled:
            return
        self._typed()
        font = self._font if isinstance(self._font, str) else ""
        DropMonth(self.widget, self._value or self._within(datetime.date.today()), self._chosen,
                  minimum=self._min, maximum=self._max, firstday=self._firstday, font=font)

    def _chosen(self, day, how):
        self._set_day(day)
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
        # A ttk field takes its colors from a style, so a colored DatePicker gets its own.
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
