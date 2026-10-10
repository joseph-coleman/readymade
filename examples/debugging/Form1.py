"""Debugging: a shopping basket with mistakes in it, to try readymade's debugger on.

README.md in this folder walks through each part step by step; the # TRY comments
mark the places it uses. In short:

    Errors       Empty the basket, then click Average price: the program pauses at the
                 line that failed, with its variables in Locals.
    Breakpoints  F9, or click a line number: the program pauses before that line runs.
                 Right-click a line number for a condition or a hit count.
    Stepping     F10 steps over a line, F11 into a function (on a Mac, ⌘F11), Shift+F11
                 out of it, Ctrl+F10 runs to the cursor, Ctrl+Shift+F10 makes the
                 cursor's line the next one to run. F5 continues, Shift+F5 ends.
    Break mode   Locals, Watches and Call Stack show beside the Immediate window, which
                 runs Python in the paused function: ? subtotal
    Watches      Debug > Add Watch. View > Watches shows them while the program runs too.
    Pause        F6 pauses as the next event starts (the clock ticks every second).
    Starting     F10 or F11 with nothing running starts the program, pausing in Form_load.
"""

from readymade import Form

import pricing


class Form1(Form):
    def Form_load(self):
        # TRY: with the program stopped, press F11 (⌘F11 on a Mac): it starts and pauses here.
        self.basket = []
        self.seconds_open = 0
        for name, price, qty in (("tea", 3.50, 2), ("jam", 4.25, 1), ("bread", 2.75, 3), ("coffee", 11.99, 1)):
            self.add(name, price, qty)
        self.show_total()

    def add(self, name, price, qty):
        item = {"name": name, "price": price, "qty": qty}
        self.basket.append(item)  # TRY: watch len(self.basket), breaking when the value changes
        self.lstBasket.add_item(f"{qty} x {name} at {price:.2f}")

    def show_total(self):
        total = pricing.total(self.basket)  # TRY: a breakpoint here, then F11 steps into pricing.py
        self.lblTotal.text = f"Total: {total:.2f}  ({len(self.basket)} items)"

    def btnAdd_click(self):
        name = self.txtItem.text.strip() or "something"
        price = float(self.txtPrice.text)  # TRY: type "free" as the price, and a ValueError pauses here
        qty = int(self.txtQty.text or "1")
        self.add(name, price, qty)
        self.show_total()
        self.txtItem.text = ""
        self.txtPrice.text = ""

    def btnTotal_click(self):
        self.show_total()

    def btnAverage_click(self):
        prices = [item["price"] for item in self.basket]
        average = sum(prices) / len(prices)  # TRY: empty the basket first, and a ZeroDivisionError pauses here
        self.lblTotal.text = f"Average price: {average:.2f}"

    def btnRemove_click(self):
        index = self.lstBasket.list_index
        if index >= 0:
            del self.basket[index - 1]
            self.lstBasket.remove_item(index)
            self.show_total()

    def btnClear_click(self):
        self.basket.clear()
        self.lstBasket.clear()
        self.show_total()

    def Timer1_timer(self):
        self.seconds_open += 1  # TRY: F6 (Pause) stops here at the next tick; watch self.seconds_open
        self.lblClock.text = f"Open for {self.seconds_open} seconds"


if __name__ == "__main__":
    Form1.run()
