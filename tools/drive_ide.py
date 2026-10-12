"""Drive the IDE with real mouse and keyboard input on a private Xvfb display.

    python3 tools/drive_ide.py [output_dir]

Needs Xvfb and xdotool. The IDE runs in this process so the script can ask Tk
where widgets are, but every click, drag and keystroke goes through the X
server, exercising the same event bindings a person would. Screenshots of each
step are saved to output_dir (default /tmp/readymade-ui). It starts from its own
Hello World form in a temporary folder, so it doesn't depend on (or touch)
examples/hello.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

DISPLAY = ":99"
ROOT = Path(__file__).resolve().parent.parent

# The starting form. The steps below draw into the empty space on the right and bottom.
START_CONTROLS = [
    ("Label", "Label1", 16, 16, 288, 24, {}),
    ("TextBox", "TextBox1", 16, 48, 184, 24, {"text": ""}),
    ("Button", "Button1", 208, 46, 96, 28, {"text": "Say Hello"}),
    ("Label", "Label2", 24, 232, 288, 24, {"text": ""}),
]
START_CODE = """from readymade import Form


class Form1(Form):
    def Form_load(self):
        self.Label1.text = "What's your name?"

    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"
        self.Label2.text = f"Hello, {name}!"

    def TextBox1_keypress(self, key):
        if key == "Enter":
            self.Button1_click()

    def Button1_mousedown(self, x, y):
        print("mouse down!")


if __name__ == "__main__":
    Form1.run()
"""


def write_start_form(folder):
    from readymade import formfile
    from readymade.controls import REGISTRY
    from readymade.project import Project

    design = formfile.FormDesign(name="Form1", text="Hello, World", width=448, height=320)
    for type_name, name, left, top, width, height, props in START_CONTROLS:
        spec = REGISTRY[type_name].new_spec(name, left, top, width, height)
        spec.update(props)
        design.controls.append(spec)
    formfile.save(design, folder / "Form1.form")
    (folder / "Form1.py").write_text(START_CODE, encoding="utf-8")
    Project(folder).set_startup("Form1")  # writes pyproject.toml


def start_xvfb():
    if Path(f"/tmp/.X{DISPLAY[1:]}-lock").exists():
        sys.exit(f"Display {DISPLAY} is already in use")
    # Under WSLg /tmp/.X11-unix is read-only, so Xvfb can only listen on its abstract
    # socket and no socket file appears. -displayfd tells us when it's ready instead.
    ready_r, ready_w = os.pipe()
    log = tempfile.TemporaryFile()
    server = subprocess.Popen(
        ["Xvfb", DISPLAY, "-screen", "0", "1280x800x24", "-nolisten", "tcp", "-displayfd", str(ready_w)],
        pass_fds=(ready_w,), stdout=log, stderr=log,
    )
    os.close(ready_w)
    with os.fdopen(ready_r) as ready:
        if not ready.readline().strip():
            server.wait()
            log.seek(0)
            sys.exit("Xvfb didn't start:\n" + log.read().decode(errors="replace"))
    return server


class Driver:
    def __init__(self, app, out):
        self.app, self.root, self.out = app, app.root, out
        self.step = 0
        self.failures = []

    def pump(self, seconds=0.15):
        end = time.time() + seconds
        while time.time() < end:
            self.root.update()
            time.sleep(0.01)

    def xdo(self, *args):
        subprocess.run(["xdotool", *map(str, args)], check=True)

    def at(self, widget, x=None, y=None):
        """Screen coordinates of a point in widget (default: its center)."""
        x = widget.winfo_width() // 2 if x is None else x
        y = widget.winfo_height() // 2 if y is None else y
        return widget.winfo_rootx() + x, widget.winfo_rooty() + y

    def click(self, x, y, repeat=1):
        self.xdo("mousemove", x, y)
        self.pump(0.05)
        self.xdo("click", "--repeat", repeat, "--delay", 60, 1)
        self.pump()

    def drag(self, x0, y0, x1, y1, steps=8):
        self.xdo("mousemove", x0, y0)
        self.pump(0.05)
        self.xdo("mousedown", 1)
        self.pump(0.05)
        for i in range(1, steps + 1):
            self.xdo("mousemove", x0 + (x1 - x0) * i // steps, y0 + (y1 - y0) * i // steps)
            self.pump(0.02)
        self.xdo("mouseup", 1)
        self.pump()

    def type(self, text):
        self.xdo("type", "--delay", 20, text)
        self.pump()

    def key(self, *keys):
        self.xdo("key", *keys)
        self.pump()

    def shot(self, name):
        from PIL import ImageGrab

        self.pump(0.3)
        self.step += 1
        path = self.out / f"{self.step:02d}-{name}.png"
        ImageGrab.grab(xdisplay=DISPLAY).crop((0, 0, 1280, 800)).save(path)
        print(f"  screenshot {path}")

    def tab_at(self, notebook, child):
        """Screen coordinates inside child's tab in a ttk.Notebook."""
        index = notebook.index(child)
        for x in range(2, notebook.winfo_width(), 4):
            try:
                if notebook.index(f"@{x},10") == index:
                    return notebook.winfo_rootx() + x + 8, notebook.winfo_rooty() + 10
            except Exception:  # no tab at that point
                continue
        raise LookupError(f"no tab for {child}")

    def prop_editor(self, prop):
        """The Properties panel's editor widget for prop, scrolled into view (as a person would)."""
        grid = self.app.properties.grid_frame
        label = next(w for w in grid.grid_slaves(column=0) if w.cget("text") == prop)
        editor = grid.grid_slaves(row=label.grid_info()["row"], column=1)[0]
        self.app.properties._see(editor)
        self.pump(0.1)
        return editor

    def check(self, label, actual, expected):
        ok = actual == expected
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
        if not ok:
            self.failures.append(label)

    def ask(self, expression, timeout=10):
        """Evaluate an expression in the running program via the Immediate window."""
        marker = f"@@{self.step}{time.time_ns()}@@"
        self.app.runner.immediate_line(f"print({marker!r}, repr({expression}))")
        deadline = time.time() + timeout
        while time.time() < deadline:
            self.pump(0.05)
            for line in self.app.immediate.output.get("1.0", "end").splitlines():
                if line.startswith(marker + " "):
                    return eval(line[len(marker) + 1 :])
        output = self.app.immediate.output.get("1.0", "end").strip().splitlines()
        raise TimeoutError(f"{expression}\n--- Immediate window (last lines) ---\n" + "\n".join(output[-15:]))


def drive(d):
    app = d.app
    editor = app.form  # Form1's editor
    canvas = editor.surface.canvas
    tool = app.toolbox.buttons  # {type name: its button}

    print("Design view")
    d.shot("design")

    print("Draw a Button by dragging a rectangle")
    d.click(*d.at(tool["Button"]))
    x0, y0 = d.at(canvas, 24, 160)
    d.drag(x0, y0, x0 + 120, y0 + 32)
    spec = editor.design.control("Button2")
    d.check("new control", spec and (spec["left"], spec["top"], spec["width"], spec["height"]), (24, 160, 120, 32))
    d.check("selected", editor.selected, "Button2")
    d.check("tool resets to pointer", app.toolbox.tool, "")
    d.shot("drawn")

    print("Move it by dragging")
    widget = editor.surface.controls["Button2"].widget
    x, y = d.at(widget)
    d.drag(x, y, x + 41, y + 22)
    d.check("moved (snapped to grid)", (spec["left"], spec["top"]), (64, 184))

    print("Resize with the bottom-right handle")
    x, y = d.at(editor.surface.handles[(1, 1)])
    d.drag(x, y, x + 30, y + 15)
    d.check("resized (snapped)", (spec["width"], spec["height"]), (152, 48))
    d.check("properties panel follows", app.properties._rows["width"][0].get(), "152")
    d.shot("moved-resized")

    print("Undo, redo and the arrow keys")
    # Undo rebuilds the form from a snapshot, so look Button2 up afresh each time.
    geometry = lambda: tuple(editor.design.control("Button2")[k] for k in ("left", "top", "width", "height"))  # noqa: E731
    d.key("ctrl+z")
    d.check("Ctrl+Z undoes the resize", geometry(), (64, 184, 120, 32))
    d.key("ctrl+y")
    d.check("Ctrl+Y redoes it", geometry(), (64, 184, 152, 48))
    d.key("Right", "Right")
    d.key("shift+Down")
    d.check("arrows move, Shift+arrow resizes", geometry(), (80, 184, 152, 56))
    d.check("the designer follows", editor.surface.controls["Button2"].left, 80)
    d.key("ctrl+z")
    d.key("ctrl+z")
    d.check("two undos: the resize, then both moves", geometry(), (64, 184, 152, 48))

    print("Select several controls: Ctrl+click, drag them together, a selection box")
    left_top = lambda name: tuple(editor.design.control(name)[k] for k in ("left", "top"))  # noqa: E731
    d.click(*d.at(editor.surface.controls["Button1"].widget))
    d.xdo("keydown", "ctrl")
    d.click(*d.at(editor.surface.controls["Button2"].widget))
    d.xdo("keyup", "ctrl")
    d.check("Ctrl+click adds to the selection", editor.selection, ["Button1", "Button2"])
    d.check("corner marks on both", len(editor.surface._markers), 8)
    d.shot("multi-select")
    x, y = d.at(editor.surface.controls["Button2"].widget)
    d.drag(x, y, x + 16, y + 8)
    d.check("both moved together", (left_top("Button1"), left_top("Button2")), ((224, 54), (80, 192)))
    d.key("ctrl+z")
    d.check("one undo puts both back", (left_top("Button1"), left_top("Button2")), ((208, 46), (64, 184)))
    x0, y0 = d.at(editor.surface.canvas, 8, 176)
    d.drag(x0, y0, x0 + 72, y0 + 72)  # from empty space, over Button2 and Label2
    d.check("the box selects what it touches", sorted(editor.selection), ["Button2", "Label2"])
    editor.align("lefts")
    d.check("Format > Align > Lefts lines them up", left_top("Button2")[0] == left_top("Label2")[0], True)
    d.key("ctrl+z")
    d.check("undo the alignment", (left_top("Button2"), left_top("Label2")), ((64, 184), (24, 232)))

    print("Copy and paste with the keyboard")
    d.click(*d.at(editor.surface.controls["Button2"].widget))
    d.check("clicking one control of a selection selects just it", editor.selection, ["Button2"])
    d.key("ctrl+c")
    d.key("ctrl+v")
    d.check("Ctrl+C, Ctrl+V: a copy, offset and selected", (editor.selection, left_top("Button3")), (["Button3"], (80, 200)))
    d.shot("pasted")
    d.key("ctrl+z")
    d.check("undo the paste", editor.design.control("Button3"), None)
    editor.set_property("Button2", "index", "0")  # a control array: copies of its control join it
    d.click(*d.at(editor.surface.controls["Button2[0]"].widget))
    d.key("ctrl+c")
    d.key("ctrl+v")
    d.check("a copy of Button2[0] is Button2[1]", [c["name"] for c in editor.design.controls if c["name"].startswith("Button2")],
            ["Button2[0]", "Button2[1]"])
    d.key("ctrl+z")
    d.key("ctrl+z")
    d.check("undo the control array", editor.design.control("Button2") is not None, True)
    editor.show_code()
    d.pump(0.3)  # let Tk lay out the Code tab before measuring where to click
    d.click(*d.at(editor.code.text, 40, 8))
    d.key("Home", "shift+End")
    d.key("ctrl+c")
    d.check("Ctrl+C in the code copies text, not controls",
            (app.root.clipboard_get(), [c["name"] for c in app.clipboard]), ("from readymade import Form", ["Button2[0]"]))  # (the controls copied last)

    print("Indent and dedent a block of code with Tab and Shift+Tab")
    before = editor.code.get_source()
    d.key("ctrl+Home", "Down", "Down", "Down", "Down")  # line 5: "    def Form_load(self):"
    d.key("shift+Down", "shift+Down")  # select lines 5 and 6
    d.key("Tab")
    lines = editor.code.get_source().splitlines()
    d.check("Tab indents both lines", (lines[4], lines[5]), ("        def Form_load(self):", "            self.Label1.text = \"What's your name?\""))
    d.key("shift+Tab")
    d.check("Shift+Tab puts them back", editor.code.get_source() == before, True)
    d.key("ctrl+slash")
    lines = editor.code.get_source().splitlines()
    d.check("Ctrl+/ comments them out", (lines[4], lines[5]), ("    # def Form_load(self):", "    #     self.Label1.text = \"What's your name?\""))
    d.check("line numbers in the gutter", [editor.code.gutter.itemcget(i, "text") for i in editor.code.gutter.find_all()][:3], ["1", "2", "3"])
    d.shot("code-editing")
    d.key("ctrl+slash")
    d.check("Ctrl+/ again uncomments", editor.code.get_source() == before, True)
    d.key("ctrl+End")
    d.type('x = print("hi", [1, 2])')
    d.check("brackets and quotes close themselves, and typing the closer steps over", editor.code.get_source().splitlines()[-1], 'x = print("hi", [1, 2])')
    editor.code.replace_source(before)
    d.key("ctrl+End")
    for line in ("def total(items):", "for item in items:", "if item:", "return item", "return None", "x = ["):
        d.type(line)
        d.key("Return")  # xdotool types "\n" as Linefeed, not the Enter key
    typed = editor.code.get_source()[len(before):]
    d.check("Enter indents and outdents to suit what's typed", typed,
            "def total(items):\n    for item in items:\n        if item:\n            return item\n"
            "        return None\n    x = [\n        \n    ]")
    editor.code.replace_source(before)

    from readymade.ide import assist

    if assist.AVAILABLE:
        print("Completion with real keys")
        d.key("ctrl+End")
        d.type("import os")
        d.key("Return")
        d.type("os.pa")
        deadline = time.time() + 15
        while not editor.code.completions.is_open() and time.time() < deadline:
            d.pump(0.1)
        d.check("the list opens as you type", editor.code.completions.is_open(), True)
        d.shot("completion")
        d.key("Down", "Return")  # past "pardir" to "path"
        d.check("Down chooses, Enter takes the name", editor.code.get_source().splitlines()[-1], "os.path")
        editor.code.replace_source(before)
    editor.show_design()
    widget = editor.surface.controls["Button2"].widget

    print("F1 help on the selected control")
    d.click(*d.at(editor.surface.controls["TextBox1"].widget))
    d.key("F1")
    d.check("F1 shows the control's help", (app.bottom.select() == str(app.help), app.help.title.cget("text")), (True, "TextBox1"))
    d.shot("help")
    app.bottom.select(app.immediate)

    print("Double-click it to get to its click handler")
    d.click(*d.at(widget), repeat=2)
    d.check("code tab shown", editor.frame.select(), str(editor.code))
    d.check("pass selected", editor.code.text.get("sel.first", "sel.last") if editor.code.text.tag_ranges("sel") else None, "pass")
    d.type('self.Label2.text = "Drawn and wired by xdotool"')
    d.check("typed over pass", "def Button2_click(self):\n        self.Label2.text" in editor.code.get_source(), True)
    d.shot("code")

    print("Draw a Frame, then two OptionButtons inside it")
    d.key("shift+F7")
    d.click(*d.at(tool["Frame"]))
    x0, y0 = d.at(canvas, 320, 16)
    d.drag(x0, y0, x0 + 112, y0 + 96)
    frame = editor.surface.controls.get("Frame1")
    d.check("frame drawn", frame and (frame.left, frame.top, frame.width, frame.height), (320, 16, 112, 96))
    for n, y in ((1, 8), (2, 40)):
        d.click(*d.at(tool["OptionButton"]))
        x0, y0 = d.at(frame.inner, 8, y)
        d.drag(x0, y0, x0 + 88, y0 + 24)
        spec = editor.design.control(f"OptionButton{n}")
        d.check(f"OptionButton{n} is inside the frame", spec and (spec.get("container"), spec["left"], spec["top"]), ("Frame1", 8, y))

    print("Move the frame: its options go with it")
    option = editor.surface.controls["OptionButton1"].widget
    before = (option.winfo_rootx(), option.winfo_rooty())
    x, y = d.at(frame.widget, 4, 30)  # the frame's left border
    d.drag(x, y, x, y + 16)
    d.check("frame moved", (frame.left, frame.top), (320, 32))
    d.check("option moved with it", (option.winfo_rootx(), option.winfo_rooty()), (before[0], before[1] + 16))

    print("Add a ListBox with items, and a Timer")
    d.click(*d.at(tool["ListBox"]))
    x0, y0 = d.at(canvas, 320, 152)
    d.drag(x0, y0, x0 + 112, y0 + 72)
    editor.set_property("ListBox1", "items", "Red\nGreen\nBlue")
    app.properties.update_values()
    d.click(*d.at(tool["Timer"]), repeat=2)
    d.check("timer added", editor.design.control("Timer1") is not None, True)
    d.check("tool resets after double-click", app.toolbox.tool, "")
    d.shot("more-controls")

    print("Make TextBox1 multi-line from the Properties panel")
    d.click(*d.at(editor.surface.controls["TextBox1"].widget))
    d.click(*d.at(d.prop_editor("multiline")))  # open the True/False dropdown
    d.key("Up", "Return")
    d.check("multiline on", editor.design.control("TextBox1")["multiline"], True)
    d.check("editor is now a Text", editor.surface.controls["TextBox1"].editor.winfo_class(), "Text")
    d.click(*d.at(d.prop_editor("height")))
    d.key("End", "BackSpace", "BackSpace", "BackSpace")
    d.type("64")
    d.key("Return")
    d.check("height", editor.design.control("TextBox1")["height"], 64)
    d.click(*d.at(d.prop_editor("scrollbars")))  # none, horizontal, vertical, both
    d.key("Down", "Down", "Return")
    d.check("scrollbars", editor.design.control("TextBox1")["scrollbars"], "vertical")
    bars = [w.winfo_class() for w in editor.surface.controls["TextBox1"].widget.winfo_children()]
    d.check("designer shows the scrollbar", bars, ["Text", "Scrollbar"])
    d.shot("multiline")

    print("Add a second form and open it from the Project Explorer")
    app.project.add_form("Settings")
    app.explorer_refresh()
    tree = app.explorer.tree
    x, y, w, h = tree.bbox("form:Settings")
    d.click(tree.winfo_rootx() + x + 20, tree.winfo_rooty() + y + h // 2, repeat=2)
    settings = app.form
    d.check("Settings tab open", settings is not None and settings.name, "Settings")
    d.check("properties follow the showing form", app.properties.app is settings, True)
    d.click(*d.at(tool["Button"]))
    x0, y0 = d.at(settings.surface.canvas, 16, 16)
    d.drag(x0, y0, x0 + 96, y0 + 32)
    d.check("drawn on Settings, not Form1", ("Button1" in settings.surface.controls, editor.design.control("Button3")), (True, None))
    d.click(*d.at(settings.surface.controls["Button1"].widget), repeat=2)
    d.type("self.close()")
    d.check("Settings code", "def Button1_click(self):\n        self.close()" in settings.code.get_source(), True)
    d.shot("second-form")
    d.click(*d.tab_at(app.documents, editor.frame))
    d.check("back on Form1's tab", app.form is editor, True)

    print("Build a File > Open menu in the Menu Editor")
    from tkinter import ttk

    from readymade.ide.menueditor import MenuEditor

    d.key("ctrl+e")
    menu_editor = next(w for w in app.root.winfo_children() if isinstance(w, MenuEditor))
    buttons = {w.cget("text"): w for w in menu_editor.winfo_children()[0].winfo_children()[-1].winfo_children()}
    d.click(*d.at(buttons["Add"]))
    d.type("&File")
    d.click(*d.at(buttons["Add Inside"]))
    d.type("&Open...")
    ctrl = next(w for w in menu_editor.fields if isinstance(w, ttk.Checkbutton) and w.cget("text") == "Ctrl")
    d.click(*d.at(ctrl))
    key_box = next(w for w in menu_editor.fields if isinstance(w, ttk.Combobox))
    d.click(*d.at(key_box, 10))
    d.type("o")
    d.shot("menu-editor")
    ok = next(w for w in menu_editor.winfo_children()[1].winfo_children()[0].winfo_children() if w.cget("text") == "OK")
    d.click(*d.at(ok))
    d.check("menu designed", editor.design.menu,
            [{"name": "mnuFile", "text": "&File", "items": [{"name": "mnuOpen", "text": "&Open...", "shortcut": "Ctrl+O"}]}])

    print("Click File > Open on the designer's menu bar to get to its handler")
    file_button = editor.surface.menubar.winfo_children()[0]
    d.click(*d.at(file_button))
    dropdown = file_button.nametowidget(file_button["menu"])
    d.click(dropdown.winfo_rootx() + 20, dropdown.winfo_rooty() + dropdown.yposition(0) + 8)
    d.check("mnuOpen_click opened", "def mnuOpen_click(self):" in editor.code.get_source() and editor.frame.select() == str(editor.code), True)
    d.type('self.Label2.text = "Opened from the menu"')

    print("Press F5 and use the running program")
    d.key("F5")
    left, top = d.ask("(form.root.winfo_rootx(), form.root.winfo_rooty())")
    form = editor.design
    textbox, button1, button2 = (form.control(n) for n in ("TextBox1", "Button1", "Button2"))

    def in_form(c):
        return left + c["left"] + c["width"] // 2, top + c["top"] + c["height"] // 2

    d.click(*in_form(textbox))
    d.type("Ada")
    d.click(*in_form(button1))
    d.check("Button1 click", d.ask("Label2.text"), "Hello, Ada!")
    d.click(*in_form(textbox))  # below the text, so the cursor goes to the end
    d.key("Return")
    d.type("Lovelace")
    d.check("multi-line text", d.ask("TextBox1.text"), "Ada\nLovelace")
    d.key("Tab")
    d.check("Tab leaves the box", d.ask("(form.root.focus_get() is TextBox1.editor, TextBox1.text)"), (False, "Ada\nLovelace"))
    d.click(*in_form(textbox))
    for i in range(6):
        d.key("Return")
        d.type(f"line {i}")
    thumb = "next(w for w in TextBox1.widget.winfo_children() if w.winfo_class() == 'Scrollbar').get()"
    d.check("scrollbar thumb moved to the bottom", d.ask(f"({thumb}[0] > 0, {thumb}[1])"), (True, 1.0))
    d.shot("running")
    d.click(*in_form(button2))
    d.check("Button2 click (new handler)", d.ask("Label2.text"), "Drawn and wired by xdotool")
    d.check("mousedown handler printed", "mouse down!" in app.immediate.output.get("1.0", "end"), True)
    d.shot("running-button2")

    def on_screen(name):
        return d.ask(f"({name}.widget.winfo_rootx() + 12, {name}.widget.winfo_rooty() + {name}.widget.winfo_height() // 2)")

    d.click(*on_screen("OptionButton1"))
    d.check("option 1 selected", d.ask("(OptionButton1.value, OptionButton2.value)"), (True, False))
    d.click(*on_screen("OptionButton2"))
    d.check("option 2 deselects option 1", d.ask("(OptionButton1.value, OptionButton2.value)"), (False, True))
    # Click the middle of item 1, wherever the font puts it.
    x, y = d.ask("(lambda w, b: (w.winfo_rootx() + b[0] + 10, w.winfo_rooty() + b[1] + b[3] // 2))"
                 "(ListBox1.widget, ListBox1.widget.bbox(1))")
    d.click(x, y)
    d.check("listbox selection", d.ask("ListBox1.text"), "Green")
    d.shot("running-more-controls")

    print("Use the menu in the running program, by mouse and by shortcut")
    app.runner.immediate_line("Label2.text = ''")
    # On X11 Tk shows copies ("clones") of menus, so find the menus actually on screen.
    app.runner.immediate_line(
        "exec(\"def shown_menus(tk):\\n out, todo = [], ['.']\\n while todo:\\n  p = todo.pop()\\n"
        "  todo += tk.splitlist(tk.call('winfo', 'children', p))\\n"
        "  if tk.call('winfo', 'class', p) == 'Menu' and tk.call('winfo', 'ismapped', p):\\n"
        "   out.append((p, tk.call('winfo', 'rootx', p), tk.call('winfo', 'rooty', p), tk.call(p, 'xposition', 0), tk.call(p, 'yposition', 0)))\\n"
        " return out\")"
    )
    (bar, x, y, entry_x, _), = d.ask("shown_menus(form.root.tk)")  # just the menu bar
    d.click(x + entry_x + 12, y + 10)  # opens the File menu
    deadline = time.time() + 5
    while len(shown := d.ask("shown_menus(form.root.tk)")) < 2 and time.time() < deadline:
        d.pump(0.1)
    d.check("File menu open", len(shown), 2)
    _, x, y, _, entry_y = next(m for m in shown if m[0] != bar)  # the File menu
    d.click(x + 20, y + entry_y + 8)
    d.check("File > Open clicked", d.ask("Label2.text"), "Opened from the menu")
    app.runner.immediate_line("Label2.text = ''")
    d.click(*in_form(button1))  # put the keyboard focus in the form
    d.key("ctrl+o")
    d.check("Ctrl+O", d.ask("Label2.text"), "Opened from the menu")
    d.shot("running-menu")

    print("Open the second form from the Immediate window, and close it with its button")
    app.runner.immediate_line("forms.Settings.show()")
    d.check("Settings shown", d.ask("forms.Settings.root.state()"), "normal")
    x, y = d.ask("(lambda w: (w.winfo_rootx() + 20, w.winfo_rooty() + 10))(forms.Settings.Button1.widget)")
    d.click(x, y)
    d.check("Settings closed by its own code", d.ask("forms.Settings.loaded"), False)

    app.runner.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)
    d.check("program ended", app.process, None)

    print("Draw an Image and choose its picture from outside the project")
    import tkinter as tk
    from tkinter import font as tkfont

    pictures = Path(tempfile.mkdtemp(prefix="readymade-pictures-"))
    photo = tk.PhotoImage(master=d.root, width=32, height=32)
    photo.put("#3060c0", to=(0, 0, 32, 32))
    photo.write(str(pictures / "badge.png"), format="png")
    editor.show_design()
    d.pump()
    d.click(*d.at(tool["Image"]))
    x0, y0 = d.at(canvas, 264, 200)
    d.drag(x0, y0, x0 + 64, y0 + 64)
    d.check("Image drawn", editor.selected, "Image1")
    # The file dialog waits for its answer inside the click, so type that answer from another process.
    typist = subprocess.Popen(["sh", "-c", f"sleep 2; xdotool type --delay 20 '{pictures / 'badge.png'}'; xdotool key Return"])
    d.click(*d.at(d.prop_editor("picture").winfo_children()[1]))  # the "..." button
    typist.wait(timeout=20)
    d.pump(0.3)
    d.check("picture copied into the project", editor.design.control("Image1")["picture"], "images/badge.png")
    d.check("copy exists", (editor.path.parent / "images" / "badge.png").exists(), True)
    d.check("picture shown", editor.surface.controls["Image1"]._photo is not None, True)
    spec = editor.design.control("Image1")
    d.check("autosized to the picture", (spec["width"], spec["height"]), (32, 32))
    d.shot("image")
    shutil.rmtree(pictures, ignore_errors=True)

    print("Draw a Canvas, give it click and drag handlers, and use them in the running program")
    d.click(*d.at(tool["Canvas"]))
    x0, y0 = d.at(canvas, 16, 240)
    d.drag(x0, y0, x0 + 224, y0 + 64)
    d.check("Canvas drawn", editor.selected, "Canvas1")
    d.click(*d.at(editor.surface.controls["Canvas1"].widget), repeat=2)
    d.check("click handler has x, y, shape", "def Canvas1_click(self, x, y, shape):" in editor.code.get_source(), True)
    d.type('self.Canvas1.circle(x, y, 8, fill="#3060c0") if shape is None else setattr(shape, "fill", "#e04040")')
    editor.goto_handler("Canvas1", "drag")
    d.type("self.Canvas1.point(x, y)")
    editor.goto_handler("Image1", "drag")
    d.type('self.Image1.circle(x, y, 2, fill="#ff0000", color="")')
    d.key("F5")
    x, y = d.ask("(Canvas1.widget.winfo_rootx(), Canvas1.widget.winfo_rooty())")
    d.click(x + 30, y + 30)
    d.check("click on the background draws a circle", d.ask("[(s.kind, s.x, s.y, s.fill) for s in Canvas1.shapes()]"),
            [("circle", 30, 30, "#3060c0")])
    d.click(x + 32, y + 28)
    d.check("click on the circle recolors it", d.ask("Canvas1.shapes()[0].fill"), "#e04040")
    d.drag(x + 100, y + 20, x + 180, y + 50, steps=10)
    d.check("drag draws points", d.ask("sum(s.kind == 'point' for s in Canvas1.shapes()) >= 5"), True)
    x, y = d.ask("(Image1.widget.winfo_rootx(), Image1.widget.winfo_rooty())")
    d.drag(x + 4, y + 16, x + 28, y + 16, steps=12)
    d.check("drag paints the Image's pixels", d.ask("[Image1.pixel(px, 16) for px in (2, 16, 28)]"),
            ["#3060c0", "#ff0000", "#ff0000"])
    d.shot("canvas-running")
    app.runner.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)

    print("Colors, font and alignment for Label1, with the Properties panel and the font dialog")
    editor.show_design()
    d.pump()
    d.click(*d.at(editor.surface.controls["Label1"].widget))
    d.check("Label1 selected", editor.selected, "Label1")
    entry = d.prop_editor("backcolor").winfo_children()[0]
    d.click(*d.at(entry))
    d.key("End")
    d.key(*["BackSpace"] * 10)
    d.type("#ffe080")
    d.key("Return")
    d.check("backcolor typed", editor.design.control("Label1")["backcolor"], "#ffe080")
    family = sorted(tkfont.families(d.root))[-1]
    # The font dialog waits for its answer inside the click; its family box starts selected.
    typist = subprocess.Popen(["sh", "-c", f"sleep 2; xdotool type --delay 20 '{family}'; xdotool key Return"])
    d.click(*d.at(d.prop_editor("font").winfo_children()[-1]))  # the "..." button
    typist.wait(timeout=20)
    d.pump(0.3)
    d.check("font chosen in the dialog", editor.design.control("Label1")["font"], family)
    d.click(*d.at(d.prop_editor("alignment")))  # open the dropdown: left, center, right
    d.key("Down", "Down", "Return")
    d.check("alignment chosen", editor.design.control("Label1")["alignment"], "right")
    label = editor.surface.controls["Label1"].widget
    d.check("designer shows them", (label["background"], str(label["anchor"])), ("#ffe080", "e"))
    d.shot("appearance")
    d.key("F5")
    d.check("the running program shows them", d.ask("(Label1.widget['background'], str(Label1.widget['anchor']), Label1.font)"),
            ("#ffe080", "e", family))
    app.runner.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)

    print("Format > Tab Order by clicking, then Tab, Shift+Tab and Enter in the running program")
    app.toggle_tab_order()
    surface = editor.surface
    for name in ("Button2", "Button1"):
        d.click(*d.at(surface.controls[name].widget, 30, 10))
    d.check("tab order set by clicking", [s["name"] for s in editor.tab_stops()][:2], ["Button2", "Button1"])
    d.check("badges numbered", len(surface._badges), len(editor.tab_stops()))
    d.shot("tab-order")
    d.key("Escape")
    d.check("Esc ends Tab Order", (surface.tab_order_next, surface._badges), (None, []))
    d.key("F5")
    focus = "__import__('readymade.controls').controls.control_of(form.root.focus_lastfor()).name"
    d.check("the first in the tab order starts with the focus", d.ask(focus), "Button2")
    x, y = d.ask("(Label1.widget.winfo_rootx() + 4, Label1.widget.winfo_rooty() + 4)")
    d.click(x, y)  # the window gets the keyboard
    d.key("Tab")
    d.check("Tab goes to the next", d.ask(focus), "Button1")
    d.key("shift+Tab")
    d.check("Shift+Tab goes back", d.ask(focus), "Button2")
    app.runner.immediate_line("Label2.text = ''")
    d.ask("Label2.text")  # wait until it's done, so it can't undo what Enter does
    d.key("Return")
    d.check("Enter presses the focused button", d.ask("Label2.text"), "Drawn and wired by xdotool")
    app.runner.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)
    d.check("program ended", app.process, None)

    print("Remove the Settings form with the Project Explorer's right-click menu")
    tree = app.explorer.tree
    app.explorer_refresh()
    d.pump()
    x, y, w, h = tree.bbox("form:Settings")
    menu = app.explorer.menu
    # The confirmation waits for its answer inside the menu click, so answer it from another
    # process: Shift+Tab from the default ("No") to "Yes", then Space presses it.
    typist = subprocess.Popen(["sh", "-c", "sleep 2; xdotool key shift+Tab; sleep 0.3; xdotool key space"])
    d.xdo("mousemove", tree.winfo_rootx() + x + 20, tree.winfo_rooty() + y + h // 2)
    d.pump(0.05)
    d.xdo("click", 3)
    d.pump(0.5)
    d.click(menu.winfo_rootx() + 20, menu.winfo_rooty() + menu.yposition("Remove...") + 8)
    typist.wait(timeout=20)
    d.pump(0.3)
    d.check("Settings deleted", (editor.path.parent / "Settings.form").exists(), False)
    d.check("its tab closed", any(e.name == "Settings" for e in app.editors), False)
    d.check("gone from the Explorer", tree.exists("form:Settings"), False)

    print("A tooltip and maxlength in the running program")
    editor.set_property("Button1", "tooltip", "Says hello")
    editor.set_property("TextBox1", "maxlength", "5")
    editor.set_property("TextBox1", "text", "")
    d.key("F5")
    x, y = d.ask("(Button1.widget.winfo_rootx() + 10, Button1.widget.winfo_rooty() + 10)")
    d.xdo("mousemove", x - 60, y)
    d.pump(0.2)
    d.xdo("mousemove", x, y)  # rest the mouse on Button1
    d.pump(1.2)
    tip = "(lambda t: t.window.winfo_children()[0].cget('text') if t.window else None)(__import__('readymade.controls.base').controls.base._tip)"
    d.check("the tooltip shows", d.ask(tip), "Says hello")
    d.shot("tooltip")
    x, y = d.ask("(TextBox1.widget.winfo_rootx() + 20, TextBox1.widget.winfo_rooty() + 10)")
    d.click(x, y)
    d.check("moving away hides it", d.ask(tip), None)
    d.type("abcdefgh")
    d.check("maxlength stops typing", d.ask("TextBox1.text"), "abcde")
    app.runner.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)


    print("The Problems tab: lint every file, click a problem to go to it")
    from readymade import lint

    folder = editor.path.parent
    linter = Path(tempfile.mkdtemp(prefix="readymade-lint-")) / "fake_linter.py"  # not in the project, or it's a module
    linter.write_text(
        "import sys\nsource = sys.stdin.read()\nfor n, line in enumerate(source.splitlines(), 1):\n"
        "    if 'bad' in line:\n        print(f\"{sys.argv[-1]}:{n}:{line.index('bad') + 1}: X100 found bad\")\n",
        encoding="utf-8")
    pyproject = app.project.pyproject
    pyproject.write_text(pyproject.read_text() + (
        "\n[tool.readymade.lint-tools.typing-check]\n"
        f'command = ["{{python}}", "{linter.as_posix()}", "--stdin", "{{file}}"]\nstdin = true\n'))
    (folder / "helpers.py").write_text("x = 1\n\n\ndef f():\n    return 'bad'\n", encoding="utf-8")
    lint.set_choices(app.project, ["typing-check"], [])
    app.linter.check_all()
    deadline = time.time() + 15
    while (app.linter.busy or not app.problems.tree.get_children()) and time.time() < deadline:
        d.pump(0.1)
    d.click(*d.tab_at(app.bottom, app.problems))
    tree = app.problems.tree
    rows = [tree.item(r, "values") for r in tree.get_children()]
    d.check("helpers.py's problem is listed", [(str(v[0]), str(v[1])) for v in rows], [("helpers.py", "5")])
    d.check("the tab shows the count", app.bottom.tab(app.problems, "text"), "Problems (1)")
    d.shot("problems")
    x, y, w, h = tree.bbox(tree.get_children()[0])
    d.click(tree.winfo_rootx() + x + 40, tree.winfo_rooty() + y + h // 2)
    module = next((e for e in app.editors if e.name == "helpers"), None)
    d.check("clicking opens the module at the problem",
            module and (app.documents.select() == str(module.frame), module.code.text.index("insert")), (True, "5.12"))
    d.shot("problem-opened")

    print("Tools > Options: the Dark theme, with real clicks")
    from tkinter import ttk

    from readymade.ide import options

    app.show_options()
    d.pump(0.3)
    dialog = next(w for w in app.root.winfo_children() if isinstance(w, options.OptionsDialog))

    def find(widget, kind, text):
        for child in widget.winfo_children():
            if isinstance(child, kind) and child.cget("text") == text:
                return child
            found = find(child, kind, text)
            if found:
                return found
        return None

    d.click(*d.at(find(dialog, ttk.Radiobutton, "Dark")))
    d.click(*d.at(find(dialog, ttk.Button, "OK")))
    d.check("the editor is dark", module.code.text.cget("background"), "#1e1e1e")
    d.click(*d.tab_at(app.documents, editor.frame))
    editor.show_design()
    d.click(*d.at(editor.surface.controls["Label1"].widget))
    d.pump(0.3)
    d.check("the whole IDE is dark", (app.root.cget("background"), ttk.Style(app.root).theme_use()), ("#252526", "readymade-dark"))
    d.shot("dark-design")
    editor.show_code()
    d.pump(0.3)
    d.shot("dark-code")
    app.show_options()
    d.pump(0.5)
    d.shot("dark-options")
    next(w for w in app.root.winfo_children() if isinstance(w, options.OptionsDialog)).destroy()
    from readymade import usersettings

    usersettings.set("theme", None)  # (in the driver's own settings folder: see main)
    options.apply(app)
    d.check("back to light", editor.code.text.cget("background"), "#ffffff")

    print("Anchors: Button2 keeps to the bottom right as the form grows, in the designer and when running")
    editor.show_design()
    editor.set_property("Button2", "anchor", "bottom right")
    before = tuple(editor.design.control("Button2")[k] for k in ("left", "top"))
    x, y = d.at(editor.surface.form_handle)
    d.drag(x, y, x + 48, y + 32)
    after = tuple(editor.design.control("Button2")[k] for k in ("left", "top"))
    d.check("dragging the form bigger moves it", (after[0] - before[0], after[1] - before[1]), (48, 32))
    d.shot("anchors-designer")
    d.key("F5")
    d.check("running at the designed place", d.ask("(Button2.left, Button2.top)"), after)
    # A person resizes the window through the window manager, and this display has none (Tk keeps its
    # window at the size it asked for when another program resizes it), so the program's Tk does it.
    app.runner.immediate_line(f"form.root.geometry('{editor.design.width + 100}x{editor.design.height + 60}')")
    deadline = time.time() + 5
    while d.ask("Button2.left") == after[0] and time.time() < deadline:
        d.pump(0.1)
    d.check("resizing the program's window moves it", d.ask("(Button2.left, Button2.top)"), (after[0] + 100, after[1] + 60))
    d.shot("anchors-running")
    app.runner.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)

    print("A Grid: draw it, draw a button into a cell, drag it to another cell")
    app.project.add_form("Gridded")
    app.explorer_refresh()
    gridded = app.open_form("Gridded")
    gridded.show_design()
    d.pump(0.3)
    gcanvas = gridded.surface.canvas
    d.click(*d.at(tool["Grid"]))
    x0, y0 = d.at(gcanvas, 16, 16)
    d.drag(x0, y0, x0 + 304, y0 + 160)
    d.check("Grid drawn", gridded.selected, "Grid1")
    gridded.set_property("Grid1", "columns", "*, *, *")
    grid = gridded.surface.controls["Grid1"]
    d.pump(0.2)

    def cell_point(row, column):
        x, y, w, h = grid.cell_box(row, column)
        return grid.inner.winfo_rootx() + x + w // 2, grid.inner.winfo_rooty() + y + h // 2

    d.click(*d.at(tool["Button"]))
    x, y = cell_point(1, 1)
    d.drag(x - 20, y - 10, x + 20, y + 10)
    spec = gridded.design.control("Button1")
    d.check("drawn into the middle cell of the bottom row", spec and (spec["row"], spec["column"]), (1, 1))
    d.drag(*cell_point(1, 1), *cell_point(0, 2), steps=10)
    d.check("dragged to the top-right cell", (spec["row"], spec["column"]), (0, 2))
    d.shot("grid-designer")

    print("Break mode: a breakpoint by clicking the gutter, F5, F10, the Immediate window while paused")
    app.close_document(gridded, ask=False)
    editor = app.open_form("Form1", "code")
    code = editor.code
    d.pump(0.3)
    line = next(n for n, text in enumerate(code.get_source().splitlines(), 1) if "name = self.TextBox1" in text)
    _, y, _, height, _ = code.text.dlineinfo(f"{line}.0")
    d.click(code.gutter.winfo_rootx() + 7, code.gutter.winfo_rooty() + y + height // 2)
    d.check("gutter click sets a breakpoint", code.breakpoint_lines(), [line])
    from readymade.ide import tooltips

    d.xdo("mousemove", code.gutter.winfo_rootx() + 8, code.gutter.winfo_rooty() + y + height // 2 + 1)
    deadline = time.time() + 3
    while tooltips._Tip.window is None and time.time() < deadline:
        d.pump(0.05)
    shown = tooltips._Tip.window.winfo_children()[0].cget("text") if tooltips._Tip.window else ""
    d.check("resting on the dot says what it is", shown.split(":")[0], "A breakpoint")
    d.shot("breakpoint-tip")
    tooltips.hide()
    code.text.focus_force()
    d.key("F5")
    d.ask("1")  # (running)
    app.runner.immediate_line("_ = Button1.widget.invoke()")
    deadline = time.time() + 10
    while code.paused_line() != line and time.time() < deadline:
        d.pump(0.05)
    d.check("paused at the breakpoint", (app.in_break_mode, code.paused_line()), (True, line))
    d.check("title says so", app.root.title().endswith("[break]"), True)
    code.text.focus_force()
    d.pump(0.2)
    d.key("F10")
    deadline = time.time() + 10
    while code.paused_line() != line + 1 and time.time() < deadline:
        d.pump(0.05)
    d.check("F10 steps over", code.paused_line(), line + 1)
    d.check("Locals shows name", app.locals.value_of("name"), ("'World'", "str"))
    x, y, w, h = code.text.bbox(f"{line}.{code.text.get(f'{line}.0', f'{line}.end').index('name') + 1}")
    d.xdo("mousemove", code.text.winfo_rootx() + x + 2, code.text.winfo_rooty() + y + h // 2)
    deadline = time.time() + 5
    while code._tip is None and time.time() < deadline:
        d.pump(0.05)
    d.check("resting the mouse on a name shows its value",
            code._tip and code._tip[0].winfo_children()[0].cget("text"), "name = 'World'")
    d.shot("value-tip")
    d.click(*d.at(app.immediate.entry))
    d.type("? name.upper()")
    d.key("Return")
    d.pump(0.5)
    d.check("Immediate runs in the paused function", "\nWORLD\n" in app.immediate.output.get("1.0", "end"), True)
    gx = code.gutter.winfo_rootx() + 8
    _, below, _, height, _ = code.text.dlineinfo(f"{line + 1}.0")
    _, above, _, _, _ = code.text.dlineinfo(f"{line}.0")
    d.drag(gx, code.gutter.winfo_rooty() + below + height // 2, gx, code.gutter.winfo_rooty() + above + height // 2)
    deadline = time.time() + 10
    while code.paused_line() != line and time.time() < deadline:
        d.pump(0.05)
    d.check("dragging the arrow up sets the next statement", code.paused_line(), line)
    code.text.focus_force()
    d.pump(0.2)
    d.key("F10")
    deadline = time.time() + 10
    while code.paused_line() != line + 1 and time.time() < deadline:
        d.pump(0.05)
    row = app.locals._rows[("name",)]
    x, y, w, h = app.locals.tree.bbox(row, "value")
    d.click(app.locals.tree.winfo_rootx() + x + 10, app.locals.tree.winfo_rooty() + y + h // 2, repeat=2)
    d.type("'Ada'")
    d.key("Return")
    deadline = time.time() + 10
    while app.locals.value_of("name")[0] != "'Ada'" and time.time() < deadline:
        d.pump(0.05)
    d.check("a value changed in Locals", app.locals.value_of("name"), ("'Ada'", "str"))
    d.shot("break-mode")
    d.click(*d.tab_at(app.debug_tabs, app.call_stack))
    d.shot("break-mode-call-stack")
    d.click(*d.tab_at(app.debug_tabs, app.breakpoints_panel))
    d.shot("breakpoints-tab")
    code.text.focus_force()
    d.pump(0.2)
    d.key("F5")
    deadline = time.time() + 10
    while app.in_break_mode and time.time() < deadline:
        d.pump(0.05)
    d.check("F5 continues, with the changed value", (app.in_break_mode, d.ask("Label2.text")), (False, "Hello, Ada!"))
    print("Watches while running (View > Watches)")
    app.debug.show_debug_window(app.watches_panel)
    app.debug.set_watches([{"expression": "Label2.text", "kind": "watch", "file": "", "function": ""},
                     {"expression": "name", "kind": "watch", "file": "Form1.py", "function": "Button1_click"}])
    deadline = time.time() + 10
    while app.watches_panel.value_of("#watch", 0)[0] != "'Hello, Ada!'" and time.time() < deadline:
        d.pump(0.05)
    d.check("a watch's value while running", app.watches_panel.value_of("#watch", 0)[:2], ("'Hello, Ada!'", "str"))
    d.shot("watches-running")
    d.key("shift+F5")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)
    d.check("Shift+F5 ends it", app.process, None)

    print("Ctrl+drag inside a Frame selects the controls in it")
    editor = app.open_form("Form1")
    editor.show_design()
    d.pump(0.3)
    frame = editor.surface.controls["Frame1"]
    x0, y0 = d.at(frame.inner, 2, 2)
    d.xdo("keydown", "ctrl")
    d.drag(x0, y0, x0 + frame.inner.winfo_width() - 4, y0 + frame.inner.winfo_height() - 4)
    d.xdo("keyup", "ctrl")
    d.check("a box inside the frame", sorted(editor.selection), ["OptionButton1", "OptionButton2"])

    print("Edit > Paste with Code (Ctrl+Shift+V) brings the click handler along, renamed")
    editor.select("Button1")
    editor.surface.canvas.focus_force()
    d.pump(0.2)
    d.key("ctrl+c")
    d.key("ctrl+shift+v")
    pasted = editor.selected
    d.check("pasted with its handler", f"def {pasted}_click(self):" in editor.code.get_source() and pasted != "Button1", True)

    print("An access key: &Say Hello is Alt+S in the running program")
    app.debug.clear_breakpoints()  # (the break mode step's breakpoint would stop the click)
    editor.set_property("Button1", "text", "&Say Hello")
    d.key("F5")
    left, top = d.ask("(form.root.winfo_rootx(), form.root.winfo_rooty())")
    textbox = editor.design.control("TextBox1")
    d.click(left + textbox["left"] + 8, top + textbox["top"] + 8)
    d.key("ctrl+a")
    d.type("Bo")
    d.key("alt+s")
    d.check("Alt+S clicks Say Hello", d.ask("Label2.text"), "Hello, Bo!")
    d.shot("access-key")
    d.key("shift+F5")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)

    print("The project's other files in the Project Explorer: open the README by double-clicking it")
    (app.project.folder / "README.md").write_text("# Hello\n\nA first readymade program.\n", encoding="utf-8")
    app.explorer_refresh()
    tree = app.explorer.tree
    tree.see("file:README.md")
    d.pump(0.2)
    x, y, w, h = tree.bbox("file:README.md")
    d.click(tree.winfo_rootx() + x + 20, tree.winfo_rooty() + y + h // 2, repeat=2)
    d.check("README opens in a tab", app.documents.tab(app.documents.select(), "text"), "README.md")
    d.shot("project-files")

    print("Find in the code window with real keys: Ctrl+F, type, Enter, F3, Esc")
    editor = app.open_form("Form1", "code")
    code = editor.code
    code.text.mark_set("insert", "1.0")
    code.text.focus_force()
    d.pump(0.2)
    d.key("ctrl+f")
    d.type("Label2")
    d.key("Return")
    bar = code.find_bar
    first = code.text.index("sel.first")
    d.key("F3")
    d.check("Ctrl+F, typing and F3 find the next one", (code.text.get("sel.first", "sel.last"),
                                                         code.text.index("sel.first") != first), ("Label2", True))
    d.shot("find-bar")
    d.key("Escape")
    d.check("Esc closes the find bar", bar.is_open(), False)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/readymade-ui")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="readymade-drive-"))
    write_start_form(work)

    server = start_xvfb()
    os.environ["DISPLAY"] = DISPLAY  # also inherited by the program F5 starts
    # Its own user settings (lint choices, theme...), never the real ones.
    os.environ["READYMADE_CONFIG_DIR"] = tempfile.mkdtemp(prefix="readymade-drive-settings-")
    os.environ["XDG_DATA_HOME"] = tempfile.mkdtemp(prefix="readymade-drive-data-")  # removed files' Trash too
    try:
        import tkinter as tk

        from readymade.ide.app import App

        root = tk.Tk()
        root.geometry("1100x720+0+0")
        app = App(root, work)
        driver = Driver(app, out)
        driver.pump(0.5)
        root.focus_force()
        try:
            drive(driver)
        finally:
            app.runner.stop()
            root.destroy()
    finally:
        server.terminate()
        shutil.rmtree(work, ignore_errors=True)

    if driver.failures:
        sys.exit(f"{len(driver.failures)} check(s) failed: {', '.join(driver.failures)}")
    print("All checks passed.")


if __name__ == "__main__":
    main()
