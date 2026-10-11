"""The Grid control: rows and columns that place the controls in it."""

from __future__ import annotations

import tkinter as tk

from readymade import layout
from readymade.controls.base import _MOUSE_EVENTS, Control, _controls, register, repaint_inside
from readymade.controls.traits import Anchored, BackColor, Cursor, Tooltip


@register
class Grid(BackColor, Cursor, Tooltip, Anchored, Control):
    """Rows and columns of controls. columns and rows are lists like "auto, *, 2*, 120": auto
    fits what's in it, * and 2*, 3*... share the space left over by weight, and a number is
    fixed pixels. Each control in it has a row and column (counting from 0), may span
    several, and its anchor names the edges of its cell it sticks to (all four fill it).
    Its width and height are the size it asks for: what auto rows and columns fit."""

    inner: tk.Canvas
    type_name = "Grid"
    default_size = (240, 160)
    is_container = True
    arranges_inside = True
    inherits_backcolor = True
    events = _MOUSE_EVENTS
    extra_props = {"columns": "*, *", "rows": "*, *", "gap": 4, "padding": 4, "border": False}

    def create_widget(self, parent):
        self._columns, self._rows = "*, *", "*, *"
        self._gap = self._padding = 4
        self._border = False
        self.column_lines = self.row_lines = None  # where its columns and rows are, once arranged
        # A canvas, so the designer can draw the cells; the controls are placed on it.
        self.inner = tk.Canvas(parent, highlightthickness=0, bd=0)
        return self.inner

    def _tracks(name, doc):
        def get(self):
            return getattr(self, "_" + name)

        def set(self, value):
            setattr(self, "_" + name, layout.normalize_tracks(value))
            self.arrange()

        return property(get, set, doc=doc)

    columns = _tracks("columns", """Its columns' widths, like "auto, *, 2*, 120": auto fits what's in it,
        * and 2*, 3*... share the space left over by weight, and a number is fixed pixels.""")
    rows = _tracks("rows", """Its rows' heights, like "auto, auto, *": as for columns.""")
    del _tracks

    @property
    def gap(self):
        """Pixels between its rows and columns."""
        return self._gap

    @gap.setter
    def gap(self, value):
        self._gap = max(0, int(value))
        self.arrange()

    @property
    def padding(self):
        """Pixels between its edge and its cells."""
        return self._padding

    @padding.setter
    def padding(self, value):
        self._padding = max(0, int(value))
        self.arrange()

    @property
    def border(self):
        """Whether a thin line is drawn around it."""
        return self._border

    @border.setter
    def border(self, value):
        self._border = bool(value)
        self.widget.configure(bd=int(self._border), relief="solid" if self._border else "flat")
        self.arrange()

    def _place(self):
        super()._place()
        self.arrange()

    def _paint(self):
        super()._paint()
        if self._ready:
            repaint_inside(self.inner)

    def children(self):
        """The controls in it."""
        found = []
        for widget in self.inner.winfo_children():
            ref = _controls.get(widget)
            control = ref() if ref else None
            if control is not None:
                found.append(control)
        return found

    def arrange(self):
        """Put the controls in it in their cells (it does this itself when anything changes)."""
        if not getattr(self, "_ready", False):
            return
        _, _, width, height = self._rect()
        edge = int(self._border)
        children = [c for c in self.children() if c.visible or c.design]
        cells = [(c.row, c.column, c.rowspan, c.columnspan, c.anchor, (c._width, c._height)) for c in children]
        rects, self.column_lines, self.row_lines = layout.arrange_grid(
            self._columns, self._rows, width - 2 * edge, height - 2 * edge, cells, self._gap, self._padding)
        for control, rect in zip(children, rects):
            control._grid_rect = rect
            control._place()
        if self.design:
            self._draw_cells(width - 2 * edge, height - 2 * edge)

    def _draw_cells(self, width, height):
        """The designer shows where the cells are."""
        self.inner.delete("cells")
        for lines, across in ((self.column_lines, True), (self.row_lines, False)):
            for start, size in zip(lines.starts, lines.sizes):
                for edge in (start, start + size):
                    points = (edge, 0, edge, height) if across else (0, edge, width, edge)
                    self.inner.create_line(*points, fill="#9a9a9a", dash=(2, 3), tags="cells")

    def cell_at(self, x, y):
        """The (row, column) at a point inside it (the nearest cell, outside its cells)."""
        if self.row_lines is None:
            return 0, 0
        return self.row_lines.index_at(y), self.column_lines.index_at(x)

    def cell_box(self, row, column, rowspan=1, columnspan=1):
        """(left, top, width, height) of a cell, or of several spanned, inside it."""
        x, width = layout.span(self.column_lines, column, columnspan, self._gap)
        y, height = layout.span(self.row_lines, row, rowspan, self._gap)
        return x, y, width, height
