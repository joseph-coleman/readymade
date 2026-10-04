"""Drive the IDE with real mouse and keyboard input on a private Xvfb display.

    python3 tools/drive_ide.py [output_dir]

Needs Xvfb and xdotool. The IDE runs in this process so the script can ask Tk
where widgets are, but every click, drag and keystroke goes through the X
server, exercising the same event bindings a person would. Screenshots of each
step are saved to output_dir (default /tmp/pybasic-ui). It starts from its own
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
START_CODE = """from pybasic import Form


class Form1(Form):
    def Form_load(self):
        self.Label1.text = "What's your name?"

    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"
        self.Label2.text = f"Hello, {name}!"

    def TextBox1_keypress(self, key):
        if key == "Return":
            self.Button1_click()

    def Button1_mousedown(self, x, y):
        print("mouse down!")


if __name__ == "__main__":
    Form1.run()
"""


def write_start_form(folder):
    from pybasic import formfile
    from pybasic.controls import REGISTRY
    from pybasic.project import Project

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
        """Screen coordinates of a point in widget (default: its centre)."""
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
        """The Properties panel's editor widget for prop."""
        grid = self.app.properties.grid_frame
        label = next(w for w in grid.grid_slaves(column=0) if w.cget("text") == prop)
        return grid.grid_slaves(row=label.grid_info()["row"], column=1)[0]

    def check(self, label, actual, expected):
        ok = actual == expected
        print(f"  {'ok  ' if ok else 'FAIL'} {label}: {actual!r}" + ("" if ok else f" (expected {expected!r})"))
        if not ok:
            self.failures.append(label)

    def ask(self, expression, timeout=10):
        """Evaluate an expression in the running program via the Immediate window."""
        marker = f"@@{self.step}{time.time_ns()}@@"
        self.app.immediate_line(f"print({marker!r}, repr({expression}))")
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
    tool = {w.cget("text"): w for w in app.toolbox.winfo_children() if w.winfo_class() == "Radiobutton"}

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

    from pybasic.ide.menueditor import MenuEditor

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
    ok = next(w for w in menu_editor.winfo_children()[1].winfo_children() if w.cget("text") == "OK")
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
    app.immediate_line("Label2.text = ''")
    # On X11 Tk shows copies ("clones") of menus, so find the menus actually on screen.
    app.immediate_line(
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
    app.immediate_line("Label2.text = ''")
    d.click(*in_form(button1))  # put the keyboard focus in the form
    d.key("ctrl+o")
    d.check("Ctrl+O", d.ask("Label2.text"), "Opened from the menu")
    d.shot("running-menu")

    print("Open the second form from the Immediate window, and close it with its button")
    app.immediate_line("forms.Settings.show()")
    d.check("Settings shown", d.ask("forms.Settings.root.state()"), "normal")
    x, y = d.ask("(lambda w: (w.winfo_rootx() + 20, w.winfo_rooty() + 10))(forms.Settings.Button1.widget)")
    d.click(x, y)
    d.check("Settings closed by its own code", d.ask("forms.Settings.loaded"), False)

    app.immediate_line("form.close()")
    deadline = time.time() + 10
    while app.process is not None and time.time() < deadline:
        d.pump(0.05)
    d.check("program ended", app.process, None)


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/pybasic-ui")
    shutil.rmtree(out, ignore_errors=True)
    out.mkdir(parents=True)
    work = Path(tempfile.mkdtemp(prefix="pybasic-drive-"))
    write_start_form(work)

    server = start_xvfb()
    os.environ["DISPLAY"] = DISPLAY  # also inherited by the program F5 starts
    try:
        import tkinter as tk

        from pybasic.ide.app import App

        root = tk.Tk()
        root.geometry("1100x720+0+0")
        app = App(root, work)
        driver = Driver(app, out)
        driver.pump(0.5)
        root.focus_force()
        try:
            drive(driver)
        finally:
            app.stop()
            root.destroy()
    finally:
        server.terminate()
        shutil.rmtree(work, ignore_errors=True)

    if driver.failures:
        sys.exit(f"{len(driver.failures)} check(s) failed: {', '.join(driver.failures)}")
    print("All checks passed.")


if __name__ == "__main__":
    main()
