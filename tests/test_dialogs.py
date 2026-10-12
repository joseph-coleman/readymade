"""msgbox, inputbox and the file dialogs, driven from inside the test while they're open."""

from pathlib import Path
from tkinter import colorchooser, filedialog

import pytest

from readymade import Form, color_dialog, folder_dialog, formfile, inputbox, msgbox, open_file_dialog, save_file_dialog

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def form(tmp_path):
    formfile.save(formfile.FormDesign(name="Form1", text="My App"), tmp_path / "Form1.form")
    form = Form(tmp_path / "Form1.form")
    form.show()
    form.root.update()
    yield form
    if form.loaded:
        form.root.destroy()


def find(root, suffix):
    """The Tcl path of a widget whose path ends with suffix (Tk's own dialogs aren't tkinter objects)."""
    pending = ["."]
    while pending:
        path = pending.pop()
        if path.endswith(suffix):
            return path
        pending += root.tk.splitlist(root.tk.call("winfo", "children", path))
    return None


def answer_messagebox(form, button, seen):
    def press():
        path = find(form.root, "__tk__messagebox")
        if path is None:
            form.root.after(20, press)
            return
        seen.append((form.root.tk.call("wm", "title", path), [str(c).rsplit(".", 1)[-1] for c in form.root.tk.splitlist(form.root.tk.call("winfo", "children", path))]))
        form.root.tk.call(f"{path}.{button}", "invoke")

    form.root.after(50, press)


def test_msgbox_asks_the_system_and_returns_the_button(form, monkeypatch):
    """On every system: what msgbox asks the message box for, and what it gives back."""
    from tkinter import messagebox

    asked = []

    def show(dialog):
        asked.append(dialog.options)
        return "no"

    monkeypatch.setattr(messagebox.Message, "show", show)
    assert msgbox("Save changes?", buttons="yesnocancel", icon="question") == "no"
    options = asked[0]
    assert options["message"] == "Save changes?" and options["title"] == "My App"  # (the form's title)
    assert options["type"] == messagebox.YESNOCANCEL and options["icon"] == "question"
    assert msgbox(42, title="Answer") == "no" and asked[1]["message"] == "42" and asked[1]["title"] == "Answer"


def test_msgbox_returns_the_button_clicked(form):
    """The real message box, clicked from inside the test: only where Tk draws it itself. On
    Windows and macOS it's the system's own, which a test can't see or click."""
    if form.root.tk.call("tk", "windowingsystem") != "x11":
        pytest.skip("the system's own message box (a test can't click it)")
    seen = []
    answer_messagebox(form, "no", seen)
    assert msgbox("Save changes?", buttons="yesnocancel", icon="question") == "no"
    title, buttons = seen[0]
    assert title == "My App"  # defaults to the form's title
    assert {"yes", "no", "cancel"} <= set(buttons)

    answer_messagebox(form, "ok", seen)
    assert msgbox(42, title="Answer") == "ok"
    assert seen[1][0] == "Answer"


@pytest.mark.parametrize("bad, message", [({"buttons": "maybe"}, "buttons must be one of"), ({"icon": "smiley"}, "icon must be one of")])
def test_msgbox_rejects_unknown_options(form, bad, message):
    with pytest.raises(ValueError, match=message):
        msgbox("x", **bad)


def answer_inputbox(form, text):
    def type_it():
        dialogs = [w for w in form.root.winfo_children() if hasattr(w, "entry")]
        if not dialogs:
            form.root.after(20, type_it)
            return
        if text is None:
            dialogs[0].cancel()
        else:
            dialogs[0].entry.delete(0, "end")
            dialogs[0].entry.insert(0, text)
            dialogs[0].ok()

    form.root.after(50, type_it)


def test_inputbox_is_like_input_but_can_be_canceled(form):
    answer_inputbox(form, "Ada")
    assert inputbox("What's your name?") == "Ada"
    answer_inputbox(form, None)
    assert inputbox("What's your name?", default="Grace") is None


def test_file_dialogs(form, monkeypatch):
    calls = []

    def fake(result):
        def dialog(**options):
            calls.append(options)
            return result
        return dialog

    monkeypatch.setattr(filedialog, "askopenfilename", fake("/data/notes.txt"))
    assert open_file_dialog(filetypes={"Text files": "*.txt", "All files": "*"}, folder="/data") == Path("/data/notes.txt")
    assert calls[-1]["filetypes"] == [("Text files", "*.txt"), ("All files", "*")]
    assert calls[-1]["initialdir"] == "/data" and calls[-1]["parent"] is form.root
    monkeypatch.setattr(filedialog, "askopenfilename", fake(""))
    assert open_file_dialog() is None  # canceled

    monkeypatch.setattr(filedialog, "askopenfilenames", fake(("/a.png", "/b.png")))
    assert open_file_dialog(multiple=True) == [Path("/a.png"), Path("/b.png")]
    monkeypatch.setattr(filedialog, "askopenfilenames", fake(()))
    assert open_file_dialog(multiple=True) == []

    monkeypatch.setattr(filedialog, "asksaveasfilename", fake("/data/report.csv"))
    assert save_file_dialog(filetypes={"CSV": "*.csv"}, filename="report") == Path("/data/report.csv")
    assert calls[-1]["defaultextension"] == ".csv" and calls[-1]["initialfile"] == "report"

    monkeypatch.setattr(filedialog, "askdirectory", fake("/data"))
    assert folder_dialog(title="Pick a folder") == Path("/data")
    assert calls[-1]["title"] == "Pick a folder" and calls[-1]["mustexist"] is True


def test_color_dialog(form, monkeypatch):
    calls = []
    monkeypatch.setattr(colorchooser, "askcolor", lambda **o: calls.append(o) or ((51, 102, 153), "#336699"))
    assert color_dialog("red", title="Background") == "#336699"
    assert calls[-1] == {"parent": form.root, "color": "red", "title": "Background"}
    monkeypatch.setattr(colorchooser, "askcolor", lambda **o: (None, None))
    assert color_dialog() is None
