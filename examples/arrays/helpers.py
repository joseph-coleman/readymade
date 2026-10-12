"""Handlers that live outside the form. They have no self, so the form is passed in:

- custom_click_event is called by the form's B2_click, which hands over self and the index.
- clear_all is attached with on(). on() sees a plain function wanting one more argument than
  the click event gives (none), and passes the form as that argument.
"""


def custom_click_event(form, index):
    button = form.B2[index]  # a control array: the index finds the button that was clicked
    form.Status.text = f"{button.text} was clicked (B2[{index}])"


def clear_all(form):
    form.UpDown1.value = 0  # (its change event takes the buttons away)
    form.Status.text = "Cleared"
