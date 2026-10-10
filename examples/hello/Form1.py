from readymade import Form, msgbox


class Form1(Form):
    def Button1_click(self):
        name = None 
        name = self.TextBox1.text.strip() or "World"

        print("why stop here?")

        if name == "break":
            print(1/0)

        print("break on this")

        name = "seven"
            
        
        msgbox(f"Hello, {name}!")


if __name__ == "__main__":
    Form1.run()
    