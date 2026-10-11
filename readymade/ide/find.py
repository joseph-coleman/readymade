"""Finding and replacing: the code window's find bar (Ctrl+F, Ctrl+H), and Find in Files.

Both search with the same choices: match case, whole word, and a regular expression
(Python's re). Replace All is one undo step.
"""

from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from readymade.ide import options
from readymade.ide.tooltips import tip

MONO = options.CODE_FONT


def compile_search(text, case=False, word=False, regex=False):
    """The pattern for a search, or None for no search. Raises re.error for a regex Python can't read."""
    if not text:
        return None
    pattern = text if regex else re.escape(text)
    if word:
        pattern = rf"(?<!\w)(?:{pattern})(?!\w)"
    return re.compile(pattern, re.MULTILINE | (0 if case else re.IGNORECASE))  # (^ and $: each line's)


OPTIONS = (("Aa", "Match case: Count isn't count"),
           ("ab", "Whole word: price doesn't find prices"),
           (".*", "Regular expression (Python's re): pric\\w+ finds price and prices; Replace can use \\1 for "
                  "what the first ( ) found"))


def _option_boxes(parent, case, word, regex, command=None):
    """The Aa, ab and .* boxes, with tips saying what they do."""
    boxes = []
    for (text, said), variable in zip(OPTIONS, (case, word, regex)):
        box = ttk.Checkbutton(parent, text=text, variable=variable, **({"command": command} if command else {}))
        box.pack(side=tk.LEFT, padx=(6, 0))
        tip(box, said)
        boxes.append(box)
    return boxes


def matches(pattern, source):
    """[(start, end)] offsets of the pattern's matches (empty ones left out)."""
    return [(m.start(), m.end()) for m in pattern.finditer(source) if m.end() > m.start()]


class FindBar(ttk.Frame):
    """Above the code: find (and with replace=True, replace) in it."""

    def __init__(self, code):
        super().__init__(code, padding=(4, 2))
        self.code = code
        self.text = code.text
        self.find = tk.StringVar(self)
        self.replace = tk.StringVar(self)
        self.case = tk.BooleanVar(self, False)
        self.word = tk.BooleanVar(self, False)
        self.regex = tk.BooleanVar(self, False)
        self.pattern = None
        self.found = []  # [(start, end)] offsets, as last searched

        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.find_entry = ttk.Entry(top, textvariable=self.find, width=30, font=MONO)
        self.find_entry.pack(side=tk.LEFT)
        for text, step, said in (("\u2193", 1, "The next match (Enter, or F3)"),  # ↓ ↑
                                 ("\u2191", -1, "The match before (Shift+Enter, or Shift+F3)")):
            button = ttk.Button(top, text=text, width=2, style="Dots.TButton", command=lambda s=step: self.step(s))
            button.pack(side=tk.LEFT, padx=(4, 0))
            tip(button, said)
        self.option_boxes = _option_boxes(top, self.case, self.word, self.regex, self.search)
        self.count = ttk.Label(top, style="Note.TLabel")
        self.count.pack(side=tk.LEFT, padx=(8, 0))
        close = ttk.Button(top, text="\u00d7", width=2, style="Dots.TButton", command=self.close)
        close.pack(side=tk.RIGHT)
        tip(close, "Close the find bar (Esc)")
        self.replace_row = ttk.Frame(self)
        self.replace_entry = ttk.Entry(self.replace_row, textvariable=self.replace, width=30, font=MONO)
        self.replace_entry.pack(side=tk.LEFT)
        for text, command, said in (("Replace", self.replace_one,
                                     "Replace the match that's chosen, then go to the next (Enter, in this box)"),
                                    ("Replace All", self.replace_all, "Replace every match (one undo step)")):
            button = ttk.Button(self.replace_row, text=text, command=command)
            button.pack(side=tk.LEFT, padx=(4, 0))
            tip(button, said)
        tip(self.find_entry, "What to look for (F1: help on finding)")
        tip(self.replace_entry, "What to put in its place (with .* on, \\1 is what the first ( ) found)")

        self.find.trace_add("write", lambda *_: self.search(from_cursor=True))
        for entry in (self.find_entry, self.replace_entry):
            entry.bind("<Return>", lambda e: self.step(1) or "break")
            entry.bind("<Shift-Return>", lambda e: self.step(-1) or "break")
            entry.bind("<Escape>", lambda e: self.close() or "break")
        self.replace_entry.bind("<Return>", lambda e: self.replace_one() or "break")

    # ----- showing -----

    def open(self, replace=False):
        """Show the bar (with the replace row too), looking for the selected text."""
        if self.text.tag_ranges("sel"):
            chosen = self.text.get("sel.first", "sel.last")
            if chosen and "\n" not in chosen:
                self.find.set(chosen)
        if replace:
            self.replace_row.pack(fill=tk.X, pady=(2, 0))
        else:
            self.replace_row.pack_forget()
        self.code.show_above_code(self)
        self.search(from_cursor=True)
        entry = self.replace_entry if replace and self.find.get() else self.find_entry
        entry.focus_set()
        entry.select_range(0, tk.END)

    def close(self):
        self.pack_forget()
        self.text.tag_remove("found", "1.0", tk.END)
        self.text.focus_set()

    def is_open(self):
        return self.winfo_ismapped()

    # ----- searching -----

    def _compile(self):
        try:
            self.pattern = compile_search(self.find.get(), self.case.get(), self.word.get(), self.regex.get())
        except re.error as e:
            self.pattern = None
            self.count.configure(text=f"Can't read that: {e.msg}")
            return False
        return True

    def search(self, from_cursor=False):
        """Mark every match; with from_cursor, choose the first at or after the cursor."""
        self.text.tag_remove("found", "1.0", tk.END)
        if not self._compile():
            self.found = []
            return
        self.found = matches(self.pattern, self.code.get_source()) if self.pattern else []
        for start, end in self.found:
            self.text.tag_add("found", self._index(start), self._index(end))
        if from_cursor and self.found:
            cursor = self._offset("insert")
            if self.text.tag_ranges("sel"):
                cursor = self._offset("sel.first")
            self._choose(next((m for m in self.found if m[0] >= cursor), self.found[0]))
        self._show_count()

    def refresh(self):
        """The code changed: mark the matches again, without moving the cursor."""
        if self.is_open():
            self.search()

    def step(self, direction):
        """F3 / Shift+F3, Enter / Shift+Enter: the next (or previous) match, around the end."""
        if self.pattern is None:
            self.search()
        if not self.found:
            self.bell()
            return
        if self.text.tag_ranges("sel"):
            start, end = self._offset("sel.first"), self._offset("sel.last")
        else:
            start = end = self._offset("insert")
        if direction > 0:
            target = next((m for m in self.found if m[0] >= end and m != (start, end)), self.found[0])
        else:
            target = next((m for m in reversed(self.found) if m[1] <= start and m != (start, end)), self.found[-1])
        self._choose(target)
        self._show_count()

    def _current(self):
        """The match that's selected, or None."""
        if not self.text.tag_ranges("sel"):
            return None
        chosen = (self._offset("sel.first"), self._offset("sel.last"))
        return chosen if chosen in self.found else None

    def _choose(self, match):
        start, end = self._index(match[0]), self._index(match[1])
        self.text.tag_remove("sel", "1.0", tk.END)
        self.text.tag_add("sel", start, end)
        self.text.mark_set("insert", end)
        self.text.see(start)

    def _show_count(self):
        if not self.find.get():
            self.count.configure(text="")
        elif not self.found:
            self.count.configure(text="No results")
        else:
            current = self._current()
            place = f"{self.found.index(current) + 1} of " if current else ""
            self.count.configure(text=f"{place}{len(self.found)}")

    # ----- replacing -----

    def _replacement(self, match_text):
        if not self.regex.get():
            return self.replace.get()
        return self.pattern.sub(self.replace.get(), match_text, count=1)

    def replace_one(self):
        """Replace the selected match, then go to the next."""
        if self.pattern is None:
            self.search()
        current = self._current()
        if current is None:
            self.step(1)
            return
        start, end = self._index(current[0]), self._index(current[1])
        try:
            new = self._replacement(self.text.get(start, end))
        except (re.error, IndexError) as e:
            self.count.configure(text=f"Can't use that: {e}")
            return

        def change():
            self.text.delete(start, end)
            self.text.insert(start, new)

        self.code.one_step(change)
        self.text.mark_set("insert", f"{start} +{len(new)}c")
        self.text.tag_remove("sel", "1.0", tk.END)
        self.search()
        if self.found:
            self.step(1)

    def replace_all(self):
        """Replace every match: one undo step."""
        if not self._compile() or self.pattern is None:
            return
        source = self.code.get_source()
        try:
            if self.regex.get():
                new, count = self.pattern.subn(self.replace.get(), source)
            else:
                new, count = self.pattern.subn(lambda m: self.replace.get(), source)
        except (re.error, IndexError) as e:
            self.count.configure(text=f"Can't use that: {e}")
            return
        if count:
            self.code.replace_keeping_place(new)
        self.search()
        self.count.configure(text=f"Replaced {count}")

    # ----- offsets and Text indexes -----

    def _index(self, offset):
        return f"1.0 + {offset} chars"

    def _offset(self, index):
        return len(self.text.get("1.0", index))


class FindInFilesPanel(ttk.Frame):
    """Find in Files (Ctrl+Shift+F): every match in the project's code and other text files,
    open ones as they are in their tabs. Click one to go to it: on_open(path, line, column, length)."""

    def __init__(self, master, search_files, on_open):
        super().__init__(master, padding=(4, 2))
        self._search_files = search_files  # () -> [(path, text)]
        self._on_open = on_open
        self.find = tk.StringVar(self)
        self.case = tk.BooleanVar(self, False)
        self.word = tk.BooleanVar(self, False)
        self.regex = tk.BooleanVar(self, False)
        top = ttk.Frame(self)
        top.pack(fill=tk.X)
        self.entry = ttk.Entry(top, textvariable=self.find, width=36, font=MONO)
        self.entry.pack(side=tk.LEFT)
        self.entry.bind("<Return>", lambda e: self.search() or "break")
        ttk.Button(top, text="Find", command=self.search).pack(side=tk.LEFT, padx=(4, 0))
        self.option_boxes = _option_boxes(top, self.case, self.word, self.regex)
        tip(self.entry, "What to look for in the project's files: Enter finds (F1: help on finding)")
        self.status = ttk.Label(top, style="Note.TLabel")
        self.status.pack(side=tk.LEFT, padx=(8, 0))
        body = ttk.Frame(self)
        body.pack(fill=tk.BOTH, expand=True, pady=(2, 0))
        self.tree = ttk.Treeview(body, columns=("line", "text"), show="tree headings", height=6, selectmode="browse",
                                 style="Problems.Treeview")
        self.tree.heading("#0", text="File", anchor="w")
        self.tree.heading("line", text="Line", anchor="w")
        self.tree.heading("text", text="Found", anchor="w")
        self.tree.column("#0", width=180, stretch=False)
        self.tree.column("line", width=60, stretch=False, anchor="w")
        self.tree.column("text", width=600, stretch=True, anchor="w")
        scroll = ttk.Scrollbar(body, command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        self._places = {}  # row -> (path, line, column, length)
        self.tree.bind("<ButtonRelease-1>", lambda e: self._open(self.tree.identify_row(e.y)))
        self.tree.bind("<Return>", lambda e: self._open(self.tree.focus()))

    def apply_theme(self, theme):
        pass  # (the Problems tab styles the tree style both use)

    def open(self, text=""):
        if text:
            self.find.set(text)
        self.entry.focus_set()
        self.entry.select_range(0, tk.END)

    def search(self):
        self.tree.delete(*self.tree.get_children())
        self._places = {}
        try:
            pattern = compile_search(self.find.get(), self.case.get(), self.word.get(), self.regex.get())
        except re.error as e:
            self.status.configure(text=f"Can't read that: {e.msg}")
            return
        if pattern is None:
            self.status.configure(text="")
            return
        total, files = 0, 0
        for path, source, label in self._search_files():
            lines = source.splitlines()
            found = matches(pattern, source)
            if not found:
                continue
            files += 1
            parent = self.tree.insert("", tk.END, text=label, open=True)
            starts = [0]
            for line in lines:
                starts.append(starts[-1] + len(line) + 1)
            row_of = 0
            for start, end in found[:500]:
                while row_of + 1 < len(starts) and starts[row_of + 1] <= start:
                    row_of += 1
                column = start - starts[row_of]
                text = lines[row_of] if row_of < len(lines) else ""
                row = self.tree.insert(parent, tk.END, text="", values=(row_of + 1, text.strip()))
                self._places[row] = (path, row_of + 1, column, end - start)
                total += 1
        self.status.configure(text=f"{total} in {files} file{'s' * (files != 1)}" if total else "No results")

    def _open(self, row):
        if row in self._places:
            self._on_open(*self._places[row])
        return "break"
