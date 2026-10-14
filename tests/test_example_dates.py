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
    assert form.Month.value == TODAY and form.DayList.text == "Dentist\nCall the plumber"
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
    events._move(len(events.rows), 1)  # a new event: on the Calendar's day
    events._edit(typed="Gym")
    events._finish()
    settle(form)
    assert events.rows[-1][:2] == [TODAY + 5 * DAY, "Gym"] and form.DayList.text == "Lunch with Sam\nGym"
    events.current = (0, "Date")
    events._edit()  # its month drops down
    assert DropMonth.current is not None and DropMonth.current.month.value == TODAY - 3 * DAY
    DropMonth.current.close()
    assert events.rows[0].forecolor == "#909090" and events.rows[1].forecolor == ""  # (done: gray)
