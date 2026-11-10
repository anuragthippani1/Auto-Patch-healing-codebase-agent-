"""Numeric helpers."""


def clamp(value: float, low: float, high: float) -> float:
    """Limit `value` to the range [low, high]."""
    if low > high:
        raise ValueError("low must not be greater than high")
    return max(low, min(value, high))


def scale_to_unit(value: float, low: float, high: float) -> float:
    """Map `value` from [low, high] onto [0, 1]. Values outside the range are clamped."""
    if low == high:
        raise ValueError("low and high must differ")
    bounded = clamp(value, low, high)
    return (bounded - low) / (high - low)


def mean(values: list[float]) -> float:
    """Arithmetic mean of a non-empty list."""
    if not values:
        raise ValueError("mean of an empty list")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    """Median of a non-empty list."""
    if not values:
        raise ValueError("median of an empty list")
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def percent_change(old: float, new: float) -> float:
    """Change from `old` to `new` as a percentage of `old`."""
    if old == 0:
        raise ValueError("old value must not be zero")
    return (new - old) / abs(old) * 100
