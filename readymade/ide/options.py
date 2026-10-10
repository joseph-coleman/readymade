"""The IDE's options (Tools > Options..., or Preferences... on a Mac): the code font, the
indent width and the color theme. They're your own, for all your projects, kept in
your user settings (see readymade.usersettings):

    "code-font": "Consolas, 11"    ("" for the system's usual fixed-width font)
    "indent-width": 4              (spaces for Tab; generated handlers always use 4)
    "theme": "light"               (or "dark")
    "break-on-errors": true        (an error in an event handler pauses the program there)
"""

from __future__ import annotations

import sys
import tkinter as tk
import weakref
from tkinter import font as tkfont
from tkinter import ttk

from readymade import appearance, usersettings
from readymade.ide import themes

CODE_FONT = "ReadymadeCode"  # the named font code shows in; changing it changes every place at once
INDENTS = (2, 4, 8)


def code_font():
    """The code font option, like "Consolas, 11"; "" for the usual."""
    try:
        return appearance.format_font(usersettings.get("code-font", ""))
    except ValueError:
        return ""


def indent_width():
    width = usersettings.get("indent-width", 4)
    return width if width in INDENTS else 4


def break_on_errors():
    return usersettings.get("break-on-errors", True) is not False


def theme():
    return themes.THEMES.get(usersettings.get("theme", "light"), themes.LIGHT)


def ensure_code_font(widget):
    """Make the named code font (once per Tk), from the option. Returns its name."""
    if CODE_FONT not in widget.tk.splitlist(widget.tk.call("font", "names")):
        widget.tk.call("font", "create", CODE_FONT, *_font_options(widget))
    return CODE_FONT


def _font_options(widget):
    usual = tkfont.nametofont("TkFixedFont", root=widget).actual()
    family, size, styles = appearance.parse_font(code_font())
    return ("-family", family or usual["family"], "-size", size or usual["size"],
            "-weight", "bold" if "bold" in styles else "normal",
            "-slant", "italic" if "italic" in styles else "roman")


def apply(app):
    """Put the options into effect in the running IDE: fonts, indents and colors change at once."""
    from readymade.ide import codeview

    ensure_code_font(app.root)
    app.root.tk.call("font", "configure", CODE_FONT, *_font_options(app.root))
    codeview.set_indent(indent_width())
    chosen = theme()
    apply_chrome(app, chosen.chrome)
    for editor in app.editors:
        editor.code.apply_theme(chosen)
    for panel in (app.immediate, app.help, app.problems, app.locals, app.watches_panel, app.call_stack):
        panel.apply_theme(chosen)


DARK_TTK = "readymade-dark"  # the ttk theme of the Dark option; Light is the IDE's usual one (clam)


def apply_chrome(app, chrome):
    """Color the IDE around the code: chrome's colors, or with None the usual look."""
    style = ttk.Style(app.root)
    if chrome is None:
        style.theme_use(app.light_theme)
    else:
        if DARK_TTK not in style.theme_names():
            _create_dark_theme(style, chrome, app.light_theme)
        style.theme_use(DARK_TTK)
    _style_own(style, chrome)
    window = style.lookup(".", "background")
    app.root.configure(background=window)
    app.root.option_add("*Toplevel.background", window)  # dialogs opened later
    app.toolbox.apply_chrome(chrome)
    app.properties.apply_chrome(chrome)
    for editor in app.editors:
        surface = getattr(editor, "surface", None)
        if surface is not None:
            surface.apply_chrome(chrome)
    _color_menus(app.root.nametowidget(app.root["menu"]), chrome)
    for menu in (app.explorer.menu, app.explorer.python_menu, app.explorer.libraries_menu):
        _color_menus(menu, chrome)
    dark_title_bar(app.root, chrome is not None)


def _style_own(style, chrome):
    """readymade's own ttk styles, which each theme needs (a theme keeps its own styles)."""
    style.configure("Dots.TButton", padding=(2, 0))
    style.configure("Note.TLabel", foreground=chrome.note if chrome else "gray40")


# ttk's standard styles. A new theme takes its parent's drawing but not these styles' settings
# (like the tabs' padding), so the dark theme starts from copies of them.
_STANDARD_STYLES = (
    ".", "TButton", "Toolbutton", "TCheckbutton", "TRadiobutton", "TCombobox", "TEntry", "TSpinbox", "TFrame",
    "TLabel", "TLabelframe", "TLabelframe.Label", "TMenubutton", "TNotebook", "TNotebook.Tab", "TPanedwindow",
    "Sash", "TProgressbar", "TScale", "TScrollbar", "TSeparator", "TSizegrip", "Treeview", "Treeview.Heading",
    "Heading", "Item", "Cell",
)


def _create_dark_theme(style, c, light):
    # The form's ComboBoxes in the designer keep the light look: they show the running program.
    preview = {key: style.lookup("TCombobox", key) for key in ("fieldbackground", "foreground", "background", "arrowcolor")}
    copied = {name: {"configure": style.configure(name) or {}, "map": style.map(name) or {}}
              for name in _STANDARD_STYLES}  # (the light theme is the one in use here)
    style.theme_create(DARK_TTK, parent=light, settings=copied)
    style.theme_settings(DARK_TTK, {
        ".": {
            "configure": {"background": c.window, "foreground": c.text, "fieldbackground": c.field,
                          "bordercolor": c.border, "lightcolor": c.button, "darkcolor": c.window,
                          "troughcolor": c.trough, "selectbackground": c.selection, "selectforeground": c.text,
                          "insertcolor": c.text, "arrowcolor": c.text, "focuscolor": c.border},
            "map": {"foreground": [("disabled", c.disabled)], "fieldbackground": [("disabled", c.window)]},
        },
        "TButton": {"configure": {"background": c.button},
                    "map": {"background": [("pressed", c.button_active), ("active", c.button_active)]}},
        "TEntry": {"configure": {"fieldbackground": c.field}},
        "TCombobox": {"configure": {"fieldbackground": c.field, "background": c.button},
                      "map": {"fieldbackground": [("readonly", c.field)], "foreground": [("readonly", c.text)],
                              "background": [("active", c.button_active)]}},
        "Preview.TCombobox": {"configure": preview,
                              "map": {"fieldbackground": [("readonly", preview["fieldbackground"])],
                                      "foreground": [("readonly", preview["foreground"])]}},
        "Treeview": {"configure": {"background": c.field, "fieldbackground": c.field, "foreground": c.text},
                     "map": {"background": [("selected", c.selection)], "foreground": [("selected", c.text)]}},
        "Treeview.Heading": {"configure": {"background": c.button, "foreground": c.text},
                             "map": {"background": [("active", c.button_active)]}},
        "TNotebook": {"configure": {"background": c.window, "bordercolor": c.border}},
        "TNotebook.Tab": {"configure": {"background": c.tab, "foreground": c.text, "bordercolor": c.border},
                          "map": {"background": [("selected", c.window), ("active", c.button_active)]}},
        "TScrollbar": {"configure": {"background": c.button, "troughcolor": c.trough, "bordercolor": c.border},
                       "map": {"background": [("active", c.button_active)]}},
        "TCheckbutton": {"configure": {"indicatorbackground": c.field, "indicatorforeground": c.text},
                         "map": {"background": [("active", c.window)]}},
        "TRadiobutton": {"configure": {"indicatorbackground": c.field, "indicatorforeground": c.text},
                         "map": {"background": [("active", c.window)]}},
    })


_usual_menu_colors: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()  # menu -> its colors before Dark


def _color_menus(menu, chrome):
    """Menus, where the system lets Tk color them (Linux; Windows and macOS draw their own)."""
    if menu not in _usual_menu_colors:
        _usual_menu_colors[menu] = {key: menu.cget(key) for key in
                                    ("background", "foreground", "activebackground", "activeforeground", "selectcolor")}
    colors = _usual_menu_colors[menu] if chrome is None else {
        "background": chrome.window, "foreground": chrome.text, "activebackground": chrome.selection,
        "activeforeground": chrome.text, "selectcolor": chrome.text}
    menu.configure(**colors)
    end = menu.index("end")
    for index in range(end + 1 if end is not None else 0):
        if menu.type(index) == "cascade":
            _color_menus(menu.nametowidget(menu.entrycget(index, "menu")), chrome)


def dark_title_bar(window, dark):
    """On Windows 10 and 11, a dark title bar (the system draws it, so Tk's colors can't)."""
    if sys.platform != "win32":
        return
    try:
        import ctypes

        window.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(window.winfo_id())
        value = ctypes.c_int(1 if dark else 0)
        for attribute in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE; 19 before Windows 10 20H1
            if ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attribute, ctypes.byref(value), ctypes.sizeof(value)) == 0:
                break
        ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x0027)  # redraw the frame (NOMOVE|NOSIZE|NOZORDER|FRAMECHANGED)
    except (AttributeError, OSError):
        pass  # an older Windows: the title bar stays as it is


class OptionsDialog(tk.Toplevel):
    """Tools > Options...: choose the code font, indent width, theme and whether to break on
    errors. OK saves and applies them."""

    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        self.title("Options")
        self.transient(app.root)
        self.resizable(False, False)
        self.font = tk.StringVar(self, code_font())
        self.indent = tk.StringVar(self, str(indent_width()))
        self.theme = tk.StringVar(self, theme().name)
        self.break_on_errors = tk.BooleanVar(self, break_on_errors())

        body = ttk.Frame(self, padding=12)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, text="Code font:").grid(row=0, column=0, sticky="w", pady=4)
        shown = ttk.Label(body, width=28, relief="sunken", padding=(4, 1))
        shown.grid(row=0, column=1, sticky="w", padx=(8, 4))
        self.font.trace_add("write", lambda *_: shown.configure(text=self.font.get() or "(the usual)"))
        shown.configure(text=self.font.get() or "(the usual)")
        ttk.Button(body, text="…", width=3, command=self._choose_font).grid(row=0, column=2)
        ttk.Button(body, text="Usual", command=lambda: self.font.set("")).grid(row=0, column=3, padx=(4, 0))
        ttk.Label(body, text="Indent:").grid(row=1, column=0, sticky="w", pady=4)
        indent = ttk.Frame(body)
        indent.grid(row=1, column=1, columnspan=3, sticky="w", padx=(8, 0))
        ttk.Combobox(indent, textvariable=self.indent, values=[str(n) for n in INDENTS], state="readonly",
                     width=4).pack(side=tk.LEFT)
        ttk.Label(indent, text="spaces").pack(side=tk.LEFT, padx=(4, 0))
        ttk.Label(body, text="Theme:").grid(row=2, column=0, sticky="w", pady=4)
        choices = ttk.Frame(body)
        choices.grid(row=2, column=1, columnspan=3, sticky="w", padx=(8, 0))
        for name, label in (("light", "Light"), ("dark", "Dark")):
            ttk.Radiobutton(choices, text=label, value=name, variable=self.theme).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Checkbutton(body, text="Break on errors in event handlers (when run from here)",
                        variable=self.break_on_errors).grid(row=3, column=0, columnspan=4, sticky="w", pady=4)
        ttk.Label(body, text="These are yours, for all your projects.", style="Note.TLabel").grid(
            row=4, column=0, columnspan=4, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(body)
        buttons.grid(row=5, column=0, columnspan=4, sticky="e", pady=(12, 0))
        ttk.Button(buttons, text="OK", command=self.ok).pack(side=tk.LEFT)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.LEFT, padx=(4, 0))
        self.bind("<Return>", lambda e: self.ok())
        self.bind("<Escape>", lambda e: self.destroy())

    def _choose_font(self):
        from readymade.dialogs import FontChooser

        chosen = FontChooser.ask(self, self.font.get(), title="Code Font")
        if chosen is not None:
            self.font.set(chosen)

    def ok(self):
        usersettings.set("code-font", self.font.get())
        usersettings.set("indent-width", int(self.indent.get()))
        usersettings.set("theme", self.theme.get())
        usersettings.set("break-on-errors", self.break_on_errors.get())
        apply(self.app)
        if self.app.session is not None:  # the running program too
            self.app.session.send(cmd="break_on_errors", on=self.break_on_errors.get())
        self.destroy()
