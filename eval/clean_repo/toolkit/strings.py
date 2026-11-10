"""String helpers."""

import re


def truncate(text: str, max_len: int, suffix: str = "...") -> str:
    """Shorten `text` to at most `max_len` characters, ending in `suffix` if it was cut."""
    if max_len < len(suffix):
        raise ValueError("max_len must be at least as long as the suffix")
    if len(text) <= max_len:
        return text
    keep = max_len - len(suffix)
    return text[:keep] + suffix


def slugify(text: str) -> str:
    """Lower-case `text` and join its words with hyphens."""
    return "-".join(re.findall(r"[a-z0-9]+", text.lower()))


def initials(name: str) -> str:
    """Upper-case first letter of every word in `name`."""
    return "".join(word[0].upper() for word in name.split())


def is_palindrome(text: str) -> bool:
    """True if `text` reads the same both ways, ignoring case and punctuation."""
    letters = [char.lower() for char in text if char.isalnum()]
    return letters == letters[::-1]
