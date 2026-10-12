"""VB's Menu Editor: build a form's menu as a tree of items.

Changes are made on a copy and applied with OK, which also renames the click
handlers of renamed items.
"""

from __future__ import annotations

import copy
import re
import tkinter as tk
from tkinter import messagebox, ttk

from readymade import menus
from readymade.form import check_name
from readymade.ide.dialog import Dialog


class MenuEditor(Dialog):
    def __init__(self, app, editor):
        super().__init__(app, f"Menu Editor - {editor.design.name}", resizable=True, padding=8)
        self.editor = editor
        self.items = copy.deepcopy(editor.design.menu)
        self._original = {id(i): i["name"] for i in menus.walk(self.items) if i.get("name")}
        self._auto_named = set()  # ids of items whose name still follows their text
        self._by_iid = {}
        self._loading = False

        body = self.body
        self.tree = ttk.Treeview(body, columns=("shortcut",), show="tree", selectmode="browse", height=14)
        self.tree.column("#0", width=220)
        self.tree.column("shortcut", width=90)
        self.tree.grid(row=0, column=0, rowspan=2, sticky="nsew")
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_fields())
        body.columnconfigure(0, weight=1)
        body.rowconfigure(1, weight=1)

        fields = ttk.Frame(body, padding=(8, 0, 0, 0))
        fields.grid(row=0, column=1, sticky="new")
        self.text_var, self.name_var = tk.StringVar(self), tk.StringVar(self)
        self.checked_var, self.enabled_var = tk.BooleanVar(self), tk.BooleanVar(self)
        self.fields = []
        for row, (label, var) in enumerate((("Text", self.text_var), ("Name", self.name_var))):
            ttk.Label(fields, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(fields, textvariable=var, width=30)
            entry.grid(row=row, column=1, sticky="ew", pady=2)
            self.fields.append(entry)
        self.text_entry = self.fields[0]

        # The shortcut: Tk binds modifiers plus a key, so that's how it's chosen.
        ttk.Label(fields, text="Shortcut").grid(row=2, column=0, sticky="w", pady=2)
        shortcut = ttk.Frame(fields)
        shortcut.grid(row=2, column=1, sticky="w", pady=2)
        self.modifier_vars = {m: tk.BooleanVar(self) for m in menus.MODIFIERS}
        for modifier, var in self.modifier_vars.items():
            box = ttk.Checkbutton(shortcut, text=menus.modifier_label(modifier), variable=var)
            box.pack(side=tk.LEFT)
            self.fields.append(box)
        self.key_var = tk.StringVar(self)
        key = ttk.Combobox(shortcut, textvariable=self.key_var, values=("", *menus.KEYS), width=7)
        key.pack(side=tk.LEFT, padx=(4, 0))
        self.fields.append(key)
        self.shortcut_error = ttk.Label(fields, foreground="#b00020", wraplength=260)
        self.shortcut_error.grid(row=3, column=1, sticky="w")

        for row, (label, var) in enumerate((("Checked", self.checked_var), ("Enabled", self.enabled_var)), start=4):
            box = ttk.Checkbutton(fields, text=label, variable=var)
            box.grid(row=row, column=1, sticky="w")
            self.fields.append(box)
        ttk.Label(fields, text="Use & before the access key: &File", style="Note.TLabel").grid(row=6, column=0, columnspan=2, sticky="w", pady=(6, 0))
        for var in (self.text_var, self.name_var, self.key_var, *self.modifier_vars.values(), self.checked_var, self.enabled_var):
            var.trace_add("write", lambda *_, v=var: self._field_changed(v))

        buttons = ttk.Frame(body, padding=(8, 8, 0, 0))
        buttons.grid(row=1, column=1, sticky="nw")
        for label, command in (
            ("Add", self.add), ("Add Inside", self.add_inside), ("Add Separator", self.add_separator),
            ("Delete", self.delete), ("Move Up", lambda: self.move(-1)), ("Move Down", lambda: self.move(1)),
            ("Indent →", self.indent), ("← Outdent", self.outdent),
        ):
            ttk.Button(buttons, text=label, command=command, width=14).pack(fill=tk.X, pady=1)

        self.add_buttons(enter=False)

        self._refresh(self.items[0] if self.items else None)
        self.grab_set()

    # ----- the tree -----

    def _refresh(self, select=None):
        self.tree.delete(*self.tree.get_children())
        self._by_iid = {}

        def add(parent, items):
            for item in items:
                iid = str(id(item))
                self._by_iid[iid] = item
                self.tree.insert(parent, tk.END, iid=iid, open=True)
                self._show(item)
                add(iid, item.get("items", []))

        add("", self.items)
        if select is not None:
            self.tree.selection_set(str(id(select)))
            self.tree.see(str(id(select)))
        self._load_fields()

    def _show(self, item):
        label = "─" * 12 if item.get("text") == menus.SEPARATOR else menus.parse_text(item.get("text", ""))[0]
        self.tree.item(str(id(item)), text=label, values=(item.get("shortcut", ""),))

    def selected(self):
        selection = self.tree.selection()
        return self._by_iid.get(selection[0]) if selection else None

    def _place(self, item) -> tuple[list, int]:
        """The list holding item, and its index there."""
        def search(items):
            for i, candidate in enumerate(items):
                if candidate is item:
                    return items, i
                found = search(candidate.get("items", []))
                if found:
                    return found
            return None
        found = search(self.items)
        if found is None:
            raise LookupError("the item isn't in the menu")
        return found

    # ----- the fields -----

    def _load_fields(self):
        item = self.selected() or {}
        self._loading = True
        try:
            separator = not item or item.get("text") == menus.SEPARATOR
            for widget in self.fields:
                widget.state(["disabled"] if separator else ["!disabled"])
            self.text_var.set("" if separator else item.get("text", ""))
            self.name_var.set("" if separator else item.get("name", ""))
            self._load_shortcut("" if separator else item.get("shortcut", ""))
            self.checked_var.set(bool(item.get("checked", False)))
            self.enabled_var.set(bool(item.get("enabled", True)))
        finally:
            self._loading = False

    def _field_changed(self, var):
        item = self.selected()
        if self._loading or item is None or item.get("text") == menus.SEPARATOR:
            return
        if var is self.text_var:
            item["text"] = self.text_var.get()
            if id(item) in self._auto_named:
                self._set_quietly(self.name_var, self._auto_name(item))
                item["name"] = self.name_var.get()
        elif var is self.name_var:
            item["name"] = self.name_var.get().strip()
            self._auto_named.discard(id(item))  # typed by hand, so leave it alone
        elif var is self.key_var or var in self.modifier_vars.values():
            self._store_shortcut(item)
        elif var is self.checked_var:
            _set_or_drop(item, "checked", self.checked_var.get(), False)
        elif var is self.enabled_var:
            _set_or_drop(item, "enabled", self.enabled_var.get(), True)
        self._show(item)

    def _load_shortcut(self, shortcut):
        try:
            modifiers, key = menus.split_shortcut(shortcut) if shortcut else (set(), "")
        except ValueError:
            modifiers, key = set(), shortcut  # as written in the file; OK will point it out
        for modifier, var in self.modifier_vars.items():
            var.set(modifier in modifiers)
        self.key_var.set(key)
        self._show_shortcut_problem(shortcut)

    def _store_shortcut(self, item):
        key = self.key_var.get().strip()
        if not key:
            item.pop("shortcut", None)
            self._show_shortcut_problem("")
            return
        written = menus.join_shortcut({m for m, var in self.modifier_vars.items() if var.get()}, key)
        try:
            item["shortcut"] = menus.normalize_shortcut(written)
            tidy = menus.split_shortcut(item["shortcut"])[1]
            if tidy != key:
                self._set_quietly(self.key_var, tidy)  # "pgup" -> "PgUp"
        except ValueError:
            item["shortcut"] = written  # kept as typed so OK refuses it, rather than silently dropped
        self._show_shortcut_problem(item["shortcut"])

    def _show_shortcut_problem(self, shortcut):
        try:
            if shortcut:
                menus.normalize_shortcut(shortcut)
            self.shortcut_error.configure(text="")
        except ValueError as e:
            self.shortcut_error.configure(text=str(e))

    def _set_quietly(self, var, value):
        self._loading = True
        try:
            var.set(value)
        finally:
            self._loading = False

    def _auto_name(self, item):
        """A name from the text, like "Save &As..." -> mnuSaveAs, unique in the form."""
        words = re.findall(r"[A-Za-z0-9]+", menus.parse_text(item.get("text", ""))[0])
        base = "mnu" + "".join(w[:1].upper() + w[1:] for w in words) if words else "mnuItem"
        taken = set(self.editor.object_names()) | {i.get("name") for i in menus.walk(self.items) if i is not item}
        name, n = base, 2
        while name in taken:
            name, n = f"{base}{n}", n + 1
        return name

    # ----- the buttons -----

    def _new_item(self):
        item = {"name": "", "text": "New Item"}
        self._auto_named.add(id(item))
        item["name"] = self._auto_name(item)
        return item

    def _insert_after_selected(self, item):
        selected = self.selected()
        if selected is None:
            self.items.append(item)
        else:
            items, index = self._place(selected)
            items.insert(index + 1, item)
        self._refresh(item)
        if item.get("text") != menus.SEPARATOR:
            self.text_entry.focus_set()
            self.text_entry.select_range(0, tk.END)

    def add(self):
        self._insert_after_selected(self._new_item())

    def add_inside(self):
        """Add an item to the selected item's submenu (making it a submenu)."""
        selected = self.selected()
        if selected is None or selected.get("text") == menus.SEPARATOR:
            return self.add()
        item = self._new_item()
        selected.setdefault("items", []).append(item)
        self._refresh(item)
        self.text_entry.focus_set()
        self.text_entry.select_range(0, tk.END)

    def add_separator(self):
        self._insert_after_selected({"text": menus.SEPARATOR})

    def delete(self):
        selected = self.selected()
        if selected is None:
            return
        items, index = self._place(selected)
        del items[index]
        neighbor = items[min(index, len(items) - 1)] if items else None
        self._refresh(neighbor)

    def move(self, step):
        selected = self.selected()
        if selected is None:
            return
        items, index = self._place(selected)
        if 0 <= index + step < len(items):
            items[index], items[index + step] = items[index + step], items[index]
            self._refresh(selected)

    def indent(self):
        """Move the item into the submenu of the item above it."""
        selected = self.selected()
        if selected is None:
            return
        items, index = self._place(selected)
        if index == 0 or items[index - 1].get("text") == menus.SEPARATOR:
            return
        items[index - 1].setdefault("items", []).append(items.pop(index))
        self._refresh(selected)

    def outdent(self):
        """Move the item out of its submenu, to just after the submenu's item."""
        selected = self.selected()
        if selected is None:
            return
        items, index = self._place(selected)
        parent = next((i for i in menus.walk(self.items) if i.get("items") is items), None)
        if parent is None:
            return  # already at the top
        outer, parent_index = self._place(parent)
        outer.insert(parent_index + 1, items.pop(index))
        if not items:
            del parent["items"]
        self._refresh(selected)

    def ok(self):
        """Check the menu, then give it to the form."""
        taken = set(self.editor.object_names())
        seen, shortcuts = set(), {}
        for item in menus.walk(self.items):
            if item.get("text") == menus.SEPARATOR:
                continue
            if not item.get("items"):
                item.pop("items", None)
            try:
                check_name(item.get("name", ""), taken | seen)
                if item.get("shortcut"):
                    item["shortcut"] = menus.normalize_shortcut(item["shortcut"])
                    if item["shortcut"] in shortcuts:
                        raise ValueError(f"{item['shortcut']} is already the shortcut for {shortcuts[item['shortcut']]}")
                    shortcuts[item["shortcut"]] = item["name"]
            except ValueError as e:
                self._refresh(item)
                messagebox.showerror("Menu Editor", f"{menus.parse_text(item.get('text', ''))[0] or 'An item'}: {e}", parent=self)
                return False
            seen.add(item["name"])
        renames = [(self._original[id(i)], i["name"]) for i in menus.walk(self.items)
                   if id(i) in self._original and self._original[id(i)] != i.get("name")]
        self.editor.set_menu(self.items, renames)
        self.destroy()
        return True


def _set_or_drop(item, key, value, default):
    """Store only values that differ from the default, so the .form file stays short."""
    if value == default:
        item.pop(key, None)
    else:
        item[key] = value
