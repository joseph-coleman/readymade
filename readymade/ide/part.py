"""What the IDE's jobs (running, debugging, project files, environments) have in common:
each is a part of the App, and reads its shared state by name."""

from __future__ import annotations


class Part:
    def __init__(self, app):
        self.app = app

    @property
    def project(self):
        return self.app.project

    @property
    def editors(self):
        return self.app.editors

    @property
    def root(self):
        return self.app.root

    @property
    def immediate(self):
        return self.app.immediate
