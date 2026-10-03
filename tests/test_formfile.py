from pathlib import Path

import pytest

from pybasic import formfile

EXAMPLE = Path(__file__).parent.parent / "examples" / "hello" / "Form1.form"


def test_example_round_trips_byte_for_byte():
    text = EXAMPLE.read_text(encoding="utf-8")
    assert formfile.dumps(formfile.loads(text)) == text


def test_control_keys_are_identity_then_geometry_then_alphabetical():
    design = formfile.FormDesign(
        controls=[{"visible": True, "text": "Hi", "height": 2, "width": 1, "top": 0, "left": 0, "name": "L", "type": "Label"}]
    )
    saved = formfile.loads(formfile.dumps(design))
    assert list(saved.controls[0]) == ["type", "name", "left", "top", "width", "height", "text", "visible"]


def test_save_and_load(tmp_path):
    design = formfile.FormDesign(name="Main", text="My App", width=200, height=100)
    formfile.save(design, tmp_path / "Main.form")
    assert formfile.load(tmp_path / "Main.form") == design


@pytest.mark.parametrize(
    "text, message",
    [
        ("not json", "not valid JSON"),
        ('{"pybasic_form": 99}', "not a version 1"),
        ('{"pybasic_form": 1, "controls": [{"type": "Label"}]}', "needs a 'type' and a 'name'"),
        ('{"pybasic_form": 1, "controls": [{"type": "Label", "name": "L", "left": "0"}]}', "integer 'left'"),
    ],
)
def test_bad_files_explain_themselves(text, message):
    with pytest.raises(formfile.FormFileError, match=message):
        formfile.loads(text)


def test_containers_must_be_defined_first():
    child = '{"type": "Label", "name": "L", "container": "F", "left": 0, "top": 0, "width": 8, "height": 8}'
    frame = '{"type": "Frame", "name": "F", "left": 0, "top": 0, "width": 8, "height": 8}'
    formfile.loads(f'{{"pybasic_form": 1, "controls": [{frame}, {child}]}}')
    with pytest.raises(formfile.FormFileError, match="isn't defined before it"):
        formfile.loads(f'{{"pybasic_form": 1, "controls": [{child}, {frame}]}}')


def test_duplicate_names_are_rejected():
    frame = '{"type": "Frame", "name": "F", "left": 0, "top": 0, "width": 8, "height": 8}'
    with pytest.raises(formfile.FormFileError, match="more than one"):
        formfile.loads(f'{{"pybasic_form": 1, "controls": [{frame}, {frame}]}}')
