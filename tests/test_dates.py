"""The date controls: a Calendar, and a DatePicker whose month drops down."""

import datetime
import time

import pytest

from readymade import Form, formfile
from readymade.controls import REGISTRY
from readymade.controls.dates import DropMonth, read_date, to_date

D = datetime.date
TODAY = D.today()


def test_dates_from_what_people_write():
    assert to_date("2026-10-14") == D(2026, 10, 14) and to_date(datetime.datetime(2026, 1, 2, 3, 4)) == D(2026, 1, 2)
    assert to_date("") is None and to_date(None) is None and to_date(D(2026, 5, 6)) == D(2026, 5, 6)
    assert read_date("10/14/2026", "%m/%d/%Y") == D(2026, 10, 14)
    assert read_date("2026-10-14", "%m/%d/%Y") == D(2026, 10, 14)  # (year-month-day always reads)
    with pytest.raises(ValueError, match="'14.10.' isn't a date \\(as 10/14/2026\\)"):
        read_date("14.10.", "%m/%d/%Y")
    with pytest.raises(ValueError, match="isn't a date"):
        to_date("soon")


@pytest.fixture
def make_form(tmp_path):
    made = []

    def make(cls=Form, calendar=None, picker=None):
        design = formfile.FormDesign(name="Form1", width=480, height=320)
        spec = REGISTRY["Calendar"].new_spec("Cal", 8, 8, 224, 184)
        spec.update(calendar or {})
        design.controls.append(spec)
        spec = REGISTRY["DatePicker"].new_spec("Pick", 248, 8, 160, 26)
        spec.update(picker or {})
        design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = cls(tmp_path / "Form1.form")
        form.show()
        settle(form)
        made.append(form)
        return form

    yield make
    for form in made:
        form.root.destroy()


def settle(form):
    for _ in range(15):
        form.root.update()
        time.sleep(0.003)


def key(form, widget, keysym, state=0):
    widget.event_generate("<KeyPress>", keysym=keysym, state=state)
    settle(form)


def dropped():
    return DropMonth.current.month.canvas


@pytest.mark.usefixtures("display")
def test_a_calendar_chooses_a_day(make_form):
    changes = []

    class Form1(Form):
        def Cal_change(self):
            changes.append(self.Cal.value)

    form = make_form(Form1, calendar={"value": "2026-10-14", "firstday": "monday"})
    cal = form.Cal
    assert cal.value == D(2026, 10, 14) and changes == []  # (as designed: no change run)
    cal.widget.focus_force()
    settle(form)
    for keysym, day in (("Right", D(2026, 10, 15)), ("Down", D(2026, 10, 22)), ("Next", D(2026, 11, 22)),
                        ("End", D(2026, 11, 30)), ("Home", D(2026, 11, 1)), ("Prior", D(2026, 10, 1))):
        key(form, cal.widget, keysym)
        assert cal.value == day, keysym
    assert changes[-1] == D(2026, 10, 1) and len(changes) == 6
    cal.value = "2027-02-28"  # (from code: a date, or year-month-day)
    assert cal.value == D(2027, 2, 28) and cal._month.shown == (2027, 2)
    cal.min, cal.max = D(2027, 2, 10), "2027-03-05"
    key(form, cal.widget, "Next")  # (a month on would be past max: max)
    assert cal.value == D(2027, 3, 5)
    with pytest.raises(ValueError, match="outside Cal's min to max"):
        cal.value = D(2027, 4, 1)
    with pytest.raises(ValueError, match="can't be after max"):
        cal.min = "2027-12-01"
    cal.max = None
    cal.value = ""  # today, within min
    assert cal.value == max(TODAY, D(2027, 2, 10))
    cal.enabled = False
    before = cal.value
    key(form, cal.widget, "Right")
    assert cal.value == before


@pytest.mark.usefixtures("display")
def test_clicking_a_day_and_the_months_either_side(make_form):
    form = make_form(calendar={"value": "2026-10-14", "firstday": "sunday"})
    month = form.Cal._month
    _, _, top, cell_w, cell_h = month._layout()

    def click(x, y):
        month.canvas.event_generate("<ButtonPress-1>", x=int(x), y=int(y))
        settle(form)

    click(cell_w * 4.5, top + cell_h * 0.5)  # the first row, Thursday: October 1st
    assert form.Cal.value == D(2026, 10, 1)
    click(month.canvas.winfo_width() - cell_w / 2, month._head() / 2)  # the arrow to November
    assert month.shown == (2026, 11) and form.Cal.value == D(2026, 10, 1)  # (the day stays chosen)
    click(cell_w / 2, month._head() / 2)
    click(cell_w / 2, month._head() / 2)
    assert month.shown == (2026, 9)


@pytest.mark.usefixtures("display")
def test_a_date_picker_types_steps_and_drops_down(make_form):
    changes = []

    class Form1(Form):
        def Pick_change(self):
            changes.append(self.Pick.value)

    form = make_form(Form1, picker={"value": "2026-03-15", "format": "%m/%d/%Y"})
    pick = form.Pick
    assert pick.value == D(2026, 3, 15) and pick.widget.get() == "03/15/2026"
    pick.widget.focus_force()
    settle(form)
    key(form, pick.widget, "Down")  # a day on
    assert pick.value == D(2026, 3, 16) and pick.widget.get() == "03/16/2026"
    pick.widget.delete(0, "end")
    pick.widget.insert(0, "4/1/2026")
    key(form, pick.widget, "Return")  # typed, in its format
    assert pick.value == D(2026, 4, 1) and pick.widget.get() == "04/01/2026"
    pick.widget.delete(0, "end")
    pick.widget.insert(0, "the first")
    key(form, pick.widget, "Return")  # not a date: put back
    assert pick.value == D(2026, 4, 1) and pick.widget.get() == "04/01/2026"
    key(form, pick.widget, "F4")  # the month drops down...
    assert DropMonth.current is not None and form.root.focus_get() is dropped()
    assert dropped().winfo_rooty() >= pick.widget.winfo_rooty() + pick.widget.winfo_height()  # (under the field)
    key(form, dropped(), "Right")
    key(form, dropped(), "Return")  # ...and Enter chooses
    assert pick.value == D(2026, 4, 2) and DropMonth.current is None and form.root.focus_get() is pick.widget
    key(form, pick.widget, "F4")
    key(form, dropped(), "Right")
    key(form, dropped(), "Escape")  # Esc: never mind
    assert pick.value == D(2026, 4, 2) and DropMonth.current is None
    assert changes == [D(2026, 3, 16), D(2026, 4, 1), D(2026, 4, 2)]
    pick.drop()
    form.Cal.widget.event_generate("<ButtonPress-1>", x=5, y=5)  # a click elsewhere: closed
    settle(form)
    assert DropMonth.current is None and form.root.focus_get() is form.Cal.widget  # (the keyboard where it went)


@pytest.mark.usefixtures("display")
def test_an_empty_date_if_allowed(make_form):
    form = make_form(picker={"allow_empty": True})
    pick = form.Pick
    assert pick.value is None and pick.widget.get() == ""  # (allowed: it starts empty)
    pick.value = "2026-01-02"
    pick.widget.focus_force()
    pick.widget.delete(0, "end")
    key(form, pick.widget, "Return")
    assert pick.value is None
    pick.allow_empty = False  # (not now: today)
    assert pick.value == TODAY
    pick.widget.delete(0, "end")
    key(form, pick.widget, "Return")
    assert pick.value == TODAY and pick.widget.get() == TODAY.isoformat()  # (cleared: put back)
    with pytest.raises(ValueError, match="isn't a date format"):
        pick.format = 7


def test_the_designer_checks_dates():
    for cls in (REGISTRY["Calendar"], REGISTRY["DatePicker"]):
        spec = cls.new_spec("X", 0, 0)
        spec.update(min="2026-01-01", max="2026-12-31", value="2026-06-01")
        cls.designer_changed(spec, "value")
        for bad, message in (({"min": "soon"}, "isn't a date"), ({"max": "2025-01-01"}, "can't be after max"),
                             ({"value": "2027-01-01"}, "from min to max"), ({"firstday": "friday"}, "firstday")):
            with pytest.raises(ValueError, match=message):
                cls.designer_changed({**spec, **bad}, "value")


@pytest.mark.usefixtures("display")
def test_the_month_and_year_are_clicks_away_from_others(make_form):
    form = make_form(calendar={"value": "2026-10-14", "max": "2031-06-30"})
    cal, month = form.Cal, form.Cal._month
    canvas = month.canvas

    def click(x, y):
        canvas.event_generate("<ButtonPress-1>", x=int(x), y=int(y))
        settle(form)

    def click_tag(tag):
        x0, y0, x1, y1 = canvas.bbox(tag)
        click((x0 + x1) / 2, (y0 + y1) / 2)

    def click_pick(index):
        width, height, *_ = month._layout()
        cell_w, cell_h = month._pick_cells(width, height, month._head())
        row, column = divmod(index, 4)
        click((column + 0.5) * cell_w, month._head() + (row + 0.5) * cell_h)

    click_tag("zoom-months")  # October's name: the year's months
    assert month.view == "months" and [label for label, *_ in month._picks()][:3] == ["Jan", "Feb", "Mar"]
    click_pick(2)  # March: its days
    assert (month.view, month.shown) == ("days", (2026, 3)) and cal.value == D(2026, 10, 14)  # (the day stays)
    click_tag("zoom-years")  # the year: a decade's years
    assert month.view == "years" and [label for label, *_ in month._picks()][:2] == ["2019", "2020"]
    click(month.canvas.winfo_width() - 10, month._head() / 2)  # the arrow: a decade on
    assert month.shown[0] == 2036 and month.view == "years"
    assert [choosable for _, _, choosable, _ in month._picks()][2:4] == [True, False]  # (past max: 2032 can't)
    click_pick(2)  # 2031: its months...
    assert (month.view, month.shown[0]) == ("months", 2031)
    assert [choosable for _, _, choosable, _ in month._picks()][5:7] == [True, False]  # (June's max's)
    click_pick(5)  # ...and June: its days, ten years on in three clicks
    assert (month.view, month.shown) == ("days", (2031, 6))

    cal.widget.focus_force()
    month.view = "years"
    month.draw()
    key(form, cal.widget, "Left")  # the keyboard among them too
    key(form, cal.widget, "Return")
    assert (month.view, month.shown[0]) == ("months", 2030)
    key(form, cal.widget, "Escape")  # Esc: back to the days
    assert month.view == "days"


@pytest.mark.usefixtures("display")
def test_esc_in_a_dropped_months_years_goes_back_before_closing(make_form):
    form = make_form()
    form.Pick.widget.focus_force()
    form.Pick.drop()
    settle(form)
    month = DropMonth.current.month
    month.view = "years"
    key(form, dropped(), "Escape")
    assert DropMonth.current is not None and month.view == "days"
    key(form, dropped(), "Escape")
    assert DropMonth.current is None
