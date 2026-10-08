"""Anchors: resize this window and watch the controls follow it.

Each control's anchor (in the Properties panel) names the edges of its container
(the form, or a Frame) it keeps its distance to:

    txtItem      "top left right"         stretches across
    btnAdd       "top right"              stays at the top right
    lstItems     "top bottom left right"  stretches both ways
    fraActions   "top bottom right"       stays at the right, stretches down;
      btnRemove  "top left"                 inside it, stays at its top
      btnClear   "bottom left"              and stays at its bottom
    lblSize      "bottom left"            stays at the bottom left
    lblHint      "bottom"                 stays centered across the bottom
    btnClose     "bottom right"           stays at the bottom right

Resize the form in the designer too: the anchored controls follow it there as well.
"""

from readymade import Form


class Form1(Form):
    def Form_load(self):
        self.show_size()

    def Form_resize(self):
        self.show_size()  # (the controls have already followed the new size)

    def show_size(self):
        self.lblSize.text = f"Window: {self.width} x {self.height}"

    def btnAdd_click(self):
        item = self.txtItem.text.strip()
        if item:
            self.lstItems.add_item(item)
            self.txtItem.text = ""

    def btnRemove_click(self):
        if self.lstItems.list_index >= 0:
            self.lstItems.remove_item(self.lstItems.list_index)

    def btnClear_click(self):
        self.lstItems.clear()

    def btnClose_click(self):
        self.close()


if __name__ == "__main__":
    Form1.run()
