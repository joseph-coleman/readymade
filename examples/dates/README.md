# A planner: dates three ways

A Calendar, two DatePickers, and a DataTable with a date column. Open it in the IDE:

    readymade examples/dates

and press **F5**. The code is in **Form1** (F7 on the form). The events are made around
today, so they're in the month the Calendar opens on.

Dates are Python's own `datetime.date` everywhere: a control's `value`, a date cell, and
what you compare them with.

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
elsewhere, closes it. Or type a date, in the field's own format or as year-month-day
(2026-10-14), and Up and Down step it a day.

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

The events' first column is `Date : date %a %d %b %Y`: a date, shown as Wed 14 Oct 2026
(after `date`, its format, as a DatePicker's; plain `date` is 2026-10-14). Press Enter, F2
or double-click a date to drop its month down, or type one. CSV files hold dates as
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
