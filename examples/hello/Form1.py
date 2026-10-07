from readymade import Form, msgbox


class Form1(Form):
    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"
        msgbox(f"Hello, {name}!")


if __name__ == "__main__":
    Form1.run()