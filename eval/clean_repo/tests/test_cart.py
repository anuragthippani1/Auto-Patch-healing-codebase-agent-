import pytest

from toolkit.cart import Cart


def test_empty_cart():
    cart = Cart()
    assert cart.item_count() == 0
    assert cart.subtotal() == 0
    assert cart.total() == 0


def test_subtotal_is_price_times_quantity():
    cart = Cart()
    cart.add("pen", 2.50, 4)
    cart.add("book", 12.00)
    assert cart.subtotal() == 22.0


def test_item_count():
    cart = Cart()
    cart.add("pen", 2.50, 4)
    cart.add("book", 12.00)
    assert cart.item_count() == 5


def test_total_with_discount():
    cart = Cart()
    cart.add("lamp", 40.0, 2)
    cart.apply_discount(25)
    assert cart.total() == 60.0


def test_total_with_tax():
    cart = Cart()
    cart.add("lamp", 50.0)
    assert cart.total(tax_rate=0.2) == 60.0


def test_total_with_discount_and_tax():
    cart = Cart()
    cart.add("desk", 100.0)
    cart.apply_discount(10)
    assert cart.total(tax_rate=0.2) == 108.0


def test_rejects_invalid_discount():
    with pytest.raises(ValueError):
        Cart().apply_discount(120)


def test_rejects_invalid_quantity():
    with pytest.raises(ValueError):
        Cart().add("pen", 1.0, 0)
