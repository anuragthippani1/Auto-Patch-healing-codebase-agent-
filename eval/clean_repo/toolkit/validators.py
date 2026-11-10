"""Input validators."""

import re

EMAIL = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)+$")
USERNAME = re.compile(r"^[a-z][a-z0-9_]{2,19}$")


def is_valid_email(text: str) -> bool:
    """True for addresses of the form name@domain.tld."""
    return bool(EMAIL.match(text))


def is_valid_username(text: str) -> bool:
    """3-20 characters: a lower-case letter, then lower-case letters, digits or underscores."""
    return bool(USERNAME.match(text))


def is_strong_password(text: str) -> bool:
    """At least 8 characters with a lower-case letter, an upper-case letter and a digit."""
    return (
        len(text) >= 8
        and any(char.islower() for char in text)
        and any(char.isupper() for char in text)
        and any(char.isdigit() for char in text)
    )


def is_valid_age(age: int) -> bool:
    """True for ages from 0 to 150 inclusive."""
    return 0 <= age <= 150
