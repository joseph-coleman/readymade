"""Control types shared by the designer and the runtime.

Each Control subclass wraps one Tk widget and gives it VB-style properties
(text, left, top, width, height, enabled, visible) and a list of events.
REGISTRY maps a type name to its class. The designer's toolbox is built from
it, in registration order, so registering a new control type makes it
available everywhere.

    base.py     Control, Event, the registry, and functions for the form and designer
    traits.py   properties controls share, as mixins: BackColor, Font, TabStop, Anchored...
    label.py, textbox.py, frame.py, tabstrip.py, buttons.py, lists.py, trees.py, datatable.py, dates.py,
    ranges.py, image.py, canvas.py, grid.py, timer.py    the controls

A control class lists the traits it has before Control, and registers itself:

    @register
    class Button(WidgetText, BackColor, ForeColor, Font, ..., TabStop, Tooltip, Anchored, Control):
        type_name = "Button"
        ...

Everything is imported here too, so `from readymade.controls import Button` works.
"""

from __future__ import annotations

from readymade.controls.arrays import ControlArray
from readymade.controls.base import (REGISTRY, Control, Event, control_of, create, focus_widget, grid_of, inner_for,
                                     option_group, page_at, register, repaint_inside, show_as_default, show_page,
                                     shown_page, tab_numbers)
from readymade.controls.traits import (GRID_CELL, LOOK_CHOICES, Aligned, Anchored, BackColor, Cursor, Flat, Font,
                                       ForeColor, Oriented, Picture, Ranged, TabIndex, TabStop, Tooltip, VAligned,
                                       WidgetText)

# isort: off
# (The order they register in is the Toolbox's order.)
from readymade.controls.label import Label
from readymade.controls.textbox import TextBox
from readymade.controls.frame import Frame
from readymade.controls.tabstrip import TabStrip
from readymade.controls.buttons import Button, CheckBox, OptionButton
from readymade.controls.lists import ComboBox, ListBox
from readymade.controls.trees import ListItem, ListView, Node, TreeView
from readymade.controls.datatable import Block, Column, DataError, DataTable, Problem
from readymade.controls.dates import Calendar, DatePicker, TimePicker
from readymade.controls.ranges import ProgressBar, ScrollBar, Slider, UpDown
from readymade.controls.image import Image
from readymade.controls.canvas import Canvas
from readymade.controls.grid import Grid
from readymade.controls.timer import Timer
# isort: on

__all__ = [
    "REGISTRY", "Control", "ControlArray", "Event", "control_of", "create", "focus_widget", "grid_of", "inner_for",
    "option_group", "page_at", "register", "repaint_inside", "show_as_default", "show_page", "shown_page",
    "tab_numbers",
    "GRID_CELL", "LOOK_CHOICES", "Aligned", "Anchored", "BackColor", "Cursor", "Flat", "Font", "ForeColor", "Oriented",
    "Picture", "Ranged", "TabIndex", "TabStop", "Tooltip", "VAligned", "WidgetText",
    "Label", "TextBox", "Frame", "TabStrip", "Button", "CheckBox", "OptionButton", "ComboBox", "ListBox", "TreeView",
    "ListView", "DataTable", "Calendar", "DatePicker", "TimePicker", "ScrollBar", "Slider", "UpDown", "ProgressBar", "Image", "Canvas", "Grid", "Timer",
    "Node", "ListItem", "Column", "Block", "DataError", "Problem",
]
