import pytest

from toolkit.strings import initials, is_palindrome, slugify, truncate


def test_truncate_leaves_short_text_alone():
    assert truncate("hello", 10) == "hello"


def test_truncate_leaves_text_of_exact_length_alone():
    assert truncate("0123456789", 10) == "0123456789"


def test_truncate_result_fits_the_limit():
    result = truncate("The quick brown fox", 10)
    assert result == "The qui..."
    assert len(result) == 10


def test_truncate_custom_suffix():
    assert truncate("abcdefghij", 6, suffix="~") == "abcde~"


def test_truncate_rejects_limit_shorter_than_suffix():
    with pytest.raises(ValueError):
        truncate("abcdef", 2)


def test_slugify():
    assert slugify("Hello, World!") == "hello-world"
    assert slugify("  Many   spaces ") == "many-spaces"


def test_initials():
    assert initials("ada lovelace") == "AL"


def test_is_palindrome():
    assert is_palindrome("A man, a plan, a canal: Panama")
    assert not is_palindrome("toolkit")
