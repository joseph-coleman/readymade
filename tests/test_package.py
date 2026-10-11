"""Make EXE: the launcher and PyInstaller arguments (fast), and one real build (opt-in, slow)."""

import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

from readymade import package
from readymade.project import Project


@pytest.fixture
def project(tmp_path):
    project = Project.create(tmp_path / "Inventory", first_form="Main")
    project.add_form("Settings")
    project.add_module("helpers")
    return project


def test_launcher_imports_everything_and_shows_the_startup_form(project):
    source = package.launcher_source(project, "Main")
    assert "import Main, Settings, helpers" in source
    assert source.endswith("forms.Main.show()\nmain_loop()\n")
    compile(source, "launcher", "exec")
    launcher = package.write_launcher(project, "Main")
    assert launcher == project.folder / "build" / "readymade" / package.LAUNCHER
    assert launcher.read_text() == source


@pytest.mark.parametrize("platform, kind, name", [
    ("linux", "--onefile", "inventory"), ("win32", "--onefile", "inventory.exe"), ("darwin", "--onedir", "inventory.app"),
])
def test_pyinstaller_arguments(project, platform, kind, name):
    launcher = package.write_launcher(project, "Main")
    args = package.pyinstaller_args(project, launcher, "/opt/readymade", platform=platform)
    assert args[:4] == ["-m", "PyInstaller", "--noconfirm", "--windowed"] and kind in args
    assert args[args.index("--name") + 1] == "inventory"
    assert args[args.index("--distpath") + 1] == str(project.folder / "dist")
    assert [args[i + 1] for i, a in enumerate(args) if a == "--paths"] == [str(project.folder), "/opt/readymade"]
    data = [args[i + 1] for i, a in enumerate(args) if a == "--add-data"]
    assert data == [f"{project.folder / f}{os.pathsep}." for f in ("Main.form", "Settings.form")]
    assert args[-1] == str(launcher)
    assert package.exe_path(project, platform=platform) == project.folder / "dist" / name


@pytest.mark.skipif(not os.environ.get("READYMADE_SLOW_TESTS"), reason="set READYMADE_SLOW_TESTS=1: needs the network and a minute")
@pytest.mark.usefixtures("display")
def test_a_real_build_runs(tmp_path):
    root = Path(__file__).parent.parent
    project = Project.create(tmp_path / "Hello")
    venv = project.folder / ".venv"
    subprocess.run([sys.executable, "-m", "venv", str(venv)], check=True)
    python = project.python()
    subprocess.run([str(python), "-m", "pip", "install", "-q", "--disable-pip-version-check", "pyinstaller"], check=True)
    launcher = package.write_launcher(project, "Form1")
    env = dict(os.environ, PYTHONPATH=str(root))
    subprocess.run([str(python), *package.pyinstaller_args(project, launcher, root)], check=True, env=env,
                   capture_output=True, cwd=project.folder)
    program = package.exe_path(project)
    assert program.exists()
    running = subprocess.Popen([str(program)], stderr=subprocess.PIPE, text=True)
    time.sleep(4)
    assert running.poll() is None, running.stderr.read()  # still running: the form is up
    running.terminate()


def test_program_details_for_windows_and_the_mac(tmp_path):
    import plistlib

    from readymade import package
    from readymade.project import Project

    project = Project.create(tmp_path / "Shop")
    package.set_details(project, {"name": project.name, "version": "2.1", "company": "Tea Co", "description": "",
                                  "copyright": "(c) Tea Co", "one_folder": False, "notices": True})
    text = (project.folder / "pyproject.toml").read_text()
    assert "program-name" not in text and "one-folder" not in text and "notices" not in text  # (the defaults)
    version = package.windows_version_file(project).read_text()
    assert "filevers=(2, 1, 0, 0)" in version and "StringStruct('CompanyName', 'Tea Co')" in version
    assert "StringStruct('FileDescription', 'shop')" in version  # (the name, with no description)
    args = package.pyinstaller_args(project, project.folder / "launcher.py", tmp_path, platform="win32")
    assert args[args.index("--version-file") + 1] == str(package.windows_version_file(project))
    assert "--onefile" in args
    assert "--version-file" not in package.pyinstaller_args(project, project.folder / "launcher.py", tmp_path,
                                                            platform="linux")

    app = tmp_path / "Shop.app" / "Contents"
    app.mkdir(parents=True)
    (app / "Info.plist").write_bytes(plistlib.dumps({"CFBundleShortVersionString": "0.0.0", "CFBundleName": "Shop"}))
    package.set_mac_details(project, tmp_path / "Shop.app")
    info = plistlib.loads((app / "Info.plist").read_bytes())
    assert info["CFBundleShortVersionString"] == info["CFBundleVersion"] == "2.1"
    assert info["NSHumanReadableCopyright"] == "(c) Tea Co" and info["CFBundleName"] == "Shop"


def test_license_notices(tmp_path):
    from readymade import notices

    notices.write(tmp_path / "LICENSES.txt", "Shop", ["pygments"])
    text = (tmp_path / "LICENSES.txt").read_text()
    assert text.startswith("Shop is made with readymade")
    for title in ("readymade\n", "\nPython 3.", "\nTcl\n", "\nTk\n", "\nPygments "):
        assert title in text
    assert "MIT License" in text  # readymade's own
    assert [t for t, _ in notices.collect(["not-a-library-anywhere"])] == [t for t, _ in notices.collect()]
