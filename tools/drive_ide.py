"""Drive the IDE with real mouse and keyboard input on a private Xvfb display.

    python3 tools/drive_ide.py [output_dir]

Needs Xvfb and xdotool. The IDE runs in this process so the script can ask Tk
where widgets are, but every click, drag and keystroke goes through the X
server, exercising the same event bindings a person would. Screenshots of each
step are saved to output_dir (default /tmp/pybasic-ui). Works on a copy of
examples/hello, so the real example is never modified.
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
        raise TimeoutError(expression)


def drive(d):
    app = d.app
    canvas = app.surface.canvas
    tool = {w.cget("text"): w for w in app.toolbox.winfo_children() if w.winfo_class() == "Radiobutton"}

    print("Design view")
    d.shot("design")

    print("Draw a Button by dragging a rectangle")
    d.click(*d.at(tool["Button"]))
    x0, y0 = d.at(canvas, 24, 160)
    d.drag(x0, y0, x0 + 120, y0 + 32)
    spec = app.design.control("Button2")
    d.check("new control", spec and (spec["left"], spec["top"], spec["width"], spec["height"]), (24, 160, 120, 32))
    d.check("selected", app.selected, "Button2")
    d.check("tool resets to pointer", app.toolbox.tool, "")
    d.shot("drawn")

    print("Move it by dragging")
    widget = app.surface.controls["Button2"].widget
    x, y = d.at(widget)
    d.drag(x, y, x + 41, y + 22)
    d.check("moved (snapped to grid)", (spec["left"], spec["top"]), (64, 184))

    print("Resize with the bottom-right handle")
    x, y = d.at(app.surface.handles[(1, 1)])
    d.drag(x, y, x + 30, y + 15)
    d.check("resized (snapped)", (spec["width"], spec["height"]), (152, 48))
    d.check("properties panel follows", app.properties._rows["width"].get(), "152")
    d.shot("moved-resized")

    print("Double-click it to get to its click handler")
    d.click(*d.at(widget), repeat=2)
    d.check("code tab shown", app.notebook.select(), str(app.code))
    d.check("pass selected", app.code.text.get("sel.first", "sel.last") if app.code.text.tag_ranges("sel") else None, "pass")
    d.type('self.Label2.text = "Drawn and wired by xdotool"')
    d.check("typed over pass", "def Button2_click(self):\n        self.Label2.text" in app.code.get_source(), True)
    d.shot("code")

    print("Press F5 and use the running program")
    d.key("F5")
    left, top = d.ask("(form.root.winfo_rootx(), form.root.winfo_rooty())")
    form = app.design
    textbox, button1, button2 = (form.control(n) for n in ("TextBox1", "Button1", "Button2"))

    def in_form(c):
        return left + c["left"] + c["width"] // 2, top + c["top"] + c["height"] // 2

    d.click(*in_form(textbox))
    d.type("Ada")
    d.click(*in_form(button1))
    d.check("Button1 click", d.ask("Label2.text"), "Hello, Ada!")
    d.shot("running")
    d.click(*in_form(button2))
    d.check("Button2 click (new handler)", d.ask("Label2.text"), "Drawn and wired by xdotool")
    d.check("mousedown handler printed", "mouse down!" in app.immediate.output.get("1.0", "end"), True)
    d.shot("running-button2")

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
    shutil.copytree(ROOT / "examples" / "hello", work, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__"))

    server = start_xvfb()
    os.environ["DISPLAY"] = DISPLAY  # also inherited by the program F5 starts
    try:
        import tkinter as tk

        from pybasic.ide.app import App

        root = tk.Tk()
        root.geometry("1100x720+0+0")
        app = App(root, work / "Form1.form")
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
