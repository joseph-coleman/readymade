"""Project > Linting... and Project > Formatting...: choose which tools work on the code.

Each tool can be chosen "For the project", saved in pyproject.toml for everyone
working on it, and in your own settings, for every project you open. The
dialog shows which tools the project's environment has, with Install for the
others.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from readymade import formatting, lint


class ToolDialog(tk.Toplevel):
    """tools: {name: tool}; shared, mine: the names chosen; switch: an optional extra row of
    two checkboxes, (label, shared, mine); on_ok(shared names, mine names, (shared, mine) switch)."""

    def __init__(self, app, title, intro, tools, shared, mine, on_ok, mine_heading, switch=None):
        super().__init__(app.root)
        self.app = app
        self.tools = tools
        self.on_ok = on_ok
        self.title(f"{title} - {app.project.name}")
        self.transient(app.root)

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, wraplength=560, justify="left", text=intro).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        for column, heading in enumerate(("Tool", "", "For the project", mine_heading, "")):
            ttk.Label(body, text=heading, foreground="gray30").grid(row=1, column=column, sticky="w", padx=4)

        self.shared, self.mine, self.status = {}, {}, {}
        row = 1
        for row, (name, tool) in enumerate(tools.items(), start=2):
            ttk.Label(body, text=name).grid(row=row, column=0, sticky="w", padx=4, pady=2)
            ttk.Label(body, text=tool.about, foreground="gray40").grid(row=row, column=1, sticky="w", padx=4)
            self.shared[name] = tk.BooleanVar(value=name in shared)
            self.mine[name] = tk.BooleanVar(value=name in mine)
            ttk.Checkbutton(body, variable=self.shared[name]).grid(row=row, column=2)
            ttk.Checkbutton(body, variable=self.mine[name]).grid(row=row, column=3)
            self.status[name] = ttk.Frame(body)
            self.status[name].grid(row=row, column=4, sticky="w", padx=4)

        self.switch = None
        if switch:
            label, on_shared, on_mine = switch
            row += 1
            ttk.Separator(body).grid(row=row, column=0, columnspan=5, sticky="ew", pady=6)
            row += 1
            ttk.Label(body, text=label).grid(row=row, column=0, columnspan=2, sticky="w", padx=4)
            self.switch = (tk.BooleanVar(value=bool(on_shared)), tk.BooleanVar(value=bool(on_mine)))
            ttk.Checkbutton(body, variable=self.switch[0]).grid(row=row, column=2)
            ttk.Checkbutton(body, variable=self.switch[1]).grid(row=row, column=3)

        self.where = ttk.Label(body, foreground="gray40")
        self.where.grid(row=row + 1, column=0, columnspan=5, sticky="w", pady=(8, 0))
        buttons = ttk.Frame(self, padding=(10, 0, 10, 10))
        buttons.pack(fill=tk.X)
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side=tk.RIGHT)
        ttk.Button(buttons, text="OK", command=self.ok).pack(side=tk.RIGHT, padx=(0, 4))
        self.bind("<Escape>", lambda e: self.destroy())
        self.refresh()
        self.grab_set()

    def refresh(self):
        """Show which tools the project's environment has, with Install for the others."""
        if not self.winfo_exists():
            return
        python, _ = self.app.python()
        found = lint.installed(python, self.tools.values(), self.app.environment())
        has_environment = self.app.project.python() is not None
        self.where.configure(text=f"Checked with {self.app.python_label()}." + (
            "" if has_environment else " To install tools, first create an environment (Project > Create Environment)."))
        for name, tool in self.tools.items():
            for child in self.status[name].winfo_children():
                child.destroy()
            if name in found or not tool.module:
                ttk.Label(self.status[name], text="installed" if name in found else "").pack(side=tk.LEFT)
            else:
                ttk.Label(self.status[name], text="not installed", foreground="#b00020").pack(side=tk.LEFT)
                if tool.package and has_environment:
                    ttk.Button(self.status[name], text="Install", command=lambda t=tool: self.install(t)).pack(side=tk.LEFT, padx=4)

    def install(self, tool):
        if self.app._idle():
            self.app._pip_install([tool.package], self.refresh, failed=f"pip couldn't install {tool.name}.")

    def ok(self):
        shared = [name for name, var in self.shared.items() if var.get()]
        mine = [name for name, var in self.mine.items() if var.get()]
        switch = tuple(var.get() for var in self.switch) if self.switch else None
        self.destroy()
        self.on_ok(shared, mine, switch)


def linting_dialog(app):
    project = app.project

    def chosen(shared, mine, _):
        lint.set_choices(project, shared, mine)
        app.linter.check_all()

    return ToolDialog(
        app, "Linting",
        "Choose the tools that check your code. \"For the project\" is shared with everyone working on it "
        "(pyproject.toml); \"All my projects\" is your own choice, used in every project you open. "
        "The tools' own settings (like ruff.toml or [tool.mypy]) apply as usual.",
        lint.definitions(project), *lint.choices(project), chosen, "All my projects",
    )


def formatting_dialog(app):
    project = app.project

    def chosen(shared, mine, on_save):
        formatting.set_choices(project, shared, mine)
        formatting.set_on_save(project, *on_save)

    return ToolDialog(
        app, "Formatting",
        "Choose the tools that tidy your code (Edit > Format Document, Shift+Alt+F). Formatting changes "
        "the code itself, so everyone on a project should use the same tools: \"For the project\" "
        "(pyproject.toml) is used when it's set, and \"My default\" for projects that haven't chosen. "
        "When several are chosen they run in the order listed. Their own settings (like [tool.black]) apply.",
        formatting.definitions(project), *formatting.choices(project), chosen, "My default",
        switch=("Format when saving", *formatting.on_save_choices(project)),
    )
