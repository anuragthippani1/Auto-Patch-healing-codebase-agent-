"""Parsers for simple text formats."""

TRUE_WORDS = {"true", "yes", "on", "1"}
FALSE_WORDS = {"false", "no", "off", "0"}


def parse_bool(text: str) -> bool:
    """Parse common spellings of true and false."""
    word = text.strip().lower()
    if word in TRUE_WORDS:
        return True
    if word in FALSE_WORDS:
        return False
    raise ValueError(f"not a boolean: {text!r}")


def parse_int_list(text: str, sep: str = ",") -> list[int]:
    """Parse '1, 2, 3' into [1, 2, 3]. Empty input gives an empty list."""
    if not text.strip():
        return []
    return [int(part) for part in text.split(sep)]


def parse_key_value(line: str, sep: str = "=") -> tuple[str, str]:
    """Split 'key = value' into ('key', 'value')."""
    if sep not in line:
        raise ValueError(f"missing {sep!r} in line: {line!r}")
    key, value = line.split(sep, 1)
    return key.strip(), value.strip()


def parse_config(text: str, comment_char: str = "#") -> dict[str, str]:
    """Parse 'key = value' lines. Blank lines and comment lines are ignored."""
    result: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith(comment_char):
            continue
        key, value = parse_key_value(line)
        result[key] = value
    return result
