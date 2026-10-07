"""Code coloring: with Pygments, and the built-in fallback without it."""

import time

import pytest

from readymade.ide import highlight

SAMPLE = '''@property
def area(self, n=3):
    """The area."""
    if n and True:
        return print(f"{n}\\n")  # done
class Box(Exception): pass
'''


def tags_by_text(spans, source=SAMPLE):
    lines = source.split("\n")

    def text(start, end):
        (l1, c1), (l2, c2) = (map(int, start.split(".")), map(int, end.split(".")))
        return lines[l1 - 1][c1:c2] if l1 == l2 else None

    return {text(start, end): tag for tag, start, end in spans}


@pytest.mark.skipif(highlight._LEXER is None, reason="needs Pygments")
def test_pygments_coloring():
    tags = tags_by_text(highlight.spans(SAMPLE))
    assert tags["@property"] == "function"
    assert tags["def"] == "keyword" and tags["area"] == "function" and tags["self"] == "variable"
    assert tags["3"] == "number" and tags['"""The area."""'] == "string"
    assert tags["if"] == "control" and tags["return"] == "control" and tags["True"] == "keyword"
    assert tags["print"] == "function" and tags["\\n"] == "escape" and tags["# done"] == "comment"
    assert tags["class"] == "keyword" and tags["Box"] == "class" and tags["Exception"] == "class"


@pytest.mark.skipif(highlight._LEXER is None, reason="needs Pygments")
def test_positions_survive_multiline_strings_and_tabs():
    source = 'x = """one\ntwo"""\n\ty = 1  # tab\n'
    spans = highlight.spans(source)
    assert ("string", "1.4", "2.6") in spans
    assert ("comment", "3.8", "3.13") in spans


def test_fallback_without_pygments(monkeypatch):
    monkeypatch.setattr(highlight, "_LEXER", None)
    tags = tags_by_text(highlight.spans(SAMPLE))
    assert tags["def"] == "keyword" and tags["return"] == "control" and tags["# done"] == "comment"
    assert tags['"""The area."""'] == "string"
    assert "print" not in tags  # only keywords, strings and comments


@pytest.mark.skipif(highlight._LEXER is None, reason="needs Pygments")
def test_adjacent_spans_of_one_color_are_merged():
    # Pygments gives the quotes and the text of "ab" as three tokens; they become one span.
    assert highlight.spans('s = "ab"\n') == [("string", "1.4", "1.8")]


def test_long_modules_color_quickly():
    source = SAMPLE * 500  # 3000 lines
    start = time.perf_counter()
    highlight.spans(source)
    assert time.perf_counter() - start < 2


@pytest.mark.parametrize("use_pygments", [True, False])
def test_imports_look_like_control_flow(monkeypatch, use_pygments):
    if not use_pygments:
        monkeypatch.setattr(highlight, "_LEXER", None)
    elif highlight._LEXER is None:
        pytest.skip("needs Pygments")
    source = "from os import path as p\nwith open(p) as f: pass\n"
    tags = tags_by_text(highlight.spans(source), source)
    assert tags["from"] == tags["import"] == tags["as"] == tags["with"] == "control"
