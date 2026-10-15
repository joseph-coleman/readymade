"""examples/dates, the planner: it does what its README.md says (run on a copy)."""

import datetime
import importlib.util
import shutil
import time
from pathlib import Path

import pytest

from readymade.controls.dates import DropMonth

pytestmark = pytest.mark.usefixtures("display")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "dates"
AS_PUBLISHED = shutil.ignore_patterns(".readymade", "__pycache__")  # (not this machine's settings for it)
TODAY = datetime.date.today()
DAY = datetime.timedelta(days=1)


@pytest.fixture
def form(tmp_path, monkeypatch):
    folder = shutil.copytree(EXAMPLE, tmp_path / "dates", ignore=AS_PUBLISHED)
    monkeypatch.chdir(folder)
    spec = importlib.util.spec_from_file_location("planner", folder / "Form1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    form = module.Form1("Form1.form")
    form.show()
    settle(form)
    yield form
    form.root.destroy()


def settle(form):
    for _ in range(10):
        form.root.update()
        time.sleep(0.005)


def test_the_calendar_shows_the_days_events(form):
    assert form.Month.value == TODAY and form.DayList.text == "10:00 AM  Dentist\nCall the plumber"
    form.Month.value = TODAY + 2 * DAY
    assert form.DayList.text == "Pay the rent"
    form.Month.value = TODAY + DAY
    assert form.DayList.text == "Nothing happening."


def test_the_range_and_its_empty_end(form):
    assert form.ToDate.value is None and form.Status.text.startswith("6 events from")
    form.FromDate.value = TODAY
    assert form.Status.text.startswith("5 events") and form.ToDate.min == TODAY
    form.ToDate.value = TODAY + 3 * DAY
    assert form.Status.text.startswith("3 events")
    form.FromDate.value = TODAY + 4 * DAY  # (past the end: the end moves up to it)
    assert form.ToDate.value == TODAY + 4 * DAY


def test_events_and_the_calendar_follow_each_other(form):
    events = form.Events
    events._move(4, 1)  # Lunch with Sam's row: the Calendar goes to its day
    assert form.Month.value == TODAY + 5 * DAY
    events._move(len(events.rows), 2)  # a new event: on the Calendar's day
    events._edit(typed="Gym")
    events._finish()
    settle(form)
    assert events.rows[-1][:3] == [TODAY + 5 * DAY, None, "Gym"] and form.DayList.text == "12:30 PM  Lunch with Sam\nGym"
    events.current = (0, "Date")
    events._edit()  # its month drops down
    assert DropMonth.current is not None and DropMonth.current.month.value == TODAY - 3 * DAY
    DropMonth.current.close()
    assert events.rows[0].forecolor == "#909090" and events.rows[1].forecolor == ""  # (done: gray)


def test_a_new_event_from_a_date_and_a_time(form):
    form.Month.value = TODAY + 2 * DAY  # (the new event's day follows the Calendar)
    assert form.NewDay.value == TODAY + 2 * DAY and form.NewTime.value == datetime.time(9)
    form.NewTime.value = "7:30 AM"
    form.NewWhat.text = "Run"
    form.AddButton.widget.invoke()
    settle(form)
    assert [row["Event"] for row in form.Events.rows][3:5] == ["Pay the rent", "Run"]  # (no time first: all day)
    assert form.DayList.text == "Pay the rent\n07:30 AM  Run" and form.NewWhat.text == ""


def test_a_reminder_with_a_date_and_time(form):
    assert form.Remind.value is None and form.RemindNote.text == "No reminder"
    form.Remind.value = datetime.datetime.combine(TODAY + 2 * DAY, datetime.time(9))
    assert form.Remind.widget.get().endswith("9:00 AM") and form.RemindNote.text.startswith("In ")
    form.Remind.value = None
    assert form.RemindNote.text == "No reminder"
