# Controls made while the program runs

Two ways to make controls from code, and the ways to handle their events. Open it in the IDE:

    readymade examples/arrays

and press **F5**. The code is in **Form1** (F7 on the form) and in the module **helpers.py**.

## 1. Adding to a control array drawn in the designer

**Try:** click **Click for more** on the left. Each click adds a numbered button under it.

**How:** in the designer there's one button, `Button1[0]`: a control array of one (its
`index` is 0 in the Properties panel). `add()` makes another control like it:

```python
def Button1_click(self, index):
    b = self.Button1.add(max(self.Button1.indexes) + 1)  # a copy of Button1[0], hidden at first
    b.text = str(b.index)
    b.visible = True
```

The copy has the same size, look, container and docking (here, `dock` "top" in Frame1), so
it lines up under the others. It's made hidden, as VB's `Load` did, so it can be placed
before it shows. Every one shares `Button1_click`, told which by `index`.

## 2. Making controls from nothing

**Try:** change the number at the top right. That many buttons appear below it. Click one,
and the status line says which.

**How:** `add_control()` makes a control as the designer would: a type, a name, and any
properties (the rest as designed). `container` puts it in a Frame:

```python
def UpDown1_change(self):
    for button in list(getattr(self, "B2", [])):  # last time's buttons, if any
        self.remove_control(button)
    for n in range(self.UpDown1.value):
        self.add_control("Button", f"B2[{n}]", container="Frame2", dock="top", text=f"Button {n}")
```

Names like `B2[0]`, `B2[1]` make them a control array, so one handler serves them all and is
told which by its index. As for a drawn control, a method named after them on the form is
attached to each as it's made:

```python
def B2_click(self, index):
    custom_click_event(self, index)  # in helpers.py: form.B2[index] is the button clicked
```

`remove_control()` takes away a control made in code (not one drawn in the designer: hide
those with `visible` instead). `getattr(self, "B2", [])` covers the first time, before the
array exists; after that it's there even when empty, ready for the next round.

## 3. Attaching handlers from code

**Try:** click **Clear** at the bottom right.

**How:** Clear is made in `Form_load`, and its handler attached with `on()`, as JavaScript's
`addEventListener` does:

```python
def Form_load(self):
    clear = self.add_control("Button", "Clear", container="Frame2", dock="bottom", height=32,
                             text="Clear")
    clear.on("click", clear_all)
```

`clear_all` is a plain function in helpers.py, with no `self`. `on()` sees it wants one more
argument than a click gives (none), and passes the form:

```python
def clear_all(form):
    form.UpDown1.value = 0  # (its change event takes the buttons away)
```

A method of the form works too (`clear.on("click", self.reset)`), as does a lambda inside
one, which can use `self` itself. `on()` adds to any handlers already there, and `off()`
takes one away. A control array has `on()` as well, for all its controls, those added later
included: `self.B2.on("click", custom_click_event)` would do what `B2_click` does here (call
it once, after the first button exists).

## Which control fired?

A handler is told what the event says (the click: nothing; a control array's click: the
index), not which control it's for. For controls made in a loop, a control array answers
that: its index finds the control (`form.B2[index]`). For a single control, a lambda can
remember it: `b.on("click", lambda b=b: show(b))`. (The `b=b` keeps each lambda's own `b`;
without it, every one would see the loop's last.)
