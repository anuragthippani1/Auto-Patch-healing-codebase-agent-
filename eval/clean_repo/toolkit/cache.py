"""Least-recently-used cache."""


class LRUCache:
    """Keeps at most `capacity` entries and evicts the least recently used one.

    Reading an entry with `get` and writing one with `put` both count as a use.
    """

    def __init__(self, capacity: int) -> None:
        if capacity <= 0:
            raise ValueError("capacity must be positive")
        self.capacity = capacity
        self._data: dict = {}  # ordered from least to most recently used

    def get(self, key: object, default: object = None) -> object:
        """Return the value for `key` and mark it as recently used."""
        if key not in self._data:
            return default
        value = self._data.pop(key)
        self._data[key] = value
        return value

    def put(self, key: object, value: object) -> None:
        """Store `value` under `key`, evicting the least recently used entry if full."""
        if key in self._data:
            self._data.pop(key)
        elif len(self._data) >= self.capacity:
            oldest = next(iter(self._data))
            del self._data[oldest]
        self._data[key] = value

    def keys(self) -> list:
        """Keys ordered from least to most recently used."""
        return list(self._data)

    def __contains__(self, key: object) -> bool:
        return key in self._data

    def __len__(self) -> int:
        return len(self._data)
