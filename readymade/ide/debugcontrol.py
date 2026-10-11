"""Break mode, from the IDE's side: stepping and the debug windows, breakpoints and watches
as commands (the menus, the line numbers' clicks, the Breakpoints and Watches tabs), and
telling the running program about them. Where they're kept is breakpoints.py; the link with
the program is debugging.py."""

from __future__ import annotations

import tkinter as tk

from readymade import usersettings
from readymade.ide import options
from readymade.ide.breakpoints import Breakpoints
from readymade.ide.debugging import BreakpointDialog, WatchDialog, function_at
from readymade.ide.part import Part
from readymade.protocol import STEPPING, Cmd


class DebugControl(Part):
    def __init__(self, app):
        super().__init__(app)
        self.breakpoints = Breakpoints(app)  # where breakpoints and watches are kept
        self._break_split = 0.5  # with the debug windows showing, the Immediate window's share of the bottom's width
        self._debug_windows_shown = False
        # View > Debug Windows: Locals, Watches and Call Stack show while running or stopped too (always in break mode).
        self.keep_debug_windows = tk.BooleanVar(app.root, usersettings.get("debug-windows", False) is True)
        self._gutter_popup = None

    def show_break_mode(self, on):
        """Break mode: the bottom area splits, with Locals, Watches and Call Stack beside the Immediate window."""
        if on and not self.app.in_break_mode:
            self.app.bottom.select(self.immediate)
        self.app.in_break_mode = on
        self.update_debug_windows()
        self.app.update_title()

    def show_debug_window(self, panel):
        """View > Locals, Watches or Call Stack: show the debug windows, with that one in front."""
        if not self.keep_debug_windows.get():
            self.keep_debug_windows.set(True)
            self.debug_windows_toggled()
        self.app.debug_tabs.select(panel)

    def debug_windows_toggled(self):
        usersettings.set("debug-windows", self.keep_debug_windows.get())
        self.update_debug_windows()

    def update_debug_windows(self):
        """The debug windows show in break mode, and whenever View > Debug Windows is ticked."""
        show = self.app.in_break_mode or self.keep_debug_windows.get()
        if show and not self._debug_windows_shown:
            self.app.bottom_area.add(self.app.debug_tabs, weight=1)
            self._place_split()
        elif not show and self._debug_windows_shown:
            width = self.app.bottom_area.winfo_width()
            if width > 1:
                self._break_split = min(0.85, max(0.15, self.app.bottom_area.sashpos(0) / width))  # as it was dragged
            self.app.bottom_area.forget(self.app.debug_tabs)
        self._debug_windows_shown = show

    def _place_split(self, tries=25):
        self.app.bottom_area.update_idletasks()  # (laid out first, or the new pane stays squeezed shut)
        width = self.app.bottom_area.winfo_width()
        if width < 50:  # the window isn't showing yet
            if tries:
                self.root.after(200, lambda: self._place_split(tries - 1))
            return
        if self._debug_windows_shown:
            self.app.bottom_area.sashpos(0, int(width * self._break_split))

    def debug_go(self, how, **extra):
        """Continue (F5), Step Into (F11), Step Over (F10) or Step Out (Shift+F11) while paused."""
        session = self.app.session
        if session is None and how in (Cmd.STEP, Cmd.NEXT) and self.project is not None:
            self.app.runner.run(step=True)  # F10 or F11 starts the program, stepping (as VB's F8 did)
            return
        if session is None or session.paused is None:
            return
        if how in STEPPING and not session.can_step():
            self.immediate.write("(After an error the program can't step on: Continue skips the rest of the event.)\n")
            return
        session.go(how, **extra)

    def run_to_cursor(self):
        """Ctrl+F10: go on until the line with the cursor."""
        editor = self.app.code_editor()
        if editor is not None:
            self.debug_go(Cmd.UNTIL, file=str(editor.code_path), line=int(editor.code.text.index("insert").split(".")[0]))

    def pause(self):
        """F6: break into the running program. It's idle between events, so it breaks as the next one starts."""
        if self.app.session is None or self.app.in_break_mode:
            return
        self.app.session.send(cmd=Cmd.PAUSE)
        self.immediate.write("--- Pausing: the program breaks when its next event starts (a click, a key, a timer). ---\n")

    # When the Debug menu's commands can be used:

    def is_paused(self):
        return self.app.in_break_mode and self.app.session is not None and self.app.session.paused is not None

    def can_step(self):
        """Paused where it can go on a step at a time (not after an error)."""
        return self.is_paused() and self.app.session.can_step()

    def can_start(self):
        """Nothing running: F10 or F11 starts the program, pausing as its first event starts."""
        return self.app.session is None and self.app.process is None and self.project is not None

    def can_pause(self):
        return self.app.session is not None and not self.app.in_break_mode

    def toggle_breakpoint(self):
        """F9: set or clear a breakpoint on the cursor's line."""
        editor = self.app.code_editor()
        if editor is not None:
            editor.code.toggle_breakpoint()

    def breakpoint_condition(self, editor=None, line=None):
        """Debug > Breakpoint Condition: a condition and hit count for the breakpoint on a line
        (the cursor's), which gets one if it hasn't."""
        editor = editor or self.app.code_editor()
        if editor is None or not editor.is_project_code:
            return None
        if line is None:
            line = int(editor.code.text.index("insert").split(".")[0])
        if not editor.code.can_break_at(line):
            self.root.bell()
            return None
        current = editor.code.breakpoint_settings(line) or {}
        return BreakpointDialog(self.app, line, current, lambda settings: editor.code.set_breakpoint_settings(
            line, {**settings, "disabled": current.get("disabled", False)}))  # (switched off stays off)

    def set_next_statement(self, editor=None, line=None):
        """Ctrl+Shift+F10, while paused: go on from another line (the cursor's) of the paused function."""
        editor = editor or self.app.code_editor()
        if editor is None or self.app.session is None or self.app.session.paused is None:
            return
        if line is None:
            line = int(editor.code.text.index("insert").split(".")[0])
        self.app.session.send(cmd=Cmd.JUMP, file=str(editor.code_path), line=line)

    def gutter_menu(self, editor, line, e):
        """A right-click in the line numbers."""
        menu = self._gutter_popup
        if menu is None:
            menu = self._gutter_popup = tk.Menu(self.root, tearoff=False)
        menu.delete(0, tk.END)
        has = editor.code.breakpoint_settings(line) is not None
        menu.add_command(label="Remove Breakpoint" if has else "Add Breakpoint",
                         command=lambda: editor.code.toggle_breakpoint(line))
        if has:
            off = editor.code.breakpoint_settings(line).get("disabled")
            menu.add_command(label="Switch Breakpoint On" if off else "Switch Breakpoint Off",
                             command=lambda: self.switch_breakpoint(self.project.relative(editor.code_path), line))
        menu.add_command(label="Breakpoint Condition...", command=lambda: self.breakpoint_condition(editor, line))
        if self.app.session is not None and self.app.session.paused is not None and self.app.session.can_step():
            menu.add_separator()
            menu.add_command(label="Run to Here",
                             command=lambda: self.debug_go(Cmd.UNTIL, file=str(editor.code_path), line=line))
            menu.add_command(label="Set Next Statement", command=lambda: self.set_next_statement(editor, line))
        options.color_menus(menu, options.theme().chrome)
        menu.tk_popup(e.x_root, e.y_root)
        return menu

    def clear_breakpoints(self):
        """Debug > Clear All Breakpoints (Ctrl+Shift+F9)."""
        self.breakpoints.clear()
        self.breakpoints_changed()

    def change_breakpoint(self, file, line, change):
        """Change a breakpoint (change(settings) -> new settings; None removes it): see Breakpoints.change."""
        if self.breakpoints.change(file, line, change):
            self.breakpoints_changed()  # (an open file's code says so itself)

    def file_renamed(self, old, new):
        """A file was renamed (relative names): its breakpoints and watches go with it."""
        if self.breakpoints.file_renamed(old, new):
            self.set_watches(self.breakpoints.watches())  # (the running program hears)
        self.show_breakpoints()

    def breakpoints_changed(self):
        """A breakpoint was set or cleared: remember it, and tell the running program."""
        self.breakpoints.store()
        self.show_breakpoints()
        if self.app.session is not None:
            self.app.session.send(cmd=Cmd.BREAKPOINTS, breakpoints=self.breakpoints.for_program())

    def show_breakpoints(self):
        """Fill the Breakpoints tab: every breakpoint, with its line's code."""
        self.app.breakpoints_panel.show(self.breakpoints.rows(), self.breakpoints.breaking_watches())

    def breakpoints_tab_watch(self, action, index):
        """A watch that breaks, chosen in the Breakpoints tab: shown in the Watches tab, or edited."""
        if action == "condition":
            self.edit_watch(index)
        elif action == "remove":
            self.delete_watch(index)
        else:
            self.show_debug_window(self.app.watches_panel)
            self.app.watches_panel.choose(index)

    def open_breakpoint(self, file, line):
        editor = self.app.open_code(self.project.folder / file)
        if editor is not None:
            editor.code.show_location(line, 0)
        return editor

    def go_to_breakpoint(self, file, line):
        """The Breakpoints tab's choice: show its line."""
        self.open_breakpoint(file, line)

    def switch_breakpoint(self, file, line):
        """Switch a breakpoint off (it stays, hollow, but doesn't stop the program) or back on."""
        self.change_breakpoint(file, line, lambda settings: {**settings, "disabled": not settings.get("disabled")})

    def set_watches(self, watches):
        if self.project is None:
            return
        self.breakpoints.save_watches(watches)
        self.show_breakpoints()  # (watches that break are listed there too)
        if self.app.session is not None:
            self.app.session.send(cmd=Cmd.WATCHES, watches=watches)  # paused, it answers with their values
        if not self.app.in_break_mode:
            self.app.watches_panel.show(watches)

    def add_watch(self, expression=None):
        """Debug > Add Watch: for the selected text (or the name at the cursor), in the function there."""
        if self.project is None:
            return
        watch = {"expression": expression or ""}
        editor = self.app.code_editor()
        if editor is not None and editor.is_project_code:
            text = editor.code.text
            line = int(text.index("insert").split(".")[0])
            if not expression:
                watch["expression"] = (text.get("sel.first", "sel.last") if text.tag_ranges("sel")
                                       else text.get("insert wordstart", "insert wordend")).strip()
            watch["file"] = self.project.relative(editor.code_path)
            watch["function"] = function_at(editor.code.get_source(), line)

        def added(new):
            self.set_watches([*self.breakpoints.watches(), new])
            self.show_debug_window(self.app.watches_panel)
        return WatchDialog(self.app, watch, added)

    def edit_watch(self, index):
        if index is None:
            return self.add_watch()
        watches = self.breakpoints.watches()

        def edited(new):
            self.set_watches([new if i == index else w for i, w in enumerate(watches)])
        return WatchDialog(self.app, watches[index], edited, title="Edit Watch")

    def delete_watch(self, index):
        self.set_watches([w for i, w in enumerate(self.breakpoints.watches()) if i != index])

    def quick_watch(self):
        """Shift+F9, while paused: the value of the selected text (or the name at the cursor)."""
        editor = self.app.code_editor()
        if self.app.session is None or self.app.session.paused is None or editor is None:
            return
        text = editor.code.text
        expression = (text.get("sel.first", "sel.last") if text.tag_ranges("sel")
                      else text.get("insert wordstart", "insert wordend")).strip()
        if expression:
            self.app.session.send(cmd=Cmd.QUICK, expression=expression)

    def code_edited(self, code):
        """Code changed: during a run, say the program won't see it until the next."""
        if self.app.session is not None:
            code.show_note("The program is running this code as it was when it started: "
                           "changes take effect the next time it runs.")

    def hovered(self, code, expression, x, y):
        if self.app.session is not None and self.app.in_break_mode:
            self.app.session.ask_tip(code, expression, x, y)
