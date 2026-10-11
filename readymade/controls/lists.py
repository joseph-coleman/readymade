"""The ComboBox and ListBox controls, with the list methods they share."""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import Aligned, Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip


class _ListItems:
    """VB-style list methods for controls with an `items` list."""

    @property
    def items(self) -> list[str]:
        """The list's items, as strings. Assigning a list replaces them all."""
        raise NotImplementedError

    @items.setter
    def items(self, values):
        raise NotImplementedError

    @property
    def list_count(self):
        """How many items there are."""
        return len(self.items)

    def add_item(self, item, index=None):
        """Add an item at the end, or at position index (counting from 0)."""
        items = self.items
        items.insert(len(items) if index is None else index, str(item))
        self.items = items

    def remove_item(self, index):
        """Remove the item at position index (counting from 0)."""
        items = self.items
        del items[index]
        self.items = items

    def clear(self):
        """Remove every item."""
        self.items = []


@register
class ComboBox(_ListItems, BackColor, ForeColor, Font, Aligned, TabStop, Cursor, Tooltip, Anchored, Control):
    """A drop-down list. With editable False the user can only pick from the list."""

    type_name = "ComboBox"
    default_size = (120, 24)
    default_event = "change"
    events = (Event("change"), Event("click", policy="latest"), Event("keypress", ("key",)), *_FOCUS_EVENTS)
    extra_props = {"text": "", "items": [], "editable": True}

    def create_widget(self, parent):
        self._var = tk.StringVar(parent)
        self._editable = True
        self._enabled = True
        self._combo = ttk.Combobox(parent, textvariable=self._var)
        return self._combo

    @property
    def text(self):
        """The text in the box: the chosen item, or what was typed if it's editable."""
        return self._var.get()

    @text.setter
    def text(self, value):
        self._var.set(str(value))

    @property
    def items(self):
        """The list's items, as strings. Assigning a list replaces them all."""
        return list(self._combo.tk.splitlist(self._combo.cget("values")))

    @items.setter
    def items(self, values):
        self.widget["values"] = [str(v) for v in values]

    @property
    def list_index(self):
        """The index of the chosen item, or -1."""
        return self._combo.current()

    @list_index.setter
    def list_index(self, index):
        if index < 0:
            self.text = ""
        else:
            self._combo.current(index)

    @property
    def editable(self):
        """Whether the user can type their own text (True) or only choose from the list (False)."""
        return self._editable

    @editable.setter
    def editable(self, value):
        self._editable = bool(value)
        self._update_state()

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self._update_state()

    def _update_state(self):
        if not self._enabled:
            self.widget["state"] = "disabled"
        else:
            self.widget["state"] = "normal" if self._editable else "readonly"

    def _paint(self):
        # A ttk widget takes its colors from a style, so each colored ComboBox gets its own.
        if not self._ready:
            return
        bg, fg = self._background(), self._foreground()
        if bg or fg:
            name = f"readymade{id(self)}.TCombobox"
            style = ttk.Style(self._combo)
            style.configure(name, **{k: v for k, v in (("fieldbackground", bg), ("foreground", fg)) if v})
            style.map(name, **{k: [("readonly", v)] for k, v in (("fieldbackground", bg), ("foreground", fg)) if v})
            self._combo["style"] = name
        else:
            # In the designer, the preview style: it stays light in a dark IDE, as the program will be.
            self._combo["style"] = "Preview.TCombobox" if self.design else "TCombobox"
        self._list_option("background", bg)
        self._list_option("foreground", fg)

    def _apply_font(self):
        super()._apply_font()
        if self._ready:
            self._list_option("font", self._combo.cget("font") if self._font else None)

    def _align(self, alignment, valignment):
        self._combo["justify"] = alignment

    def _list_option(self, option, value):
        """Set an option of the drop-down list (a Tk widget readymade doesn't otherwise see)."""
        call = self._combo.tk.call
        path = call("ttk::combobox::PopdownWindow", self._combo) + ".f.l"
        key = (path, option)
        if key not in self._originals:
            self._originals[key] = call(path, "cget", f"-{option}")
        call(path, "configure", f"-{option}", self._originals[key] if value is None else value)

    def bind_event(self, event, handler):
        if event == "change":
            self._var.trace_add("write", lambda *_: handler())
        elif event == "click":
            self.widget.bind("<<ComboboxSelected>>", lambda e: handler(), add="+")
        else:
            super().bind_event(event, handler)


@register
class ListBox(_ListItems, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """A list to choose from. click runs when the choice changes; list_index and text tell
    which item is chosen."""

    type_name = "ListBox"
    default_size = (120, 96)
    events = (Event("click", policy="latest"), Event("dblclick"), *_FOCUS_EVENTS)
    extra_props = {"items": []}

    def create_widget(self, parent):
        # exportselection=False keeps the selection when text is selected elsewhere.
        self._list = tk.Listbox(parent, exportselection=False, activestyle="none")
        return self._list

    @property
    def items(self):
        """The list's items, as strings. Assigning a list replaces them all."""
        return list(self._list.get(0, tk.END))

    @items.setter
    def items(self, values):
        self._list.delete(0, tk.END)
        self._list.insert(tk.END, *[str(v) for v in values])

    @property
    def list_index(self):
        """The index of the selected item, or -1."""
        selection = self._list.curselection()
        return selection[0] if selection else -1

    @list_index.setter
    def list_index(self, index):
        self._list.selection_clear(0, tk.END)
        if index >= 0:
            self._list.selection_set(index)
            self._list.see(index)

    @property
    def text(self):
        """The selected item's text, or ""."""
        index = self.list_index
        return self._list.get(index) if index >= 0 else ""

    def bind_event(self, event, handler):
        if event == "click":
            self.widget.bind("<<ListboxSelect>>", lambda e: handler(), add="+")
        else:
            super().bind_event(event, handler)


# Which point of a text is at (x, y), in Pillow's terms.
