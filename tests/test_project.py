"""Projects: the pyproject.toml-based project model, and running multi-form programs."""

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

from readymade import forms, formfile
from readymade.controls import REGISTRY
from readymade.project import Project, ProjectError, add_dependency, describe_python, find_pythons, requirement_name, set_setting

ROOT = Path(__file__).parent.parent

# Reading pyproject.toml is the IDE's job and needs tomllib; running a program doesn't.
needs_tomllib = pytest.mark.skipif(sys.version_info < (3, 11), reason="reading pyproject.toml needs Python 3.11")


@needs_tomllib
def test_create(tmp_path):
    project = Project.create(tmp_path / "My Inventory")
    assert project.name == "my-inventory"
    assert project.forms() == ["Form1"] and project.modules() == []
    assert project.startup == "Form1"
    assert 'startup = "Form1"' in project.pyproject.read_text()
    with pytest.raises(ProjectError, match="isn't empty"):
        Project.create(project.folder)


def test_forms_and_modules_are_found_in_the_folder(tmp_path):
    project = Project.create(tmp_path / "p")
    project.add_form("Settings")
    project.add_module("helpers")
    (project.folder / "notes.txt").write_text("not code")
    assert project.forms() == ["Form1", "Settings"]
    assert project.modules() == ["helpers"]
    assert Project.find(project.folder / "Settings.form").folder == project.folder


@pytest.mark.parametrize(
    "name, message",
    [("2fast", "valid Python name"), ("class", "valid Python name"), ("random", "hide Python's own"),
     ("form1", "already has"), ("Helpers", "already has")],
)
def test_bad_names(tmp_path, name, message):
    project = Project.create(tmp_path / "p")
    project.add_module("helpers")
    with pytest.raises(ProjectError, match=message):
        project.add_form(name)


@needs_tomllib
def test_startup_falls_back_to_the_first_form(tmp_path):
    (tmp_path / "B.form").write_text(formfile.dumps(formfile.FormDesign(name="B")))
    (tmp_path / "A.form").write_text(formfile.dumps(formfile.FormDesign(name="A")))
    assert Project(tmp_path).startup == "A"  # no pyproject.toml at all
    Project(tmp_path).set_startup("B")  # creates one
    assert Project(tmp_path).startup == "B"


@pytest.mark.parametrize(
    "before, after",
    [
        ('[project]\nname = "x"\n', '[project]\nname = "x"\n\n[tool.readymade]\nstartup = "Main"\n'),
        ('[tool.readymade]\n\n[tool.other]\na = 1\n', '[tool.readymade]\nstartup = "Main"\n\n[tool.other]\na = 1\n'),
        ('[tool.readymade]\nstartup = "Old"  # comment\ntheme = "x"\n', '[tool.readymade]\nstartup = "Main"\ntheme = "x"\n'),
        ('[tool.readymade]\nstartup="Old"\n[[tool.readymade.plugins]]\nname = "p"\n',
         '[tool.readymade]\nstartup = "Main"\n[[tool.readymade.plugins]]\nname = "p"\n'),
    ],
)
def test_set_setting_edits_only_that_line(before, after):
    assert set_setting(before, "startup", "Main") == after


@needs_tomllib
def test_removing_and_escaping_settings():
    text = '[tool.readymade]\nstartup = "Main"\npython = "x"\n\n[tool.other]\n'
    assert set_setting(text, "python", None) == '[tool.readymade]\nstartup = "Main"\n\n[tool.other]\n'
    assert set_setting('[project]\n', "python", None) == '[project]\n'
    windows = set_setting(text, "python", r"C:\envs\app\python.exe")
    assert 'python = "C:\\\\envs\\\\app\\\\python.exe"' in windows
    import tomllib
    assert tomllib.loads(windows)["tool"]["readymade"]["python"] == r"C:\envs\app\python.exe"


@needs_tomllib
def test_choosing_the_interpreter(tmp_path):
    project = Project.create(tmp_path / "p")
    assert project.python() is None  # the IDE's own
    other = project.folder / ".venv" / ("bin/python" if os.name == "nt" else "Scripts/python.exe")
    other.parent.mkdir(parents=True)
    other.write_text("")
    assert project.python() is None  # another platform's .venv (e.g. made from Windows, seen from WSL)
    venv_python = project.venv_python()
    venv_python.parent.mkdir(parents=True, exist_ok=True)
    venv_python.write_text("")
    assert project.python() == venv_python

    project.set_python(project.folder / "envs" / "py" / "python")
    assert project.local_settings()["python"] == "envs/py/python"  # stored relative, so the project can move
    assert project.python_choice() == (project.folder / "envs" / "py" / "python", "envs/py/python")
    outside = tmp_path / "conda" / "python"
    project.set_python(outside)
    assert project.python() == outside
    assert project.setting("python") is None  # never in pyproject.toml, which is shared
    project.set_python(None)
    assert "python" not in project.local_settings() and project.python_choice() == (venv_python, ".venv")


@needs_tomllib
def test_interpreter_choices_are_per_machine_and_kept_out_of_git(tmp_path, monkeypatch):
    project = Project.create(tmp_path / "p")
    monkeypatch.setattr("readymade.project._machine", lambda: "MYPC win32")
    project.set_local_setting("python", "D:/miniforge3/envs/app/python.exe")  # as the IDE on Windows stores it
    monkeypatch.setattr("readymade.project._machine", lambda: "MYPC linux")  # WSL, same folder
    assert project.python() is None  # Windows' choice isn't used here
    project.set_python(tmp_path / "envs" / "app" / "bin" / "python")
    machines = json.loads((project.folder / ".readymade" / "local.json").read_text())["machines"]
    assert machines == {
        "MYPC win32": {"python": "D:/miniforge3/envs/app/python.exe"},
        "MYPC linux": {"python": (tmp_path / "envs" / "app" / "bin" / "python").as_posix()},
    }
    assert (project.folder / ".readymade" / ".gitignore").read_text().splitlines()[-1] == "*"
    assert project.setting("python") is None  # nothing machine-specific in the shared pyproject.toml


def test_a_broken_local_settings_file_is_reported(tmp_path):
    project = Project.create(tmp_path / "p")
    (project.folder / ".readymade").mkdir()
    (project.folder / ".readymade" / "local.json").write_text("{not json")
    with pytest.raises(ProjectError, match="local.json"):
        project.python()


def test_describe_python(tmp_path):
    version = "%d.%d.%d" % sys.version_info[:3]
    assert describe_python(sys.executable) == version
    assert describe_python(tmp_path / "missing") == "can't run it (FileNotFoundError)"


def make_two_form_project(folder):
    project = Project.create(folder, first_form="Main")
    project.add_form("Dialog")
    for name, controls in (("Main", [("Button", "Ask"), ("Label", "Answer")]), ("Dialog", [("Button", "OK")])):
        design = formfile.load(project.folder / f"{name}.form")
        design.controls += [REGISTRY[t].new_spec(n, 8, 8 + 32 * i) for i, (t, n) in enumerate(controls)]
        formfile.save(design, project.folder / f"{name}.form")
    (project.folder / "Main.py").write_text(
        "from readymade import Form, forms\n\n\nclass Main(Form):\n"
        "    def Ask_click(self):\n"
        "        forms.Dialog.show(modal=True)\n"
        "        self.Answer.text = f'result: {forms.Dialog.result}'\n"
    )
    (project.folder / "Dialog.py").write_text(
        "from readymade import Form\n\n\nclass Dialog(Form):\n"
        "    def Form_load(self):\n        self.result = None\n\n"
        "    def OK_click(self):\n        self.result = 'ok'\n        self.close()\n"
    )
    return project


@pytest.mark.usefixtures("display")
def test_modal_dialog_and_ending_when_the_last_form_closes(tmp_path):
    project = make_two_form_project(tmp_path / "p")
    env = dict(os.environ, PYTHONPATH=str(ROOT), PYTHONUNBUFFERED="1")
    process = subprocess.Popen(
        [sys.executable, "-m", "readymade.run", "--immediate", "--startup", "Main", str(project.folder)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env,
    )
    output = queue.Queue()
    threading.Thread(target=lambda: [output.put(line.rstrip("\n")) for line in process.stdout], daemon=True).start()

    def send(line):
        process.stdin.write(line + "\n")
        process.stdin.flush()

    def ask(expression, until, seconds=10):
        """Print expression in the program until it equals until."""
        deadline = time.time() + seconds
        while time.time() < deadline:
            send(f"print(repr({expression}))")
            try:
                answer = output.get(timeout=2)
            except queue.Empty:
                continue
            if answer == repr(until):
                return
            time.sleep(0.1)
        raise AssertionError(f"{expression} never became {until!r} (last: {answer})")

    try:
        send("_ = form.root.after(0, Ask.widget.invoke)")  # a modal dialog blocks, so start it from the event loop
        ask("forms.Dialog.loaded and forms.Dialog.root.state()", "normal")
        send("_ = forms.Dialog.OK.widget.invoke()")
        ask("Answer.text", "result: ok")
        send("forms.Dialog.show()")
        send("form.close()")
        ask("[f for f, x in forms.loaded().items() if x.loaded]", ["Dialog"])  # still running
        send("forms.Dialog.close()")
        assert process.wait(timeout=15) == 0, process.stderr.read()
    finally:
        process.kill()


@pytest.mark.usefixtures("display")
def test_default_and_explicit_instances(tmp_path, monkeypatch):
    project = make_two_form_project(tmp_path / "p")
    monkeypatch.syspath_prepend(str(project.folder))
    forms.reset()
    made = []
    try:
        from Dialog import Dialog

        first, second = Dialog(), Dialog()
        made += [first, second, forms.Dialog]
        assert first is not second and forms.Dialog is forms.Dialog
        assert forms.Dialog is not first
        first.root.after(50, first.OK.widget.invoke)
        first.show(modal=True)  # returns when OK closes it
        assert (first.loaded, first.result, second.result) == (False, "ok", None)
        first.show()  # showing a closed form loads it again
        assert first.loaded and first.result is None
        with pytest.raises(AttributeError, match="no form named 'Nope'"):
            forms.Nope
    finally:
        for form in made:
            if form.loaded:
                form.root.destroy()
        forms.reset()
        sys.modules.pop("Dialog", None)


@pytest.mark.parametrize(
    "before, after",
    [
        ('[project]\nname = "x"\n', '[project]\ndependencies = ["rich"]\nname = "x"\n'),
        ('[project]\ndependencies = []\n', '[project]\ndependencies = [\n    "rich",\n]\n'),
        ('[project]\ndependencies = [\n  "Rich==13",  # pinned, ] in a comment\n  "requests[socks]>=2",\n]\n\n[tool.readymade]\n',
         '[project]\ndependencies = [\n    "requests[socks]>=2",\n    "rich",\n]\n\n[tool.readymade]\n'),
        ('[tool.readymade]\n', '[tool.readymade]\n\n[project]\ndependencies = ["rich"]\n'),
    ],
)
@needs_tomllib
def test_add_dependency(before, after):
    assert add_dependency(before, "rich") == after


@pytest.mark.parametrize(
    "requirement, name",
    [("requests", "requests"), ("Requests[socks]>=2", "requests"), ("typing_extensions ; python_version<'3.11'", "typing-extensions"),
     ("my.pkg @ https://x/y.whl", "my-pkg")],
)
def test_requirement_name(requirement, name):
    assert requirement_name(requirement) == name


def test_find_pythons_starts_with_the_ides_own():
    pythons = find_pythons()
    assert pythons and pythons[0].exists()
    assert len({os.path.realpath(p) for p in pythons}) == len(pythons)


def test_find_pythons_looks_on_the_path_and_in_conda(tmp_path, monkeypatch):
    def fake_python(path):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
        return path

    bin_name = "python.exe" if os.name == "nt" else "python3"
    on_path = [fake_python(tmp_path / "a" / bin_name), fake_python(tmp_path / "b" / bin_name)]
    store = fake_python(tmp_path / "WindowsApps" / bin_name)
    env = tmp_path / "conda" / "envs" / "app"
    conda_python = fake_python(env / ("python.exe" if os.name == "nt" else "bin/python"))
    fake_conda = tmp_path / "conda.py"
    fake_conda.write_text(f"import json; print(json.dumps({{'envs': [{str(env)!r}]}}))")
    script = tmp_path / ("fake-conda.bat" if os.name == "nt" else "fake-conda")
    script.write_text(f'@"{sys.executable}" "{fake_conda}"' if os.name == "nt" else f'#!/bin/sh\nexec "{sys.executable}" "{fake_conda}"\n')
    script.chmod(0o755)
    monkeypatch.setenv("PATH", os.pathsep.join(str(p.parent) for p in [*on_path, store]))
    monkeypatch.setenv("CONDA_EXE", str(script))
    monkeypatch.delenv("MAMBA_EXE", raising=False)

    pythons = find_pythons()
    assert pythons[1:] == [*on_path, conda_python]  # the IDE's own first, then these
    assert store not in pythons


def test_other_files_and_bundling(tmp_path):
    from readymade.project import Project

    project = Project.create(tmp_path / "Shop")
    folder = project.folder
    for name in ("README.md", "data/prices.csv", "data/old/2019.csv", "images/logo.png", ".venv/x",
                 "build/x", "__pycache__/x.pyc", "helpers.py", "notes.txt"):
        (folder / name).parent.mkdir(parents=True, exist_ok=True)
        (folder / name).write_text("x")
    assert project.other_files() == [("data", True), ("images", True), ("notes.txt", False),
                                     ("pyproject.toml", False), ("README.md", False)]
    assert project.other_files("data") == [("data/old", True), ("data/prices.csv", False)]
    project.set_bundled("data", True)
    project.set_bundled("README.md", True)
    assert project.include() == ["data", "README.md"]
    project.set_bundled("data", False)
    assert project.include() == ["README.md"]
    project.set_bundled("README.md", False)
    assert project.include() == [] and "include" not in (folder / "pyproject.toml").read_text()
