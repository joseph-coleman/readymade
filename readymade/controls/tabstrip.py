"""The TabStrip control: pages behind tabs, each holding its own controls (VB's SSTab)."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade.controls.base import Control, Event, _controls, register, repaint_inside
from readymade.controls.traits import Anchored, BackColor, Cursor, Tooltip


@register
class TabStrip(BackColor, Cursor, Tooltip, Anchored, Control):
    """Pages behind tabs; click a tab to see its page. Controls drawn on a page belong to
    it (its `page` in the Properties panel): they show only while their page does. tabs
    are the tabs' captions, and tab is the page showing, counting from 0; click runs when
    the user picks a tab. In the designer, click a tab to work on its page."""

    type_name = "TabStrip"
    default_size = (280, 180)
    default_event = "click"
    is_container = True
    has_pages = True
    inherits_backcolor = False
    events = (Event("click", policy="latest"),)
    extra_props = {"tabs": ["Tab 1", "Tab 2", "Tab 3"], "tab": 0}

    def create_widget(self, parent):
        self._tab = 0
        self._enabled = True
        self._tabs = []
        self._pages = []  # a tk.Frame for each page there's been (pages past the tabs are hidden)
        self._on_click = []
        self._notebook = ttk.Notebook(parent, style="Preview.TNotebook" if self.design else "TNotebook")
        self._notebook.bind("<<NotebookTabChanged>>", lambda e: self._changed(), add="+")
        return self._notebook

    def widgets(self):
        return [self._notebook, *self._pages]

    @property
    def inner(self):
        """The page showing: where the designer draws new controls."""
        return self._pages[self._shown()]

    @property
    def tabs(self):
        """The tabs' captions, as a list of strings (one per line in the Properties panel). A
        page whose tab is taken away keeps its controls, out of sight."""
        return list(self._tabs)

    @tabs.setter
    def tabs(self, captions):
        captions = [str(c) for c in captions] or ["Tab 1"]
        self._tabs = captions
        while len(self._pages) < len(captions):
            page = tk.Frame(self._notebook)
            self._pages.append(page)
            self._notebook.add(page)
        for index, page in enumerate(self._pages):
            if index < len(captions):
                self._notebook.tab(page, state="normal" if self._enabled else "disabled", text=captions[index])
            else:
                self._notebook.hide(page)
        if self._tab >= len(captions):
            self.tab = len(captions) - 1
        self._paint()

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled TabStrip's tabs are grayed out, and its
        page can't be changed (except by code)."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        for page in self._pages[:len(self._tabs)]:
            self._notebook.tab(page, state="normal" if self._enabled else "disabled")

    @property
    def tab(self):
        """The page showing, counting from 0 (the one shown when the program starts)."""
        return self._tab

    @tab.setter
    def tab(self, index):
        index = int(index)
        if not 0 <= index < len(self._tabs):
            raise ValueError(f"tab must be from 0 to {len(self._tabs) - 1}, not {index}")
        changed = index != self._tab
        self._tab = index
        self._notebook.select(self._pages[index])
        if changed and self._ready:
            self._click()

    def _shown(self):
        try:
            return self._notebook.index("current")
        except tk.TclError:
            return 0

    def _changed(self):
        """A tab was picked: tab follows it, and click runs. (In the designer a click on a
        tab only shows its page.)"""
        shown = self._shown()
        if not self.design and shown != self._tab:
            self._tab = shown
            self._click()

    def _click(self):
        for handler in self._on_click:
            handler()

    def bind_event(self, event, handler):
        if event == "click":
            self._on_click.append(handler)
        else:
            super().bind_event(event, handler)

    # ----- for the form and the designer (see base.inner_for, page_at, show_page) -----

    def _inner_for(self, page):
        """The page a control with this page number goes on (the last one, if it's past the tabs)."""
        return self._pages[min(max(int(page), 0), len(self._tabs) - 1)]

    def _page_at(self, x_root, y_root):
        """The page whose tab is at a screen point, or None."""
        x, y = x_root - self._notebook.winfo_rootx(), y_root - self._notebook.winfo_rooty()
        if not self._notebook.identify(x, y):
            return None
        try:
            index = self._notebook.index(f"@{x},{y}")
        except tk.TclError:
            return None
        return index if isinstance(index, int) and 0 <= index < len(self._tabs) else None

    def _show(self, page):
        """Show a page in the designer, without changing tab."""
        self._notebook.select(self._inner_for(page))

    # ----- how it looks -----

    def _painted(self):
        return self._pages

    def _paint(self):
        super()._paint()
        if self._ready:
            for page in self._pages:
                repaint_inside(page)  # controls showing its color follow it

    def _place(self):
        super()._place()
        if not self._ready or self.design:
            return  # (the designer moves anchored controls itself, in the form's design)
        # The controls on its pages follow its size, measured from the size it was designed at.
        _, _, width, height = self._rect()
        designed = getattr(self, "_designed_size", None)
        if designed is None:
            designed = self._designed_size = (width, height)
        for page in self._pages:
            for child in page.winfo_children():
                ref = _controls.get(child)
                control = ref() if ref else None
                if control is not None:
                    control.follow_container(width - designed[0], height - designed[1])
