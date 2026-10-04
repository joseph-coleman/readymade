from pybasic import Form, msgbox, inputbox, open_file_dialog

class Form2(Form):
    def btnOpen_click(self):
          path = open_file_dialog(filetypes={"Text files": "*.txt", "All files": "*"})
          if path is None:
              return  # cancelled
          self.TextBox1.text = path.read_text()

    def btnDelete_click(self):
          if msgbox("Delete this contact?", buttons="yesno", icon="question") == "yes":
              ...

    def btnAdd_click(self):
          name = inputbox("Name of the new contact:")  # None if Cancel