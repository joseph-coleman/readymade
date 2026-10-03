"""Open documents in the IDE: a FormEditor per open form, a ModuleEditor per open module.

Each editor owns one tab in the IDE's document notebook. A form's tab holds its
Design and Code views. The shared panels (Toolbox, Properties) work on the form
whose tab is showing.
"""

from __future__ import annotations

import keyword
from tkinter import messagebox, ttk

from pybasic import codegen, formfile
from pybasic.controls import REGISTRY
from pybasic.form import FORM, FORM_EVENTS, check_name
from pybasic.ide.codeview import CodeView
from pybasic.ide.designer import GRID, DesignSurface, snap


class FormEditor:
    def __init__(self, app, path):
        self.app = app
        self.path = path
        self.design = formfile.load(path)
        code_path = path.with_suffix(".py")
        saved_source = code_path.read_text(encoding="utf-8") if code_path.exists() else None
        self.selected = FORM
        self.frame = ttk.Notebook(app.documents)
        self.surface = DesignSurface(self.frame, self)
        self.code = CodeView(self.frame, self)
        self.frame.add(self.surface, text="Design")
        self.frame.add(self.code, text="Code")
        self.surface.rebuild()
        self.code.set_source(saved_source if saved_source is not None else codegen.new_module(self.design.name))
        self.code.refresh_objects()
        self._saved = (formfile.dumps(self.design), saved_source)

    @property
    def name(self):
        return self.path.stem

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
        return [FORM] + [c["name"] for c in self.design.controls]

    def events_for(self, obj):
        if obj == FORM:
            return FORM_EVENTS
        spec = self.design.control(obj)
        return REGISTRY[spec["type"]].events if spec else ()

    def props_for(self, obj):
        if obj == FORM:
            d = self.design
            return [("name", d.name), ("text", d.text), ("width", d.width), ("height", d.height)]
        spec = self.design.control(obj)
        if spec is None:
            return []
        defaults = REGISTRY[spec["type"]].prop_defaults()
        return [("name", obj)] + [(prop, spec.get(prop, default)) for prop, default in defaults.items()]

    def choices_for(self, obj, prop):
        """The allowed values of a property limited to fixed choices, or None."""
        spec = self.design.control(obj)
        return REGISTRY[spec["type"]].prop_choices.get(prop) if spec else None

    def _spec(self, name) -> dict:
        spec = self.design.control(name)
        if spec is None:
            raise KeyError(name)
        return spec

    def select(self, obj):
        self.selected = obj
        self.surface.show_selection(obj)
        self.properties.show(obj)

    def set_property(self, obj, prop, raw):
        """Apply an edit from the Properties panel. Returns the object's (possibly new) name, or None if invalid."""
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
                    self.properties.show(obj)
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
        check_name(new, [n for n in self.object_names() if n != obj])
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
        spec = self._spec(name)
        for key, value in zip(("left", "top", "width", "height"), geometry):
            if key in spec:  # a Timer has no size
                spec[key] = value
        self.properties.update_values()
        self.update_title()

    def set_form_size(self, width, height):
        self.design.width, self.design.height = width, height
        self.surface.refresh_form()
        self.properties.update_values()
        self.update_title()

    def add_control(self, type_name, left, top, width=None, height=None, container=None):
        names = set(self.object_names())
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

    def object_names(self):
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
