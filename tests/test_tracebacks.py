from pathlib import Path

from pybasic.ide.tracebacks import TracebackWatcher


def watch(folder, output):
    errors = []
    watcher = TracebackWatcher(folder, lambda path, line, message: errors.append((path.name, line, message)))
    for line in output.splitlines(keepends=True):
        watcher.feed(line)
    return errors


def test_error_in_a_handler(tmp_path):
    output = f"""Exception in Tkinter callback
Traceback (most recent call last):
  File "/usr/lib/python3.13/tkinter/__init__.py", line 2068, in __call__
    return self.func(*args)
           ~~~~~~~~~^^^^^^^
  File "{tmp_path}/Form1.py", line 7, in Button1_click
    self.total = 1 / 0
                 ~~^~~
ZeroDivisionError: division by zero
"""
    assert watch(tmp_path, output) == [("Form1.py", 7, "ZeroDivisionError: division by zero")]


def test_the_last_project_frame_wins(tmp_path):
    output = f"""Traceback (most recent call last):
  File "{tmp_path}/Form1.py", line 9, in Button1_click
    helpers.load()
  File "{tmp_path}/helpers.py", line 3, in load
    return open("missing.txt").read()
  File "/usr/lib/python3.13/codecs.py", line 1, in open
FileNotFoundError: [Errno 2] No such file or directory: 'missing.txt'
"""
    assert watch(tmp_path, output) == [("helpers.py", 3, "FileNotFoundError: [Errno 2] No such file or directory: 'missing.txt'")]


def test_syntax_error(tmp_path):
    output = f"""Traceback (most recent call last):
  File "<frozen runpy>", line 198, in _run_module_as_main
  File "{tmp_path}/Form1.py", line 12
    x = (
        ^
SyntaxError: '(' was never closed
"""
    assert watch(tmp_path, output) == [("Form1.py", 12, "SyntaxError: '(' was never closed")]


def test_errors_outside_the_project_and_ordinary_output_are_ignored(tmp_path):
    output = """hello
Traceback (most recent call last):
  File "<console>", line 1, in <module>
NameError: name 'x' is not defined
Traceback (most recent call last):
  File "/elsewhere/Form1.py", line 3, in f
ValueError: elsewhere
"""
    assert watch(tmp_path, output) == []


def test_chained_exceptions_report_each(tmp_path):
    output = f"""Traceback (most recent call last):
  File "{tmp_path}/Form1.py", line 5, in load
KeyError: 'x'

During handling of the above exception, another exception occurred:

Traceback (most recent call last):
  File "{tmp_path}/Form1.py", line 7, in load
ValueError: bad settings
"""
    assert watch(tmp_path, output) == [("Form1.py", 5, "KeyError: 'x'"), ("Form1.py", 7, "ValueError: bad settings")]
