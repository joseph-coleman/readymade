# A planner: dates and times

A Calendar, DatePickers (one with a time), a TimePicker, and a DataTable with date and time
columns. Open it in the IDE:

    readymade examples/dates

and press **F5**. The code is in **Form1** (F7 on the form). The events are made around
today, so they're in the month the Calendar opens on.

Dates and times are Python's own everywhere: `datetime.date`, `datetime.time` and
`datetime.datetime`, as a control's `value`, a cell, and what you compare them with.

## The Calendar

**Try:** click a day, or use the arrow keys (Page Up and Down for a month, Home and End for
the month's first and last day). The small arrows beside the month show the months either
side. To go further, click the month's name to pick another month, or the year to pick
another year from a decade's (its arrows step a decade): picking a year shows its months,
and picking a month its days. Esc goes back to the days. The day's events show underneath.

**How:** `self.Month.value` is the chosen day, and `Month_change` runs as it changes:

```python
def Month_change(self):
    day = self.Month.value
    on_the_day = self.Events[self.Events["Date"].eq(day), "Event"]
```

In the Properties panel: `value` (empty for today, or a date like 2026-10-14), `min` and
`max` (empty for no limit) to limit the days that can be chosen, and `firstday`, "sunday"
or "monday", the day weeks start on. Set them from code as dates or as text:
`self.Month.min = datetime.date.today()`.

## The DatePickers

**Try:** click the button at the right of a date (or press F4, or Alt+Down) and choose a day
in the month that drops down: a click, or the arrow keys and Enter. Esc, or a click
elsewhere, closes it. Or type a date, in the field's own format, as year-month-day
(2026-10-14), or as people write them: Oct 18, 2026; 18 Oct; 10/18/2026; 10/18; tomorrow.
(Numbers are month first, unless the field's format puts the day first.) Typing while the
month is down works too: it goes, and the field takes what's typed. Up and Down step the
date a day.

**How:** `format` is how the date shows, in strftime's codes: here `%d %b %Y` (14 Oct
2026). The usual is `%Y-%m-%d` (2026-10-14); `%m/%d/%Y` is 10/14/2026, and `%x` the
locale's own.

The second, **to**, has `allow_empty` on: it can be left empty (clear it, or it starts that
way), and its `value` is then `None`, as a database's NULL. So the range has no end:

```python
if self.ToDate.value is not None:  # (empty: no end)
    within = within & (dates <= self.ToDate.value)
```

Its `min` follows the first's, so the end can't be before the start:

```python
def FromDate_change(self):
    self.ToDate.min = self.FromDate.value
```

## A date column

The events' first column is `Date : date %a %-d %b %Y`: a date, shown as Mon 5 Oct 2026
(after `date`, its format, as a DatePicker's; plain `date` is 2026-10-05). Press Enter or
double-click a date to drop its month down; F2 edits its text, as a text cell's; or just
type one (typing while the month is down works too). CSV files hold dates as
year-month-day, whatever's shown.

A date column's cells can be empty: a date has no zero, so an empty one is `None`. In a
condition, an empty date is neither before nor after any date: `dates >= start` is False
for it, as a database's NULL.

A new event (type in the blank row at the bottom) starts on the day chosen in the Calendar,
and clicking an event's row takes the Calendar to its day:

```python
def Events_rowadd(self, row):
    self.Events[row, "Date"] = self.Month.value

def Events_rowclick(self, row):
    if self.Events[row, "Date"] is not None:
        self.Month.value = self.Events[row, "Date"]
```

Click the Date header to sort by date (empty dates last). Done events are grayed.

## Times: a TimePicker

**Try:** in the **New** row, the field after the date is a TimePicker. Its button (or F4,
or Alt+Down) drops down the times, every half hour, the nearest one chosen: click one, or
use the arrows and Enter. Or type a time as people write them: 9:30 PM, 9:30pm, 21:30, 2130,
9 pm. Up and Down step it to the next half hour. Then type what's on and click **Add**.

**How:** `self.NewTime.value` is a `datetime.time` (or None, with `allow_empty`). Its
`step` is the minutes between the times dropped down (and that Up and Down step), and
`min` and `max` limit them (8:00 to 18:00 for working hours, say). Its `format` is
`%-I:%M %p`, 9:30 PM; `%H:%M` is 21:30. (`%-I` leaves out the hour's leading zero, on every
system: readymade sees to that, though Python's own strftime doesn't on Windows.)

The new event's day and time go into the table together:

```python
self.Events.rows.append([self.NewDay.value, self.NewTime.value, self.NewWhat.text, False])
```

and `datetime.datetime.combine(day, time)` makes them one date and time, when one's wanted.

## A date with a time: Remind me

**Try:** drop down **Remind me**'s month and choose a day, then change the time in the
field: 2026-10-20 9:00 AM, or as its format shows it. It can be left empty: no reminder.

**How:** a DatePicker whose `format` has a time in it (here `%a %-d %b %Y %-I:%M %p`) holds
a `datetime.datetime`: the month chooses its day, the time staying as it was, and the time
is typed. Arithmetic on it is Python's own: how long until the reminder is

```python
left = self.Remind.value - datetime.datetime.now()  # a timedelta
```

## A time column

The table's second column is `Time : time`: a `datetime.time`, shown as 9:30 PM. Press
Enter or double-click a time to drop down the times (every half hour), F2 to edit its text,
or just type one. A time can be empty
(None, as Call the plumber's): "all day". CSV files hold times as 21:30. A `datetime` column
holds both (`Logged : datetime`): its month drops down for its day, keeping its time, and a
CSV file holds 2026-10-14 21:30.

