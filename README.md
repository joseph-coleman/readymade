# readymade

**readymade** is a Python language version of a classic VB style coding experience. 
This is for small tools that might need a user interface.  You draw on a form,
double-click a button to write its code, press F5 to run.  **readymade** aims to
leave almost no time between having an idea and running the program.

> Still early: readymade is a pre-alpha. It works, and it's changing quickly.

## What it does

- **A form designer.** Draw controls from the Toolbox (Label, TextBox, Button,
  CheckBox, OptionButton, ComboBox, ListBox, TreeView, ListView, ScrollBar, Slider,
  UpDown, ProgressBar, Frame, TabStrip, Grid, Image, Canvas, Timer), then set
  their properties in the Properties panel. Align and size them with the Format menu,
  design menus in the Menu Editor, and set the tab order by clicking. Control arrays work
  as in VB: `Digit[0]`, `Digit[1]`... share one `Digit_click(self, index)`. Anchors, docking
  (WinForms-style: a control fills an edge, or what's left) and Grids (rows and columns sized
  like WPF's: `auto, *, 2*, 120`) make forms that resize well. Buttons and Labels can show
  pictures, and flat buttons and button-look toggles make toolbars.
- **Double-click to code.** Double-clicking a control takes you to its event handler,
  written for you as a method named after it: `Button1_click`, `Form_load`. Code can add
  controls too (`self.add_control("Button", "Save", text="Save")`) and attach more handlers,
  as JavaScript does: `self.Save.on("click", self.save_all)`.
- **F5 to run.** While your program runs, the Immediate window runs Python inside it.
- **A debugger, as in VB.** A run-time error pauses the program on the line that failed,
  with its variables in Locals and the Call Stack. Set breakpoints (F9, with conditions,
  hit counts or log messages), step (F10, F11), set the next statement, and watch
  expressions, or break when one changes. `examples/debugging` walks through it all.
- **Plain Python.** A form is two files: a `.form` file (JSON, for the layout) and a
  `.py` file (your code).  One can run the form directly with python without starting
  the IDE by running just the python file, `python path/to/Form.py`.
- **Projects.** A project has a `pyproject.toml`, its own virtual environment and
  libraries (Project > Add Library), linting and formatting with the tools you choose,
  and Make EXE (via PyInstaller), which turns it into a program that runs without Python.
- **The toolkit is Tkinter**, which comes with Python, so programs need nothing else
  installed. Pillow, if you add it to a project, opens more picture formats and lets
  programs draw on pictures.

```python
from readymade import Form, msgbox


class Form1(Form):
    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"
        msgbox(f"Hello, {name}!")


if __name__ == "__main__":
    Form1.run()
```

## Install and start

readymade needs Python 3.11 or later, with Tkinter (Python's Windows and macOS
installers include it; on Linux it may be a separate package, like `python3-tk`).

```
python -m pip install "readymade[ide]"
readymade my-first-project
```

`readymade` opens the IDE, creating the project folder if it doesn't exist
(`python -m readymade.ide` does the same). The `ide` extra adds syntax coloring
(Pygments), completion with Go to Definition (Jedi), and JPEG and other pictures in
the designer (Pillow). The IDE works without them. A program that uses Pillow, to
show those pictures or draw on them, needs it in its own project too
(Project > Add Library), so that Make EXE includes it.

Press F1 in the IDE for help on whatever you're working on.

## Examples

The repository's `examples` folder has projects to open in the IDE (`readymade examples/controls`):

- **controls**: a recipe book using most of the controls for real jobs: docking, a toolbar of
  flat picture buttons and toggles, a control array, TabStrip, TreeView, ListView, UpDown,
  Slider, ScrollBar, ProgressBar and a Timer. Its README walks through each.
- **arrays**: controls made while the program runs: adding to a control array, `add_control()`,
  and handlers attached with `on()`.
- **debugging**: a shopping basket with mistakes in it, and a walkthrough of the debugger.
- **anchors**: a form whose controls follow its size.
- **hello**: a small first program: type a name and click a button, laid out in a Grid.

## Disclosure

I used Claude. 

## License

MIT. See [LICENSE](LICENSE).
