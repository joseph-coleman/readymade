"""Tooltips for the IDE's own small buttons (the find bar's Aa, ab and .* and the like):
what they do, shown when the mouse rests on them. dynamic() does the same for parts of a
widget, like the marks in the line numbers or the notes in a list's rows."""

from __future__ import annotations

import tkinter as tk

from readymade.ide import options

DELAY = 600  # milliseconds the mouse rests on a widget before its tip shows


class _Tip:
    """The one tip window showing (or about to)."""

    window = None
    job = None


_texts = {}  # widget path -> its tip


def tip(widget, text):
    """Show text when the mouse rests on widget."""
    _texts[str(widget)] = text
    widget.bind("<Enter>", lambda e: _wait(widget, text), add="+")
    for sequence in ("<Leave>", "<ButtonPress>"):
        widget.bind(sequence, lambda e: hide(), add="+")


def dynamic(widget, text_at):
    """Tips for parts of a widget: text_at(x, y) is the tip for the place the mouse is at
    (in the widget), or "" for none there. The tip shows under the mouse."""
    showing = {"text": ""}

    def moved(e):
        text = text_at(e.x, e.y)
        if text == showing["text"]:
            return
        showing["text"] = text
        hide()
        if text:
            x, y = e.x_root, e.y_root
            _Tip.job = (widget, widget.after(DELAY, lambda: _show(widget, text, x, y + 20)))

    def gone(_):
        showing["text"] = ""
        hide()

    widget.bind("<Motion>", moved, add="+")
    for sequence in ("<Leave>", "<ButtonPress>"):
        widget.bind(sequence, gone, add="+")


def _wait(widget, text):
    hide()
    _Tip.job = (widget, widget.after(DELAY, lambda: _show(widget, text)))


def _show(widget, text, x=None, y=None):
    _Tip.job = None
    if not widget.winfo_viewable():
        return
    chrome = options.theme().chrome
    window = _Tip.window = tk.Toplevel(widget)
    window.wm_overrideredirect(True)  # no title bar or border from the window manager
    tk.Label(window, text=text, justify="left", wraplength=360, padx=4, pady=2, relief="solid", bd=1,
             background=chrome.window if chrome else "#ffffe1",
             foreground=chrome.text if chrome else "#000000").pack()
    if x is None:
        x, y = widget.winfo_rootx(), widget.winfo_rooty() + widget.winfo_height() + 4
    window.wm_geometry(f"+{x}+{y}")


def hide():
    if _Tip.job is not None:
        widget, job = _Tip.job
        _Tip.job = None
        try:
            widget.after_cancel(job)
        except tk.TclError:
            pass
    if _Tip.window is not None:
        try:
            _Tip.window.destroy()
        except tk.TclError:
            pass
        _Tip.window = None


def text_of(widget):
    """The tip set for a widget, or ""."""
    return _texts.get(str(widget), "")
