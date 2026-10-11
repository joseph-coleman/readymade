"""Moving removed files to the Trash (the Linux way here; Windows and macOS use the system's)."""

import sys
from urllib.parse import unquote

import pytest

from readymade.ide import trash

pytestmark = pytest.mark.skipif(sys.platform in ("win32", "darwin"), reason="the freedesktop.org trash")


def test_files_go_to_the_trash_with_where_they_came_from(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))  # (on the same drive as the files)
    project = tmp_path / "Shop"
    project.mkdir()
    for _ in range(2):
        (project / "helpers.py").write_text("x = 1\n")
        trash.move_to_trash(project / "helpers.py")
    assert not (project / "helpers.py").exists()
    bin_ = tmp_path / "data" / "Trash"
    assert sorted(p.name for p in (bin_ / "files").iterdir()) == ["helpers.py", "helpers.py.2"]
    info = (bin_ / "info" / "helpers.py.2.trashinfo").read_text()
    assert info.startswith("[Trash Info]\n") and "DeletionDate=" in info
    assert unquote(info.split("Path=")[1].splitlines()[0]) == str(project / "helpers.py")


def test_folders_too_and_missing_files_say_so(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    (tmp_path / "sounds").mkdir()
    (tmp_path / "sounds" / "ding.wav").write_bytes(b"RIFF")
    trash.move_to_trash(tmp_path / "sounds")
    assert (tmp_path / "data" / "Trash" / "files" / "sounds" / "ding.wav").exists()
    with pytest.raises(trash.TrashError):
        trash.move_to_trash(tmp_path / "nothing.txt")
