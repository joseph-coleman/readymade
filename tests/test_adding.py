"""Handlers attached from code (on/off), and controls added while the program runs."""

import time

import pytest

from readymade import Form, formfile, while_running
from readymade.controls import REGISTRY

pytestmark = pytest.mark.usefixtures("display")


@pytest.fixture
def make_form(tmp_path):
    made = []

    def make(cls, *controls):
        design = formfile.FormDesign(name="Form1", width=400, height=300)
        for type_name, name, props in controls:
            spec = REGISTRY[type_name].new_spec(name, 8, 8)
            spec.update(props)
            design.controls.append(spec)
        formfile.save(design, tmp_path / "Form1.form")
        form = cls(tmp_path / "Form1.form")
        form.show()
        settle(form)
        made.append(form)
        return form

    yield make
    for form in made:
        if form.loaded:
            form.root.destroy()


def settle(form, seconds=0.05):
    end = time.time() + seconds
    while time.time() < end:
        form.root.update()
        time.sleep(0.005)


# A handler in another module: a plain function, given the form first (it has no self of its own).
def module_handler(form):
    form.seen.append(("module", form.text))


def test_on_attaches_handlers_after_the_named_one(make_form):
    class Form1(Form):
        seen = []

        def OK_click(self):
            self.seen.append("named")

        def also(self):
            self.seen.append("method")

    form = make_form(Form1, ("Button", "OK", {}), ("ListBox", "Pick", {"top": 60}))
    ok = form.OK
    assert ok.form is form and form.Pick.form is form
    ok.on("click", form.also)  # a method of the form: self is bound already
    ok.on("click", lambda: form.seen.append("lambda"))
    ok.on("click", module_handler)  # given the form

    @ok.on("click")
    def decorated():
        form.seen.append("decorated")

    ok.widget.invoke()
    assert form.seen == ["named", "method", "lambda", ("module", "Form1"), "decorated"]
    assert ok.off("click", module_handler) and not ok.off("click", module_handler)
    assert ok.off("click", form.also)  # (an equal bound method)
    form.seen.clear()
    ok.widget.invoke()
    assert form.seen == ["named", "lambda", "decorated"]
    with pytest.raises(ValueError, match="a Button has no 'change' event; its events: click"):
        ok.on("change", form.also)


def test_handlers_get_the_events_arguments(make_form):
    class Form1(Form):
        seen = []

    form = make_form(Form1, ("TextBox", "Box", {}), ("Slider", "Level", {"top": 60, "max": 10}))
    form.Box.on("keypress", lambda key: form.seen.append(("key", key)))
    form.Box.on("keypress", lambda form, key: form.seen.append(("form and key", key)))  # one more: the form
    form.Level.on("change", lambda: form.seen.append(("level", form.Level.value)))
    form.Box.editor.focus_force()
    settle(form)
    form.Box.editor.event_generate("<KeyPress>", keysym="a")
    form.Level.value = 4
    settle(form)
    assert form.seen == [("key", "a"), ("form and key", "a"), ("level", 4)]


def test_policies_and_async_handlers(make_form):
    class Form1(Form):
        seen = []

    form = make_form(Form1, ("Button", "Go", {}))

    @form.Go.on("click")
    @while_running("ignore")
    def busy():
        form.seen.append("start")
        form.Go.widget.invoke()  # (clicked again while busy: ignored)
        form.seen.append("end")

    async def later():
        form.seen.append("async")

    form.Go.on("click", later)
    form.Go.widget.invoke()
    settle(form, 0.2)
    assert form.seen == ["start", "end", "async"]


def test_a_control_arrays_handlers(make_form):
    class Form1(Form):
        seen = []

    form = make_form(Form1, ("Button", "Key[0]", {}), ("Button", "Key[1]", {"left": 60}))
    form.Key.on("click", lambda index: form.seen.append(index))
    form.Key.on("click", lambda form, index: form.seen.append(("form", index)))
    nine = form.Key.add(9)  # added later: it gets them too
    for key in form.Key:
        key.widget.invoke()
    assert form.seen == [0, ("form", 0), 1, ("form", 1), 9, ("form", 9)]
    assert nine.off("click", form.seen.append) is False
    form.seen.clear()
    handler = form.Key._listeners[0][1]
    assert form.Key.off("click", handler)
    form.Key[1].widget.invoke()
    assert form.seen == [("form", 1)]


def test_the_forms_own_events(make_form):
    class Form1(Form):
        seen = []

    form = make_form(Form1, ("Button", "OK", {}))
    form.on("keydown", lambda key: form.seen.append(("down", key)))  # (it starts listening for keys)
    form.on("unload", lambda: True)  # keeps the form open
    later = form.add_control("TextBox", "Later", top=60)  # made after: its keys count too
    later.editor.focus_force()
    settle(form)
    later.editor.event_generate("<KeyPress>", keysym="b")
    settle(form)
    assert ("down", "B") in form.seen
    form.close()
    assert form.loaded
    with pytest.raises(ValueError, match="a form has no 'change' event"):
        form.on("change", print)


def test_adding_and_removing_controls(make_form):
    class Form1(Form):
        seen = []

        def Search_change(self):  # written before the control exists: attached when it's added
            self.seen.append(self.Search.text)

    form = make_form(Form1, ("Frame", "Box", {"width": 200, "height": 120}), ("Button", "OK", {"left": 220}))
    search = form.add_control("TextBox", "Search", left=8, top=180, width=200, text="")
    assert form.Search is search and search.form is form and (search.left, search.width) == (8, 200)
    search.text = "jam"
    assert form.seen == ["jam"]
    assert search.tabindex == max(c.tabindex for c in form.controls.values() if hasattr(c, "tabindex"))  # last
    inside = form.add_control("Label", "Inside", container=form.Box, text="Hello")
    assert inside.widget.master is form.Box.inner and inside.text == "Hello"
    docked = form.add_control("Label", "Status", dock="bottom", height=20, text="Ready")
    settle(form)
    assert (docked.top, docked.width) == (280, 400)
    with pytest.raises(ValueError, match="there's no 'Spinner' control"):
        form.add_control("Spinner", "X")
    with pytest.raises(ValueError, match="already a control named 'OK'"):
        form.add_control("Label", "OK")
    with pytest.raises(ValueError, match="a Label has no colour"):
        form.add_control("Label", "Z", colour="red")
    with pytest.raises(ValueError, match="isn't a container"):
        form.add_control("Label", "Z", container="OK")
    holder = form.add_control("Frame", "Holder", top=200)
    form.add_control("Label", "Held", container=holder)
    with pytest.raises(ValueError, match="has controls in it"):
        form.remove_control(holder)
    form.remove_control("Inside")
    assert "Inside" not in form.controls and not hasattr(form, "Inside")
    with pytest.raises(ValueError, match="made in the designer"):
        form.remove_control(form.OK)


def test_starting_a_control_array_from_code(make_form):
    class Form1(Form):
        seen = []

        def Digit_click(self, index):
            self.seen.append(index)

    form = make_form(Form1)
    for i in range(3):
        form.add_control("Button", f"Digit[{i}]", left=8 + 40 * i, width=32, text=str(i))
    assert form.Digit.indexes == [0, 1, 2] and form.Digit[2].text == "2"
    form.Digit[1].widget.invoke()
    assert form.seen == [1]
    with pytest.raises(ValueError, match="a control array of Buttons, not Labels"):
        form.add_control("Label", "Digit[3]")
    del form.Digit[2]
    assert form.Digit.indexes == [0, 1]
