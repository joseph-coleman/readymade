"""Default form instances, as in VB: `forms.Settings.show()`.

forms.Name is the shared instance of the form class Name (from Name.py), created
the first time it's used. Closing a form destroys its window but keeps the
object, so attributes like a dialog's result can still be read afterwards, and
showing it again reloads it. For more than one instance, create the class
directly: `from Settings import Settings; Settings().show()`.
"""

from __future__ import annotations

import importlib

_instances = {}


def __getattr__(name):
    if name.startswith("__"):
        raise AttributeError(name)
    if name not in _instances:
        _instances[name] = _form_class(name)()
    return _instances[name]


def register(name, form):
    """Make form the default instance for name, e.g. the startup form."""
    _instances[name] = form


def loaded():
    """The default instances that exist so far, by name."""
    return dict(_instances)


def reset():
    _instances.clear()


def _form_class(name):
    from pybasic.form import Form

    try:
        module = importlib.import_module(name)
    except ModuleNotFoundError as e:
        if e.name == name:
            raise AttributeError(f"There's no form named {name!r}: {name}.py wasn't found") from None
        raise
    cls = getattr(module, name, None)
    if not (isinstance(cls, type) and issubclass(cls, Form)):
        raise AttributeError(f"{name}.py has no class {name}(Form)")
    return cls
