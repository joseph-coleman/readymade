"""The code window: Object and Event dropdowns above a Python editor.

Picking an object and event jumps to its handler, creating an empty one if
it doesn't exist yet, the way VB's code window did. Events that already have
a handler are marked with a check.
"""

from __future__ import annotations

import keyword
import re
import tkinter as tk
from tkinter import ttk

from pybasic import codegen
from pybasic.ide.panels import MONO

_STRING = r"'''[\s\S]*?'''|\"\"\"[\s\S]*?\"\"\"|'(?:\\.|[^'\\\n])*'|\"(?:\\.|[^\"\\\n])*\""
_TOKENS = re.compile(
    rf"(?P<comment>#[^\n]*)|(?P<string>{_STRING})|(?P<keyword>\b(?:{'|'.join(keyword.kwlist)})\b)"
)
_ERROR_COLOR = "#fff59d"  # VB marked the current line in yellow
_COLORS = {"keyword": "#000080", "comment": "#008000", "string": "#a31515"}  # VB's blue and green
_IMPLEMENTED = "  ✓"


class CodeView(ttk.Frame):
    """app is the editor this code belongs to. Modules have no objects, so no dropdowns."""

    def __init__(self, master, app, objects=True):
        super().__init__(master)
        self.app = app
        self._highlight_job = None

        bar = ttk.Frame(self, padding=(0, 2))
        if objects:
            bar.pack(fill=tk.X)
        self.objects = ttk.Combobox(bar, state="readonly", width=24)
        self.objects.pack(side=tk.LEFT)
        self.objects.bind("<<ComboboxSelected>>", lambda e: self._refresh_events())
        self.events = ttk.Combobox(bar, state="readonly", width=24, postcommand=self._refresh_events)
        self.events.pack(side=tk.LEFT, padx=(4, 0))
        self.events.bind("<<ComboboxSelected>>", self._event_chosen)

        # Shown above the code while a run-time error is being pointed out.
        self.error_bar = tk.Label(self, bg=_ERROR_COLOR, anchor="w", padx=6, pady=2)
        body = ttk.Frame(self)
        self._body = body
        body.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(body, font=MONO, undo=True, wrap="none")
        yscroll = ttk.Scrollbar(body, command=self.text.yview)
        xscroll = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.text.xview)
        self.text.configure(yscrollcommand=yscroll.set, xscrollcommand=xscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        for tag, color in _COLORS.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("error", background=_ERROR_COLOR)
        self.text.tag_raise("sel")

        # Let the window's shortcuts (Ctrl+O, F5, ...) run before Text's own key bindings.
        self.text.bindtags((str(self.text), str(self.winfo_toplevel()), "Text", "all"))
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Return>", self._newline)
        self.text.bind("<Tab>", lambda e: self._insert(codegen.INDENT))

    # ----- source -----

    def get_source(self):
        return self.text.get("1.0", "end-1c")

    def set_source(self, source):
        """Load new source, clearing undo history."""
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", source)
        self.text.edit_reset()
        self.text.mark_set("insert", "1.0")
        self.highlight()

    def replace_source(self, source):
        """Replace the source as one undoable step, keeping the scroll position."""
        if source == self.get_source():
            return
        top = self.text.yview()[0]
        self.text.edit_separator()
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", source)
        self.text.edit_separator()
        self.text.yview_moveto(top)

    def apply_edit(self, edit):
        self.text.edit_separator()
        self.text.delete(f"{edit.start + 1}.0", f"{edit.end + 1}.0")
        self.text.insert(f"{edit.start + 1}.0", edit.text)
        self.text.edit_separator()

    # ----- navigation -----

    def refresh_objects(self):
        self.objects["values"] = self.app.object_names()

    def show_method(self, obj, event, def_line):
        """Put the cursor in the method body. A placeholder `pass` is selected so typing replaces it."""
        self.objects.set(obj)
        self._refresh_events()
        self.events.set(event)
        body = def_line + 1
        line = self.text.get(f"{body}.0", f"{body}.end")
        indent = len(line) - len(line.lstrip())
        self.text.tag_remove("sel", "1.0", tk.END)
        self.text.mark_set("insert", f"{body}.{indent}")
        if line.strip() == "pass":
            self.text.tag_add("sel", "insert", "insert lineend")
        self.text.see("insert")
        self.text.focus_set()

    def _refresh_events(self):
        obj = self.objects.get()
        defined = codegen.defined_methods(self.get_source())
        self.events["values"] = [
            e.name + (_IMPLEMENTED if f"{obj}_{e.name}" in defined else "") for e in self.app.events_for(obj)
        ]

    def _event_chosen(self, _):
        event = self.events.get().removesuffix(_IMPLEMENTED)
        self.app.goto_handler(self.objects.get(), event)

    # ----- editing -----

    def _insert(self, text):
        if self.text.tag_ranges("sel"):
            self.text.delete("sel.first", "sel.last")
        self.text.insert("insert", text)
        self.text.see("insert")
        return "break"

    def _newline(self, _):
        line = self.text.get("insert linestart", "insert")
        indent = line[: len(line) - len(line.lstrip())]
        if line.rstrip().endswith(":"):
            indent += codegen.INDENT
        return self._insert("\n" + indent)

    def show_error(self, line, message):
        """Highlight the line where a run-time error happened, with its message above the code."""
        self.clear_error()
        self.text.tag_add("error", f"{line}.0", f"{line}.0 lineend +1c")
        self.text.mark_set("insert", f"{line}.0")
        self.text.see(f"{line}.0")
        self.error_bar.configure(text=f"Line {line}: {message}")
        self.error_bar.pack(fill=tk.X, before=self._body)

    def clear_error(self):
        self.text.tag_remove("error", "1.0", tk.END)
        self.error_bar.pack_forget()

    def _on_modified(self, _):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        self.clear_error()  # once the code changes, the error may no longer be there
        if self._highlight_job:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(200, self.highlight)
        self.app.update_title()

    def highlight(self):
        self._highlight_job = None
        source = self.get_source()
        for tag in _COLORS:
            self.text.tag_remove(tag, "1.0", tk.END)
        for m in _TOKENS.finditer(source):
            if m.lastgroup:
                self.text.tag_add(m.lastgroup, f"1.0+{m.start()}c", f"1.0+{m.end()}c")
