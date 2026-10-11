from readymade import Form, msgbox


class Form1(Form):
    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"

        if name == "break":
            # You can intentionally cause an error and then resume, F5
            print(1 / 0)

        msgbox(f"Hello, {name}!")

    def mnuHello_click(self):
        msgbox(
            message=(
                "You can use & in the menu to access the menu with" \
                "letter shortcuts.\n\nPress Alt or Cmd+Opt, and " \
                "then you can navigate with Letter pressed according" \
                "to the undrlined letter in the menus."
            ),
            title="Did you know?",
            buttons="ok",
            icon="question",
        )

    def mnuQA_click(self):
        msgbox("This menu label is really ''Q && A''")


if __name__ == "__main__":
    Form1.run()
