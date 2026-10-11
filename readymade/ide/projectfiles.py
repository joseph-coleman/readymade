"""The project's files, from the IDE: opening other files, new files and folders, renaming
forms, modules and files (with the code that uses them), removing them (to the Recycle Bin or
Trash), bundling with Make EXE, the program icon, and noticing changes made outside the IDE."""

from __future__ import annotations

import os
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog

from readymade import formfile, package
from readymade import project as project_module
from readymade.controls import REGISTRY
from readymade.form import FORM
from readymade.formfile import FormFileError
from readymade.ide import trash
from readymade.ide.editors import FileEditor, FormEditor, ModuleEditor, bring_in
from readymade.project import ProjectError
from readymade.ide.part import Part


class ProjectFiles(Part):
    ICON_TYPES = {"Icons and pictures": "*.png *.gif *.ico *.icns", "All files": "*"}

    def __init__(self, app):
        super().__init__(app)
        self._away = False  # another program has the keyboard: changes may be made outside the IDE
        self._snapshot = None  # the project's files as last seen

    def project_opened(self):
        """A project was opened: its files as they are now count as seen."""
        self._snapshot = self.project.snapshot()

    def open_file(self, relative):
        """Open one of the project's other files: text in a tab, anything else (a picture, a
        sound) with the system's program for it. Returns the editor, if it opened in one."""
        path = self.project.folder / relative
        if path.is_dir():
            return None
        if path.suffix == ".py" and path.parent == self.project.folder:
            return self.app.open_code(path)
        editor = next((e for e in self.editors if e.path == path), None)
        if editor is None:
            if not is_text(path):
                self.open_with_system(path)
                return None
            try:
                editor = FileEditor(self.app, path)
            except (OSError, UnicodeDecodeError):
                self.open_with_system(path)
                return None
            self.app.add_tab(editor)
        self.app.documents.select(editor.frame)
        self.app.tab_changed()
        return editor

    def open_with_system(self, path):
        """Open a file (or folder) with the program the system uses for it."""
        try:
            if sys.platform == "win32":
                os.startfile(path)  # noqa: S606 - the user's own file, as Explorer would
            else:
                subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.immediate.write(f"(Couldn't open {path.name}: {e})\n")

    def new_file(self, folder="", name=None):
        """Project Explorer > New File...: an empty file in one of the project's folders
        (relative, "" for the top), opened to type in. Returns its relative path."""
        return self._new_thing(folder, name, folder_too=False)

    def new_folder(self, folder="", name=None):
        """Project Explorer > New Folder...: a folder in one of the project's folders."""
        return self._new_thing(folder, name, folder_too=True)

    def _new_thing(self, folder, name, folder_too):
        if self.project is None:
            return None
        kind = "Folder" if folder_too else "File"
        where = f" in {folder}" if folder else ""
        if name is None:
            name = simpledialog.askstring(f"New {kind}", f"Name of the new {kind.lower()}{where}:", parent=self.root)
        name = (name or "").strip()
        if not name:
            return None
        path = self.project.folder / folder / name
        if not name or name in (".", "..") or any(c in name for c in '/\\:*?"<>|') or path.exists():
            messagebox.showerror(f"New {kind}", f"{name!r} can't be used: " + (
                "there's one by that name already." if path.exists() else "it isn't a name for a file."), parent=self.root)
            return None
        try:
            path.mkdir() if folder_too else path.touch()
        except OSError as e:
            messagebox.showerror(f"New {kind}", str(e), parent=self.root)
            return None
        relative = path.relative_to(self.project.folder).as_posix()
        self.app.explorer_refresh()
        if self.app.explorer.tree.exists(f"file:{folder}"):
            self.app.explorer.tree.item(f"file:{folder}", open=True)
            self.app.explorer.fill_folder(f"file:{folder}")
        if self.app.explorer.tree.exists(f"file:{relative}"):
            self.app.explorer.tree.focus(f"file:{relative}")
            self.app.explorer.tree.selection_set(f"file:{relative}")
            self.app.explorer.tree.see(f"file:{relative}")
        if not folder_too:
            self.open_file(relative)
        return relative

    def rename_file(self, relative, new=None):
        """Project Explorer > Rename... (F2): one of the project's other files or folders. Open
        files follow it, and so does Make EXE's include list. Returns the new relative path."""
        old_name = relative.rpartition("/")[2]
        if new is None:
            new = simpledialog.askstring("Rename", f"New name for {old_name}:", initialvalue=old_name, parent=self.root)
        new = (new or "").strip()
        if not new or new == old_name:
            return None
        old_path = self.project.folder / relative
        uses = self._forms_using(old_path)
        try:
            renamed = self.project.rename_file(relative, new)
        except (ProjectError, OSError) as e:
            messagebox.showerror("Rename", str(e), parent=self.root)
            return None
        new_path = self.project.folder / renamed
        for editor in self.editors:  # open files in it follow
            if editor.path == old_path or old_path in editor.path.parents:
                editor.path = new_path / editor.path.relative_to(old_path) if editor.path != old_path else new_path
        self.app.debug.file_renamed(relative, renamed)
        self.app.explorer_refresh()
        self.app.update_title()
        self.immediate.write(f"--- Renamed {relative} to {renamed}. ---\n")
        if uses:
            self.immediate.write(f"--- {', '.join(uses)} showed {relative}: choose the picture again in the "
                                 "Properties panel. ---\n")
        return renamed

    def _forms_using(self, path):
        """The controls (Form1.Image1) whose pictures are path, or in it if it's a folder."""
        found = []
        for form in self.project.forms():
            try:
                design = formfile.load(self.project.folder / f"{form}.form")
            except (OSError, FormFileError):
                continue
            for spec in design.controls:
                for prop in getattr(REGISTRY.get(spec["type"]), "file_props", {}):
                    used = self.project.folder / spec[prop] if spec.get(prop) else None
                    if used is not None and (used == path or path in used.parents):
                        found.append(f"{form}.{spec['name']}")
        return found

    def window_left(self):
        try:
            self._away = self.root.focus_get() is None  # (None: another program has the keyboard)
        except (KeyError, tk.TclError):
            self._away = True

    def window_back(self):
        if self._away:
            self._away = False
            self.root.after_idle(self.check_outside_changes)

    def check_outside_changes(self):
        """The IDE came back to the front: notice files added, removed or changed outside it.
        The Project Explorer shows what's there; open files changed on disk show it, unless
        they've been edited here (then the edits are kept, and a note says so)."""
        if self.project is None:
            return
        snapshot = self.project.snapshot()
        if self._snapshot is not None and snapshot != self._snapshot:
            self.app.explorer_refresh()
            self.app.linter.check_project()
        self._snapshot = snapshot
        for editor in list(self.editors):
            if not editor.changed_on_disk():
                continue
            name = Path(editor.code_path).name
            if not Path(editor.code_path).exists():
                continue  # (removed: its tab stays, to save again or close)
            if editor.is_dirty():
                editor.seen_on_disk()  # (said once)
                self.immediate.write(f"--- {name} was changed outside readymade. Your changes here are kept; "
                                     "saving writes them over it. ---\n")
                continue
            if not editor.reload():
                self.immediate.write(f"--- {editor.path.name} was changed outside readymade: close it and "
                                     "open it again to see the new design. ---\n")
            self.app.linter.check(editor, saved=True)
        self.app.update_title()
        self.app.debug.show_breakpoints()

    def bundled_paths(self):
        """The files and folders Make EXE bundles: the forms, their pictures, the icon, and include."""
        return [path for path, _ in package.bundled_files(self.project)[0]] if self.project else []

    def is_bundled(self, relative, bundled):
        """Whether a file or folder (relative) is among bundled (from bundled_paths), or in one of them."""
        path = self.project.folder / relative
        return any(path == b or b in path.parents for b in bundled)

    def set_bundled(self, relative, bundled):
        """Project Explorer > Bundle with Make EXE: put a file or folder in [tool.readymade] include, or not."""
        self.project.set_bundled(relative, bundled)
        self.app.explorer_refresh()
        self.immediate.write(f"--- Make EXE {'bundles' if bundled else 'leaves out'} {relative}. ---\n")

    def uses_of(self, name, form=False):
        """The project's code that uses a module (or form) by name, besides its own:
        [(file, line number, the line)]; open files as they are in their tabs."""
        if self.project is None:
            return []
        found = []
        for path, source, relative in self.search_files():
            if path.suffix == ".py" and path.stem != name:
                found += [(relative, line, text) for line, text in project_module.uses_of(source, name, form)]
        return found

    def rename_form(self, name, new=None):
        """Project Explorer > Rename... (F2) on a form: its class and files get the new name, and
        so does code that uses it (forms.Old, its imports), open or not (open code then needs
        saving). Its unsaved changes are saved first. Returns whether it was renamed."""
        if self.project is None:
            return False
        if new is None:
            new = simpledialog.askstring("Rename Form", f"New name for {name}:", initialvalue=name, parent=self.root)
        new = (new or "").strip()
        if not new or new == name:
            return False
        try:
            self.project.check_new_name(new)
        except ProjectError as e:
            messagebox.showerror("Rename Form", str(e), parent=self.root)
            return False
        editor = self.app.editor_of(FormEditor, name) or self.app.open_form(name)
        if editor is None or (editor.is_dirty() and not editor.save()):
            return False
        if editor.set_property(FORM, "name", new) is None or not editor.save():  # (save renames its files)
            return False
        changed = []
        on_disk = {path: path.read_text(encoding="utf-8") for path in self.project.folder.glob("*.py")}
        for other in self.editors:
            if other is editor or not other.is_project_code:
                continue
            source = other.code.get_source()
            renamed = project_module.rename_form_references(source, name, new)
            on_disk.pop(Path(other.code_path), None)
            if renamed != source:
                other.code.replace_source(renamed)
                changed.append(Path(other.code_path).name)
        on_disk.pop(editor.code_path, None)
        for path, source in on_disk.items():
            renamed = project_module.rename_form_references(source, name, new)
            if renamed != source:
                path.write_text(renamed, encoding="utf-8")
                changed.append(path.name)
        self.app.debug.file_renamed(f"{name}.py", f"{new}.py")
        self.app.explorer_refresh()
        self.app.update_title()
        self.app.linter.check_project()
        self.immediate.write(f"--- Renamed {name} to {new}" +
                             (f", and its uses in {', '.join(sorted(changed))}" if changed else "") + ". ---\n")
        return True

    def rename_module(self, name, new=None):
        """Project Explorer > Rename...: give a module a new name, changing the project's imports
        of it to match (in open code too, which then needs saving). Returns whether it was renamed."""
        if self.project is None:
            return False
        if new is None:
            new = simpledialog.askstring("Rename Module", f"New name for {name}.py:", initialvalue=name,
                                         parent=self.root)
        new = (new or "").strip().removesuffix(".py")
        if not new or new == name:
            return False
        editor = self.app.editor_of(ModuleEditor, name)
        if editor is not None and editor.is_dirty() and not editor.save():
            return False
        try:
            on_disk = self.project.rename_module(name, new)
        except (ProjectError, OSError) as e:
            messagebox.showerror("Rename Module", str(e), parent=self.root)
            return False
        if editor is not None:
            editor.path = self.project.folder / f"{new}.py"
        changed = []
        for open_editor in self.editors:
            if not open_editor.is_project_code:
                continue  # (not the project's code)
            source = open_editor.code.get_source()
            renamed = project_module.rename_imports(source, name, new)
            on_disk.pop(Path(open_editor.code_path), None)
            if renamed != source:
                open_editor.code.replace_source(renamed)
                changed.append(Path(open_editor.code_path).name)
        for path, source in on_disk.items():
            path.write_text(source, encoding="utf-8")
            changed.append(path.name)
        self.app.debug.file_renamed(f"{name}.py", f"{new}.py")
        self.app.explorer_refresh()
        self.app.update_title()
        self.app.linter.check_project()
        self.immediate.write(f"--- Renamed {name}.py to {new}.py" +
                             (f", and its imports in {', '.join(sorted(changed))}" if changed else "") + ". ---\n")
        return True

    def remove_from_project(self, kind, name):
        """Move a form's or module's files ("form", "module") to the Recycle Bin / Trash, or
        take a library out of the project ("library"), after asking. Returns whether it was removed."""
        if self.project is None or not self.app.runner.idle():
            return False
        if kind == "library":
            return self.app.envs.remove_library(name)
        if kind == "file":
            return self._remove_file(name)
        files = " and ".join([f"{name}.form", f"{name}.py"] if kind == "form" else [f"{name}.py"])
        uses = self.uses_of(name, form=kind == "form")
        if uses:
            shown = [f"    {file}, line {line}: {text}" for file, line, text in uses[:8]]
            if len(uses) > 8:
                shown.append(f"    and {len(uses) - 8} more")
            said = "This code uses it, and will need changing:\n" + "\n".join(shown)
        else:
            said = "Nothing else in the project uses it."
        if not messagebox.askyesno(
            f"Remove {kind.capitalize()}",
            f"Remove {name} from the project? This moves {files} to the {trash.name()}.\n\n{said}",
            icon="warning", default="no", parent=self.root,
        ):
            return False
        editor = self.app.editor_of(FormEditor if kind == "form" else ModuleEditor, name)
        if editor is not None:
            self.app.close_document(editor, ask=False)  # its unsaved changes go with it
        remove = self.project.remove_form if kind == "form" else self.project.remove_module
        try:
            remove(name, discard=trash.move_to_trash)
            done = f"Moved {files} to the {trash.name()}"
        except OSError as e:
            if not messagebox.askyesno(
                f"Remove {kind.capitalize()}",
                f"{e}\n\nDelete {files} for good instead? That can't be undone.",
                icon="warning", default="no", parent=self.root,
            ):
                self.app.explorer_refresh()
                return False
            remove(name)
            done = f"Deleted {files}"
        self.app.explorer_refresh()
        self.app.linter.check_project()  # forgets its problems
        self.immediate.write(f"--- {done}. ---\n")
        return True

    def _remove_file(self, relative):
        path = self.project.folder / relative
        what = f"the {relative} folder and everything in it" if path.is_dir() else relative
        if not messagebox.askyesno("Remove", f"Move {what} to the {trash.name()}?", icon="warning", default="no",
                                   parent=self.root):
            return False
        for editor in list(self.editors):  # its open files close (their unsaved changes go with them)
            open_path = Path(editor.code_path)
            if open_path == path or path in open_path.parents:
                self.app.close_document(editor, ask=False)
        try:
            trash.move_to_trash(path)
        except OSError as e:
            messagebox.showerror("Remove", str(e), parent=self.root)
            return False
        if relative in self.project.include():
            self.project.set_bundled(relative, False)
        self.app.explorer_refresh()
        self.immediate.write(f"--- Moved {relative} to the {trash.name()}. ---\n")
        return True

    def search_files(self):
        """What Find in Files looks in: [(path, text, label)], the project's code and other text
        files (open ones as they are in their tabs), not .form files or what's hidden."""
        if self.project is None:
            return []
        open_text = {Path(e.code_path): e.code.get_source() for e in self.editors
                     if not e.read_only}
        found = []
        for relative in sorted(self.project.snapshot(), key=str.lower):
            path = self.project.folder / relative
            if relative.endswith("/") or path.suffix == ".form":
                continue
            if path in open_text:
                found.append((path, open_text[path], relative))
            elif is_text(path):
                try:
                    found.append((path, path.read_text(encoding="utf-8"), relative))
                except (OSError, UnicodeDecodeError):
                    continue
        return found

    def code_files(self):
        """The project's code: {file name relative to the project: source}, open files as edited."""
        if self.project is None:
            return {}
        files = {path.name: path.read_text(encoding="utf-8", errors="replace")
                 for path in sorted(self.project.folder.glob("*.py"))}
        for editor in self.editors:
            if editor.is_project_code:
                files[self.project.relative(editor.code_path)] = editor.code.get_source()
        return files

    def choose_icon(self):
        """Project > Program Icon: choose the picture the program's windows, and the program
        Make EXE makes, show as their icon. One from outside the project is copied into images/."""
        if self.project is None:
            return
        chosen = filedialog.askopenfilename(parent=self.root, title="Program Icon", initialdir=self.project.folder,
                                            filetypes=list(self.ICON_TYPES.items()))
        if chosen:
            try:
                self.set_icon(bring_in(self.project.folder, Path(chosen)))
            except OSError as e:
                messagebox.showerror("Program Icon", f"Couldn't copy {chosen}: {e}", parent=self.root)

    def set_icon(self, path):
        """Set (or with None, remove) the project's icon: a path relative to the project folder."""
        if self.project is None:
            return
        self.project.set_setting("icon", path)
        self.app.explorer_refresh()  # (a copy in images/ shows in the Files list)
        if path is None:
            self.immediate.write("--- The program no longer has an icon of its own. ---\n")
            return
        self.immediate.write(f"--- The program's icon is now {path}. ---\n")
        if Path(path).suffix.lower() not in (".png", ".gif"):
            self.immediate.write("(A .png works everywhere; other formats need the Pillow library in the project "
                                 "for the windows' icon.)\n")


def is_text(path, size=8192):
    """Whether a file looks like text: UTF-8, without the NUL bytes binary files have."""
    try:
        with open(path, "rb") as file:
            start = file.read(size)
    except OSError:
        return False
    if b"\0" in start:
        return False
    try:
        import codecs

        codecs.getincrementaldecoder("utf-8")().decode(start, final=False)  # (a character may be cut off)
    except UnicodeDecodeError:
        return False
    return True
