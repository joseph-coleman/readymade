"""examples/controls, the Recipe Box: each control does what its README.md says (run on a copy)."""

import importlib.util
import shutil
import sys
import time
import tkinter as tk
from pathlib import Path

import pytest

pytestmark = pytest.mark.usefixtures("display")
EXAMPLE = Path(__file__).resolve().parent.parent / "examples" / "controls"


@pytest.fixture
def program(tmp_path, monkeypatch):
    """The example's Form1 module, loaded from a copy, with its message boxes answered."""
    folder = shutil.copytree(EXAMPLE, tmp_path / "controls")
    monkeypatch.syspath_prepend(str(folder))
    monkeypatch.chdir(folder)
    monkeypatch.delitem(sys.modules, "recipes", raising=False)  # (a fresh copy of its data)
    spec = importlib.util.spec_from_file_location("recipe_box", folder / "Form1.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.said = []
    monkeypatch.setattr(module, "msgbox", lambda message, *a, **kw: module.said.append(message) or "yes")
    monkeypatch.setattr(module, "inputbox", lambda *a, **kw: "Toast")
    yield module
    sys.modules.pop("recipes", None)


@pytest.fixture
def form(program):
    form = program.Form1("Form1.form")
    form.show()
    settle(form)
    yield form
    form.root.destroy()


def settle(form, seconds=0.05):
    end = time.time() + seconds
    while time.time() < end:
        form.root.update()
        time.sleep(0.005)


def test_choosing_a_recipe_and_its_servings(form):
    assert form.Recipes.selected.text == "Pancakes"
    assert form.Status.text == "Pancakes: serves 4, about 15 minutes"
    assert [i.values for i in form.Ingredients.items][:2] == [["Flour", "200", "g"], ["Milk", "300", "ml"]]
    form.Servings.value = 2  # half as many
    assert form.Ingredients.items[0].values == ["Flour", "100", "g"]
    form.Servings.value = 3
    assert form.Ingredients.items[2].values == ["Eggs", "1.5", ""]
    soup = next(n for n in form.Recipes.node("Dinner").children if n.text == "Tomato soup")
    form.Recipes.selected = soup
    settle(form)
    assert form.Servings.value == 4 and form.Minutes.value == 30 and form.MinutesValue.text == "30"
    assert "Soften the onion" in form.Method.text


def test_the_toolbar(form, program):
    form.Bold.widget.invoke()  # a CheckBox that looks like a button: a toggle
    form.Align[2].widget.invoke()  # a control array of OptionButtons: Align_click(self, index)
    assert form.Method.font == ", 11, bold" and form.Method.alignment == "right"
    form.TextSize.value = 16
    assert form.Method.font == ", 16, bold"
    form.Bold.widget.invoke()
    assert form.Method.font == ", 16"
    form.NewRecipe.widget.invoke()  # (the input box answers "Toast")
    settle(form)
    assert form.Recipes.selected.text == "Toast" and form.Recipes.selected.parent.text == "Breakfast"
    assert "Toast" in program.RECIPES["Breakfast"]
    form.DeleteRecipe.widget.invoke()  # (the message box answers yes)
    assert "Toast" not in program.RECIPES["Breakfast"] and form.Status.text == "Deleted Toast"


def test_cooking_counts_down(form, program):
    form.Tabs.tab = 2
    form.Minutes.value = 3
    form.Start.widget.invoke()
    assert form.Start.text == "Stop" and form.Progress.max == 3
    settle(form, 1.5)  # (a "minute" is a quarter of a second here)
    assert form.Progress.value == 3 and form.CookStatus.text == "Ready!" and program.said == ["Ready!"]
    assert form.Start.text == "Start" and not form.CookTimer.enabled


def test_it_opens_in_the_designer(tmp_path):
    from readymade.ide.app import App

    shutil.copytree(EXAMPLE, tmp_path / "controls")
    root = tk.Tk()
    app = App(root, tmp_path / "controls")
    try:
        surface = app.form.surface
        assert len(surface.controls) == 27
        assert surface.controls["NewRecipe"]._photo is not None  # (its picture, from images/)
        assert surface.controls["Align[1]"].widget.winfo_class() == "TRadiobutton"  # (flat: a Toolbutton)
    finally:
        app.runner.stop()
        root.destroy()
