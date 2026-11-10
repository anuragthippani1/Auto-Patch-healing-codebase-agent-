import pytest

from toolkit.inventory import Inventory


def test_new_inventory_is_empty():
    assert Inventory().total_units() == 0


def test_add_accumulates():
    inventory = Inventory()
    inventory.add("bolt", 3)
    inventory.add("bolt", 2)
    assert inventory.quantity("bolt") == 5


def test_remove():
    inventory = Inventory({"bolt": 5})
    inventory.remove("bolt", 2)
    assert inventory.quantity("bolt") == 3


def test_remove_more_than_stock_fails():
    inventory = Inventory({"bolt": 1})
    with pytest.raises(ValueError):
        inventory.remove("bolt", 2)


def test_low_stock_includes_items_at_the_threshold():
    inventory = Inventory({"bolt": 5, "nut": 2, "gear": 9})
    assert inventory.low_stock(threshold=5) == ["bolt", "nut"]


def test_low_stock_default_threshold():
    assert Inventory({"gear": 6, "nut": 1}).low_stock() == ["nut"]


def test_initial_items_are_copied():
    stock = {"bolt": 1}
    inventory = Inventory(stock)
    inventory.add("bolt")
    assert stock == {"bolt": 1}


def test_inventories_do_not_share_stock():
    first = Inventory()
    first.add("washer", 4)
    second = Inventory()
    assert second.quantity("washer") == 0
    assert second.total_units() == 0


def test_total_units():
    assert Inventory({"bolt": 5, "nut": 2}).total_units() == 7
