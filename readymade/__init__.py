"""readymade: Visual Basic style forms for Python and Tkinter."""

from readymade.events import doevents, in_thread, pause, while_running
from readymade.dialogs import (color_dialog, folder_dialog, font_dialog, inputbox, msgbox, open_file_dialog,
                             save_file_dialog)
from readymade.form import Form, app_path, set_app_icon

__all__ = [
    "Form", "app_path", "color_dialog", "doevents", "folder_dialog", "font_dialog", "in_thread", "inputbox", "msgbox",
    "open_file_dialog", "pause", "save_file_dialog", "set_app_icon", "while_running",
]
