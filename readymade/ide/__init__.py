"""The readymade IDE. Start it with `python -m readymade.ide [Form1.form]`."""

from pathlib import Path

PACKAGE_ROOT = str(Path(__file__).resolve().parents[2])  # the folder containing readymade/, for programs to import it
