import os
import shutil
import subprocess
import tkinter as tk
from tkinter import messagebox

import pytest


def _start_private_display():
    """Run the tests on a private Xvfb display when available, so their windows
    (and any program they run) never appear on the desktop."""
    if not shutil.which("Xvfb"):
        return None
    # Under WSLg Xvfb can't pick a display number itself (/tmp/.X11-unix is read-only),
    # so try free numbers explicitly; -displayfd reports when the server is ready.
    for number in range(100, 120):
        if os.path.exists(f"/tmp/.X{number}-lock"):
            continue
        ready_r, ready_w = os.pipe()
        server = subprocess.Popen(
            ["Xvfb", f":{number}", "-displayfd", str(ready_w), "-screen", "0", "1280x800x24", "-nolisten", "tcp"],
            pass_fds=(ready_w,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        os.close(ready_w)
        with os.fdopen(ready_r) as ready:
            if ready.readline().strip():
                os.environ["DISPLAY"] = f":{number}"  # inherited by programs the tests start
                return server
        server.wait()
    return None


_XVFB = _start_private_display()


def pytest_report_header(config):
    where = "private Xvfb" if _XVFB else "the desktop (Xvfb unavailable)"
    return f"Tk display: {os.environ.get('DISPLAY', '(none)')} on {where}"


def pytest_unconfigure(config):
    if _XVFB is not None:
        _XVFB.terminate()


def _has_display():
    try:
        tk.Tk().destroy()
        return True
    except tk.TclError:
        return False


HAS_DISPLAY = _has_display()


@pytest.fixture
def display():
    """Skip the test when Tk can't open a window."""
    if not HAS_DISPLAY:
        pytest.skip("needs a display for Tk")


@pytest.fixture(autouse=True)
def no_dialogs(monkeypatch):
    """A message box would wait for a click, so fail the test with its message instead."""
    def fail(title=None, message=None, **kwargs):
        raise AssertionError(f"unexpected dialog {title!r}: {message}")

    for name in ("showerror", "showwarning", "showinfo", "askyesno", "askyesnocancel", "askokcancel"):
        monkeypatch.setattr(messagebox, name, fail)
