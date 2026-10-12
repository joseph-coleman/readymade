"""Control arrays: controls that share a name and their event handlers (VB's control arrays)."""

from __future__ import annotations

from typing import Generic, Iterator, TypeVar

T = TypeVar("T")


class ControlArray(Generic[T]):
    """Controls that share a name, each with its own index: the designer's Digit[0],
    Digit[1]... are self.Digit[0], self.Digit[1]. They share their event handlers, which
    are told which one with index, before the event's own arguments:

        def Digit_click(self, index):
            self.Display.text += str(index)

    Indexes needn't run on without gaps. add() makes another one while the program runs,
    and remove() (or del self.Digit[9]) takes away one made that way. on() attaches a handler
    to all of them, those added later too."""

    def __init__(self, name, form):
        self.name = name
        self._form = form
        self._items = {}  # index -> control
        self._listeners = []  # (event, handler): on() for every control, those added later too

    def __getitem__(self, index) -> T:
        try:
            return self._items[int(index)]
        except KeyError:
            raise IndexError(f"{self.name} has no control {index}{self._which()}") from None

    def __iter__(self) -> Iterator[T]:
        return iter([self._items[i] for i in sorted(self._items)])

    def __len__(self):
        return len(self._items)

    def __contains__(self, index):
        return index in self._items

    @property
    def indexes(self):
        """Its controls' indexes, from lowest to highest."""
        return sorted(self._items)

    def add(self, index) -> T:
        """Make another control in it, with this index, while the program runs: a copy of the
        lowest-numbered one, in the same place and hidden (move it, and set visible). Returns it."""
        index = int(index)
        if index in self._items:
            raise ValueError(f"{self.name} already has a control {index}")
        if not 0 <= index <= 32767:
            raise ValueError(f"an index can be 0 to 32767, not {index}")
        return self._form._add_element(self, index)

    def remove(self, index):
        """Take away a control that add() made (not one from the designer)."""
        self._form.remove_control(self[index])

    def __delitem__(self, index):
        self.remove(index)

    def on(self, event, handler=None):
        """Run handler too when event happens to any of its controls, those added later too.

        It's told which by index first, as Name_event(self, index) is: def lit(index): ...
        (a plain function wanting one more argument is given the form before index). Returns
        handler, so it works as a decorator too."""
        if handler is None:
            return lambda func: self.on(event, func)
        for control in self:
            control._listen(event, handler, first=(control.index,))
        self._listeners.append((event, handler))
        return handler

    def off(self, event, handler):
        """Stop running a handler that on() attached to its controls. True if it was attached."""
        attached = (event, handler) in self._listeners
        if attached:
            self._listeners.remove((event, handler))
        return any([control.off(event, handler) for control in self]) or attached

    def _which(self):
        return f" (it has {', '.join(map(str, self.indexes))})" if self._items else ""

    def __repr__(self):
        return f"<ControlArray {self.name}: {', '.join(map(str, self.indexes))}>"
