"""What a name can be (readymade.names), and the checks that use it."""

import pytest

from readymade import names


@pytest.mark.parametrize("name", ["Form1", "lblTotal", "_hidden", "Ünïcode"])
def test_python_names(name):
    names.check_python_name(name)


@pytest.mark.parametrize("name, said", [("1st", "valid Python name"), ("for", "valid Python name"),
                                        ("my form", "valid Python name"), ("", "valid Python name")])
def test_not_python_names(name, said):
    with pytest.raises(ValueError, match=said):
        names.check_python_name(name)


def test_module_names():
    names.check_module_name("helpers")
    for hidden in ("json", "os", "tkinter", "readymade"):
        with pytest.raises(ValueError, match="would hide Python's own"):
            names.check_module_name(hidden)


@pytest.mark.parametrize("name", ["README.md", "data", ".gitignore", "prices 2026.csv", "a.b.c"])
def test_file_names(name):
    names.check_file_name(name)


@pytest.mark.parametrize("name, said", [
    ("", "can't be empty"), (".", "can't be empty"), ("..", "can't be empty"), (" notes.txt", "start or end"),
    ("notes.", "end with a dot"), ("a/b", "can't have /"), ("what?.txt", r"can't have \?"),
    ("CON", "Windows keeps CON"), ("nul.txt", "Windows keeps NUL"), ("com1.log", "Windows keeps COM1"),
])
def test_not_file_names(name, said):
    with pytest.raises(ValueError, match=said):
        names.check_file_name(name)


def test_the_checks_agree(tmp_path):
    """A form renamed in the Properties panel, or from the Project Explorer, is checked the same way."""
    from readymade.project import Project, ProjectError

    project = Project.create(tmp_path / "Shop")
    project.add_module("helpers")
    for bad in ("json", "Helpers", "1st"):
        with pytest.raises(ProjectError):
            project.check_new_name(bad)
    assert project.name_taken("FORM1") and not project.name_taken("Settings")
    with pytest.raises(ProjectError, match="Windows keeps"):
        project.rename_file("pyproject.toml", "aux.toml")
