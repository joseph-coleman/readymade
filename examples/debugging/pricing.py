"""Prices for the debugging example. Form1's show_total() calls total(), so F11 on that
line steps in here, and the Call Stack shows both."""

TAX_RATE = 0.08  # TRY: watch TAX_RATE with pricing.py as its file: it shows while the program runs
BIG_ORDER = 40  # a basket over this gets a discount

# TRY (an error as the program starts): remove the # from the next line, then press F5.
# FREE_DELIVERY = BIG_ORDER / 0


def line_total(item):
    return item["price"] * item["qty"]


def total(basket, discount=0):
    subtotal = 0
    for item in basket:
        cost = line_total(item)  # TRY: a breakpoint with the condition item["name"] == "jam", or a hit count
        subtotal += cost  # TRY: watch subtotal > 20 in total(), breaking when it becomes true
    if subtotal > BIG_ORDER:
        discount = 5  # TRY: paused here, put the cursor on the next line and press Ctrl+Shift+F10
    taxed = (subtotal - discount) * (1 + TAX_RATE)
    return round(taxed, 2)
