from pybasic import Form, msgbox, inputbox, open_file_dialog
from pybasic import pause, in_thread, doevents, while_running
from time import sleep


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
          
    def crunch(self):
        for n in range(10):
            sleep(1)
          
          

    async def btnProcess_click(self):          # async handler: the window stays responsive
        for n in range(10):
            self.TextBox1.text = f"{n}"
            print(f"sleeping {n}")
            sleep(1)
            await pause()                       # let clicks and repaints through
        total = await in_thread(self.crunch)   # heavy work off the GUI thread
        self.TextBox1.text = "After in thread"

    def btnOld_click(self):                     # VB style still works
        for n in range(10):
            sleep(1)
            doevents()

    @while_running("queue")                     # rarely needed: change the default
    async def btnAddSomething_click(self):
        print("Added something")
        sleep(3)
        print("...")

  