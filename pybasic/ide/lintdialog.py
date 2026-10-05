"""Project > Linting...: choose which tools check the project's code.

"For the project" is saved in pyproject.toml, for everyone working on it;
"All my projects" in your own settings, for every project you open.
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from pybasic import lint


class LintDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.app = app
        project = app.project
        self.title(f"Linting - {project.name}")
        self.transient(app.root)
        self.tools = lint.definitions(project)
        shared, mine = lint.choices(project)

        body = ttk.Frame(self, padding=10)
        body.pack(fill=tk.BOTH, expand=True)
        ttk.Label(body, wraplength=520, justify="left", text=(
            "Choose the tools that check your code. \"For the project\" is shared with everyone "
            "working on it (pyproject.toml); \"All my projects\" is your own choice, used in every "
            "project you open. The tools' own settings (like ruff.toml or [tool.mypy]) apply as usual."
        )).grid(row=0, column=0, columnspan=5, sticky="w", pady=(0, 8))
        for column, heading in enumerate(("Tool", "", "For the project", "All my projects", "")):
            ttk.Label(body, text=heading, foreground="gray30").grid(row=1, column=column, sticky="w", padx=4)

        self.shared, self.mine, self.status = {}, {}, {}
        for row, (name, tool) in enumerate(self.tools.items(), start=2):
            ttk.Label(body, text=name).grid(row=row, column=0, sticky="w", padx=4, pady=2)
            ttk.Label(body, text=tool.about, foreground="gray40").grid(row=row, column=1, sticky="w", padx=4)
            self.shared[name] = tk.BooleanVar(value=name in shared)
            self.mine[name] = tk.BooleanVar(value=name in mine)
            ttk.Checkbutton(body, variable=self.shared[name]).grid(row=row, column=2)
            ttk.Checkbutton(body, variable=self.mine[name]).grid(row=row, column=3)
            self.status[name] = ttk.Frame(body)
            self.status[name].grid(row=row, column=4, sticky="w", padx=4)

        self.where = ttk.Label(body, foreground="gray40")
        self.where.grid(row=len(self.tools) + 2, column=0, columnspan=5, sticky="w", pady=(8, 0))
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
        lint.set_choices(self.app.project, shared, mine)
        self.destroy()
        self.app.explorer_refresh()
        self.app.linter.check_all()
