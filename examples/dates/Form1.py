"""A planner: a Calendar, two DatePickers, and a DataTable with a date column. README.md
walks through it."""

import datetime

from readymade import Form

DAY = datetime.timedelta(days=1)


class Form1(Form):
    def Form_load(self):
        today = datetime.date.today()  # (events around today, so they're in the month shown)
        self.Events.rows = [
            [today - 3 * DAY, "Car service", True],
            [today, "Dentist", False],
            [today, "Call the plumber", True],
            [today + 2 * DAY, "Pay the rent", False],
            [today + 5 * DAY, "Lunch with Sam", False],
            [today + 12 * DAY, "Book club", False],
        ]
        self.Events.autosize_columns("Date")
        self.FromDate.value = today - 7 * DAY
        self.events_changed()

    # ----- the Calendar: the chosen day's events -----

    def Month_change(self):
        self.show_day()

    def show_day(self):
        day = self.Month.value  # (a datetime.date)
        on_the_day = self.Events[self.Events["Date"].eq(day), "Event"]  # a condition on the date column
        self.DayLabel.text = day.strftime("%A %d %B")
        self.DayList.text = "\n".join(on_the_day) or "Nothing happening."

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
        self.Status.text = f"{len(self.Events[within, 'Event'])} events from {self.FromDate.value:%d %b} {end}"

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
