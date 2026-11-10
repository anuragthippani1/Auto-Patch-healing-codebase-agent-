from toolkit.validators import (
    is_strong_password,
    is_valid_age,
    is_valid_email,
    is_valid_username,
)


def test_is_valid_email():
    assert is_valid_email("ada@example.com")
    assert is_valid_email("first.last+tag@mail.example.org")
    assert not is_valid_email("no-at-sign.example.com")
    assert not is_valid_email("ada@localhost")


def test_is_valid_username():
    assert is_valid_username("ada_99")
    assert not is_valid_username("ab")
    assert not is_valid_username("9lives")
    assert not is_valid_username("a" * 21)


def test_is_strong_password():
    assert is_strong_password("Secret123")
    assert not is_strong_password("short1A")
    assert not is_strong_password("alllowercase1")
    assert not is_strong_password("NoDigitsHere")


def test_is_valid_age():
    assert is_valid_age(0)
    assert is_valid_age(150)
    assert not is_valid_age(-1)
    assert not is_valid_age(151)
