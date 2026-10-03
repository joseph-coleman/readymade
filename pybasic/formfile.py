"""Reading and writing .form files, the declarative half of a form.

A .form file is pretty-printed JSON so that design changes diff cleanly in git.
The form's code lives beside it in a .py file with the same name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

FORMAT_VERSION = 1
_HEAD_KEYS = ("type", "name", "container", "left", "top", "width", "height")


class FormFileError(Exception):
    pass


@dataclass
class FormDesign:
    name: str = "Form1"
    text: str = "Form1"
    width: int = 400
    height: int = 300
    controls: list[dict] = field(default_factory=list)

    def control(self, name):
        return next((c for c in self.controls if c["name"] == name), None)


def _ordered(spec):
    # Identity and geometry first, everything else alphabetical, so diffs stay stable.
    out = {k: spec[k] for k in _HEAD_KEYS if k in spec}
    out.update(sorted((k, v) for k, v in spec.items() if k not in _HEAD_KEYS))
    return out


def dumps(design):
    data = {
        "pybasic_form": FORMAT_VERSION,
        "name": design.name,
        "text": design.text,
        "width": design.width,
        "height": design.height,
        "controls": [_ordered(c) for c in design.controls],
    }
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def loads(text, source="<string>"):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FormFileError(f"{source}: not valid JSON ({e})") from None
    if not isinstance(data, dict) or data.get("pybasic_form") != FORMAT_VERSION:
        raise FormFileError(f"{source}: not a version {FORMAT_VERSION} pybasic form")
    controls = data.get("controls", [])
    names = set()
    for i, spec in enumerate(controls):
        if not isinstance(spec, dict) or not isinstance(spec.get("type"), str) or not isinstance(spec.get("name"), str):
            raise FormFileError(f"{source}: control #{i + 1} needs a 'type' and a 'name'")
        name = spec["name"]
        if name in names:
            raise FormFileError(f"{source}: more than one control is named {name!r}")
        for key in ("left", "top", "width", "height"):
            # Some controls, like Timer, have no size.
            if not isinstance(spec.get(key), int) and (key in ("left", "top") or key in spec):
                raise FormFileError(f"{source}: control {name!r} needs an integer {key!r}")
        # A container must come before the controls inside it.
        if "container" in spec and spec["container"] not in names:
            raise FormFileError(f"{source}: control {name!r} is in {spec['container']!r}, which isn't defined before it")
        names.add(name)
    return FormDesign(
        name=data.get("name", "Form1"),
        text=data.get("text", ""),
        width=int(data.get("width", 400)),
        height=int(data.get("height", 300)),
        controls=controls,
    )


def load(path):
    path = Path(path)
    return loads(path.read_text(encoding="utf-8"), str(path))


def save(design, path):
    Path(path).write_text(dumps(design), encoding="utf-8")
