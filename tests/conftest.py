import tkinter as tk

import pytest


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
