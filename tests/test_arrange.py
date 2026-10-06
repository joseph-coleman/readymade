import pytest

from readymade.ide import arrange

RECTS = {"a": (10, 10, 50, 20), "b": (30, 50, 100, 40), "ref": (20, 100, 80, 30)}


@pytest.mark.parametrize("edge, expected", [
    ("lefts", {"a": (20, 10, 50, 20), "b": (20, 50, 100, 40)}),
    ("centers", {"a": (35, 10, 50, 20), "b": (10, 50, 100, 40)}),
    ("rights", {"a": (50, 10, 50, 20), "b": (0, 50, 100, 40)}),
    ("tops", {"a": (10, 100, 50, 20), "b": (30, 100, 100, 40)}),
    ("middles", {"a": (10, 105, 50, 20), "b": (30, 95, 100, 40)}),
    ("bottoms", {"a": (10, 110, 50, 20), "b": (30, 90, 100, 40)}),
])
def test_align_to_the_reference(edge, expected):
    result = arrange.align(RECTS, "ref", edge)
    assert result["ref"] == RECTS["ref"]
    assert {k: v for k, v in result.items() if k != "ref"} == expected


def test_to_grid_and_same_size():
    assert arrange.to_grid({"a": (13, 3, 50, 20)}, 8) == {"a": (16, 0, 50, 20)}
    sized = arrange.same_size(RECTS, "ref", height=False, fixed={"b"})
    assert sized == {"a": (10, 10, 80, 20), "b": (30, 50, 100, 40), "ref": (20, 100, 80, 30)}


def test_space_evenly_keeps_the_ends():
    rects = {"a": (0, 0, 10, 10), "c": (100, 0, 20, 10), "b": (30, 0, 30, 10)}  # gaps of 20 and 40
    assert arrange.space_evenly(rects, "x") == {"a": (0, 0, 10, 10), "b": (40, 0, 30, 10), "c": (100, 0, 20, 10)}
    assert arrange.space_evenly({"a": (0, 0, 1, 1), "b": (9, 0, 1, 1)}, "x") == {"a": (0, 0, 1, 1), "b": (9, 0, 1, 1)}


def test_center_moves_the_group_as_one():
    rects = {"a": (0, 10, 20, 10), "b": (40, 30, 20, 10)}  # 60 wide, 30 tall together
    assert arrange.center(rects, (200, 100), "x") == {"a": (70, 10, 20, 10), "b": (110, 30, 20, 10)}
    assert arrange.center(rects, (200, 100), "y") == {"a": (0, 35, 20, 10), "b": (40, 55, 20, 10)}
