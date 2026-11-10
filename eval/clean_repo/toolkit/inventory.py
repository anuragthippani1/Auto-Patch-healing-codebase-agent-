"""Stock tracking."""


class Inventory:
    """Tracks how many units of each item are in stock."""

    def __init__(self, items: dict[str, int] | None = None) -> None:
        self._items: dict[str, int] = dict(items) if items else {}

    def add(self, name: str, quantity: int = 1) -> None:
        """Add `quantity` units of `name`."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._items[name] = self._items.get(name, 0) + quantity

    def remove(self, name: str, quantity: int = 1) -> None:
        """Remove `quantity` units of `name`; fails if there is not enough stock."""
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        if self.quantity(name) < quantity:
            raise ValueError(f"not enough stock of {name}")
        self._items[name] -= quantity

    def quantity(self, name: str) -> int:
        """Units of `name` in stock (0 if unknown)."""
        return self._items.get(name, 0)

    def low_stock(self, threshold: int = 5) -> list[str]:
        """Names of items whose quantity is at or below `threshold`, sorted."""
        return sorted(name for name, qty in self._items.items() if qty <= threshold)

    def total_units(self) -> int:
        """Total number of units across all items."""
        return sum(self._items.values())
