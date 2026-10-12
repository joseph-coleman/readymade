# Recipe Box: the controls at work

A small recipe book that uses most of readymade's controls for real jobs, rather than
showing them off one by one. Open it in the IDE:

    readymade examples/controls

(or `python -m readymade.ide examples/controls`), and press **F5** to run it. The code is in
**Form1** (F7 on the form) and the recipes in the module **recipes.py**. Nothing you change
while it runs is saved: each run starts with the same recipes.

Each part below says what to try while it runs, then how it's built, so you can look at the
same properties in the designer (click a control, and read the Properties panel).

## The layout: docking

Nothing on this form is placed by its left and top. Each part is **docked** to an edge:

| Control | `dock` | What it does |
| --- | --- | --- |
| Bar (a Frame) | top | the toolbar |
| Status (a Label) | bottom | the status line |
| Recipes (a TreeView) | left | the list of recipes |
| Tabs (a TabStrip) | fill | everything else |

**Try:** make the window bigger and smaller. The toolbar and status line keep their height,
the recipe list keeps its width, and the tabs take the rest. Drag the edge between the recipe
list and the tabs to make the list wider or narrower. The window won't get smaller than 600 by
400, so nothing gets squeezed out of sight.

**How:** docked controls take their edges in the order they were drawn (Format > Order changes
it), and `fill` takes what's left. Docking works inside containers too: on the Ingredients
page, the Servings row is a Frame docked to the top of the page, with the list filling the rest.

The recipe list has `splitter` True: a bar along its inner edge that the user drags. The form
has `minwidth` 600 and `minheight` 400 (click the form itself and look in the Properties panel;
`maxwidth`, `maxheight` and `resizable` are there too).

## The toolbar: flat buttons, toggles, and a control array

**Try:** open the **Method** tab, then click **B** (bold) and the three alignment buttons.
Rest the mouse on a button for its tooltip.

**How:**
- **Bar** is a Frame with `border` False: just the buttons show (the designer still
  outlines it, so you can find it).
- **NewRecipe** and **DeleteRecipe** are Buttons with a `picture` from `images/`, no text,
  and `flat` True: a toolbar's button, drawn as each system draws them. `tabstop` is False,
  so Tab passes them by.
- **Bold** is a CheckBox with `appearance` "button": a toggle that stays pressed while it's on.
- **Align[0]**, **Align[1]** and **Align[2]** are a **control array** of OptionButtons, also
  with `appearance` "button". As OptionButtons in one container, one is chosen at a time; as a
  control array, they share one handler, which is told which by its index:

  ```python
  def Align_click(self, index):
      self.Method.alignment = ALIGNMENTS[index]
  ```

  Click one and look at its `index` in the Properties panel. Giving a control an `index`
  starts an array; pasting a copy of one of its controls adds the next.
- **Gap** is an empty Label docked left: a space between the groups.

## Recipes: a TreeView

**Try:** click a recipe, then a category. Click **New recipe** (the page with a +) and give it
a name. Then **Delete** it (the ✕).

**How:** `Form_load` fills the tree with `add()`, which returns a Node that can `add()` its own:

```python
node = self.Recipes.add(category, key=category)
for name in recipes:
    node.add(name)
```

`Recipes_nodeclick(self, node)` runs when one is chosen: it's given the Node, whose `parent`
says whether it's a recipe (under a category) or a category itself.

## Ingredients: an UpDown and a ListView

**Try:** change **Servings** with its arrows, the Up and Down keys, or by typing. The amounts
follow. Click a column's header to sort by it, and click again to sort the other way.

**How:** `Servings` is an UpDown (`min` 1, `max` 24); its `change` event refills the list with
the amounts scaled. `Ingredients` is a ListView whose `columns` are set in the designer; rows
come from `add("Flour", "200", "g")`. With `sortable` True, a header click sorts. Numbers sort
as numbers, so 1,000 comes after 200.

## Method: a multi-line TextBox and a Slider

**Try:** edit the method; switch recipes and come back (it's kept while the program runs).
Drag **Text size**, or click it and use the arrow keys, Page Up/Down, Home and End.

**How:** `TextSize` is a Slider (`min` 9, `max` 24). Its `change` event and the Bold toggle both
set the text's font:

```python
self.Method.font = f", {self.TextSize.value}" + (", bold" if self.Bold.value else "")
```

(An empty family, before the first comma, keeps the usual font.)

## Cook: a ScrollBar, a ProgressBar and a Timer

**Try:** set **Minutes** with the ScrollBar (its arrows, a click beside the thumb, or a drag),
and click **Start**. It counts down quickly: a "minute" is a quarter of a second here. Click
**Stop** to stop it partway.

**How:** `Minutes` is a ScrollBar (`smallchange` 1 for its arrows, `largechange` 10 for a click
beside the thumb). **Start** sets the ProgressBar's `max` and switches on `CookTimer`, whose
`interval` is 250 milliseconds; each `CookTimer_timer` moves the ProgressBar on one, and when
it's full, a `msgbox` says it's ready. Set the interval to 60000 for real minutes.

The Timer is invisible while the program runs. In the designer it sits at the right end of
the status line; click it there to see its properties.

## Pictures

The toolbar's pictures are PNG files in `images/`, chosen with the **…** beside a Button's
`picture` property, which copies a file into `images/` if it isn't in the project already.
`picture_position` puts the picture beside the text: the **Start** button has both, with its
picture on the left. Make EXE bundles the pictures a program uses.
