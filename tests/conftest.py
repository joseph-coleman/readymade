import ctypes
import os
import signal
import shutil
import subprocess
import tkinter as tk
import traceback
from tkinter import messagebox

import pytest


def _ends_with_us():
    """In the Xvfb process, before it starts: Linux ends it when the test run's process does,
    even a run that's killed (pytest_unconfigure, which stops it otherwise, never runs then)."""
    try:
        ctypes.CDLL(None).prctl(1, signal.SIGTERM)  # PR_SET_PDEATHSIG
    except (OSError, AttributeError):
        pass


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
            pass_fds=(ready_w,), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, preexec_fn=_ends_with_us,
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


@pytest.fixture(autouse=True)
def no_popup_menus(monkeypatch):
    """A right-click menu is built but never shown: on Windows, tk_popup waits inside the
    system's menu loop until someone clicks, which would stop the tests there. (A test can
    put its own tk_popup in, to see that a menu was asked for.)"""
    monkeypatch.setattr(tk.Menu, "tk_popup", lambda menu, x, y, entry="": None)


@pytest.fixture(autouse=True)
def own_settings(monkeypatch, tmp_path_factory):
    """Each test gets its own user settings folder, never the real one."""
    monkeypatch.setenv("READYMADE_CONFIG_DIR", str(tmp_path_factory.mktemp("settings")))


@pytest.fixture(autouse=True)
def own_trash(request, monkeypatch, tmp_path_factory):
    """Files removed in tests go to a trash of their own, never the real Trash or Recycle Bin.
    (test_trash.py tries the Linux trash itself, in a temporary folder.)"""
    if request.module.__name__ == "test_trash":
        return
    from readymade.ide import trash

    folder = tmp_path_factory.mktemp("trash")

    def move_to_trash(path):
        path.rename(folder / path.name)

    monkeypatch.setattr(trash, "move_to_trash", move_to_trash)


@pytest.fixture(autouse=True)
def collect_garbage_here():
    """Free each test's leftover Tk objects on the main thread, before the next test's
    background threads (linting, completion, program output) could, which would crash Tk."""
    yield
    import gc

    gc.collect()


@pytest.fixture(autouse=True)
def no_callback_errors(monkeypatch):
    """An error in a Tk callback (a binding, an after(), a button's command) is only printed by
    Tk, so the test would carry on and pass. Fail it instead, with the error's traceback."""
    errors = []
    monkeypatch.setattr(tk.Tk, "report_callback_exception",
                        lambda root, kind, value, tb: errors.append("".join(traceback.format_exception(kind, value, tb))))
    yield
    if errors:
        pytest.fail(f"{len(errors)} error(s) in Tk callbacks:\n\n" + "\n".join(errors), pytrace=False)
