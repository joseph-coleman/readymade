from pybasic import Form


class Form1(Form):
    def Form_load(self):
        self.Label1.text = "What's your name?"

    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"
        self.Label2.text = f"Hello, {name}!"

    def TextBox1_keypress(self, key):
        if key == "Return":
            self.Button1_click()

    def Button1_mousedown(self, x, y):
        print("mouse down!")


if __name__ == "__main__":
    Form1.run()
