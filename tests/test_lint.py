"""Lint tools: reading their output, choosing them, and running them."""

import sys
from pathlib import Path

import pytest

from pybasic import lint, usersettings
from pybasic.project import Project, set_setting

# What the real tools printed for one small file (recorded with pyflakes 4.0, ruff 0.16,
# flake8 7.4, pylint 4.1 and mypy 2.4).
OUTPUTS = {
    "pyflakes": "<stdin>:1:1: 'os' imported but unused\n<stdin>:7:17: undefined name 'undefined_name'\n",
    "ruff": "Form1.py:1:8: F401 [*] `os` imported but unused\nForm1.py:7:17: F821 Undefined name `undefined_name`\n"
            "Found 2 errors.\n[*] 1 fixable with the `--fix` option.\n",
    "flake8": "Form1.py:1:1: F401 'os' imported but unused\nForm1.py:7:17: F821 undefined name 'undefined_name'\n",
    "pylint": "************* Module Form1\nForm1.py:1:0: C0114 Missing module docstring\n"
              "Form1.py:7:16: E0602 Undefined variable 'undefined_name'\n",
    "mypy": "Form1.py:8:18: error: Incompatible types in assignment  [assignment]\n"
            "helpers.py:3:1: error: Name \"x\" is not defined  [name-defined]\n"
            "Form1.py:8:9: note: By default the bodies of untyped functions are not checked  [annotation-unchecked]\n",
}


@pytest.mark.parametrize("name, expected", [
    ("pyflakes", [(1, 0, "'os' imported but unused"), (7, 16, "undefined name 'undefined_name'")]),
    ("ruff", [(1, 7, "F401 [*] `os` imported but unused"), (7, 16, "F821 Undefined name `undefined_name`")]),
    ("flake8", [(1, 0, "F401 'os' imported but unused"), (7, 16, "F821 undefined name 'undefined_name'")]),
    ("pylint", [(1, 0, "C0114 Missing module docstring"), (7, 16, "E0602 Undefined variable 'undefined_name'")]),
    ("mypy", [(8, 17, "Incompatible types in assignment  [assignment]")]),  # not helpers.py, not the note
])
def test_reading_each_tools_output(name, expected):
    problems = lint.parse(OUTPUTS[name], lint.BUILT_IN[name], Path("/project/Form1.py"))
    assert [(p.line, p.column, p.message) for p in problems] == expected  # columns from 0, as Tk counts
    assert {p.tool for p in problems} == {name}


def test_windows_paths_and_commands():
    problems = lint.parse(r"C:\code\app\Form1.py:3:5: E1 bad", lint.BUILT_IN["flake8"], Path("Form1.py"))
    assert [(p.line, p.column) for p in problems] == [(3, 4)]
    command = lint.command_for(lint.BUILT_IN["pylint"], "/py/python", Path("/p/Form1.py"))
    assert command[0] == "/py/python" and command[-1] == "/p/Form1.py"
    assert "--msg-template={path}:{line}:{column}: {msg_id} {msg}" in command  # its own braces survive


FAKE_LINTER = '''import sys
source = sys.stdin.read() if "--stdin" in sys.argv else open(sys.argv[-1]).read()
for n, line in enumerate(source.splitlines(), 1):
    if "bad" in line:
        print(f"{sys.argv[-1]}:{n}:{line.index('bad') + 1}: X100 found bad")
'''


@pytest.fixture
def project(tmp_path):
    project = Project.create(tmp_path / "p")
    (tmp_path / "fake_linter.py").write_text(FAKE_LINTER)
    script = str(tmp_path / "fake_linter.py").replace("\\\\", "/")
    project.pyproject.write_text(project.pyproject.read_text() + (
        "\n[tool.pybasic.lint-tools.typing-check]\n"
        f'command = ["{{python}}", "{script}", "--stdin", "{{file}}"]\nstdin = true\n'
        "\n[tool.pybasic.lint-tools.save-check]\n"
        f'command = ["{{python}}", "{script}", "{{file}}"]\n'
    ))
    return project


def test_choosing_tools_for_the_project_and_for_me(project):
    assert lint.tools_for(project) == []  # off until chosen
    lint.set_choices(project, ["ruff", "typing-check"], ["mypy", "ruff", "nonexistent"])
    assert lint.choices(project) == (["ruff", "typing-check"], ["mypy", "ruff", "nonexistent"])
    assert [t.name for t in lint.tools_for(project)] == ["ruff", "typing-check", "mypy"]  # unknown names left out
    assert 'lint = ["ruff", "typing-check"]' in project.pyproject.read_text()
    assert not (project.folder / ".pybasic").exists()  # your own choices aren't kept in the project
    assert lint.definitions(project)["typing-check"].stdin is True
    other = Project.create(project.folder.parent / "other")
    assert lint.choices(other) == ([], ["mypy", "ruff", "nonexistent"])  # they follow you to every project
    lint.set_choices(project, [], [])
    assert project.setting("lint") is None and lint.tools_for(project) == lint.tools_for(other) == []


def test_running_a_tool(project):
    path = project.folder / "Form1.py"
    path.write_text("x = 1\ny = bad\n")
    tools = lint.definitions(project)
    unsaved = "x = bad\n"
    problems, trouble = lint.run(tools["typing-check"], sys.executable, project.folder, path, unsaved, None)
    assert trouble is None and [(p.line, p.column, p.message) for p in problems] == [(1, 4, "X100 found bad")]
    problems, _ = lint.run(tools["save-check"], sys.executable, project.folder, path, unsaved, None)
    assert [(p.line, p.column) for p in problems] == [(2, 4)]  # it read the saved file


def test_a_missing_tool_says_so():
    tool = lint.Tool("ghost", ("{python}", "-m", "no_such_linter_xyz"), module="no_such_linter_xyz")
    problems, trouble = lint.run(tool, sys.executable, Path.cwd(), Path("Form1.py"), "", None)
    assert problems == [] and trouble == "ghost isn't installed in this project's environment"
    found = lint.installed(sys.executable, [lint.Tool("j", (), module="json"), tool])
    assert found == {"j"}


def test_lists_over_several_lines_are_replaced_whole():
    text = '[tool.pybasic]\nlint = [\n  "ruff",  # fast\n  "mypy",\n]\ntheme = "x"\n'
    assert set_setting(text, "lint", ["pyflakes"]) == '[tool.pybasic]\nlint = ["pyflakes"]\ntheme = "x"\n'
    assert set_setting(text, "lint", None) == '[tool.pybasic]\ntheme = "x"\n'


def test_personal_tools_can_be_defined_in_your_settings(project):
    usersettings.set("lint-tools", {"mine": {"command": ["{python}", "-m", "mine", "{file}"], "stdin": True}})
    usersettings.set("lint", ["mine"])
    assert [t.name for t in lint.tools_for(project)] == ["mine"] and lint.tools_for(project)[0].stdin


@pytest.mark.parametrize("platform, env, expected", [
    ("win32", {"APPDATA": "C:/Users/me/AppData/Roaming"}, "C:/Users/me/AppData/Roaming/pybasic"),
    ("linux", {"XDG_CONFIG_HOME": "/home/me/.cfg"}, "/home/me/.cfg/pybasic"),
    ("linux", {}, str(Path.home() / ".config" / "pybasic")),
    ("darwin", {}, str(Path.home() / "Library" / "Application Support" / "pybasic")),
])
def test_settings_folder_for_each_system(monkeypatch, platform, env, expected):
    for name in ("PYBASIC_CONFIG_DIR", "APPDATA", "XDG_CONFIG_HOME"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setattr(usersettings.sys, "platform", platform)
    assert usersettings.folder() == Path(expected)


def test_a_damaged_settings_file_is_ignored_then_rewritten():
    (usersettings.folder()).mkdir(parents=True, exist_ok=True)
    (usersettings.folder() / "settings.json").write_text("{not json")
    assert usersettings.get("lint", []) == []
    usersettings.set("lint", ["ruff"])
    assert usersettings.get("lint") == ["ruff"]
