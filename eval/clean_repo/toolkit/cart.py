"""Shopping cart."""


class Cart:
    """A list of priced lines with an optional percentage discount."""

    def __init__(self) -> None:
        self._lines: list[tuple[str, float, int]] = []
        self._discount_percent = 0.0

    def add(self, name: str, unit_price: float, quantity: int = 1) -> None:
        """Add `quantity` units of `name` at `unit_price` each."""
        if unit_price < 0:
            raise ValueError("unit_price must not be negative")
        if quantity <= 0:
            raise ValueError("quantity must be positive")
        self._lines.append((name, unit_price, quantity))

    def item_count(self) -> int:
        """Total number of units in the cart."""
        return sum(quantity for _, _, quantity in self._lines)

    def subtotal(self) -> float:
        """Sum of price times quantity over all lines, before discount and tax."""
        return round(sum(price * quantity for _, price, quantity in self._lines), 2)

    def apply_discount(self, percent: float) -> None:
        """Set a discount between 0 and 100 percent."""
        if not 0 <= percent <= 100:
            raise ValueError("percent must be between 0 and 100")
        self._discount_percent = percent

    def total(self, tax_rate: float = 0.0) -> float:
        """Subtotal after discount, plus tax (`tax_rate` 0.2 means 20%)."""
        discounted = self.subtotal() * (1 - self._discount_percent / 100)
        return round(discounted * (1 + tax_rate), 2)
