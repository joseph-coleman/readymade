"""Open documents in the IDE: a FormEditor per open form, a ModuleEditor per open module.

Each editor owns one tab in the IDE's document notebook. A form's tab holds its
Design and Code views. The shared panels (Toolbox, Properties) work on the form
whose tab is showing.
"""

from __future__ import annotations

import contextlib
import functools
import keyword
from tkinter import messagebox, ttk

from pybasic import codegen, formfile, menus
from pybasic.controls import REGISTRY, Event
from pybasic.form import FORM, FORM_EVENTS, check_name
from pybasic.ide import arrange
from pybasic.ide.codeview import CodeView
from pybasic.ide.designer import GRID, DesignSurface, snap

UNDO_LIMIT = 200
MULTIPLE = "(multiple controls)"  # the Properties panel's object while several controls are selected


def _undoable(method):
    """Record a designer change so it can be undone. Changes made inside it count as one."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self._change():
            return method(self, *args, **kwargs)
    return wrapper


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
            return [("name", d.name), ("text", d.text), ("width", d.width), ("height", d.height)]
        spec = self.design.control(obj)
        if spec is None:
            return []
        defaults = REGISTRY[spec["type"]].prop_defaults()
        return [("name", obj)] + [(prop, spec.get(prop, default)) for prop, default in defaults.items()]

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
        if obj == MULTIPLE:
            spec = self._spec(self.selected)
            if isinstance(REGISTRY[spec["type"]].prop_defaults().get(prop), bool):
                return ("True", "False")
            obj = self.selected
        spec = self.design.control(obj)
        return REGISTRY[spec["type"]].prop_choices.get(prop) if spec else None

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
                setattr(self.design, prop, value)
                self.surface.refresh_form()
            else:
                spec = self._spec(obj)
                spec[prop] = value
                if prop == "multiline" and not value and "\n" in spec.get("text", ""):
                    spec["text"] = " ".join(spec["text"].splitlines())  # a single line can't hold line breaks
                self.surface.refresh_control(obj)
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
        for child in self.design.controls:
            if child.get("container") == obj:
                child["container"] = new
        events = [e.name for e in REGISTRY[spec["type"]].events]
        self.code.replace_source(codegen.rename_control(source, obj, new, events))
        self.surface.rename(obj, new)
        self.selected = new
        self.properties.refresh_objects()
        self.code.refresh_objects()
        return new

    def geometry_changed(self, name, geometry):
        self.set_geometries({name: geometry})

    @_undoable
    def set_geometries(self, geometries):
        """Move and resize controls, as {name: (left, top, width, height)}."""
        for name, geometry in geometries.items():
            spec = self._spec(name)
            for key, value in zip(("left", "top", "width", "height"), geometry):
                if key in spec:  # a Timer has no size
                    spec[key] = value
            self.surface.refresh_control(name)
        self.properties.update_values()
        self.update_title()

    @_undoable
    def set_form_size(self, width, height):
        self.design.width, self.design.height = width, height
        self.surface.refresh_form()
        self.properties.update_values()
        self.update_title()

    @_undoable
    def add_control(self, type_name, left, top, width=None, height=None, container=None):
        names = set(self.object_names() + menus.names(self.design.menu))
        n = 1
        while f"{type_name}{n}" in names:
            n += 1
        spec = REGISTRY[type_name].new_spec(f"{type_name}{n}", left, top, width, height, container)
        self.design.controls.append(spec)
        self.surface.add(spec)
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(spec["name"])
        self.update_title()

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
        self.properties.refresh_objects()
        self.code.refresh_objects()
        self.select(FORM)
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
        chosen = set(self.selected_controls())
        if not chosen:
            return
        block = []  # the chosen controls, with everything inside them
        for spec in self.design.controls:
            if spec["name"] in chosen or spec.get("container") in {s["name"] for s in block}:
                block.append(spec)
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
        """Move or resize the selected controls from the keyboard."""
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
