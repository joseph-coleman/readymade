"""The TreeView and ListView controls: nodes in a tree, and rows under column headers.

Both are ttk's Treeview underneath. Their entries are objects (a Node, a ListItem) that
stay the same while they're there, so code can keep one and compare: `if node is tree.selected`.
"""

from __future__ import annotations

from tkinter import font as tkfont
from tkinter import ttk

from readymade import appearance
from readymade.controls.base import _FOCUS_EVENTS, Control, Event, register
from readymade.controls.traits import Anchored, BackColor, Cursor, Font, ForeColor, TabStop, Tooltip, _TtkEnabled


class _TreeLook:
    """Colors and font for a ttk Treeview, which takes them from a style: each colored one gets its own."""

    widget: ttk.Treeview

    def _look_tree(self):
        """The Treeview to style (a DataTable's is inside its frame)."""
        return self.widget

    def _style_name(self):
        if self._background() or self._foreground() or self._font:
            return f"readymade{id(self)}.Treeview"
        return "Preview.Treeview" if self.design else "Treeview"  # (light in a dark IDE, as the program will be)

    def _paint(self):
        if not self._ready:
            return
        name = self._style_name()
        if name.startswith("readymade"):
            style = ttk.Style(self._look_tree())
            bg, fg = self._background(), self._foreground()
            style.configure(name, **{k: v for k, v in (("background", bg), ("fieldbackground", bg), ("foreground", fg))
                                     if v})
            # Windows' and macOS's own themes draw a Treeview's empty space themselves, ignoring
            # fieldbackground: with a backcolor, the space under the rows is ttk's plain field instead.
            style.layout(name, _with_plain_field(style, style.layout("Treeview")) if bg else style.layout("Treeview"))
            if self._font:
                usual = tkfont.nametofont("TkDefaultFont", root=self._look_tree()).actual()
                spec = appearance.tk_font(self._font, usual)  # (a Tk font description: a dict isn't one)
                font = tkfont.Font(root=self._look_tree(), font=spec)
                style.configure(name, font=spec, rowheight=font.metrics("linespace") + 4)
                style.configure(f"{name}.Heading", font=spec)
        self._look_tree()["style"] = name

    def _apply_font(self):
        self._paint()  # (a Treeview's font is its style's)


_PLAIN_FIELD = "Readymade.field"


def _with_plain_field(style, layout):
    """A Treeview layout with ttk's plain field (it shows fieldbackground) in place of the theme's."""
    if _PLAIN_FIELD not in style.element_names():  # (an element is made in the theme in use)
        style.element_create(_PLAIN_FIELD, "from", "default", "field")
    def inner(options):
        return {**options, "children": _with_plain_field(style, options["children"])} if "children" in options else options

    return [(_PLAIN_FIELD if name.endswith(".field") else name, inner(options)) for name, options in layout]


class Node:
    """One entry in a TreeView: its text, the nodes under it, and whether it's open
    (expanded) to show them. Made by TreeView.add() or another node's add()."""

    def __init__(self, tree, key):
        self._tree, self._key = tree, key

    def _there(self):
        """Its key, if it's still in its tree (a removed node can't be shown or changed)."""
        if self._tree._nodes.get(self._key) is not self:
            raise ValueError(f"{self._tree.name} no longer has this node (it was removed)")
        return self._key

    @property
    def key(self):
        """The name it's known by: TreeView.node(key) finds it."""
        return self._key

    @property
    def text(self):
        """The words it shows."""
        return self._tree.widget.item(self._there(), "text")

    @text.setter
    def text(self, value):
        self._tree.widget.item(self._there(), text=str(value))

    @property
    def parent(self):
        """The node it's under, or None at the top."""
        parent = self._tree.widget.parent(self._there())
        return self._tree._nodes[parent] if parent else None

    @property
    def children(self):
        """The nodes just under it, in order."""
        return [self._tree._nodes[k] for k in self._tree.widget.get_children(self._there())]

    @property
    def expanded(self):
        """Whether it's open, showing the nodes under it."""
        return bool(self._tree.widget.item(self._there(), "open"))

    @expanded.setter
    def expanded(self, value):
        self._tree.widget.item(self._there(), open=bool(value))

    def add(self, text, key=None):
        """Add a node under this one (at the end); returns it."""
        return self._tree.add(text, parent=self, key=key)

    def remove(self):
        """Take it (and the nodes under it) out of the tree."""
        self._tree._remove(self._there())

    def see(self):
        """Open the nodes above it and scroll it into view."""
        self._tree.widget.see(self._there())

    def __repr__(self):
        removed = self._tree._nodes.get(self._key) is not self
        return "<Node (removed)>" if removed else f"<Node {self.text!r}>"


@register
class TreeView(_TtkEnabled, _TreeLook, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """Nodes in a tree, each able to hold more under it, opened and closed with the ▸ beside
    it (as Windows Explorer's folders). add() makes a node and returns it (a Node), which
    can add() nodes of its own:

        fruit = self.TreeView1.add("Fruit")
        fruit.add("Apple")
        fruit.expanded = True

    nodeclick runs when a node is chosen, expand and collapse when the user opens or closes
    one; each is given the Node. In the designer, items lists the nodes, one per line, two
    spaces in for each level under."""

    type_name = "TreeView"
    default_size = (160, 160)
    default_event = "nodeclick"
    events = (Event("nodeclick", ("node",), policy="latest"), Event("dblclick"), Event("expand", ("node",)),
              Event("collapse", ("node",)), *_FOCUS_EVENTS)
    extra_props = {"items": []}

    def create_widget(self, parent):
        self._nodes = {}  # key -> Node
        self._enabled = True
        tree = ttk.Treeview(parent, show="tree", selectmode="browse")
        return tree

    @property
    def items(self):
        """The nodes as lines, each indented two spaces for each level it's under (set in the
        designer, or give a list to replace them all)."""
        lines = []

        def walk(key, depth):
            for child in self.widget.get_children(key):
                lines.append("  " * depth + self.widget.item(child, "text"))
                walk(child, depth + 1)

        walk("", 0)
        return lines

    @items.setter
    def items(self, lines):
        self.clear()
        above = []  # the latest node at each depth
        for line in lines:
            text = str(line)
            depth = (len(text) - len(text.lstrip(" "))) // 2
            depth = min(depth, len(above))  # (one too far in goes just under the one before)
            node = self.add(text.strip(), parent=above[depth - 1] if depth else None)
            above[depth:] = [node]

    def add(self, text, parent=None, key=None):
        """Add a node (at the top, or under parent: a Node or its key); returns the Node.
        key names it for node(key); without one it's given a key of its own."""
        if isinstance(parent, Node):
            parent = parent.key
        if parent is not None and parent not in self._nodes:
            raise ValueError(f"{self.name} has no node {parent!r}")
        if key is not None:
            key = str(key)
            if key in self._nodes:
                raise ValueError(f"{self.name} already has a node {key!r}")
        key = self.widget.insert(parent or "", "end", iid=key, text=str(text))
        node = self._nodes[key] = Node(self, key)
        return node

    def node(self, key):
        """The node with this key, or None."""
        return self._nodes.get(str(key))

    @property
    def nodes(self):
        """The nodes at the top, in order."""
        return [self._nodes[k] for k in self.widget.get_children("")]

    def clear(self):
        """Take out every node."""
        self.widget.delete(*self.widget.get_children(""))
        self._nodes.clear()

    @property
    def selected(self):
        """The chosen node, or None. Set it to a Node (or its key) to choose one."""
        chosen = self.widget.selection()
        return self._nodes.get(chosen[0]) if chosen else None

    @selected.setter
    def selected(self, node):
        if node is None:
            self.widget.selection_set(())
            return
        key = node.key if isinstance(node, Node) else str(node)
        if key not in self._nodes:
            raise ValueError(f"{self.name} has no node {key!r}")
        self.widget.selection_set(key)
        self.widget.focus(key)
        self.widget.see(key)

    def _remove(self, key):
        def forget(k):
            for child in self.widget.get_children(k):
                forget(child)
            self._nodes.pop(k, None)

        forget(key)
        self.widget.delete(key)

    def bind_event(self, event, handler):
        if event == "nodeclick":
            self.widget.bind("<<TreeviewSelect>>", lambda e: self.selected and handler(self.selected), add="+")
        elif event in ("expand", "collapse"):
            sequence = "<<TreeviewOpen>>" if event == "expand" else "<<TreeviewClose>>"
            self.widget.bind(sequence, lambda e: self._focused() and handler(self._focused()), add="+")
        elif event == "dblclick":
            self.widget.bind("<Double-Button-1>", lambda e: self.widget.identify_row(e.y) and handler(), add="+")
        else:
            super().bind_event(event, handler)

    def _focused(self):
        return self._nodes.get(self.widget.focus())


class ListItem:
    """One row of a ListView: its values, one for each column. Made by ListView.add()."""

    def __init__(self, view, key):
        self._view, self._key = view, key

    def _there(self):
        """Its key, if it's still in its list (a removed row can't be shown or changed)."""
        if self._view._items.get(self._key) is not self:
            raise ValueError(f"{self._view.name} no longer has this row (it was removed)")
        return self._key

    @property
    def key(self):
        """The name it's known by: ListView.item(key) finds it."""
        return self._key

    @property
    def values(self):
        """Its values, one for each column, as strings. Set a list to change them all."""
        values = [str(v) for v in self._view.widget.item(self._there(), "values")]
        return values + [""] * (len(self._view.columns) - len(values))

    @values.setter
    def values(self, values):
        self._view.widget.item(self._there(), values=[str(v) for v in values])

    @property
    def text(self):
        """Its first column's value."""
        return self.values[0] if self.values else ""

    @text.setter
    def text(self, value):
        self.values = [value, *self.values[1:]]

    @property
    def index(self):
        """Its place in the list as shown, counting from 0."""
        return self._view.widget.index(self._there())

    def remove(self):
        """Take it out of the list."""
        self._view.widget.delete(self._there())
        self._view._items.pop(self._key, None)

    def see(self):
        """Scroll it into view."""
        self._view.widget.see(self._there())

    def __repr__(self):
        removed = self._view._items.get(self._key) is not self
        return "<ListItem (removed)>" if removed else f"<ListItem {self.values!r}>"


@register
class ListView(_TtkEnabled, _TreeLook, BackColor, ForeColor, Font, TabStop, Cursor, Tooltip, Anchored, Control):
    """Rows of values under column headers (VB's ListView in its Report view). columns are
    the headers; add() adds a row and returns it (a ListItem):

        row = self.ListView1.add("readme.txt", "4 KB")
        row.values = ["readme.md", "4 KB"]

    With sortable, a click on a header sorts by that column (again: the other way).
    itemclick runs when a row is chosen, given the ListItem; columnclick when a header is
    clicked, given its column number (counting from 0)."""

    type_name = "ListView"
    default_size = (240, 160)
    default_event = "itemclick"
    events = (Event("itemclick", ("item",), policy="latest"), Event("dblclick"), Event("columnclick", ("column",)),
              *_FOCUS_EVENTS)
    extra_props = {"columns": ["Name", "Value"], "sortable": True, "multiselect": False}

    def create_widget(self, parent):
        self._items = {}  # key -> ListItem
        self._enabled = True
        self._columns = []
        self._sortable, self._multiselect = True, False
        self._sorted = None  # (column, descending) it's sorted by
        self._on_column = []
        return ttk.Treeview(parent, show="headings", selectmode="browse")

    @property
    def columns(self):
        """The column headers, as a list of strings (one per line in the Properties panel)."""
        return list(self._columns)

    @columns.setter
    def columns(self, headers):
        self._columns = [str(h) for h in headers] or ["Column 1"]
        ids = [f"c{i}" for i in range(len(self._columns))]
        self.widget.configure(columns=ids, displaycolumns=ids)
        for index, header in enumerate(self._columns):
            self.widget.column(ids[index], width=60, stretch=True, anchor="w")
            self.widget.heading(ids[index], text=header, anchor="w", command=lambda i=index: self._header_clicked(i))
        self._sorted = None

    @property
    def sortable(self):
        """Whether a click on a column header sorts the rows by it."""
        return self._sortable

    @sortable.setter
    def sortable(self, value):
        self._sortable = bool(value)

    @property
    def multiselect(self):
        """Whether several rows can be chosen at once (with Ctrl and Shift)."""
        return self._multiselect

    @multiselect.setter
    def multiselect(self, value):
        self._multiselect = bool(value)
        self.widget.configure(selectmode="extended" if self._multiselect else "browse")

    def add(self, *values, key=None):
        """Add a row at the end, with a value for each column; returns it (a ListItem).
        key names it for item(key); without one it's given a key of its own."""
        if key is not None:
            key = str(key)
            if key in self._items:
                raise ValueError(f"{self.name} already has an item {key!r}")
        key = self.widget.insert("", "end", iid=key, values=[str(v) for v in values])
        item = self._items[key] = ListItem(self, key)
        return item

    def item(self, key):
        """The row with this key, or None."""
        return self._items.get(str(key))

    @property
    def items(self):
        """The rows, in the order shown."""
        return [self._items[k] for k in self.widget.get_children("")]

    def clear(self):
        """Take out every row."""
        self.widget.delete(*self.widget.get_children(""))
        self._items.clear()

    @property
    def selected(self):
        """The chosen row (with multiselect, the first), or None. Set it to a ListItem (or its
        key) to choose just that one."""
        chosen = self.selected_items
        return chosen[0] if chosen else None

    @selected.setter
    def selected(self, item):
        if item is None:
            self.widget.selection_set(())
            return
        key = item.key if isinstance(item, ListItem) else str(item)
        if key not in self._items:
            raise ValueError(f"{self.name} has no item {key!r}")
        self.widget.selection_set(key)
        self.widget.focus(key)
        self.widget.see(key)

    @property
    def selected_items(self):
        """The chosen rows, in the order shown."""
        chosen = set(self.widget.selection())
        return [self._items[k] for k in self.widget.get_children("") if k in chosen]

    def sort(self, column, descending=False):
        """Sort the rows by a column (counting from 0): as numbers if they all are, otherwise
        as text, ignoring case. The header shows ▲ or ▼."""
        column = int(column)
        if not 0 <= column < len(self._columns):
            raise ValueError(f"column must be from 0 to {len(self._columns) - 1}, not {column}")
        rows = self.items
        texts = [row.values[column] for row in rows]
        try:
            keys = [float(t.replace(",", "")) for t in texts]
        except ValueError:
            keys = [t.casefold() for t in texts]
        order = sorted(range(len(rows)), key=lambda i: keys[i], reverse=bool(descending))
        for place, i in enumerate(order):
            self.widget.move(rows[i].key, "", place)
        self._sorted = (column, bool(descending))
        for index, header in enumerate(self._columns):
            mark = (" ▼" if descending else " ▲") if index == column else ""
            self.widget.heading(f"c{index}", text=header + mark)

    def _header_clicked(self, column):
        if self.design:
            return
        if self._sortable:
            again = self._sorted is not None and self._sorted[0] == column
            self.sort(column, descending=again and not self._sorted[1])
        for handler in self._on_column:
            handler(column)

    def bind_event(self, event, handler):
        if event == "itemclick":
            self.widget.bind("<<TreeviewSelect>>", lambda e: self.selected and handler(self.selected), add="+")
        elif event == "columnclick":
            self._on_column.append(handler)
        elif event == "dblclick":
            self.widget.bind("<Double-Button-1>", lambda e: self.widget.identify_row(e.y) and handler(), add="+")
        else:
            super().bind_event(event, handler)
