"""The form design surface: draw, select, move and resize controls on a grid.

Controls in the designer are the same Control classes the runtime uses, created
in design mode, so what you see while designing is what you get when running.
A control drawn inside a Frame belongs to that Frame, and its position is
relative to it.

The form editor owns the selection (app.selection, the reference control last).
Ctrl+click adds or removes a control; dragging a box on the form selects the
controls it touches. Selected controls always share a container.
"""

from __future__ import annotations

import tkinter as tk

from pybasic import menus
from pybasic.controls import create
from pybasic.form import FORM

GRID = 8
HANDLE = 6
SURROUND = "#808080"
_CONTROL_KEY = 0x0004  # the Control modifier in a Tk event's state

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
        self._markers = []  # the corner marks of a multiple selection
        self._drag = None  # (kind, control, x_root, y_root, {name: original geometry})
        self._band = None  # (container, x, y) while drawing a new control
        self._lasso = None  # (x, y, adding) while dragging a box to select controls
        self._form_drag = (0, 0, 0, 0)  # (x_root, y_root, width, height) while resizing the form

        self.window = tk.Frame(self, relief=tk.RAISED, bd=2)
        self.window.place(x=16, y=16)
        self.title = tk.Label(self.window, anchor="w", bg="#000080", fg="white", padx=4)
        self.title.pack(fill=tk.X)
        # The form's menu bar, shown when it has one. Clicking an item opens its click handler, as in VB.
        self.menubar = tk.Frame(self.window)
        self.canvas = tk.Canvas(self.window, highlightthickness=0, bd=0, bg=self.window.cget("bg"))
        self.canvas.pack()
        self.canvas.bind("<ButtonPress-1>", self._canvas_press)
        self.canvas.bind("<B1-Motion>", self._motion)
        self.canvas.bind("<ButtonRelease-1>", self._release)
        self.canvas.bind("<Double-Button-1>", lambda e: app.goto_handler(FORM, "load"))
        self.canvas.bind("<Delete>", lambda e: self.app.delete_selection())
        # Arrows move the selected controls a grid step (Ctrl: 1 pixel); with Shift they resize them.
        for key, dx, dy in (("Left", -1, 0), ("Right", 1, 0), ("Up", 0, -1), ("Down", 0, 1)):
            for modifiers, step, resize in (("", GRID, False), ("Control-", 1, False), ("Shift-", GRID, True), ("Control-Shift-", 1, True)):
                self.canvas.bind(f"<{modifiers}{key}>", lambda e, x=dx * step, y=dy * step, r=resize: self._arrow(x, y, r))

        self.form_handle = tk.Frame(self, bg="black", width=HANDLE, height=HANDLE, cursor="bottom_right_corner")
        self.form_handle.place(in_=self.window, relx=1.0, rely=1.0)
        self.form_handle.bind("<ButtonPress-1>", self._form_handle_press)
        self.form_handle.bind("<B1-Motion>", self._form_handle_motion)
        self.form_handle.bind("<ButtonRelease-1>", self._form_handle_release)

        self.handles = {}
        for spot, cursor in _HANDLES.items():
            handle = tk.Frame(self.canvas, bg="black", width=HANDLE, height=HANDLE, cursor=cursor)
            handle.bind("<ButtonPress-1>", lambda e, s=spot: self._start_drag(e, s))
            handle.bind("<B1-Motion>", self._motion)
            handle.bind("<ButtonRelease-1>", self._release)
            self.handles[spot] = handle
        # The rubber band shown while drawing: four thin lines that stay above other controls.
        self.band = [tk.Frame(self.canvas, bg="black") for _ in range(4)]

    # ----- building from the design -----

    def rebuild(self):
        for control in self.controls.values():
            control.widget.destroy()
        self.controls = {}
        self.refresh_form()
        self.refresh_menu()
        for spec in self.app.design.controls:
            self.add(spec)
        self.show_selection()

    def refresh_form(self):
        design = self.app.design
        self.title.configure(text=design.text)
        self.canvas.configure(width=design.width, height=design.height)
        self._draw_grid(design.width, design.height)

    def refresh_menu(self):
        for child in self.menubar.winfo_children():
            child.destroy()
        items = [i for i in self.app.design.menu if i.get("text") != menus.SEPARATOR]
        if not items:
            self.menubar.pack_forget()
            return
        self.menubar.pack(fill=tk.X, before=self.canvas)
        for item in items:
            label, underline = menus.parse_text(item.get("text", ""))
            button = tk.Menubutton(self.menubar, text=label, underline=underline, padx=6, takefocus=0)
            button.pack(side=tk.LEFT)
            if item.get("items"):
                dropdown = tk.Menu(button, tearoff=False)
                menus.build(dropdown, item["items"], self._menu_entry)
                button["menu"] = dropdown
            else:
                button.bind("<ButtonRelease-1>", lambda e, n=item["name"]: self.app.goto_handler(n, "click"))

    def _menu_entry(self, item, menu, index, variable):
        if variable is None:
            return None  # a submenu

        def command():
            variable.set(bool(item.get("checked", False)))  # show the designed state, not a toggle
            self.app.goto_handler(item["name"], "click")

        return command

    def add(self, spec):
        container = self.controls.get(spec.get("container"))
        control = create(self.canvas if container is None else container.inner, spec, design=True,
                         folder=self.app.path.parent)  # the project's folder, for pictures
        for widget in control.design_widgets():
            widget.bind("<ButtonPress-1>", lambda e, c=control: self._control_press(e, c))
            widget.bind("<B1-Motion>", self._motion)
            widget.bind("<ButtonRelease-1>", self._release)
            widget.bind("<Double-Button-1>", lambda e, c=control: self._control_double(c))
        self.controls[control.name] = control
        _follow_size(spec, control)
        self._lift_handles()

    def refresh_control(self, name):
        control = self.controls[name]
        spec = self.app.design.control(name)
        defaults = control.prop_defaults()
        if any(spec.get(prop, defaults[prop]) != getattr(control, prop) for prop in control.recreate_props):
            self._recreate(spec)
        else:
            for prop, default in defaults.items():
                setattr(control, prop, spec.get(prop, default))
            _follow_size(spec, control)
        self.show_selection()

    def _recreate(self, spec):
        """Rebuild a control whose widget type depends on a property (not for containers)."""
        self.controls.pop(spec["name"]).widget.destroy()
        self.add(spec)
        # add() puts it on top; put it back below the siblings that came after it.
        specs = self.app.design.controls
        for later in specs[specs.index(spec) + 1 :]:
            if later.get("container") == spec.get("container"):
                self.controls[spec["name"]].widget.lower(self.controls[later["name"]].widget)
                break

    def rename(self, old, new):
        control = self.controls.pop(old)
        control.name = new
        self.controls[new] = control

    def remove(self, name):
        self.controls.pop(name).widget.destroy()
        self.show_selection()

    def show_selection(self):
        """One selected control gets resize handles; several get corner marks, solid on the
        reference control (the last one selected) and hollow on the others."""
        for marker in self._markers:
            marker.destroy()
        self._markers = []
        selection = [self.controls[n] for n in self.app.selection if n in self.controls]
        if len(selection) != 1:
            for handle in self.handles.values():
                handle.place_forget()
        if not selection:
            return
        self.canvas.update_idletasks()
        if len(selection) == 1:
            x, y = self._on_canvas(selection[0])
            for (fx, fy), handle in self.handles.items():
                handle.place(x=int(x + fx * selection[0].width - HANDLE / 2), y=int(y + fy * selection[0].height - HANDLE / 2))
            self._lift_handles()
            return
        for control in selection:
            x, y = self._on_canvas(control)
            reference = control is selection[-1]
            for fx, fy in ((0, 0), (1, 0), (0, 1), (1, 1)):
                marker = tk.Frame(self.canvas, width=HANDLE, height=HANDLE, bg="black" if reference else "white",
                                  highlightthickness=1, highlightbackground="black")
                marker.place(x=int(x + fx * control.width - HANDLE / 2), y=int(y + fy * control.height - HANDLE / 2))
                marker.bind("<ButtonPress-1>", lambda e, c=control: self._control_press(e, c))
                marker.bind("<B1-Motion>", self._motion)
                marker.bind("<ButtonRelease-1>", self._release)
                self._markers.append(marker)

    def _on_canvas(self, control):
        """Where a control is on the canvas, measured on screen, since a control inside a
        Frame is positioned relative to the Frame."""
        return (control.widget.winfo_rootx() - self.canvas.winfo_rootx(),
                control.widget.winfo_rooty() - self.canvas.winfo_rooty())

    def _lift_handles(self):
        for handle in self.handles.values():
            handle.lift()

    def _draw_grid(self, width, height):
        self.canvas.delete("grid")
        for x in range(GRID, width, GRID):
            for y in range(GRID, height, GRID):
                self.canvas.create_line(x, y, x + 1, y, fill="#606060", tags="grid")

    # ----- mouse handling -----

    def _canvas_press(self, e):
        self.canvas.focus_set()
        if self.app.toolbox.tool:
            return self._start_band(e)
        self._lasso = (e.x, e.y, bool(e.state & _CONTROL_KEY))

    def _control_press(self, e, control):
        self.canvas.focus_set()
        if self.app.toolbox.tool:
            return self._start_band(e)
        if e.state & _CONTROL_KEY:
            self.app.toggle_selected(control.name)
            return "break"
        if control.name not in self.app.selection:
            self.app.select(control.name)
        return self._start_drag(e, "move", control)

    def _control_double(self, control):
        self.app.goto_handler(control.name, control.default_event)
        return "break"

    def _motion(self, e):
        if self._band:
            self._band_motion(e, self._band)
        elif self._drag:
            self._drag_motion(e, self._drag)
        elif self._lasso:
            x0, y0, _ = self._lasso
            self._draw_rect(min(x0, e.x), min(y0, e.y), abs(e.x - x0), abs(e.y - y0))
        return "break"

    def _release(self, e):
        if self._band:
            self._band_release(e, self._band)
        elif self._drag:
            self._drag_release(self._drag)
        elif self._lasso:
            self._lasso_release(e, self._lasso)
        return "break"

    def _lasso_release(self, e, lasso):
        """Select the controls on the form that the box touches (Ctrl: add them)."""
        x0, y0, adding = lasso
        self._lasso = None
        for line in self.band:
            line.place_forget()
        left, top, right, bottom = min(x0, e.x), min(y0, e.y), max(x0, e.x), max(y0, e.y)
        if right - left < 3 and bottom - top < 3:
            if not adding:
                self.app.select(FORM)  # just a click on the form
            return
        touched = [c.name for c in self.controls.values()
                   if self.app.design.control(c.name).get("container") is None
                   and c.left < right and c.left + c.width > left and c.top < bottom and c.top + c.height > top]
        if adding:
            touched = [n for n in self.app.selection if n in self.controls] + [n for n in touched if n not in self.app.selection]
        self.app.select_many(touched)

    def _arrow(self, dx, dy, resize):
        if resize:
            self.app.nudge(dwidth=dx, dheight=dy)
        else:
            self.app.nudge(dx=dx, dy=dy)
        return "break"

    # ----- drawing new controls -----

    def _origin(self, container):
        """Screen position of (0, 0) inside a container, or on the form for None."""
        widget = self.canvas if container is None else container.inner
        return widget.winfo_rootx(), widget.winfo_rooty()

    def _container_at(self, x_root, y_root):
        """The innermost Frame under a screen point, or None for the form itself."""
        best, best_area = None, None
        for control in self.controls.values():
            if not control.is_container:
                continue
            inner = control.inner
            x, y, w, h = inner.winfo_rootx(), inner.winfo_rooty(), inner.winfo_width(), inner.winfo_height()
            if x <= x_root < x + w and y <= y_root < y + h and (best_area is None or w * h < best_area):
                best, best_area = control, w * h
        return best

    def _local(self, container, e):
        ox, oy = self._origin(container)
        return snap(e.x_root - ox), snap(e.y_root - oy)

    def _start_band(self, e):
        container = self._container_at(e.x_root, e.y_root)
        x, y = self._local(container, e)
        self._band = (container, x, y)
        self._draw_band(container, x, y, x, y)
        return "break"

    def _draw_band(self, container, x0, y0, x1, y1):
        ox, oy = self._origin(container)
        left = min(x0, x1) + ox - self.canvas.winfo_rootx()
        top = min(y0, y1) + oy - self.canvas.winfo_rooty()
        self._draw_rect(left, top, abs(x1 - x0), abs(y1 - y0))

    def _draw_rect(self, left, top, w, h):
        """Show a rectangle on the canvas: four thin lines that stay above the controls."""
        lines = [(left, top, w + 1, 1), (left, top + h, w + 1, 1), (left, top, 1, h + 1), (left + w, top, 1, h + 1)]
        for line, (x, y, lw, lh) in zip(self.band, lines):
            line.place(x=x, y=y, width=lw, height=lh)
            line.lift()

    def _band_motion(self, e, band):
        container, x0, y0 = band
        self._draw_band(container, x0, y0, *self._local(container, e))

    def _band_release(self, e, band):
        container, x0, y0 = band
        self._band = None
        for line in self.band:
            line.place_forget()
        x1, y1 = self._local(container, e)
        tool = self.app.toolbox.tool
        self.app.toolbox.reset()
        name = container.name if container else None
        if abs(x1 - x0) < GRID or abs(y1 - y0) < GRID:
            self.app.add_control(tool, x0, y0, container=name)  # a click, not a drag: use the default size
        else:
            self.app.add_control(tool, min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0), container=name)

    # ----- moving and resizing -----

    def _start_drag(self, e, kind, control=None):
        """Start moving the selection (dragging one of its controls) or resizing one control."""
        control = control or self.controls[self.app.selected]
        if kind != "move" and not control.resizable:
            return "break"
        moving = [self.controls[n] for n in self.app.selection if n in self.controls] if kind == "move" else [control]
        if control not in moving:
            moving = [control]
        originals = {c.name: (c.left, c.top, c.width, c.height) for c in moving}
        self._drag = (kind, control, e.x_root, e.y_root, originals)
        return "break"

    def _drag_motion(self, e, drag):
        kind, control, x0, y0, originals = drag
        left, top, width, height = originals[control.name]
        dx, dy = e.x_root - x0, e.y_root - y0
        if kind == "move":
            # Snap the control being dragged; the others keep their places relative to it.
            dx, dy = snap(left + dx) - left, snap(top + dy) - top
            for name, (l, t, _, _) in originals.items():
                self.controls[name].left, self.controls[name].top = l + dx, t + dy
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
        self.show_selection()

    def _drag_release(self, drag):
        kind, pressed, _, _, originals = drag
        self._drag = None
        changed = {}
        for name, before in originals.items():
            control = self.controls[name]
            after = (control.left, control.top, control.width, control.height)
            if after != before:
                changed[name] = after
        if changed:
            self.app.set_geometries(changed)
        elif kind == "move" and len(originals) > 1:
            # Pressing a control in a multiple selection keeps it, so the group can be dragged;
            # just clicking it (no drag) selects that control alone.
            self.app.select(pressed.name)

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


def _follow_size(spec, control):
    """A control that sizes itself (an autosized Image) decides its size; the design follows."""
    if not control.resizable:
        for prop in ("width", "height"):
            if prop in spec:
                spec[prop] = getattr(control, prop)
