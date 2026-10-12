"""Every readymade module imports by itself: an import cycle can hide behind the order the
IDE happens to import things in."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

CHECK = """
import importlib, pkgutil, sys
import readymade
names = sorted(m.name for m in pkgutil.walk_packages(readymade.__path__, "readymade.")
               if not m.name.endswith("__main__"))  # (that one starts the IDE)
failed = []
for name in names:
    for loaded in [m for m in sys.modules if m == "readymade" or m.startswith("readymade.")]:
        del sys.modules[loaded]
    try:
        importlib.import_module(name)
    except Exception as e:
        failed.append(f"{name}: {type(e).__name__}: {e}")
print(len(names))
print("\\n".join(failed))
"""


def test_every_module_imports_alone():
    result = subprocess.run([sys.executable, "-c", CHECK], cwd=ROOT, capture_output=True, text=True, timeout=120)
    count, *failed = result.stdout.strip().split("\n")
    assert result.returncode == 0, result.stderr
    assert int(count) > 50  # (so it's finding them)
    assert [f for f in failed if f] == []


def test_tk_objects_name_their_window():
    """tk.StringVar() and the like, without a window, belong to whichever Tk was made first:
    in a program with two (the tests, say) a button and its variable can end up apart."""
    import ast

    makers = {"StringVar", "BooleanVar", "IntVar", "DoubleVar", "Style", "PhotoImage"}
    found = []
    for path in (ROOT / "readymade").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in makers
                    and isinstance(node.func.value, ast.Name) and node.func.value.id in ("tk", "ttk")
                    and not node.args and not any(k.arg == "master" for k in node.keywords)):
                found.append(f"{path.relative_to(ROOT)}:{node.lineno}: {node.func.value.id}.{node.func.attr}()")
    assert found == []
