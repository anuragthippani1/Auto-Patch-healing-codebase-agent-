import pytest

from toolkit.pagination import page_count, page_window, paginate


def test_page_count():
    assert page_count(0, 10) == 0
    assert page_count(10, 10) == 1
    assert page_count(11, 10) == 2


def test_page_count_rejects_bad_page_size():
    with pytest.raises(ValueError):
        page_count(10, 0)


def test_paginate():
    items = list(range(1, 11))
    assert paginate(items, 1, 3) == [1, 2, 3]
    assert paginate(items, 4, 3) == [10]
    assert paginate(items, 5, 3) == []


def test_paginate_rejects_page_zero():
    with pytest.raises(ValueError):
        paginate([1, 2, 3], 0, 2)


def test_page_window_in_the_middle():
    assert page_window(5, 10) == [3, 4, 5, 6, 7]
    assert page_window(4, 20, size=3) == [3, 4, 5]


def test_page_window_near_the_start():
    assert page_window(1, 10) == [1, 2, 3, 4, 5]
    assert page_window(2, 10) == [1, 2, 3, 4, 5]


def test_page_window_near_the_end():
    assert page_window(10, 10) == [6, 7, 8, 9, 10]
    assert page_window(9, 10) == [6, 7, 8, 9, 10]


def test_page_window_with_few_pages():
    assert page_window(2, 3) == [1, 2, 3]
    assert page_window(1, 0) == []
