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
    and remove() (or del self.Digit[9]) takes away one made that way."""

    def __init__(self, name, form):
        self.name = name
        self._form = form
        self._items = {}  # index -> control

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
        self._form._remove_element(self, self[index])

    def __delitem__(self, index):
        self.remove(index)

    def _which(self):
        return f" (it has {', '.join(map(str, self.indexes))})" if self._items else ""

    def __repr__(self):
        return f"<ControlArray {self.name}: {', '.join(map(str, self.indexes))}>"
