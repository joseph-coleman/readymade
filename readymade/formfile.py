"""Reading and writing .form files, the declarative half of a form.

A .form file is pretty-printed JSON so that design changes diff cleanly in git.
The form's code lives beside it in a .py file with the same name.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from readymade.names import check_python_name

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
    backcolor: str = ""  # "" is the usual color
    cursor: str = "default"
    default_button: str = ""  # the Button that Enter presses
    cancel_button: str = ""  # the Button that Esc presses
    controls: list[dict] = field(default_factory=list)
    menu: list[dict] = field(default_factory=list)  # see readymade.menus

    def control(self, name):
        return next((c for c in self.controls if c["name"] == name), None)


def _ordered(spec):
    # Identity and geometry first, everything else alphabetical, so diffs stay stable.
    out = {k: spec[k] for k in _HEAD_KEYS if k in spec}
    out.update(sorted((k, v) for k, v in spec.items() if k not in _HEAD_KEYS))
    return out


def _ordered_menu_item(item):
    head = ("name", "text", "shortcut", "checked", "enabled")
    out = {k: item[k] for k in head if k in item}
    out.update(sorted((k, v) for k, v in item.items() if k not in (*head, "items")))
    if item.get("items"):
        out["items"] = [_ordered_menu_item(child) for child in item["items"]]
    return out


def _check_menu(items, names, source):
    if not isinstance(items, list):
        raise FormFileError(f"{source}: a menu must be a list of items")
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            raise FormFileError(f"{source}: every menu item needs a 'text'")
        if item["text"] == "-":
            continue
        name = item.get("name")
        try:
            check_python_name(name)
        except ValueError:
            raise FormFileError(f"{source}: menu item {item['text']!r} needs a 'name' that's a Python name") from None
        if name in names:
            raise FormFileError(f"{source}: more than one control or menu item is named {name!r}")
        names.add(name)
        _check_menu(item.get("items", []), names, source)


def dumps(design):
    data = {
        "readymade_form": FORMAT_VERSION,
        "name": design.name,
        "text": design.text,
        "width": design.width,
        "height": design.height,
    }
    # Only forms that change these mention them, so other forms' files don't change.
    if design.backcolor:
        data["backcolor"] = design.backcolor
    if design.cursor != "default":
        data["cursor"] = design.cursor
    for key in ("default_button", "cancel_button"):
        if getattr(design, key):
            data[key] = getattr(design, key)
    data["controls"] = [_ordered(c) for c in design.controls]
    if design.menu:  # only forms with a menu mention it, so other forms' files don't change
        data["menu"] = [_ordered_menu_item(item) for item in design.menu]
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


def loads(text, source="<string>"):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise FormFileError(f"{source}: not valid JSON ({e})") from None
    if not isinstance(data, dict) or data.get("readymade_form") != FORMAT_VERSION:
        raise FormFileError(f"{source}: not a version {FORMAT_VERSION} readymade form")
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
    menu = data.get("menu", [])
    _check_menu(menu, names, source)
    return FormDesign(
        name=data.get("name", "Form1"),
        text=data.get("text", ""),
        width=int(data.get("width", 400)),
        height=int(data.get("height", 300)),
        backcolor=data.get("backcolor", ""),
        cursor=data.get("cursor", "default"),
        default_button=data.get("default_button", ""),
        cancel_button=data.get("cancel_button", ""),
        controls=controls,
        menu=menu,
    )


def load(path):
    path = Path(path)
    return loads(path.read_text(encoding="utf-8"), str(path))


def save(design, path):
    Path(path).write_text(dumps(design), encoding="utf-8")
