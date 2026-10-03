"""The form design surface: draw, select, move and resize controls on a grid.

Controls in the designer are the same Control classes the runtime uses, created
in design mode, so what you see while designing is what you get when running.
"""

from __future__ import annotations

import tkinter as tk

from pybasic.controls import create
from pybasic.form import FORM

GRID = 8
HANDLE = 6
SURROUND = "#808080"

# Selection handles: (x fraction, y fraction) of the control -> cursor.
_HANDLES = {
    (0, 0): "top_left_corner",
    (0.5, 0): "top_side",
    (1, 0): "top_right_corner",
    (0, 0.5): "left_side",
    (1, 0.5): "right_side",
    (0, 1): "bottom_left_corner",
    (0.5, 1): "bottom_side",
    (1, 1): "bottom_right_corner",
}


def snap(value):
    return round(value / GRID) * GRID


class DesignSurface(tk.Frame):
    def __init__(self, master, app):
        super().__init__(master, bg=SURROUND)
        self.app = app
        self.controls = {}
        self.selected = None
        self._drag = None  # (kind, control, x_root, y_root, original geometry)
        self._band = None  # (x, y, canvas item) while drawing a new control

        self.window = tk.Frame(self, relief=tk.RAISED, bd=2)
        self.window.place(x=16, y=16)
        self.title = tk.Label(self.window, anchor="w", bg="#000080", fg="white", padx=4)
        self.title.pack(fill=tk.X)
        self.canvas = tk.Canvas(self.window, highlightthickness=0, bd=0, bg=self.window.cget("bg"))
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._canvas_press)
        self.canvas.bind("<B1-Motion>", self._canvas_motion)
        self.canvas.bind("<ButtonRelease-1>", self._canvas_release)
        self.canvas.bind("<Double-Button-1>", lambda e: app.goto_handler(FORM, "load"))
        self.canvas.bind("<Delete>", self._delete_selected)

        self.form_handle = tk.Frame(self, bg="black", width=HANDLE, height=HANDLE, cursor="bottom_right_corner")
        self.form_handle.place(in_=self.window, relx=1.0, rely=1.0)
        self.form_handle.bind("<ButtonPress-1>", self._form_handle_press)
        self.form_handle.bind("<B1-Motion>", self._form_handle_motion)
        self.form_handle.bind("<ButtonRelease-1>", self._form_handle_release)

        self.handles = {}
        for spot, cursor in _HANDLES.items():
            handle = tk.Frame(self.canvas, bg="black", width=HANDLE, height=HANDLE, cursor=cursor)
            handle.bind("<ButtonPress-1>", lambda e, s=spot: self._start_drag(e, s))
            handle.bind("<B1-Motion>", self._drag_motion)
            handle.bind("<ButtonRelease-1>", self._drag_release)
            self.handles[spot] = handle

    # ----- building from the design -----

    def rebuild(self):
        for control in self.controls.values():
            control.widget.destroy()
        self.controls = {}
        self.refresh_form()
        for spec in self.app.design.controls:
            self.add(spec)
        self.show_selection(None)

    def refresh_form(self):
        design = self.app.design
        self.title.configure(text=design.text)
        self.canvas.configure(width=design.width, height=design.height)
        self._draw_grid(design.width, design.height)

    def add(self, spec):
        control = create(self.canvas, spec, design=True)
        widget = control.widget
        widget.bind("<ButtonPress-1>", lambda e, c=control: self._control_press(e, c))
        widget.bind("<B1-Motion>", self._drag_motion)
        widget.bind("<ButtonRelease-1>", self._drag_release)
        widget.bind("<Double-Button-1>", lambda e, c=control: self._control_double(c))
        self.controls[control.name] = control
        self._lift_handles()

    def refresh_control(self, name):
        control = self.controls[name]
        spec = self.app.design.control(name)
        for prop, default in control.prop_defaults().items():
            setattr(control, prop, spec.get(prop, default))
        self.show_selection(self.selected)

    def rename(self, old, new):
        control = self.controls.pop(old)
        control.name = new
        self.controls[new] = control
        if self.selected == old:
            self.selected = new

    def remove(self, name):
        self.controls.pop(name).widget.destroy()
        if self.selected == name:
            self.show_selection(None)

    def show_selection(self, obj):
        self.selected = obj
        control = self.controls.get(obj)
        for (fx, fy), handle in self.handles.items():
            if control is None:
                handle.place_forget()
            else:
                handle.place(
                    x=int(control.left + fx * control.width - HANDLE / 2),
                    y=int(control.top + fy * control.height - HANDLE / 2),
                )
        self._lift_handles()

    def _lift_handles(self):
        for handle in self.handles.values():
            handle.lift()

    def _draw_grid(self, width, height):
        self.canvas.delete("grid")
        for x in range(GRID, width, GRID):
            for y in range(GRID, height, GRID):
                self.canvas.create_line(x, y, x + 1, y, fill="#606060", tags="grid")

    # ----- drawing new controls on the form -----

    def _canvas_press(self, e):
        self.canvas.focus_set()
        if self.app.toolbox.tool:
            x, y = snap(e.x), snap(e.y)
            self._band = (x, y, self.canvas.create_rectangle(x, y, x, y, dash=(2, 2)))
        else:
            self.app.select(FORM)

    def _canvas_motion(self, e):
        if self._band:
            x, y, item = self._band
            self.canvas.coords(item, x, y, snap(e.x), snap(e.y))

    def _canvas_release(self, e):
        if not self._band:
            return
        x0, y0, item = self._band
        self._band = None
        self.canvas.delete(item)
        x1, y1 = snap(e.x), snap(e.y)
        tool = self.app.toolbox.tool
        self.app.toolbox.reset()
        if abs(x1 - x0) < GRID or abs(y1 - y0) < GRID:
            self.app.add_control(tool, x0, y0)  # a click rather than a drag: use the default size
        else:
            self.app.add_control(tool, min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))

    # ----- selecting, moving and resizing controls -----

    def _control_press(self, e, control):
        self.canvas.focus_set()
        self.app.select(control.name)
        return self._start_drag(e, "move", control)

    def _control_double(self, control):
        self.app.goto_handler(control.name, control.default_event)
        return "break"

    def _start_drag(self, e, kind, control=None):
        control = control or self.controls[self.selected]
        geometry = (control.left, control.top, control.width, control.height)
        self._drag = (kind, control, e.x_root, e.y_root, geometry)
        return "break"

    def _drag_motion(self, e):
        if not self._drag:
            return "break"
        kind, control, x0, y0, (left, top, width, height) = self._drag
        dx, dy = e.x_root - x0, e.y_root - y0
        if kind == "move":
            control.left, control.top = snap(left + dx), snap(top + dy)
        else:
            fx, fy = kind
            right, bottom = left + width, top + height
            if fx == 0:
                left = min(snap(left + dx), right - GRID)
            elif fx == 1:
                right = max(snap(right + dx), left + GRID)
            if fy == 0:
                top = min(snap(top + dy), bottom - GRID)
            elif fy == 1:
                bottom = max(snap(bottom + dy), top + GRID)
            control.left, control.top = left, top
            control.width, control.height = right - left, bottom - top
        self.show_selection(control.name)
        return "break"

    def _drag_release(self, _):
        if self._drag:
            _, control, _, _, before = self._drag
            self._drag = None
            after = (control.left, control.top, control.width, control.height)
            if after != before:
                self.app.geometry_changed(control.name, after)
        return "break"

    def _delete_selected(self, _):
        if self.selected in self.controls:
            self.app.delete_control(self.selected)

    # ----- resizing the form -----

    def _form_handle_press(self, e):
        design = self.app.design
        self._form_drag = (e.x_root, e.y_root, design.width, design.height)

    def _form_handle_motion(self, e):
        x0, y0, width, height = self._form_drag
        self.canvas.configure(
            width=max(GRID * 8, snap(width + e.x_root - x0)),
            height=max(GRID * 4, snap(height + e.y_root - y0)),
        )

    def _form_handle_release(self, _):
        self.app.set_form_size(int(self.canvas.cget("width")), int(self.canvas.cget("height")))
