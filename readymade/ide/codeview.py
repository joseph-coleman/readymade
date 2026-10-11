"""The code window: Object and Event dropdowns above a Python editor.

Picking an object and event jumps to its handler, creating an empty one if
it doesn't exist yet, the way VB's code window did. Events that already have
a handler are marked with a check.
"""

from __future__ import annotations

import keyword
import re
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk

from readymade import codegen, menus
from readymade.ide import highlight, options
from readymade.ide.panels import MONO

INDENT = codegen.INDENT  # the spaces Tab inserts (Tools > Options: indent width); never a tab character


def set_indent(width):
    """Make Tab, Shift+Tab, Backspace and Enter work in steps of width spaces."""
    global INDENT
    INDENT = " " * width
_PAIRS = {"(": ")", "[": "]", "{": "}"}
_QUOTES = ("'", '"')
_CLOSE_BEFORE = set(")]}:;,.")  # a pair closes itself only before one of these, a space or the line's end
_STRING_PREFIXES = {"", "r", "b", "f", "u", "rb", "br", "fr", "rf"}  # quotes after these still pair up
_AUTO = "auto_closed"  # tags closers the editor added
_ENDS_BLOCK = re.compile(r"(return|pass|break|continue|raise)\b")  # statements after which a block is done


def _in_string(text):
    """Whether the end of text is inside a string (on this line)."""
    quote, i = None, 0
    while i < len(text):
        if quote:
            if text[i] == "\\":
                i += 2
                continue
            if text.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        elif text[i] in "\"'":
            quote = text[i : i + 3] if text[i : i + 3] in ('"""', "'''") else text[i]
            i += len(quote)
            continue
        i += 1
    return quote is not None


class CompletionList:
    """The list of completions under the cursor. Typing narrows it; Up/Down choose;
    Enter or Tab accepts; Escape, clicking elsewhere or leaving the window closes it."""

    def __init__(self, code):
        self.code = code
        self.window = None
        self.items = []
        self.shown = []
        self.start = None  # where the name being completed begins

    def is_open(self):
        return self.window is not None

    def open(self, items, start):
        self.items = items
        self.start = start
        if self.window is None:
            self.window = tk.Toplevel(self.code)
            self.window.overrideredirect(True)
            theme = self.code.theme
            self.listbox = tk.Listbox(self.window, font=MONO, activestyle="none", exportselection=False,
                                      height=8, width=44, bg=theme.background, fg=theme.foreground,
                                      selectbackground=theme.selection, selectforeground=theme.foreground,
                                      highlightthickness=1)
            self.listbox.pack(fill=tk.BOTH, expand=True)
            self.listbox.bind("<Double-Button-1>", lambda e: self.accept())
        self.refresh()

    def refresh(self):
        """Narrow the list to what's been typed, or close it if that's no longer a name."""
        if self.window is None:
            return
        text = self.code.text
        if text.compare("insert", "<", self.start) or text.index("insert").split(".")[0] != self.start.split(".")[0]:
            return self.close()
        typed = text.get(self.start, "insert")
        if typed and not typed.isidentifier():
            return self.close()
        self.shown = sorted((c for c in self.items if c.name.lower().startswith(typed.lower())),
                            key=lambda c: (c.name.startswith("_"), not c.name.startswith(typed)))
        if not self.shown or (len(self.shown) == 1 and self.shown[0].name == typed):
            return self.close()
        chosen = self.listbox.curselection()
        was = self.listbox.get(chosen[0]).split()[0] if chosen else None  # keep the choice if it's still there
        names = [c.name for c in self.shown]
        self.listbox.delete(0, tk.END)
        for c in self.shown:
            self.listbox.insert(tk.END, f"{c.name:<32}{c.kind}")
        self.listbox.configure(height=min(8, len(self.shown)))
        index = names.index(was) if was in names else 0
        self.listbox.selection_set(index)
        self.listbox.see(index)
        place = text.bbox(self.start) or text.bbox("insert")
        if place:
            x, y, _, height = place
            self.window.geometry(f"+{text.winfo_rootx() + x}+{text.winfo_rooty() + y + height}")
            self.window.lift()

    def move(self, step):
        current = self.listbox.curselection()
        index = max(0, min(len(self.shown) - 1, (current[0] if current else 0) + step))
        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(index)
        self.listbox.see(index)

    def accept(self):
        """Put the chosen name in place of what's been typed. False if the list wasn't open."""
        if self.window is None:
            return False
        current = self.listbox.curselection()
        if current:
            name, text = self.shown[current[0]].name, self.code.text

            def put():
                text.delete(self.start, "insert")
                text.insert(self.start, name)

            self.code._one_step(put)
        self.close()
        return True

    def close(self):
        """Close the list. True if it was open."""
        if self.window is None:
            return False
        self.window.destroy()
        self.window = None
        return True


def _scan(line):
    """(the line without its comment, the columns of brackets still open at its end).
    Strings are skipped, so brackets, quotes and # inside them don't count."""
    open_brackets, quote, i = [], None, 0
    while i < len(line):
        c = line[i]
        if quote:
            if c == "\\":
                i += 2
                continue
            if line.startswith(quote, i):
                i += len(quote)
                quote = None
                continue
        elif c == "#":
            return line[:i], open_brackets
        elif c in "\"'":
            quote = line[i : i + 3] if line[i : i + 3] in ('"""', "'''") else c
            i += len(quote)
            continue
        elif c in "([{":
            open_brackets.append(i)
        elif c in ")]}" and open_brackets:
            open_brackets.pop()
        i += 1
    return line, open_brackets  # VB marked the current line in yellow
_IMPLEMENTED = "  ✓"


class CodeView(ttk.Frame):
    """app is the editor this code belongs to. Modules have no objects, so no dropdowns."""

    def __init__(self, master, app, objects=True):
        super().__init__(master)
        self.app = app
        self._highlight_job = None
        self._numbers_job = None
        self.on_change = None  # called soon after typing stops (the IDE checks the code then)
        self._change_job = None
        self._problems = {}  # tool name -> [lint.Problem]
        self._problem_tags = {}  # Text tag -> the Problem it underlines
        self.on_breakpoints = None  # called when breakpoints are added or removed (None: none allowed here)
        # Text marks at the start of lines with breakpoints, so they move with edits -> the breakpoint's
        # condition and hit count, if it has them ({condition, hit_mode, hits}, see readymade.debugger.BreakCondition).
        self._breakpoints = {}
        self.on_gutter_menu = None  # on_gutter_menu(line, event): a right-click in the line numbers
        self.on_edited = None  # called on every change to the code (the IDE notes edits made during a run)
        self.on_hover = None  # on_hover(expression, x, y): the mouse rests on a name (screen x, y)
        self._hover_job = None
        self._tip = None  # (window, expression) while a value tip shows
        self._next_breakpoint = 0

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
        options.ensure_code_font(self)
        self.error_bar = tk.Label(self, anchor="w", padx=6, pady=2)
        # Shown above the code when it's changed while the program runs (see show_note).
        self.note_bar = tk.Label(self, anchor="w", padx=6, pady=2)
        body = ttk.Frame(self)
        self._body = body
        body.pack(fill=tk.BOTH, expand=True)
        self.text = tk.Text(body, font=MONO, undo=True, wrap="none", highlightthickness=0)  # the cursor shows the focus
        yscroll = ttk.Scrollbar(body, command=self.text.yview)
        xscroll = ttk.Scrollbar(body, orient=tk.HORIZONTAL, command=self.text.xview)
        # Scrolling also moves the line numbers.
        self.text.configure(yscrollcommand=lambda *a: (yscroll.set(*a), self._show_numbers()), xscrollcommand=xscroll.set)
        yscroll.pack(side=tk.RIGHT, fill=tk.Y)
        xscroll.pack(side=tk.BOTTOM, fill=tk.X)
        self.gutter = tk.Canvas(body, width=1, highlightthickness=0, bd=0)
        self.gutter.pack(side=tk.LEFT, fill=tk.Y)
        self.gutter.bind("<Button-1>", self._gutter_click)  # sets or clears a breakpoint, as F9 does
        for sequence in menus.context_clicks(self.gutter):
            self.gutter.bind(sequence, self._gutter_menu)
        self.text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        # Messages for problems on the cursor's line, under the code.
        self.problem_bar = tk.Label(self, anchor="w", padx=6, pady=1)
        self._underline = {"underline": True}
        self.apply_theme(options.theme())
        self.text.tag_raise("current")
        self.text.tag_raise("sel")

        # Let the window's shortcuts (Ctrl+O, F5, ...) run before Text's own key bindings.
        self.text.bindtags((str(self.text), str(self.winfo_toplevel()), "Text", "all"))
        self.text.bind("<<Modified>>", self._on_modified)
        self.text.bind("<Return>", self._newline)
        # Indentation, as in other editors: always spaces, one undo step each.
        self.text.bind("<Tab>", self._tab)
        for sequence in ("<Shift-Tab>", "<ISO_Left_Tab>"):  # Shift+Tab arrives as ISO_Left_Tab on X11
            try:
                self.text.bind(sequence, self._dedent)
            except tk.TclError:  # a keysym this platform's Tk doesn't know
                pass
        self.text.bind("<BackSpace>", self._backspace)
        menus.bind_shortcut(self.text, "Ctrl+/", self.toggle_comment)  # (Text's own Ctrl+/ selects everything)
        # Brackets and quotes close themselves.
        for keysym, opener in (("parenleft", "("), ("bracketleft", "["), ("braceleft", "{")):
            self.text.bind(f"<KeyPress-{keysym}>", lambda e, o=opener: self._open(o))
        for keysym, closer in (("parenright", ")"), ("bracketright", "]"), ("braceright", "}")):
            self.text.bind(f"<KeyPress-{keysym}>", lambda e, c=closer: self._step_over(c))
        for keysym, quote in (("quotedbl", '"'), ("apostrophe", "'")):
            self.text.bind(f"<KeyPress-{keysym}>", lambda e, q=quote: self._quote(q))
        for sequence in ("<ButtonRelease-1>", "<Prior>", "<Next>"):  # the cursor went elsewhere
            self.text.bind(sequence, lambda e: self.text.tag_remove(_AUTO, "1.0", tk.END), add="+")
        # Completion (the IDE answers on_complete) and Go to Definition (on_goto).
        self.on_complete = None  # on_complete(code, manual) asks for completions at the cursor
        self.on_goto = None  # on_goto(code, index) goes to the definition of the name there
        self.completions = CompletionList(self)
        self.text.bind("<Up>", lambda e: self._up_down(-1))
        self.text.bind("<Down>", lambda e: self._up_down(1))
        self.text.bind("<Escape>", lambda e: "break" if self.completions.close() else None)
        # The physical Control key everywhere: on a Mac ⌘Space is Spotlight (VS Code uses ⌃Space too).
        self.text.bind("<Control-space>", lambda e: self._ask_completions(manual=True))
        self.text.bind("<KeyRelease>", self._key_released, add="+")
        self.text.bind("<FocusOut>", lambda e: self.completions.close(), add="+")
        self.text.bind("<ButtonPress-1>", lambda e: self.completions.close(), add="+")
        self.text.bind(f"<{menus.tk_modifier('Ctrl')}-Button-1>", self._control_click)  # ⌘-click on a Mac
        for sequence in ("<Configure>", "<KeyRelease>", "<ButtonRelease-1>"):  # resized, or the cursor moved
            self.text.bind(sequence, lambda e: self._show_numbers(), add="+")
        # While the program is paused, resting the mouse on a name shows its value (on_hover asks).
        self.text.bind("<Motion>", self._mouse_moved, add="+")
        for sequence in ("<Leave>", "<KeyPress>", "<ButtonPress>", "<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.text.bind(sequence, lambda e: self.hide_tip(), add="+")

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

        def replace():
            self.text.delete("1.0", tk.END)
            self.text.insert("1.0", source)

        # One step: on its own, Tk starts a new undo step when deleting turns into inserting.
        self._one_step(replace)
        self.text.yview_moveto(top)

    def replace_keeping_place(self, source):
        """Replace all the code (one undo step), keeping the cursor's line and column, e.g. after formatting."""
        place = self.text.index("insert")
        self.replace_source(source)
        self.text.mark_set("insert", place)  # Tk keeps it within the new text
        self.text.see("insert")

    def apply_edit(self, edit):
        self.text.edit_separator()
        self.text.delete(f"{edit.start + 1}.0", f"{edit.end + 1}.0")
        self.text.insert(f"{edit.start + 1}.0", edit.text)
        self.text.edit_separator()

    # ----- navigation -----

    def refresh_objects(self):
        self.objects["values"] = self.app.code_objects()

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

    def _selected_lines(self):
        """The first and last line numbers of the selection, or None. A selection that ends
        at the very start of a line doesn't include that line."""
        if not self.text.tag_ranges("sel"):
            return None
        first = int(self.text.index("sel.first").split(".")[0])
        last_line, last_column = map(int, self.text.index("sel.last").split("."))
        return first, (last_line - 1 if last_column == 0 and last_line > first else last_line)

    def _one_step(self, change):
        """Make a change of several edits undo in one step."""
        self.text.configure(autoseparators=False)
        self.text.edit_separator()
        try:
            change()
        finally:
            self.text.edit_separator()
            self.text.configure(autoseparators=True)

    def _tab(self, _):
        if self.completions.accept():
            return "break"
        lines = self._selected_lines()
        if lines and (lines[0] != lines[1] or self._whole_line_selected(lines[0])):
            first, last = lines

            def indent():
                for n in range(first, last + 1):
                    if self.text.get(f"{n}.0", f"{n}.end").strip():  # blank lines stay empty
                        self.text.insert(f"{n}.0", INDENT)

            self._one_step(indent)
            self._select_lines(first, last)
            return "break"
        start = "sel.first" if self.text.tag_ranges("sel") else "insert"  # where the spaces will begin
        column = int(self.text.index(start).split(".")[1])
        return self._insert(" " * (len(INDENT) - column % len(INDENT)))  # to the next tab stop

    def _dedent(self, _):
        lines = self._selected_lines()
        first, last = lines if lines else (int(self.text.index("insert").split(".")[0]),) * 2

        def remove():
            for n in range(first, last + 1):
                line = self.text.get(f"{n}.0", f"{n}.end")
                spaces = len(line) - len(line.lstrip(" "))
                width = 1 if line.startswith("\t") else min(spaces, len(INDENT))
                if width:
                    self.text.delete(f"{n}.0", f"{n}.{width}")

        self._one_step(remove)
        if lines:
            self._select_lines(first, last)
        return "break"

    def _backspace(self, _):
        """Backspace between a pair the editor just made, like (|), deletes both. In a line's
        leading spaces, it goes back to the previous tab stop."""
        if self.text.tag_ranges("sel"):
            return None
        before, after = self.text.get("insert -1c"), self.text.get("insert")
        closer = _PAIRS.get(before) or (before if before in _QUOTES else None)
        if closer == after and _AUTO in self.text.tag_names("insert"):
            self.text.delete("insert -1c", "insert +1c")
            return "break"
        before = self.text.get("insert linestart", "insert")
        if not before or before.strip(" "):
            return None  # not in the indentation: the usual Backspace
        width = len(before) % len(INDENT) or len(INDENT)
        self.text.delete(f"insert -{width}c", "insert")
        return "break"

    # ----- brackets and quotes -----

    def _open(self, opener):
        if self.text.tag_ranges("sel"):
            return self._wrap(opener, _PAIRS[opener])
        if not self._closing_fits():
            return None  # e.g. before a word: just the opener
        return self._insert_pair(opener, _PAIRS[opener])

    def _step_over(self, closer):
        """Typing a closer the editor added steps over it rather than adding another."""
        if not self.text.tag_ranges("sel") and self.text.get("insert") == closer and _AUTO in self.text.tag_names("insert"):
            self.text.tag_remove(_AUTO, "insert")
            self.text.mark_set("insert", "insert +1c")
            return "break"
        return None

    def _quote(self, quote):
        if self.text.tag_ranges("sel"):
            return self._wrap(quote, quote)
        if self._step_over(quote):
            return "break"
        before = self.text.get("insert linestart", "insert")
        if before.endswith(quote * 2) and not before.endswith(quote * 3) and self._closing_fits():
            return self._insert_pair(quote, quote * 3)  # the third quote of a docstring: """|"""
        word = re.search(r"\w*$", before).group()
        if word.lower() not in _STRING_PREFIXES or not self._closing_fits():
            return None  # e.g. the apostrophe in don't
        return self._insert_pair(quote, quote)

    def _closing_fits(self):
        after = self.text.get("insert")
        return after.isspace() or after in _CLOSE_BEFORE

    def _insert_pair(self, opener, closer):
        self.text.insert("insert", opener + closer)
        self.text.tag_add(_AUTO, f"insert -{len(closer)}c", "insert")  # so it can be stepped over or deleted with the opener
        self.text.mark_set("insert", f"insert -{len(closer)}c")
        self.text.see("insert")
        return "break"

    def _wrap(self, opener, closer):
        """Put the selection inside the pair, keeping it selected."""
        def wrap():
            # Text inserted at either edge of the selection isn't selected, so it stays on the text.
            self.text.insert("sel.first", opener)
            self.text.insert("sel.last", closer)

        self._one_step(wrap)
        self.text.mark_set("insert", "sel.last")
        return "break"

    # ----- completion and Go to Definition -----

    def word_start(self):
        """Where the name being typed at the cursor begins (the cursor itself after a ".")."""
        before = self.text.get("insert linestart", "insert")
        typed = re.search(r"[A-Za-z_]\w*$", before)
        return self.text.index(f"insert -{len(typed.group())}c") if typed else self.text.index("insert")

    def _ask_completions(self, manual=False):
        if self.on_complete and str(self.text.cget("state")) != "disabled":
            self.on_complete(self, manual)
        return "break"

    def _key_released(self, e):
        if self.completions.is_open():
            self.completions.refresh()
        elif e.keysym == "period" or (e.char and (e.char.isalnum() or e.char == "_") and self._typed_enough()):
            self._ask_completions()

    def _typed_enough(self):
        """Offer completions once three letters of a name are typed (not in a comment or string)."""
        before = self.text.get("insert linestart", "insert")
        code, _ = _scan(before)
        typed = re.search(r"[A-Za-z_]\w*$", before)
        return len(code) == len(before) and typed is not None and len(typed.group()) == 3 and not _in_string(before)

    def _up_down(self, step):
        if self.completions.is_open():
            self.completions.move(step)
            return "break"
        self.text.tag_remove(_AUTO, "1.0", tk.END)  # the cursor went elsewhere
        return None

    def _control_click(self, e):
        if self.on_goto:
            self.on_goto(self, self.text.index(f"@{e.x},{e.y}"))
        return "break"

    def show_location(self, line, column, length=0):
        """Put the cursor at a line and column, selecting a name there."""
        self.text.tag_remove("sel", "1.0", tk.END)
        self.text.mark_set("insert", f"{line}.{column}")
        if length:
            self.text.tag_add("sel", "insert", f"insert +{length}c")
        self.text.see("insert")
        self.text.focus_set()

    def toggle_comment(self, _=None):
        """Comment the selected lines (or the current one) out, or back in if they all are.
        New # marks line up at the block's shallowest indentation; blank lines are left alone."""
        lines = self._selected_lines()
        first, last = lines if lines else (int(self.text.index("insert").split(".")[0]),) * 2
        code = {n: line for n in range(first, last + 1) if (line := self.text.get(f"{n}.0", f"{n}.end")).strip()}
        if not code:
            return "break"
        indent = {n: len(line) - len(line.lstrip()) for n, line in code.items()}
        commented = all(line.lstrip().startswith("#") for line in code.values())

        def change():
            for n, line in code.items():
                if commented:
                    at = indent[n]
                    self.text.delete(f"{n}.{at}", f"{n}.{at + (2 if line[at:at + 2] == '# ' else 1)}")
                else:
                    self.text.insert(f"{n}.{min(indent.values())}", "# ")

        self._one_step(change)
        if lines:
            self._select_lines(first, last)
        return "break"

    def _changed(self):
        self._change_job = None
        if self.on_change:
            self.on_change()

    # ----- problems found by lint tools -----

    def set_problems(self, tool, problems):
        """Show a lint tool's latest problems (replacing its earlier ones)."""
        self._problems[tool] = list(problems)
        self._mark_problems()

    def keep_problems_of(self, tools):
        """Forget the problems of tools no longer in use."""
        if set(self._problems) - set(tools):
            self._problems = {t: p for t, p in self._problems.items() if t in tools}
            self._mark_problems()

    def problems(self):
        return [problem for found in self._problems.values() for problem in found]

    def _mark_problems(self):
        """Underline each problem's word. Tags move with the text, so marks stay put while editing."""
        for tag in self._problem_tags:
            self.text.tag_delete(tag)
        self._problem_tags = {}
        lines = int(self.text.index("end-1c").split(".")[0])
        for i, problem in enumerate(self.problems()):
            if problem.line > lines:
                continue
            start = self.text.index(f"{problem.line}.{problem.column}")
            end = self.text.index(f"{start} wordend") if self.text.get(start).isalnum() or self.text.get(start) == "_" else f"{start} +1c"
            tag = f"problem{i}"
            self.text.tag_add(tag, start, end)
            self.text.tag_configure(tag, **self._underline)
            self._problem_tags[tag] = problem
        self.text.tag_raise("sel")
        self._show_numbers()

    def _problem_lines(self):
        return {tag: int(self.text.index(f"{tag}.first").split(".")[0])
                for tag in self._problem_tags if self.text.tag_ranges(tag)}

    def _show_problems_here(self, current):
        here = [f"{self._problem_tags[tag].tool}: {self._problem_tags[tag].message}"
                for tag, line in self._problem_lines().items() if line == current]
        if here:
            self.problem_bar.configure(text="   \u2022   ".join(here))
            self.problem_bar.pack(side=tk.BOTTOM, fill=tk.X, before=self._body)
        else:
            self.problem_bar.pack_forget()

    # ----- line numbers -----

    def _show_numbers(self):
        """Redraw the line numbers once things settle (many events can ask for it at once)."""
        if self._numbers_job is None:
            self._numbers_job = self.after_idle(self._draw_numbers)

    def _draw_numbers(self):
        self._numbers_job = None
        self.gutter.delete("all")
        lines = int(self.text.index("end-1c").split(".")[0])
        width = tkfont.nametofont(MONO, root=self).measure("0" * max(2, len(str(lines)))) + 30  # room for the marks
        if int(self.gutter.cget("width")) != width:
            self.gutter.configure(width=width)
        current = int(self.text.index("insert").split(".")[0])
        problem_lines = set(self._problem_lines().values())
        breakpoints = set(self.breakpoint_lines())
        items = [item for item in self.breakpoints() if isinstance(item, dict)]
        disabled = {item["line"] for item in items if item.get("disabled")}
        conditional = {item["line"] for item in items if item.get("condition") or item.get("hit_mode")}
        self.text.tag_remove("breakpoint", "1.0", tk.END)
        for n in breakpoints - disabled:
            self.text.tag_add("breakpoint", f"{n}.0", f"{n}.0 lineend +1c")
        paused = self.paused_line()
        self._show_problems_here(current)
        index = self.text.index("@0,0")  # the first line in view
        while (place := self.text.dlineinfo(index)) is not None:
            n = int(index.split(".")[0])
            self.gutter.create_text(width - 6, place[1], anchor="ne", text=str(n), font=MONO,
                                    fill=self.theme.number_current if n == current else self.theme.number)
            middle = place[1] + place[3] // 2
            if n in breakpoints:
                off = n in disabled  # switched off in the Breakpoints tab: hollow
                self.gutter.create_oval(2, middle - 5, 12, middle + 5, fill="" if off else self.theme.breakpoint,
                                        outline=self.theme.breakpoint, width=2 if off else 1, tags="breakpoint")
                if n in conditional and not off:  # a + on it, as Visual Studio marks a condition or hit count
                    self.gutter.create_line(4, middle, 11, middle, fill="#ffffff", width=2, tags="breakpoint")
                    self.gutter.create_line(7, middle - 3, 7, middle + 4, fill="#ffffff", width=2, tags="breakpoint")
            if n == paused:
                self.gutter.create_polygon(2, middle - 4, 8, middle - 4, 8, middle - 7, 14, middle, 8, middle + 7,
                                           8, middle + 4, 2, middle + 4, fill=self.theme.arrow,
                                           outline=self.theme.foreground if n in breakpoints else "", tags="arrow")
            if n in problem_lines:
                self.gutter.create_oval(16, middle - 3, 22, middle + 3, fill=self.theme.problem, outline="", tags="problem")
            following = self.text.index(f"{index} +1line")
            if following == index:
                break  # the last line
            index = following

    def _whole_line_selected(self, n):
        return self.text.index("sel.first") == f"{n}.0" and self.text.compare("sel.last", ">=", f"{n}.0 lineend")

    def _select_lines(self, first, last):
        self.text.tag_remove("sel", "1.0", tk.END)
        self.text.tag_add("sel", f"{first}.0", f"{last + 1}.0")
        self.text.mark_set("insert", f"{last + 1}.0")

    def _newline(self, _):
        """Enter, with the next line indented to suit what's before the cursor (one undo step)."""
        if self.completions.accept():
            return "break"
        if self.text.tag_ranges("sel"):
            self.text.delete("sel.first", "sel.last")
        before = self.text.get("insert linestart", "insert")
        after = self.text.get("insert", "insert lineend")
        base = before[: len(before) - len(before.lstrip())]
        code, open_brackets = _scan(before)
        code = code.rstrip()
        between_pair = before[-1:] in _PAIRS and after[:1] == _PAIRS[before[-1]]
        if between_pair:
            indent = base  # the closer's line; the cursor goes on an indented line above it
        elif open_brackets:
            column = open_brackets[-1]
            # A bracket ending the line: one level in. Code after it: line up just after the bracket.
            indent = base + INDENT if column == len(code) - 1 else " " * (column + 1)
        elif code.endswith(":"):
            indent = base + INDENT
        elif _ENDS_BLOCK.match(code.lstrip()):
            indent = base[: max(0, len(base) - len(INDENT))]  # nothing more can follow in this block
        else:
            indent = base

        def change():
            spaces_after = len(after) - len(after.lstrip(" "))
            if spaces_after:
                self.text.delete("insert", f"insert +{spaces_after}c")  # the rest of the line starts at the indent
            if not before.strip():
                self.text.delete("insert linestart", "insert")  # a line of only spaces is left empty
            if between_pair:
                self.text.insert("insert", "\n" + indent + INDENT + "\n" + indent)
                self.text.mark_set("insert", f"insert -{len(indent) + 1}c")
            else:
                self.text.insert("insert", "\n" + indent)

        self._one_step(change)
        self.text.see("insert")
        return "break"

    def apply_theme(self, theme):
        """Show the code in a theme's colors (see themes.py)."""
        self.theme = theme
        self.text.configure(background=theme.background, foreground=theme.foreground,
                            insertbackground=theme.cursor, selectbackground=theme.selection,
                            selectforeground=theme.foreground, inactiveselectbackground=theme.selection)
        self.gutter.configure(background=theme.gutter)
        for tag, color in theme.tokens.items():
            self.text.tag_configure(tag, foreground=color)
        self.text.tag_configure("error", background=theme.error)
        self.text.tag_configure("breakpoint", background=theme.breakpoint_bg)
        self.text.tag_configure("changed", background=theme.changed)
        self.text.tag_configure("current", background=theme.current)
        self.error_bar.configure(background=theme.error, foreground=theme.error_text)
        self.problem_bar.configure(background=theme.problem_bg, foreground=theme.problem)
        self.note_bar.configure(background=theme.gutter, foreground=theme.number_current)
        try:
            self.text.tag_configure("problem", underline=True, underlinefg=theme.problem)
            self._underline = {"underline": True, "underlinefg": theme.problem}
        except tk.TclError:  # a Tk before 8.6.6 can't color underlines
            self._underline = {"underline": True}
        for tag in self._problem_tags:
            self.text.tag_configure(tag, **self._underline)
        completions = getattr(self, "completions", None)  # (made after the first apply_theme)
        if completions is not None and completions.is_open():
            completions.close()  # it opens again in the new colors
        self._show_numbers()

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

    def show_note(self, text):
        """A note above the code, like the one saying edits during a run wait for the next."""
        self.note_bar.configure(text=text)
        if not self.note_bar.winfo_ismapped():
            self.note_bar.pack(fill=tk.X, before=self._body)

    def clear_note(self):
        self.note_bar.pack_forget()

    # ----- values under the mouse, while paused -----

    def expression_at(self, x, y):
        """The name under the mouse at (x, y) in the text, with the dotted names before it
        (self.basket.append over "basket" is self.basket), or "" if it isn't on one."""
        index = self.text.index(f"@{x},{y}")
        box = self.text.bbox(index)
        if box is None or not (box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[3]):
            return ""  # past the end of the line, or below the last
        tags = self.text.tag_names(index)
        if "comment" in tags or "string" in tags:
            return ""
        text = self.text.get(f"{index} linestart", f"{index} lineend")
        column = int(index.split(".")[1])

        def name_char(c):
            return c.isalnum() or c == "_"

        if column >= len(text) or not name_char(text[column]):
            return ""
        end = column
        while end < len(text) and name_char(text[end]):
            end += 1
        start = column
        while start > 0 and (name_char(text[start - 1]) or text[start - 1] == "."):
            start -= 1
        found = text[start:end]
        # Not after a call or an index (f().x), not a number, not a keyword like "for".
        if found.startswith(".") or ".." in found or found[0].isdigit() or keyword.iskeyword(found):
            return ""
        if start > 0 and text[start - 1] in ")]\"'":
            return ""
        return found

    def _mouse_moved(self, e):
        if self.on_hover is None:
            return
        expression = self.expression_at(e.x, e.y)
        if self._tip is not None and self._tip[1] == expression:
            return  # still on the same name
        self.hide_tip()
        if expression:
            x, y = e.x_root, e.y_root
            self._hover_job = self.after(450, lambda: self._hover(expression, x, y))

    def _hover(self, expression, x, y):
        self._hover_job = None
        if self.on_hover is not None:
            self.on_hover(expression, x, y)

    def show_tip(self, expression, text, x, y):
        """Show a value under the mouse (the IDE's answer to on_hover)."""
        self.hide_tip()
        window = tk.Toplevel(self)
        window.wm_overrideredirect(True)  # no title bar or border from the window manager
        chrome = self.theme.chrome
        tk.Label(window, text=text, font=MONO, justify="left", wraplength=640, padx=4, pady=2, relief="solid", bd=1,
                 background=chrome.window if chrome else "#ffffe1",
                 foreground=chrome.text if chrome else "#000000").pack()
        window.wm_geometry(f"+{x + 12}+{y + 16}")
        self._tip = (window, expression)

    def hide_tip(self):
        if self._hover_job is not None:
            self.after_cancel(self._hover_job)
            self._hover_job = None
        if self._tip is not None:
            try:
                self._tip[0].destroy()
            except tk.TclError:
                pass
            self._tip = None

    # ----- debugging -----

    def show_paused(self, line):
        """While the program is paused: the line it's at, in yellow with an arrow (as in VB)."""
        self.clear_paused()
        self.text.mark_set("paused", f"{line}.0")
        self.text.mark_gravity("paused", tk.LEFT)
        self.text.tag_add("current", f"{line}.0", f"{line}.0 lineend +1c")
        code = self.text.get(f"{line}.0", f"{line}.0 lineend")
        self.text.mark_set("insert", f"{line}.{len(code) - len(code.lstrip())}")  # at its first word
        self.text.see(f"{line}.0")
        self._show_numbers()

    def clear_paused(self):
        if "paused" in self.text.mark_names():
            self.text.mark_unset("paused")
        self.text.tag_remove("current", "1.0", tk.END)
        self.text.tag_remove("changed", "1.0", tk.END)
        self._show_numbers()

    def show_changed(self, line):
        """While paused by a watch: the line that changed its value (it pauses on a later one)."""
        self.text.tag_add("changed", f"{line}.0", f"{line}.0 lineend +1c")

    def paused_line(self):
        if "paused" not in self.text.mark_names():
            return None
        return int(self.text.index("paused").split(".")[0])

    def breakpoint_lines(self):
        """The lines with breakpoints, in order."""
        return sorted({int(self.text.index(mark).split(".")[0]) for mark in self._breakpoints})

    def can_break_at(self, line):
        """Whether a breakpoint can go on a line: one with code (not blank, nor only a comment)."""
        if not 1 <= line <= int(self.text.index("end-1c").split(".")[0]):
            return False
        code = self.text.get(f"{line}.0", f"{line}.0 lineend").strip()
        return bool(code) and not code.startswith("#")

    def breakpoints(self):
        """The breakpoints, in order: a line number, or with a condition or hit count
        {line, condition, hit_mode, hits}."""
        found = {}
        for mark, settings in self._breakpoints.items():
            line = int(self.text.index(mark).split(".")[0])
            if line not in found or settings:  # (two on one line, after an edit: the one with settings)
                found[line] = {"line": line, **settings} if settings else line
        return [found[line] for line in sorted(found)]

    def breakpoint_settings(self, line):
        """A breakpoint's {condition, hit_mode, hits} ({} for none), or None if there's no breakpoint."""
        found = None
        for mark, settings in self._breakpoints.items():
            if int(self.text.index(mark).split(".")[0]) == line:
                found = settings if found is None or settings else found
        return found

    def set_breakpoints(self, items):
        """Put breakpoints on these lines (and remove any others), skipping lines that can't have
        one. An item is a line, or {line, condition, hit_mode, hits}."""
        for mark in self._breakpoints:
            self.text.mark_unset(mark)
        self._breakpoints = {}
        for item in items:
            line = item["line"] if isinstance(item, dict) else item
            if self.can_break_at(line):
                self._add_breakpoint(line, {k: v for k, v in item.items() if k != "line" and v}
                                     if isinstance(item, dict) else {})
        self._show_numbers()

    def set_breakpoint_settings(self, line, settings):
        """Give a line's breakpoint (made if needed) a condition and hit count ({} for none).
        Returns False if the line can't have one."""
        if self.on_breakpoints is None or not self.can_break_at(line):
            self.bell()
            return False
        self._remove_breakpoints(line)
        self._add_breakpoint(line, {k: v for k, v in settings.items() if v})
        self._show_numbers()
        self.on_breakpoints()
        return True

    def _add_breakpoint(self, line, settings):
        self._next_breakpoint += 1
        mark = f"breakpoint{self._next_breakpoint}"
        self.text.mark_set(mark, f"{line}.0")
        self.text.mark_gravity(mark, tk.LEFT)
        self._breakpoints[mark] = settings

    def _remove_breakpoints(self, line):
        """Remove the breakpoints on a line. Returns whether there were any."""
        on_line = [mark for mark in self._breakpoints if int(self.text.index(mark).split(".")[0]) == line]
        for mark in on_line:
            self.text.mark_unset(mark)
            del self._breakpoints[mark]
        return bool(on_line)

    def toggle_breakpoint(self, line=None):
        """F9: set or clear a breakpoint on a line (the cursor's). Returns whether one was set or cleared."""
        if line is None:
            line = int(self.text.index("insert").split(".")[0])
        if self.on_breakpoints is None:
            self.bell()  # code from outside the project
            return False
        if self._remove_breakpoints(line):
            pass
        elif self.can_break_at(line):
            self._add_breakpoint(line, {})
        else:
            self.bell()
            return False
        self._show_numbers()
        self.on_breakpoints()
        return True

    def _gutter_line(self, y):
        """The line at a height in the line numbers, or None below the last line."""
        index = self.text.index(f"@0,{y}")
        place = self.text.dlineinfo(index)
        if place is not None and place[1] <= y < place[1] + place[3]:
            return int(index.split(".")[0])
        return None

    def _gutter_click(self, e):
        line = self._gutter_line(e.y)
        if line is not None:
            self.toggle_breakpoint(line)

    def _gutter_menu(self, e):
        line = self._gutter_line(e.y)
        if line is not None and self.on_gutter_menu is not None:
            self.on_gutter_menu(line, e)
        return "break"

    def _on_modified(self, _):
        if not self.text.edit_modified():
            return
        self.text.edit_modified(False)
        self.clear_error()  # once the code changes, the error may no longer be there
        if self.on_edited is not None:
            self.on_edited()
        self._show_numbers()
        if self.on_change:
            if self._change_job:
                self.after_cancel(self._change_job)
            self._change_job = self.after(800, self._changed)
        if self._highlight_job:
            self.after_cancel(self._highlight_job)
        self._highlight_job = self.after(200, self.highlight)
        self.app.update_title()

    def highlight(self):
        self._highlight_job = None
        for tag in highlight.COLORS:
            self.text.tag_remove(tag, "1.0", tk.END)
        for tag, start, end in highlight.spans(self.get_source()):
            self.text.tag_add(tag, start, end)
