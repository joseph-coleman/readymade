"""A planner: a Calendar, DatePickers (one with a time), a TimePicker, and a DataTable with
date and time columns. README.md walks through it."""

import datetime

from readymade import Form

DAY = datetime.timedelta(days=1)
T = datetime.time


class Form1(Form):
    def Form_load(self):
        today = datetime.date.today()  # (events around today, so they're in the month shown)
        self.Events.rows = [
            [today - 3 * DAY, T(8, 30), "Car service", True],
            [today, T(10), "Dentist", False],
            [today, None, "Call the plumber", True],  # (no time: an empty time cell)
            [today + 2 * DAY, None, "Pay the rent", False],
            [today + 5 * DAY, T(12, 30), "Lunch with Sam", False],
            [today + 12 * DAY, T(19), "Book club", False],
        ]
        self.Events.autosize_columns("Date", "Time", "Done")  # (Event shares out what's left)
        self.FromDate.value = today - 7 * DAY
        self.NewDay.value = today
        self.Remind_change()
        self.events_changed()

    # ----- the Calendar: the chosen day's events -----

    def Month_change(self):
        self.NewDay.value = self.Month.value  # (a new event: on the day chosen, at first)
        self.show_day()

    def show_day(self):
        day = self.Month.value  # (a datetime.date)
        on_the_day = self.Events[self.Events["Date"].eq(day), "Time":"Event"]  # a condition on the date column
        self.DayLabel.text = day.strftime("%A %d %B")
        lines = [f"{time:%I:%M %p}  {event}" if time else event for time, event in on_the_day]
        self.DayList.text = "\n".join(lines) or "Nothing happening."

    # ----- the DatePickers: a range, its end optional -----

    def FromDate_change(self):
        self.ToDate.min = self.FromDate.value  # (the end can't be before the start)
        self.count_between()

    def ToDate_change(self):
        self.count_between()

    def count_between(self):
        dates = self.Events["Date"]
        within = dates >= self.FromDate.value
        if self.ToDate.value is not None:  # (empty: no end)
            within = within & (dates <= self.ToDate.value)
        end = " to " + self.ToDate.value.strftime("%d %b") if self.ToDate.value else " onwards."
        self.Status.text = f"{len(self.Events[within, 'Event'])} events from {self.FromDate.value:%d %b}{end}"

    # ----- a new event: a DatePicker and a TimePicker -----

    def AddButton_click(self):
        if not self.NewWhat.text.strip():
            return
        self.Events.rows.append([self.NewDay.value, self.NewTime.value, self.NewWhat.text, False])
        # By day, then time: those with no time first, as a calendar shows all-day ones.
        self.Events.rows.sort(key=lambda row: (row["Date"], row["Time"] or T.min))
        self.NewWhat.text = ""
        self.events_changed()  # (code's changes run no events: so, by hand)

    # ----- a reminder: a DatePicker with a time, which can be empty -----

    def Remind_change(self):
        when = self.Remind.value  # a datetime.datetime, or None
        if when is None:
            self.RemindNote.text = "No reminder"
            return
        left = when - datetime.datetime.now()  # (a timedelta)
        hours = round(left.total_seconds() / 3600)
        self.RemindNote.text = f"In {hours // 24} days, {hours % 24} hours" if hours >= 0 else "That's past"

    # ----- the DataTable: events with dates -----

    def Events_rowclick(self, row):  # the Calendar goes to the event's day
        if self.Events[row, "Date"] is not None:
            self.Month.value = self.Events[row, "Date"]

    def Events_rowadd(self, row):  # a new event: on the day chosen in the Calendar
        self.Events[row, "Date"] = self.Month.value

    def Events_cellchange(self, row, column):
        self.events_changed()

    def Events_rowdelete(self, row, values):
        self.events_changed()

    def events_changed(self):
        for row in self.Events.rows:  # done ones grayed
            row.forecolor = "#909090" if row["Done"] else ""
        self.show_day()
        self.count_between()


if __name__ == "__main__":
    Form1.run()
