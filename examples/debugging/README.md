# Debugging: a walkthrough

A shopping basket with a few mistakes in it, for trying every part of readymade's
debugger. Open it in the IDE:

    readymade examples/debugging

(or `python -m readymade.ide examples/debugging`). The code is in **Form1** (press F7
on the form for its code) and the module **pricing.py**. Lines marked `# TRY` are the
places this walkthrough uses.

Keys are written as on Windows and Linux. On a Mac, Ctrl is ⌘ (so Ctrl+F10 is ⌘F10),
F-keys may need fn, and Step Into is ⌘F11, since macOS keeps F11 for Show Desktop.

| Key | Does |
| --- | --- |
| F5 | Start, or continue when paused |
| Shift+F5 | End the program |
| F9 (or click a line number) | Set or clear a breakpoint |
| F10 | Step over: run the line, and pause on the next |
| F11 | Step into the function the line calls |
| Shift+F11 | Step out: finish this function, pause back where it was called |
| Ctrl+F10 | Run to the cursor's line |
| Ctrl+Shift+F10 | Set next statement: carry on from the cursor's line instead |
| F6 | Pause as the program's next event starts |
| Shift+F9 | Quick Watch: the value of the selected expression |

While the program is paused (the title says **[break]**), Locals, Watches and Call Stack
show beside the Immediate window. View > Debug Windows keeps them showing at other
times too.

## 1. An error pauses the program

1. Press **F5** to run the program.
2. Click **Empty basket**, then **Average price**.

The program pauses on the line that failed, `average = sum(prices) / len(prices)`,
with the error above the code (`ZeroDivisionError: division by zero`). Nothing is
lost yet:

- **Locals** shows the function's variables: `prices` is `[]`. Open `self` (the form)
  to look at its controls and the `basket`.
- The **Immediate window** runs Python inside the paused function. Type `? len(prices)`
  and press Enter.
- **Call Stack** shows how the program got here (just the click, this time).

Press **F5** to continue. Python can't redo a line that failed, so the rest of that
click is skipped and the program carries on. (Tools > Options can turn breaking on
errors off.)

Try it again with a bad number: type `free` as the price and click **Add**.

## 2. Breakpoints and stepping

1. End the program (**Shift+F5**).
2. In Form1's code, click the line number beside
   `total = pricing.total(self.basket)` in `show_total`. A red dot appears.
3. Press **F5**. Form_load calls show_total, so the program pauses there at once, before
   its window shows. The yellow line is the next to run.
4. Press **F11** to step into `pricing.total`. pricing.py opens, paused on
   `subtotal = 0`. **Call Stack** now lists `total`, `show_total` and `Form_load`;
   click one to see its variables and its place in the code.
5. Press **F10** a few times to go around the loop, watching `subtotal`, `item` and
   `cost` change in **Locals**. Open `basket` there to see the items in it.
6. While it's paused, try the **Immediate window**: `? subtotal`, `? item["name"]`,
   `? [i["name"] for i in basket]`.
7. Put the cursor on `taxed = (subtotal - discount) * (1 + TAX_RATE)` and press
   **Ctrl+F10** to run to it.
8. Press **Shift+F11** to step out, back to `show_total`, then **F5** to continue.

Breakpoints are remembered with the project (on this computer), and move with the code
as you edit it. **Ctrl+Shift+F9** clears them all.

## 3. A breakpoint with a condition, or a hit count

A breakpoint inside a loop stops every time around. To stop only when it matters:

1. Right-click the line number beside `cost = line_total(item)` in pricing.py and
   choose **Breakpoint Condition...**.
2. Type `item["name"] == "jam"` and click OK. The dot gets a white **+**.
3. Run the program (or click **Total** if it's running). It pauses only for the jam.

Open the dialog again and clear the condition, then choose a **hit count** instead,
and run the program again: "When the hit count is 3" stops the third time the line runs
(the bread, as the program works out its first total) and not again; "at least" stops
from then on; "a multiple of" stops every so many times. Hits are counted from the
start of each run, and only when the condition (if there is one) is true.

## 4. Set Next Statement

A basket over 40 gets 5 off. To see the total without the discount, without changing
any code:

1. Set a breakpoint on `discount = 5` in pricing.py.
2. With the program running, add an item that makes the basket bigger: Item `cheese`,
   Price `9.50`, then **Add**. It pauses on `discount = 5`.
3. Put the cursor on the next line, `taxed = ...`, and press **Ctrl+Shift+F10** (or
   right-click its line number: **Set Next Statement**). The yellow line jumps there,
   and the discount line never runs.
4. Press **F5**: the total shown has no discount.

It only works within the function that's paused, and Python refuses some jumps (into
the middle of a loop, for one); the Immediate window says why.

## 5. Watches

Watches keep an eye on an expression. **Debug > Add Watch...** asks for the expression,
its context (a function, a file, or anywhere) and what to do:

- **Watch the expression**: show its value.
- **Break when the value is true**: pause as soon as it becomes true.
- **Break when the value changes**: pause just after it changes.

Try these (open **View > Watches** first, so you can see them while the program runs):

1. `self.seconds_open`, context anywhere: it counts up live, as the clock ticks.
2. `TAX_RATE`, file pricing.py: a module's own names show while the program runs.
3. `subtotal`, function `total` in pricing.py: a function's variables only exist while
   it runs, so this shows its value "as total left it" (click **Total** to update it).
4. With the program running, add `subtotal > 20`, function `total`, **Break when the
   value is true**, then click **Total**: it pauses as the loop pushes the subtotal
   past 20.
5. While the program runs, add `len(self.basket)`, file Form1.py, **Break when the value
   changes**, then add an item. It pauses on the line after `self.basket.append(item)`:
   Python tells the debugger about a line just before it runs, so the change is noticed
   as the next line starts. The message names the line that made the change, and it's
   marked in green.

Right-click a watch to edit or delete it. Watches that break slow the program while they
check every line in their context, so choose a function when you can.

**Quick Watch**: while paused, select an expression in the code and press **Shift+F9**
to see its value at once, with a button to add it as a watch. For example, paused at
the breakpoint in `show_total` (section 2), select `pricing.total(self.basket)`.

## 6. Pause

A program waiting for a click isn't running any code, so there's nothing to stop in.
**F6** pauses as the next event starts. Here a timer ticks every second, so press F6 and
it pauses in `Timer1_timer` within a second.

## 7. Starting by stepping

With the program stopped, press **F11** (or F10). The program starts and pauses on the
first line of its first event, Form_load. Step from there.

## 8. An error as the program starts

In pricing.py, remove the `#` from `# FREE_DELIVERY = BIG_ORDER / 0` and press **F5**.
The error happens while Form1 is importing pricing, before there's a window, so the
program pauses on that line with the module's names in Locals; it can't go on, and
Continue or End ends it. Put the `#` back afterwards.

## 9. Find the bug

There's one more mistake, a quiet one. Run the program, choose **2 x tea** in the
list and click **Remove**. The tea goes from the list, but the total doesn't drop by
7.00 (twice 3.50) as it should. Use a breakpoint in `btnRemove_click` and Locals (or
a watch on `self.basket`) to find out why.

The answer is at the end of this file.



































**Answer:** `del self.basket[index - 1]` removes the item *before* the chosen one.
For the first item, `index - 1` is `-1`, which in Python means the last item, so the
coffee went instead of the tea. It should be `del self.basket[index]`.
