"""The TextBox control."""

from __future__ import annotations

import tkinter as tk

from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import Aligned, Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip


SCROLLBARS = ("none", "horizontal", "vertical", "both")


@register
class TextBox(BackColor, ForeColor, Font, Aligned, TabStop, Cursor, Tooltip, Anchored, Control):
    """A text field. With multiline True it's a multi-line text area, optionally with
    scrollbars. As in VB, both are set in the designer, and scrollbars only apply to
    multi-line boxes. readonly, password and maxlength limit what the user can do;
    code can always set text. `editor` is the Entry or Text the user types in.
    """

    type_name = "TextBox"
    default_size = (120, 24)
    default_event = "change"
    recreate_props = ("multiline", "scrollbars")
    prop_choices = {"scrollbars": SCROLLBARS}
    events = (Event("change"), Event("keypress", ("key",)), *_FOCUS_EVENTS, Event("click"), Event("dblclick"))
    extra_props = {"text": "", "multiline": False, "scrollbars": "none", "readonly": False, "password": False,
                   "maxlength": 0}

    def __init__(self, parent, spec, design=False, folder=None):
        self._multiline = bool(spec.get("multiline", False))
        self._scrollbars = spec.get("scrollbars", "none")
        if self._scrollbars not in SCROLLBARS:
            raise ValueError(f"scrollbars must be one of: {', '.join(SCROLLBARS)}")
        super().__init__(parent, spec, design, folder)

    @classmethod
    def designer_changed(cls, spec, prop):
        super().designer_changed(spec, prop)
        if prop == "multiline" and not spec.get("multiline") and "\n" in spec.get("text", ""):
            spec["text"] = " ".join(spec["text"].splitlines())  # a single line can't hold line breaks

    def create_widget(self, parent):
        self._readonly = self._password = False
        self._maxlength = 0
        if not self._multiline:
            self._var = tk.StringVar(parent)
            self.editor = tk.Entry(parent, textvariable=self._var)
            # Tk checks each edit the user makes (not code's) with this before making it.
            self.editor.configure(validate="key", validatecommand=(self.editor.register(self._fits), "%P"))
            self._parts = [self.editor]
            return self.editor
        horizontal = self._scrollbars in ("horizontal", "both")
        vertical = self._scrollbars in ("vertical", "both")
        frame = tk.Frame(parent)
        # Long lines wrap unless there's a horizontal scrollbar, as in VB. The 1x1 size
        # request lets the frame's placed size decide the real size.
        self.editor = tk.Text(frame, width=1, height=1, font="TkTextFont", wrap="none" if horizontal else "word", undo=True)
        self.editor.grid(row=0, column=0, sticky="nsew")
        self.editor.bind("<Tab>", self._tab_out)
        # (On Windows, Shift+Tab is Tab with Shift held, which the <Tab> binding alone would take
        # forward; on X11 it's ISO_Left_Tab, which Tk turns into <<PrevWindow>> itself.)
        self.editor.bind("<Shift-Tab>", self._tab_back)
        self.editor.bind("<KeyPress>", self._limit_typing, add="+")  # maxlength (a Text can't validate)
        self.editor.bind("<<Paste>>", self._limit_paste, add="+")
        # A Text has no alignment of its own, only its tags', so keep all of its text tagged.
        self.editor.tag_configure("readymade-align", justify="left")
        for sequence in ("<KeyRelease>", "<ButtonRelease-2>"):
            self.editor.bind(sequence, self._retag, add="+")
        frame.rowconfigure(0, weight=1)
        frame.columnconfigure(0, weight=1)
        self._parts = [frame, self.editor]
        if vertical:
            bar = tk.Scrollbar(frame, orient=tk.VERTICAL, command=self.editor.yview)
            self.editor["yscrollcommand"] = bar.set
            bar.grid(row=0, column=1, sticky="ns")
            self._parts.append(bar)
        if horizontal:
            bar = tk.Scrollbar(frame, orient=tk.HORIZONTAL, command=self.editor.xview)
            self.editor["xscrollcommand"] = bar.set
            bar.grid(row=1, column=0, sticky="ew")
            self._parts.append(bar)
        return frame

    def widgets(self):
        return [self.editor]

    def design_widgets(self):
        return self._parts

    def _painted(self):
        return [w for w in self._parts if not isinstance(w, tk.Scrollbar)]

    def _paint(self):
        super()._paint()
        if self._ready and not self._multiline:
            self.editor["readonlybackground"] = self.editor["background"]  # read-only looks the same, as in VB
    def _font_widgets(self):
        return [self.editor]

    def _align(self, alignment, valignment):
        if self._multiline:
            self.editor.tag_configure("readymade-align", justify=alignment)
            self._retag()
        else:
            self.editor["justify"] = alignment

    def _retag(self, _=None):
        self.editor.tag_add("readymade-align", "1.0", "end")

    def _focus_widget(self):
        return self.editor

    @staticmethod
    def _tab_out(e):
        # As in VB, Tab moves to the next control rather than inserting a tab; the form does that.
        e.widget.event_generate("<<NextControl>>")
        return "break"

    @staticmethod
    def _tab_back(e):
        e.widget.event_generate("<<PrevWindow>>")
        return "break"

    @property
    def text(self):
        """What's in the box. Setting it replaces the contents (and raises change)."""
        return self.editor.get("1.0", "end-1c") if self._multiline else self._var.get()

    @text.setter
    def text(self, value):
        if not self._multiline:
            self._var.set(str(value))
            return
        # A disabled Text ignores edits, even from code.
        state = self.editor.cget("state")
        self.editor["state"] = tk.NORMAL
        self.editor.replace("1.0", "end-1c", str(value))
        self._retag()
        self.editor["state"] = state

    @property
    def multiline(self):
        """Whether it's a multi-line text area rather than a single line. Set in the designer."""
        return self._multiline

    @multiline.setter
    def multiline(self, value):
        self._design_only("multiline", self._multiline, bool(value))

    @property
    def scrollbars(self):
        """A multi-line box's scrollbars: "none", "horizontal", "vertical" or "both". Set in the designer."""
        return self._scrollbars

    @scrollbars.setter
    def scrollbars(self, value):
        self._design_only("scrollbars", self._scrollbars, value)

    @property
    def enabled(self):
        """Whether it responds to the user. A disabled control is grayed out."""
        return self._enabled

    @enabled.setter
    def enabled(self, value):
        self._enabled = bool(value)
        self._update_state()

    @property
    def readonly(self):
        """Whether the user can't change the text, as with VB's Locked. They can still select
        it (and in a single-line box, copy it). Code can still set text."""
        return self._readonly

    @readonly.setter
    def readonly(self, value):
        self._readonly = bool(value)
        self._update_state()

    @property
    def password(self):
        """Whether the text shows as dots, for passwords. Single-line boxes only."""
        return self._password

    @password.setter
    def password(self, value):
        self._password = bool(value)
        if not self._multiline:
            self.editor["show"] = "\u2022" if self._password else ""

    @property
    def maxlength(self):
        """The most characters the user can type or paste in; 0 for no limit. Code can still set longer text."""
        return self._maxlength

    @maxlength.setter
    def maxlength(self, value):
        value = int(value)
        if value < 0:
            raise ValueError("maxlength can't be negative (0 means no limit)")
        self._maxlength = value

    def _update_state(self):
        if not getattr(self, "_enabled", True):
            state = tk.DISABLED
        elif self._readonly:
            state = tk.DISABLED if self._multiline else "readonly"  # a Text has no read-only state
        else:
            state = tk.NORMAL
        self.editor["state"] = state

    def _fits(self, proposed):
        return not self._maxlength or len(proposed) <= self._maxlength

    def _limit_typing(self, e):
        """Stop typing into a full multi-line box (unless it replaces a selection)."""
        typing = (e.char and e.char.isprintable()) or e.keysym in ("Return", "KP_Enter")
        if self._maxlength and typing and not self.editor.tag_ranges("sel") and len(self.text) >= self._maxlength:
            return "break"
        return None

    def _limit_paste(self, e):
        """Paste only as much as fits into a multi-line box."""
        if not self._maxlength:
            return None
        try:
            pasted = self.editor.clipboard_get()
        except tk.TclError:
            return "break"  # nothing to paste
        selected = self.editor.tag_ranges("sel")
        replaced = len(self.editor.get(*selected)) if selected else 0
        room = max(0, self._maxlength - len(self.text) + replaced)
        if len(pasted) <= room:
            return None  # it all fits: paste as usual
        if selected:
            self.editor.delete(*selected)
        self.editor.insert("insert", pasted[:room])
        return "break"

    def bind_event(self, event, handler):
        if event != "change":
            super().bind_event(event, handler)
        elif not self._multiline:
            self._var.trace_add("write", lambda *_: handler())
        else:
            # Text raises <<Modified>> when its modified flag goes from clear to set, so
            # clear it each time, and compare the text so each change is reported once.
            editor = self.editor
            self._last_text = self.text
            editor.edit_modified(False)

            def modified(_):
                if not editor.edit_modified():
                    return
                editor.edit_modified(False)
                if self.text != self._last_text:
                    self._last_text = self.text
                    handler()

            editor.bind("<<Modified>>", modified, add="+")
