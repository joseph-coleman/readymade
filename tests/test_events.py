"""Responsive forms: async handlers, doevents(), in_thread(), and events that arrive while a handler is busy."""

import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

import pytest

from readymade import Form, codegen, doevents, formfile, in_thread, pause, while_running
from readymade.controls import REGISTRY
from readymade.events import Handler, policy_for
from readymade.form import app_root

pytestmark = pytest.mark.usefixtures("display")
ROOT = Path(__file__).parent.parent


def pump(seconds, until=lambda: False):
    end = time.time() + seconds
    while time.time() < end and not until():
        app_root().update()
        time.sleep(0.002)


def make(tmp_path, cls, *controls):
    design = formfile.FormDesign(name="Form1")
    for i, (type_name, name) in enumerate(controls):
        design.controls.append(REGISTRY[type_name].new_spec(name, 8, 8 + 32 * i))
    formfile.save(design, tmp_path / "Form1.form")
    form = cls(tmp_path / "Form1.form")
    form.show()
    return form


@pytest.fixture
def forms_made():
    made = []
    yield made.append
    for form in made:
        if form.loaded:
            form.root.destroy()
    pump(0.05)


def test_async_handler_keeps_the_form_responsive(tmp_path, forms_made):
    log = []

    class Form1(Form):
        async def btnGo_click(self):
            for i in range(50):
                self.lblStatus.text = f"row {i}"
                time.sleep(0.003)  # a little real work per row
                await pause()
            log.append("done")

        def btnOther_click(self):
            log.append(("other, while go was at", self.lblStatus.text))

    form = make(tmp_path, Form1, ("Button", "btnGo"), ("Button", "btnOther"), ("Label", "lblStatus"))
    forms_made(form)
    form.btnGo.widget.invoke()
    form.btnGo.widget.invoke()  # ignored: it's still running
    pump(0.02)
    form.btnOther.widget.invoke()  # a different handler runs straight away
    pump(5, until=lambda: "done" in log)
    assert log[-1] == "done" and log.count("done") == 1
    assert log[0][0] == "other, while go was at" and log[0][1] != "row 49"
    assert form.lblStatus.text == "row 49"


def run_policy(policy, calls=("a", "b", "c")):
    """Call a slow async handler three times in a row; return the arguments it ran with."""
    seen = []

    async def handler(value):
        seen.append(value)
        await pause(0.03)

    form = types.SimpleNamespace(loaded=True, root=app_root(), _tasks=set())
    run = Handler(form, handler, policy)
    for value in calls:
        run(value)
    pump(2, until=lambda: not run.busy and not run.pending and len(seen) >= {"ignore": 1, "latest": 2}.get(policy, 3))
    pump(0.1)
    return seen


@pytest.mark.parametrize("policy, expected", [
    ("ignore", ["a"]), ("latest", ["a", "c"]), ("queue", ["a", "b", "c"]), ("overlap", ["a", "b", "c"]),
])
def test_while_running_policies(policy, expected):
    assert run_policy(policy) == expected


def test_policy_defaults_and_the_decorator():
    def plain():
        pass

    assert [policy_for(plain, e) for e in ("click", "change", "keypress", "timer", "load")] == ["ignore", "latest", "queue", "latest", "ignore"]
    assert policy_for(plain, "click", declared="latest") == "latest"  # e.g. a ListBox's click is a selection
    assert policy_for(while_running("queue")(plain), "click", declared="latest") == "queue"
    with pytest.raises(ValueError, match="ignore, latest, queue, overlap"):
        while_running("sometimes")


def test_doevents_lets_other_handlers_run_but_not_the_same_one(tmp_path, forms_made):
    log = []

    class Form1(Form):
        def btnLoop_click(self):
            for _ in range(40):
                time.sleep(0.005)
                doevents()
            log.append("loop done")

        def btnOther_click(self):
            log.append("other")

    form = make(tmp_path, Form1, ("Button", "btnLoop"), ("Button", "btnOther"))
    forms_made(form)
    app_root().after(30, form.btnOther.widget.invoke)
    app_root().after(40, form.btnLoop.widget.invoke)  # while the loop runs: ignored
    form.btnLoop.widget.invoke()
    assert log == ["other", "loop done"]


def test_overlap_reenters_like_vb(tmp_path, forms_made):
    depth = []

    class Form1(Form):
        @while_running("overlap")
        def btnGo_click(self):
            depth.append(len(depth))
            if len(depth) == 1:
                app_root().after(1, self.btnGo.widget.invoke)
                for _ in range(20):
                    time.sleep(0.005)
                    doevents()

    form = make(tmp_path, Form1, ("Button", "btnGo"))
    forms_made(form)
    form.btnGo.widget.invoke()
    assert depth == [0, 1]  # the second click ran inside the first


def test_closing_the_form_stops_busy_handlers_quietly(tmp_path, capsys):
    log = []

    class Form1(Form):
        async def btnAsync_click(self):
            try:
                while True:
                    self.text = "busy"
                    await pause(0.01)
            finally:
                log.append("async stopped")

        def btnSync_click(self):
            while True:
                doevents()  # raises FormClosed once the form has closed
                time.sleep(0.005)

    form = make(tmp_path, Form1, ("Button", "btnAsync"), ("Button", "btnSync"))
    form.btnAsync.widget.invoke()
    app_root().after(100, form.close)
    form.btnSync.widget.invoke()  # returns when the form closes
    pump(1, until=lambda: "async stopped" in log)
    assert log == ["async stopped"] and not form.loaded
    assert "Traceback" not in capsys.readouterr().err


def test_async_errors_are_reported_like_other_handler_errors(tmp_path, forms_made, capsys):
    class Form1(Form):
        async def btnGo_click(self):
            await pause()
            return 1 / 0

    form = make(tmp_path, Form1, ("Button", "btnGo"))
    forms_made(form)
    form.btnGo.widget.invoke()
    pump(1, until=lambda: not form._tasks)
    err = capsys.readouterr().err
    assert "Traceback (most recent call last):" in err and "ZeroDivisionError" in err
    assert f'File "{__file__}"' in err  # so the IDE can show the line


def test_in_thread(tmp_path, forms_made):
    results = []

    def crunch(n):
        if n < 0:
            raise ValueError("negative")
        time.sleep(0.05)
        return n * 2, threading.get_ident()

    class Form1(Form):
        async def Form_load(self):  # async handlers work for form events too
            value, thread = await in_thread(crunch, 21)
            results.append((value, thread != threading.get_ident()))
            try:
                await in_thread(crunch, -1)
            except ValueError as e:
                results.append(str(e))

    form = make(tmp_path, Form1)
    forms_made(form)
    pump(3, until=lambda: len(results) == 2)
    assert results == [(42, True), "negative"]


def test_the_program_ends_when_its_last_form_closes_even_mid_thread(tmp_path):
    formfile.save(formfile.FormDesign(name="Form1"), tmp_path / "Form1.form")
    (tmp_path / "Form1.py").write_text(
        "import time\nfrom readymade import Form, in_thread\n\n\nclass Form1(Form):\n"
        "    async def Form_load(self):\n"
        "        self.root.after(200, self.close)\n"
        "        await in_thread(time.sleep, 30)\n"
    )
    env = dict(os.environ, PYTHONPATH=str(ROOT))
    start = time.time()
    result = subprocess.run([sys.executable, "-m", "readymade.run", "--startup", "Form1", str(tmp_path)],
                            capture_output=True, text=True, env=env, timeout=20)
    assert result.returncode == 0, result.stderr
    assert time.time() - start < 10 and "Traceback" not in result.stderr


def test_async_handlers_are_found_in_the_code():
    source = "class Form1(Form):\n    async def btnGo_click(self):\n        await pause()\n"
    assert codegen.defined_methods(source) == {"btnGo_click"}
    assert codegen.find_method(source, "btnGo_click") == 2
    assert "async def btnStart_click(self):" in codegen.rename_control(source, "btnGo", "btnStart", ["click"])


def test_garbage_is_collected_on_the_gui_thread_while_a_window_runs():
    import gc
    import tkinter as tk

    from readymade.events import collect_garbage_on

    root = tk.Tk()
    collect_garbage_on(root, every=10)
    assert not gc.isenabled()  # no collecting in whatever thread happens to allocate
    root.update()
    root.destroy()
    assert gc.isenabled()  # back to normal once the window has closed
