"""Open documents in the IDE: a FormEditor per open form, a ModuleEditor per open module.

Each editor owns one tab in the IDE's document notebook. A form's tab holds its
Design and Code views. The shared panels (Toolbox, Properties) work on the form
whose tab is showing.
"""

from __future__ import annotations

import contextlib
import copy
import functools
import keyword
import shutil
from pathlib import Path
from tkinter import colorchooser, filedialog, messagebox, ttk

from readymade import appearance, codegen, dialogs, formfile, layout, menus
from readymade.controls import GRID_CELL, LOOK_CHOICES, REGISTRY, Event, Grid
from readymade.form import FORM, FORM_EVENTS, check_name
from readymade.ide import arrange, assist
from readymade.ide.codeview import CodeView
from readymade.ide.designer import GRID, DesignSurface, snap

UNDO_LIMIT = 200
# Properties whose controls tidy what's typed, which is then saved tidied too.
_TIDIED = ("columns", "rows", "font", "anchor", "backcolor", "forecolor")
MULTIPLE = "(multiple controls)"  # the Properties panel's object while several controls are selected


def _undoable(method):
    """Record a designer change so it can be undone. Changes made inside it count as one."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._change():
            return method(self, *args, **kwargs)
    return wrapper


def bring_in(folder, path, into="images"):
    """The path, relative to folder, to use for a chosen file. A file from outside the folder
    is copied into its images folder first, so the program (and Make EXE) can always find
    it; a different file of the same name gets a numbered name instead of replacing it."""
    folder = Path(folder).resolve()
    path = Path(path).resolve()
    if path.is_relative_to(folder):
        return path.relative_to(folder).as_posix()
    target = folder / into / path.name
    number = 1
    while target.exists() and not _same_file_contents(target, path):
        number += 1
        target = target.with_name(f"{path.stem}-{number}{path.suffix}")
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
    return target.relative_to(folder).as_posix()


def _same_file_contents(a, b):
    return a.stat().st_size == b.stat().st_size and a.read_bytes() == b.read_bytes()


class FormEditor:
    def __init__(self, app, path):
        self.app = app
        self.path = path
        self.design = formfile.load(path)
        code_path = path.with_suffix(".py")
        saved_source = code_path.read_text(encoding="utf-8") if code_path.exists() else None
        self.selection = [FORM]  # selected objects; the last is the reference control
        self.frame = ttk.Notebook(app.documents)
        self.surface = DesignSurface(self.frame, self)
        self.code = CodeView(self.frame, self)
        self.frame.add(self.surface, text="Design")
        self.frame.add(self.code, text="Code")
        self.surface.rebuild()
        self.code.set_source(saved_source if saved_source is not None else codegen.new_module(self.design.name))
        self.code.refresh_objects()
        self._saved = (formfile.dumps(self.design), saved_source)
        # Each entry is (state before, state after, merge key); a state is (design JSON, code).
        self._undo: list[tuple[tuple[str, str], tuple[str, str], object]] = []
        self._redo: list[tuple[tuple[str, str], tuple[str, str], object]] = []
        self._changing = 0

    @property
    def name(self):
        return self.path.stem

    @property
    def selected(self):
        """The selected object, or with several selected, the reference control (the last one)."""
        return self.selection[-1]

    @selected.setter
    def selected(self, obj):
        self.selection = [obj]

    @property
    def code_path(self):
        return self.path.with_suffix(".py")

    def prepared_code(self):
        """The code as Jedi sees it, with the controls and menu items declared (see assist.py)."""
        controls = [(spec["type"], spec["name"]) for spec in self.design.controls]
        return assist.prepare(self.code.get_source(), self.design.name, controls, menus.names(self.design.menu))

    @property
    def toolbox(self):
        return self.app.toolbox

    @property
    def properties(self):
        """The Properties panel while it's showing this form, else a stand-in that ignores updates."""
        panel = self.app.properties
        return panel if panel.app is self else _DETACHED

    def title(self):
        return f"{self.name}{'*' if self.is_dirty() else ''}"

    def update_title(self):
        self.app.update_title()

    # ----- the design -----

    def object_names(self):
        """The objects in the Properties panel: the form and its controls."""
        return [FORM] + [c["name"] for c in self.design.controls]

    def menu_commands(self):
        """Menu items that can be clicked (not submenus or separators)."""
        return [i["name"] for i in menus.walk(self.design.menu) if i.get("name") and not i.get("items")]

    def code_objects(self):
        """The objects in the Code window's dropdown: the form, its controls and its menu commands."""
        return self.object_names() + self.menu_commands()

    def events_for(self, obj):
        if obj == FORM:
            return FORM_EVENTS
        if obj in self.menu_commands():
            return (Event("click"),)
        spec = self.design.control(obj)
        return REGISTRY[spec["type"]].events if spec else ()

    def props_for(self, obj):
        if obj == MULTIPLE:
            return self._common_props()
        if obj == FORM:
            d = self.design
            return [("name", d.name), ("text", d.text), ("width", d.width), ("height", d.height),
                    ("backcolor", d.backcolor), ("cursor", d.cursor),
                    ("default_button", d.default_button), ("cancel_button", d.cancel_button)]
        spec = self.design.control(obj)
        if spec is None:
            return []
        defaults = REGISTRY[spec["type"]].prop_defaults()
        props = [("name", obj)]
        in_grid = self._grid_of(spec) is not None
        for prop, default in defaults.items():
            if in_grid and prop == "left":  # in a Grid its cell says where it goes
                props += [(key, spec.get(key, value)) for key, value in GRID_CELL.items()]
            elif not (in_grid and prop == "top"):
                props.append((prop, spec.get(prop, default)))
        return props

    def _grid_size(self, spec):
        """(rows, columns) of the Grid a control is in."""
        grid = self._grid_of(spec)
        return len(layout.parse_tracks(grid.get("rows", "*, *"))), len(layout.parse_tracks(grid.get("columns", "*, *")))

    def _check_cell(self, spec, prop, value):
        """A row, column or span typed in the Properties panel must fit in the control's Grid."""
        rows, columns = self._grid_size(spec)
        cell = {key: spec.get(key, default) for key, default in GRID_CELL.items()}
        cell[prop] = value
        fits = {"row": (0, rows - cell["rowspan"]), "column": (0, columns - cell["columnspan"]),
                "rowspan": (1, rows - cell["row"]), "columnspan": (1, columns - cell["column"])}
        low, high = fits[prop]
        if not low <= value <= high:
            grid = self._grid_of(spec)
            raise ValueError(f"{grid['name']} has {rows} row{'s' * (rows != 1)} and {columns} column{'s' * (columns != 1)}, "
                             f"so {prop} can be {low} to {high} here (add more in its rows or columns)")

    def _grid_of(self, spec):
        """The spec of the Grid a control is in, or None."""
        container = self.design.control(spec["container"]) if spec.get("container") else None
        return container if container and container["type"] == "Grid" else None

    @_undoable
    def set_cells(self, changes):
        """Move controls in a Grid to other cells, or change their spans: {name: {"row": 2, ...}}."""
        for name, cell in changes.items():
            spec = self._spec(name)
            spec.update(cell)
            rows, columns = self._grid_size(spec)  # (a group moved together stays inside the Grid)
            fitted = layout.fit_cell(*(spec.get(k, d) for k, d in GRID_CELL.items()), rows, columns)
            spec.update(zip(GRID_CELL, fitted))
            self.surface.refresh_control(name)
        self.properties.update_values()
        self.update_title()

    def _common_props(self):
        """The simple properties every selected control has; a value only where they all agree."""
        specs = [self._spec(n) for n in self.selected_controls()]
        if not specs:
            return []
        props = []
        for prop, default in REGISTRY[specs[0]["type"]].prop_defaults().items():
            if isinstance(default, list) or any(prop not in REGISTRY[s["type"]].prop_defaults() for s in specs):
                continue
            values = {repr(s.get(prop, REGISTRY[s["type"]].prop_defaults()[prop])) for s in specs}
            props.append((prop, specs[0].get(prop, default) if len(values) == 1 else ""))
        return props

    def choices_for(self, obj, prop):
        """The allowed values of a property limited to fixed choices, or None."""
        if obj == FORM:
            if prop in ("default_button", "cancel_button"):
                return ("", *(c["name"] for c in self.design.controls if c["type"] == "Button"))
            return LOOK_CHOICES["cursor"] if prop == "cursor" else None
        if obj == MULTIPLE:
            spec = self._spec(self.selected)
            if isinstance(REGISTRY[spec["type"]].prop_defaults().get(prop), bool):
                return ("True", "False")
            obj = self.selected
        spec = self.design.control(obj)
        return REGISTRY[spec["type"]].choices(prop) if spec else None

    def file_types_for(self, obj, prop):
        """For a property holding a file's path, the files to offer ({label: patterns}), or None."""
        spec = self.design.control(self.selected if obj == MULTIPLE else obj)
        return REGISTRY[spec["type"]].file_props.get(prop) if spec else None

    def chooser_for(self, obj, prop):
        """How the Properties panel's "..." button helps choose a value: "file", "color",
        "font", or None for no button."""
        if prop in ("backcolor", "forecolor"):
            return "color"
        if prop == "font":
            return "font"
        return "file" if obj != FORM and self.file_types_for(obj, prop) else None

    def choose(self, obj, prop):
        """Choose a value with a dialog: a file, color or font. Returns the object's name,
        or None if nothing was chosen."""
        kind = self.chooser_for(obj, prop)
        if kind == "file":
            return self.choose_file(obj, prop)
        current = dict(self.props_for(obj)).get(prop, "")
        if kind == "color":
            chosen = colorchooser.askcolor(color=current or None, title=f"{obj}.{prop}", parent=self.app.root)[1]
        elif kind == "font":
            chosen = dialogs.FontChooser.ask(self.app.root, current, title=f"{obj}.{prop}")
        else:
            return None
        return None if chosen is None else self.set_property(obj, prop, chosen)

    def choose_file(self, obj, prop):
        """Choose the file for a property like an Image's picture. Returns the object's name,
        or None if nothing was chosen."""
        types = self.file_types_for(obj, prop) or {"All files": "*"}
        chosen = filedialog.askopenfilename(parent=self.app.root, title=f"{obj}.{prop}",
                                            initialdir=self.path.parent, filetypes=list(types.items()))
        if not chosen:
            return None
        try:
            path = bring_in(self.path.parent, Path(chosen))
        except OSError as e:
            messagebox.showerror("Choose a file", f"Couldn't copy {chosen}: {e}", parent=self.app.root)
            return None
        return self.set_property(obj, prop, path)

    def _spec(self, name) -> dict:
        spec = self.design.control(name)
        if spec is None:
            raise KeyError(name)
        return spec

    def select(self, obj):
        self.properties.commit_all()  # any edit in progress belongs to what's selected now
        self.properties.clear()  # then the old rows mustn't be compared with the new selection
        self.selection = [obj]
        self.surface.show_selection()
        self.properties.show(obj)

    def select_many(self, names):
        """Select several controls (in one container); the last is the reference control."""
        names = [n for n in dict.fromkeys(names) if self.design.control(n)]
        if not names:
            return self.select(FORM)
        container = self._spec(names[-1]).get("container")
        names = [n for n in names if self._spec(n).get("container") == container]
        if len(names) == 1:
            return self.select(names[0])
        self.properties.commit_all()  # any edit in progress belongs to what's selected now
        self.properties.clear()  # then the old rows mustn't be compared with the new selection
        self.selection = names
        self.surface.show_selection()
        self.properties.show(MULTIPLE)

    def toggle_selected(self, name):
        """Ctrl+click: add a control to the selection, or take it out."""
        current = [n for n in self.selection if n != FORM]
        if name in current:
            current.remove(name)
        elif current and self._spec(current[0]).get("container") != self._spec(name).get("container"):
            current = [name]  # a selection stays within one container
        else:
            current.append(name)
        self.select_many(current)

    def selected_controls(self):
        return [n for n in self.selection if n != FORM and self.design.control(n)]

    @_undoable
    def set_property(self, obj, prop, raw):
        """Apply an edit from the Properties panel. Returns the object's (possibly new) name, or None if invalid."""
        if obj == MULTIPLE:
            for name in self.selected_controls():  # one undo step, as this is all inside set_property
                if self.set_property(name, prop, raw) is None:
                    return None
            self.properties.update_values()
            return MULTIPLE
        current = dict(self.props_for(obj))[prop]
        try:
            value = _convert(raw, type(current))
            choices = self.choices_for(obj, prop)
            if choices and value not in choices:
                raise ValueError(f"{prop} must be one of: {', '.join(choices)}")
            if prop in ("width", "height") and value < GRID:
                raise ValueError(f"{prop} must be at least {GRID}")
            if prop == "name":
                obj = self._rename(obj, value)
            elif obj == FORM:
                if prop == "backcolor":
                    value = appearance.check_color(value)
                setattr(self.design, prop, value)
                self.surface.refresh_form()
            else:
                spec = self._spec(obj)
                if prop in GRID_CELL and self._grid_of(spec) is not None:
                    self._check_cell(spec, prop, value)
                if prop == "tabindex":
                    self._order_tabs(obj, value)  # the others make room
                    value = spec["tabindex"]
                spec[prop] = value
                if prop == "multiline" and not value and "\n" in spec.get("text", ""):
                    spec["text"] = " ".join(spec["text"].splitlines())  # a single line can't hold line breaks
                try:
                    self.surface.refresh_control(obj)
                except ValueError:  # the control refused it (like a backcolor that isn't a color)
                    spec[prop] = current
                    self.surface.refresh_control(obj)
                    raise
                if prop in _TIDIED:  # keep what the control made of it: "auto,250" is saved as "auto, 250"
                    spec[prop] = getattr(self.surface.controls[obj], prop)
                if prop in REGISTRY[spec["type"]].recreate_props:
                    # Rebuild the rows (the text row changes editor) without committing their old values.
                    self.properties.clear()
                    self.properties.show(MULTIPLE if len(self.selection) > 1 else obj)
        except ValueError as e:
            messagebox.showerror("Invalid property value", str(e), parent=self.app.root)
            return None
        self.properties.update_values()  # so the panel never shows (and later commits) a stale value
        self.update_title()
        return obj

    def _rename(self, obj, new):
        if new == obj:
            return obj
        source = self.code.get_source()
        if obj == FORM:
            # The form's files are renamed to match when it's saved.
            if not new.isidentifier() or keyword.iskeyword(new):
                raise ValueError(f"{new!r} is not a valid Python name")
            if new != self.name and (self.path.with_name(f"{new}.form").exists() or self.path.with_name(f"{new}.py").exists()):
                raise ValueError(f"The project already has a form or module named {new!r}")
            self.code.replace_source(codegen.rename_class(source, self.design.name, new))
            self.design.name = new
            return FORM
        check_name(new, [n for n in self.object_names() + menus.names(self.design.menu) if n != obj])
        spec = self._spec(obj)
        spec["name"] = new
        for key in ("default_button", "cancel_button"):
            if getattr(self.design, key) == obj:
                setattr(self.design, key, new)
        for child in self.design.controls:
            if child.get("container") == obj:
                child["container"] = new
        events = [e.name for e in REGISTRY[spec["type"]].events]
        self.code.replace_source(codegen.rename_control(source, obj, new, events))
        self.surface.rename(obj, new)
        self.selected = new
        self.properties.renamed(obj, new)
        self.properties.refresh_objects()
        self.code.refresh_objects()
        return new

    def geometry_changed(self, name, geometry):
        self.set_geometries({name: geometry})

    @_undoable
    def set_geometries(self, geometries):
        """Move and resize controls, as {name: (left, top, width, height)}. A Frame that changes
        size takes the anchored controls inside it along."""
        geometries = dict(geometries)
        for name, geometry in list(geometries.items()):
            spec = self._spec(name)
            if spec["type"] == "Frame":
                grown = (geometry[2] - spec["width"], geometry[3] - spec["height"])
                for inside, moved in self._anchored(name, *grown).items():
                    geometries.setdefault(inside, moved)
        self._apply_geometries(geometries)

    def _apply_geometries(self, geometries):
        for name, geometry in geometries.items():
            spec = self._spec(name)
            in_grid = self._grid_of(spec) is not None
            for key, value in zip(("left", "top", "width", "height"), geometry):
                if key in spec and not (in_grid and key in ("left", "top")):  # (a Timer has no size;
                    spec[key] = value  # in a Grid, its cell decides where it goes)
            self.surface.refresh_control(name)
        self.properties.update_values()
        self.update_title()

    def _anchored(self, container, across, down):
        """Where the anchored controls in a container (a Frame's name, or None for the form) go
        when it grows by across and down: {name: (left, top, width, height)}, Frames' contents too."""
        moves = {}
        if not (across or down):
            return moves
        for spec in self.design.controls:
            if spec.get("container") != container or "width" not in spec:
                continue  # elsewhere, or a Timer
            old = (spec["left"], spec["top"], spec["width"], spec["height"])
            new = layout.follow(old, spec.get("anchor", layout.DEFAULT), across, down)
            if new != old:
                moves[spec["name"]] = new
                if spec["type"] == "Frame":
                    moves.update(self._anchored(spec["name"], new[2] - old[2], new[3] - old[3]))
        return moves

    @_undoable
    def set_form_size(self, width, height):
        """Resize the form; its anchored controls follow, as they will when the program runs."""
        across, down = width - self.design.width, height - self.design.height
        self.design.width, self.design.height = width, height
        self.surface.refresh_form()
        self._apply_geometries(self._anchored(None, across, down))

    @_undoable
    def add_control(self, type_name, left, top, width=None, height=None, container=None):
        name = self._free_name(type_name, set(self.object_names() + menus.names(self.design.menu)))
        spec = REGISTRY[type_name].new_spec(name, left, top, width, height, container)
        grid = self.surface.controls.get(container) if container else None
        if isinstance(grid, Grid):
            spec["row"], spec["column"] = grid.cell_at(left, top)
            if "anchor" in spec:
                spec["anchor"] = "top bottom left right"  # fills its cell, as in WPF
        self.design.controls.append(spec)
        self._order_tabs(last=[spec])
        self.surface.add(spec)
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(spec["name"])
        self.update_title()

    @staticmethod
    def _free_name(type_name, taken):
        n = 1
        while f"{type_name}{n}" in taken:
            n += 1
        return f"{type_name}{n}"

    def add_control_centered(self, type_name):
        width, height = REGISTRY[type_name].default_size
        self.toolbox.reset()
        self.add_control(type_name, snap((self.design.width - width) / 2), snap((self.design.height - height) / 2))

    @_undoable
    def delete_control(self, name):
        """Delete a control, and everything inside it if it's a Frame. Like VB, handlers stay in the code."""
        doomed = {name}
        for spec in self.design.controls:  # containers come before their contents
            if spec.get("container") in doomed:
                doomed.add(spec["name"])
        for spec in reversed(list(self.design.controls)):  # contents first
            if spec["name"] in doomed:
                self.design.controls.remove(spec)
                self.surface.remove(spec["name"])
        for key in ("default_button", "cancel_button"):
            if getattr(self.design, key) in doomed:
                setattr(self.design, key, "")
        self._order_tabs()
        self.properties.update_values()  # so the panel doesn't put back a deleted button
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(FORM)
        self.update_title()

    # ----- tab order -----

    def tab_stops(self):
        """The specs of the controls Tab moves through, in order: by tabindex, then as designed."""
        stops = [s for s in self.design.controls if "tabindex" in REGISTRY[s["type"]].prop_defaults()]
        return sorted(stops, key=lambda s: s.get("tabindex", 0))  # a stable sort: ties stay in design order

    def _order_tabs(self, name=None, index=0, last=()):
        """Number the tab stops 0, 1, 2...: moving name to index, and the specs in last to the end."""
        ordered = self.tab_stops()
        late = [s for s in last if any(s is t for t in ordered)]
        stops = [s for s in ordered if not any(s is t for t in late)] + late
        if name is not None:
            spec = self._spec(name)
            stops.remove(spec)
            stops.insert(max(0, min(int(index), len(stops))), spec)
        for number, spec in enumerate(stops):
            spec["tabindex"] = number
            control = self.surface.controls.get(spec["name"])
            if control is not None:
                control.tabindex = number

    @_undoable
    def set_tab_index(self, name, index):
        """Put a control at a place in the tab order (Format > Tab Order clicks do this)."""
        self._order_tabs(name, index)
        self.properties.update_values()
        self.update_title()

    @_undoable
    def delete_selection(self):
        for name in self.selected_controls():
            if self.design.control(name):  # not already gone with its Frame
                self.delete_control(name)

    # ----- the Format menu (see arrange.py) -----

    def _rects(self):
        controls = self.surface.controls
        return {n: (controls[n].left, controls[n].top, controls[n].width, controls[n].height) for n in self.selected_controls()}

    def _fixed_size(self):
        return {n for n in self.selected_controls() if not self.surface.controls[n].resizable}

    def align(self, edge):
        if len(self.selected_controls()) > 1:
            self.set_geometries(arrange.align(self._rects(), self.selected, edge))

    def align_to_grid(self):
        self.set_geometries(arrange.to_grid(self._rects(), GRID))

    def make_same_size(self, width=True, height=True):
        if len(self.selected_controls()) > 1:
            self.set_geometries(arrange.same_size(self._rects(), self.selected, width, height, self._fixed_size()))

    def space_evenly(self, axis):
        self.set_geometries(arrange.space_evenly(self._rects(), axis))

    def center_in_container(self, axis):
        names = self.selected_controls()
        if not names:
            return
        container = self._spec(names[0]).get("container")
        if container is None:
            size = (self.design.width, self.design.height)
        else:
            inner = self.surface.controls[container].inner
            size = (inner.winfo_width(), inner.winfo_height())
        self.set_geometries(arrange.center(self._rects(), size, axis))

    @_undoable
    def change_order(self, to_front):
        """Bring the selected controls in front of the others in their container, or send them behind."""
        block = self._with_contents(self.selected_controls())
        if not block:
            return
        rest = [s for s in self.design.controls if s not in block]
        container = block[0].get("container")
        if to_front:
            order = rest + block
        else:  # behind its siblings, but still after its container, which must come first
            at = next((i + 1 for i, s in enumerate(rest) if s["name"] == container), 0)
            order = rest[:at] + block + rest[at:]
        self.design.controls[:] = order
        self.surface.rebuild()
        self.update_title()

    def _with_contents(self, names):
        """The named controls with everything inside them, in .form order (containers first)."""
        block, inside = [], set(names)
        for spec in self.design.controls:
            if spec["name"] in inside or spec.get("container") in inside:
                block.append(spec)
                inside.add(spec["name"])
        return block

    # ----- copy and paste -----

    def copy_selection(self):
        """The selected controls and their contents, ready for paste(); None if nothing's selected."""
        return copy.deepcopy(self._with_contents(self.selected_controls())) or None

    def copy_handlers(self, specs):
        """The event handlers of copied controls, for paste(): [(control, method name, its code)]."""
        source = self.code.get_source()
        found = []
        for spec in specs:
            for event in REGISTRY[spec["type"]].events:
                method = f"{spec['name']}_{event.name}"
                text = codegen.method_text(source, method)
                if text is not None:
                    found.append((spec["name"], method, text))
        return found

    @_undoable
    def paste(self, specs, handlers=()):
        """Add copies of controls: into the selected Frame if one is selected, else onto the form.
        Names are kept where they're free; copies that would land on top of others are offset.
        handlers (from copy_handlers) come too, renamed to match (Edit > Paste with Code);
        one whose name the code already has is left out (and named in handlers_left_out).
        Returns the names of the controls added."""
        selected = self.selected_controls()
        target = selected[0] if len(selected) == 1 and self.surface.controls[selected[0]].is_container else None
        copied = {spec["name"] for spec in specs}
        outermost = [spec for spec in specs if spec.get("container") not in copied]
        taken = set(self.object_names() + menus.names(self.design.menu))
        renames = {}
        for spec in specs:
            try:
                check_name(spec["name"], taken)
                renames[spec["name"]] = spec["name"]
            except ValueError:
                renames[spec["name"]] = self._free_name(spec["type"], taken)
            taken.add(renames[spec["name"]])
        occupied = {(c["left"], c["top"]) for c in self.design.controls if c.get("container") == target}
        offset = 0
        while any((s["left"] + offset, s["top"] + offset) in occupied for s in outermost):
            offset += 2 * GRID
        added = []
        for spec in specs:
            new = copy.deepcopy(spec)
            new["name"] = renames[spec["name"]]
            if spec.get("container") not in copied:  # outermost: goes into the target
                new.pop("container", None)
                if target:
                    new["container"] = target
                new["left"] += offset
                new["top"] += offset
            else:
                new["container"] = renames[spec["container"]]
            self.design.controls.append(new)
            added.append(new)
        self._order_tabs(last=added)
        for new in added:
            self.surface.add(new)
        self.handlers_left_out = self._paste_handlers(specs, handlers, renames) if handlers else []
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select_many([renames[s["name"]] for s in outermost])
        self.update_title()
        return [s["name"] for s in added]

    def _paste_handlers(self, specs, handlers, renames):
        source = self.code.get_source()
        events = {spec["name"]: [e.name for e in REGISTRY[spec["type"]].events] for spec in specs}
        left_out = []
        for control, method, text in handlers:
            if control not in renames:
                continue
            for old, new in renames.items():  # its name, and self.Other for other controls pasted with it
                if old != new:
                    text = codegen.rename_control(text, old, new, events[old])
            name = renames[control] + method[len(control):]
            if codegen.find_method(source, name) is not None:
                left_out.append(name)
                continue
            try:
                source = codegen.add_method_text(source, self.design.name, text)
            except codegen.CodeGenError:
                left_out.append(name)
        self.code.replace_source(source)
        return left_out

    def goto_handler(self, obj, event_name):
        """Show the handler for obj's event in the code window, creating it if needed."""
        event = next(e for e in self.events_for(obj) if e.name == event_name)
        method = f"{obj}_{event.name}"
        line = codegen.find_method(self.code.get_source(), method)
        if line is None:
            try:
                edit = codegen.add_method(self.code.get_source(), self.design.name, method, event.params)
            except codegen.CodeGenError as e:
                messagebox.showerror("Code", str(e), parent=self.app.root)
                return
            self.code.apply_edit(edit)
            line = edit.method_line
        self.show_code()
        self.code.show_method(obj, event.name, line)

    @_undoable
    def set_menu(self, items, renames=()):
        """Replace the form's menu (from the Menu Editor), renaming handlers of renamed items."""
        source = self.code.get_source()
        for old, new in renames:
            source = codegen.rename_control(source, old, new, ["click"])
        self.code.replace_source(source)
        self.design.menu = items
        self.surface.refresh_menu()
        self.code.refresh_objects()
        self.update_title()

    # ----- undo -----

    def _state(self):
        return formfile.dumps(self.design), self.code.get_source()

    @contextlib.contextmanager
    def _change(self, merge=None):
        """Record what the enclosed code changes. Repeated changes with the same merge
        key (like holding an arrow key) become one undo step."""
        self._changing += 1
        before = self._state() if self._changing == 1 else None
        try:
            yield
        finally:
            self._changing -= 1
        if before is None:
            return
        after = self._state()
        if after == before:
            return  # nothing changed, e.g. a property edit that was refused
        if merge is not None and self._undo and self._undo[-1][2] == merge and not self._redo:
            before = self._undo.pop()[0]
        self._undo.append((before, after, merge))
        del self._undo[:-UNDO_LIMIT]
        self._redo.clear()

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo(self):
        if self._undo:
            before, after, merge = self._undo.pop()
            self._redo.append((before, after, merge))
            self._restore(before, after)

    def redo(self):
        if self._redo:
            before, after, merge = self._redo.pop()
            self._undo.append((before, after, None))  # a redone step doesn't merge with what follows
            self._restore(after, before)

    def _restore(self, target, current):
        """Go back (or forward) to target. The code goes back too, unless it's been edited
        since the change, which would lose that work; then only the design does."""
        design, source = target
        if source != current[1] and self.code.get_source() == current[1]:
            self.code.replace_source(source)
        selection = self.selection
        self.properties.clear()  # don't commit whatever the panel showed before
        self.design = formfile.loads(design)
        self.surface.rebuild()
        self.code.refresh_objects()
        self.properties.refresh_objects()
        if selection == [FORM]:
            self.select(FORM)
        else:
            self.select_many(selection)
        self.update_title()

    def nudge(self, dx=0, dy=0, dwidth=0, dheight=0):
        """Move or resize the selected controls from the keyboard (in a Grid: by cells)."""
        selected = self.selected_controls()
        if selected and all(self._grid_of(self._spec(n)) for n in selected):
            def step(n):
                return (n > 0) - (n < 0)

            changes = {}
            for name in selected:
                spec = self._spec(name)
                rows, columns = self._grid_size(spec)
                row, column = spec.get("row", 0), spec.get("column", 0)
                if dwidth or dheight:  # spans stop at the Grid's edge
                    cell = {"rowspan": max(1, min(rows - row, spec.get("rowspan", 1) + step(dheight))),
                            "columnspan": max(1, min(columns - column, spec.get("columnspan", 1) + step(dwidth)))}
                else:  # and so do moves
                    cell = {"row": max(0, min(rows - spec.get("rowspan", 1), row + step(dy))),
                            "column": max(0, min(columns - spec.get("columnspan", 1), column + step(dx)))}
                if any(spec.get(k, GRID_CELL[k]) != v for k, v in cell.items()):
                    changes[name] = cell
            if changes:
                with self._change(merge=("cells", tuple(self.selection), bool(dwidth or dheight))):
                    self.set_cells(changes)
            return
        geometries = {}
        for name in self.selected_controls():
            control = self.surface.controls[name]
            if (dwidth or dheight) and not control.resizable:
                continue
            geometries[name] = (control.left + dx, control.top + dy,
                                max(GRID, control.width + dwidth), max(GRID, control.height + dheight))
        if geometries:
            with self._change(merge=("nudge", tuple(self.selection), bool(dwidth or dheight))):
                self.set_geometries(geometries)

    def show_code(self):
        self.code.refresh_objects()
        self.app.documents.select(self.frame)
        self.frame.select(self.code)

    def show_design(self):
        self.app.documents.select(self.frame)
        self.frame.select(self.surface)

    # ----- files -----

    def is_dirty(self):
        return (formfile.dumps(self.design), self.code.get_source()) != self._saved

    def save(self):
        """Save the form, renaming its files if the form was renamed. Returns False on failure."""
        self.properties.commit_all()
        source = self.code.get_source()
        old = self.path
        path = old.with_name(f"{self.design.name}.form")
        try:
            formfile.save(self.design, path)
            path.with_suffix(".py").write_text(source, encoding="utf-8")
            if path != old:
                old.unlink()
                old.with_suffix(".py").unlink(missing_ok=True)
        except OSError as e:
            messagebox.showerror("Save", str(e), parent=self.app.root)
            return False
        self.path = path
        self._saved = (formfile.dumps(self.design), source)
        if path != old:
            self.app.form_renamed(old.stem, path.stem)
        return True


class ModuleEditor:
    """A plain Python module in the project."""

    def __init__(self, app, path):
        self.app = app
        self.path = path
        self.frame = CodeView(app.documents, self, objects=False)
        self._saved = path.read_text(encoding="utf-8")
        self.frame.set_source(self._saved)

    @property
    def name(self):
        return self.path.stem

    @property
    def code(self):
        return self.frame

    @property
    def code_path(self):
        return self.path

    def prepared_code(self):
        return assist.prepare(self.code.get_source())

    def title(self):
        return f"{self.path.name}{'*' if self.is_dirty() else ''}"

    def update_title(self):
        self.app.update_title()

    def code_objects(self):
        return []

    def events_for(self, obj):
        return ()

    def is_dirty(self):
        return self.code.get_source() != self._saved

    def save(self):
        source = self.code.get_source()
        try:
            self.path.write_text(source, encoding="utf-8")
        except OSError as e:
            messagebox.showerror("Save", str(e), parent=self.app.root)
            return False
        self._saved = source
        return True


class ViewerEditor(ModuleEditor):
    """Code from outside the project, like a library's, opened by Go to Definition: read-only."""

    read_only = True

    def __init__(self, app, path):
        self.app = app
        self.path = path
        self.frame = CodeView(app.documents, self, objects=False)
        self._saved = path.read_text(encoding="utf-8", errors="replace")
        self.frame.set_source(self._saved)
        self.frame.text.configure(state="disabled")

    @property
    def name(self):
        return self.path.name

    def title(self):
        return f"{self.path.name} (read-only)"

    def is_dirty(self):
        return False

    def save(self):
        return True


class FileEditor(ModuleEditor):
    """Another file of the project, like a README or some data, edited as plain text: no
    colors, completion, checking or breakpoints, as it isn't Python. (Python in a folder of
    the project, like a package's, is edited as code.)"""

    def __init__(self, app, path):
        self.app = app
        self.path = path
        self.plain = path.suffix.lower() not in (".py", ".pyw")
        self.frame = CodeView(app.documents, self, objects=False, python=not self.plain)
        self._saved = path.read_text(encoding="utf-8")
        self.frame.set_source(self._saved)

    @property
    def name(self):
        """Its place in the project, like "docs/README.md" (so never a module's name)."""
        try:
            return self.path.relative_to(self.app.project.folder).as_posix()
        except (AttributeError, ValueError):
            return self.path.name


class _DetachedPanel:
    """Stands in for the Properties panel while it shows another form."""

    def __getattr__(self, name):
        return lambda *args, **kwargs: None


_DETACHED = _DetachedPanel()


def _convert(raw, kind):
    if kind is list:
        return [line for line in raw.splitlines() if line.strip()]
    if kind is bool:
        if raw not in ("True", "False"):
            raise ValueError("Choose True or False")
        return raw == "True"
    if kind is int:
        try:
            return int(raw)
        except ValueError:
            raise ValueError(f"{raw!r} is not a whole number") from None
    return raw
