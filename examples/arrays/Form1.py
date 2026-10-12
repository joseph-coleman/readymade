"""Controls made while the program runs, two ways. README.md walks through it."""

from readymade import Form

from helpers import clear_all, custom_click_event


class Form1(Form):
    def Form_load(self):
        # A control made from nothing, with a handler attached in code (as JavaScript does).
        # clear_all is a plain function in helpers.py: on() passes it the form.
        clear = self.add_control("Button", "Clear", container="Frame2", dock="bottom", height=32,
                                 text="Clear")
        clear.on("click", clear_all)

    # 1. Button1 is a control array drawn in the designer (Button1[0]); add() makes more like it.
    def Button1_click(self, index):
        b = self.Button1.add(max(self.Button1.indexes) + 1)  # a copy of Button1[0], hidden at first
        b.text = str(b.index)
        b.visible = True
        self.Status.text = f"Button1[{index}] made Button1[{b.index}]"

    # 2. B2 is a control array made in code: add_control() with names like "B2[0]". The
    # handler below, B2_click, is attached to each one as it's made, and told which by index.
    def UpDown1_change(self):
        for button in list(getattr(self, "B2", [])):  # last time's buttons, if any
            self.remove_control(button)
        for n in range(self.UpDown1.value):
            self.add_control("Button", f"B2[{n}]", container="Frame2", dock="top", text=f"Button {n}")

    def B2_click(self, index):
        custom_click_event(self, index)


if __name__ == "__main__":
    Form1.run()
