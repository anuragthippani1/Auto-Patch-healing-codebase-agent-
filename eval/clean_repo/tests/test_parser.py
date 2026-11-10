import pytest

from toolkit.parser import parse_bool, parse_config, parse_int_list, parse_key_value


def test_parse_bool():
    assert parse_bool("Yes") is True
    assert parse_bool(" off ") is False
    with pytest.raises(ValueError):
        parse_bool("maybe")


def test_parse_int_list():
    assert parse_int_list("1, 2, 3") == [1, 2, 3]
    assert parse_int_list("") == []
    assert parse_int_list("4;5", sep=";") == [4, 5]


def test_parse_key_value():
    assert parse_key_value("name = demo") == ("name", "demo")
    assert parse_key_value("url=http://x/?a=b") == ("url", "http://x/?a=b")


def test_parse_key_value_needs_separator():
    with pytest.raises(ValueError):
        parse_key_value("no separator here")


def test_parse_config_skips_comments_and_blank_lines():
    text = "# settings\nname = demo\n\nretries = 3\n"
    assert parse_config(text) == {"name": "demo", "retries": "3"}


def test_parse_config_custom_comment_char():
    assert parse_config("; note\nname = demo\n", comment_char=";") == {"name": "demo"}


def test_parse_config_empty_text():
    assert parse_config("") == {}
