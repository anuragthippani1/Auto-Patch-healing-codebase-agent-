"""A stack and a bracket checker built on it."""

PAIRS = {")": "(", "]": "[", "}": "{"}


class Stack:
    """Last-in, first-out container."""

    def __init__(self) -> None:
        self._items: list = []

    def push(self, item: object) -> None:
        """Put `item` on top."""
        self._items.append(item)

    def pop(self) -> object:
        """Remove and return the top item."""
        if not self._items:
            raise IndexError("pop from empty stack")
        return self._items.pop()

    def peek(self) -> object:
        """Return the top item without removing it."""
        if not self._items:
            raise IndexError("peek at empty stack")
        return self._items[-1]

    def is_empty(self) -> bool:
        """True if the stack holds no items."""
        return not self._items

    def __len__(self) -> int:
        return len(self._items)


def balanced_brackets(text: str) -> bool:
    """True if every (, [ and { in `text` is closed in the right order."""
    stack = Stack()
    for char in text:
        if char in PAIRS.values():
            stack.push(char)
        elif char in PAIRS:
            if stack.is_empty() or stack.pop() != PAIRS[char]:
                return False
    return stack.is_empty()
