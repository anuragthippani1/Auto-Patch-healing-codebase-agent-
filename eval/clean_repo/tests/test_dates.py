from datetime import date

import pytest

from toolkit.dates import add_business_days, days_between, format_duration, is_leap_year


def test_days_between():
    assert days_between(date(2024, 1, 1), date(2024, 1, 31)) == 30
    assert days_between(date(2024, 1, 31), date(2024, 1, 1)) == -30


def test_is_leap_year():
    assert is_leap_year(2024)
    assert is_leap_year(2000)
    assert not is_leap_year(1900)
    assert not is_leap_year(2023)


def test_add_business_days_skips_the_weekend():
    friday = date(2024, 1, 5)
    assert add_business_days(friday, 1) == date(2024, 1, 8)


def test_add_business_days_full_week():
    monday = date(2024, 1, 1)
    assert add_business_days(monday, 5) == date(2024, 1, 8)
    assert add_business_days(monday, 0) == monday


def test_add_business_days_rejects_negative():
    with pytest.raises(ValueError):
        add_business_days(date(2024, 1, 1), -1)


def test_format_duration_with_hours():
    assert format_duration(3723) == "1h 02m 03s"
    assert format_duration(36059) == "10h 00m 59s"


def test_format_duration_without_hours():
    assert format_duration(125) == "2m 05s"
    assert format_duration(0) == "0m 00s"


def test_format_duration_rejects_negative():
    with pytest.raises(ValueError):
        format_duration(-1)
