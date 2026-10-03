from pybasic import Form


class Form1(Form):
    def Form_load(self):
        self.n = 0
        self.Label1.text = "What's your name?"

    def Button1_click(self):
        name = self.TextBox1.text.strip() or "World"
        self.Label2.text = f"Hello, {name}!"

    def TextBox1_keypress(self, key):
        if key == "Return":
            self.Button1_click()

    def Button1_mousedown(self, x, y):
        print("mouse down!")

    def Timer1_timer(self):
        self.n += 1
        self.Label3.text = self.n 

    def Button2_click(self):
        self.Timer1.enabled = not self.Timer1.enabled


if __name__ == "__main__":
    Form1.run()
