"""Tests for picking context files from a pytest log."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopatch.localize import extract_paths, select_context

SAMPLE_LOG = """\
F
=================================== FAILURES ===================================
________________________________ test_subtotal _________________________________
tests/test_cart.py:9: in test_subtotal
    assert cart.subtotal() == 25.0
shop/cart.py:14: in subtotal
    return sum(price + qty for price, qty in self._items)
E   TypeError: unsupported operand
  File "/work/shop/pricing.py", line 3, in tax
/usr/local/lib/python3.11/site-packages/_pytest/python.py:159: in pytest_pyfunc_call
=========================== short test summary info ============================
FAILED tests/test_cart.py::test_subtotal - TypeError: unsupported operand
"""


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A small repo: a package, its tests, and directories that must be ignored."""
    (tmp_path / "shop").mkdir()
    (tmp_path / "shop" / "__init__.py").write_text("")
    (tmp_path / "shop" / "cart.py").write_text("class Cart:\n    pass\n")
    (tmp_path / "shop" / "pricing.py").write_text("def tax(x):\n    return x\n")
    (tmp_path / "shop" / "discounts.py").write_text("def discount(x):\n    return x\n")
    (tmp_path / "shop" / "unrelated.py").write_text("UNRELATED = True\n")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_cart.py").write_text(
        "import os\nfrom shop.cart import Cart\nfrom shop import discounts\n\n"
        "def test_subtotal():\n    assert Cart()\n"
    )
    (tmp_path / "venv" / "lib").mkdir(parents=True)
    (tmp_path / "venv" / "lib" / "dep.py").write_text("DEP = 1\n")
    (tmp_path / "shop" / "huge.py").write_text("# pad\n" * 5000)
    return tmp_path


def test_extract_paths_from_log() -> None:
    paths = extract_paths(SAMPLE_LOG)
    assert paths[:2] == ["tests/test_cart.py", "shop/cart.py"]
    assert "/work/shop/pricing.py" in paths
    assert len(paths) == len(set(paths))


def test_selects_log_files_and_imports(repo: Path) -> None:
    context = select_context(str(repo), SAMPLE_LOG, max_chars=30_000)
    assert set(context.test_files) == {"tests/test_cart.py"}
    assert set(context.source_files) == {"shop/cart.py", "shop/pricing.py", "shop/discounts.py"}
    assert context.source_files["shop/cart.py"] == "class Cart:\n    pass\n"


def test_respects_max_chars(repo: Path) -> None:
    context = select_context(str(repo), SAMPLE_LOG, max_chars=130)
    assert 0 < context.total_chars <= 130
    assert set(context.test_files) == {"tests/test_cart.py"}
    assert set(context.source_files) == {"shop/cart.py"}


def test_falls_back_to_all_sources_smallest_first(repo: Path) -> None:
    context = select_context(str(repo), "no file paths in this log", max_chars=30_000)
    assert context.test_files == {}
    assert list(context.source_files) == [
        "shop/unrelated.py",
        "shop/cart.py",
        "shop/pricing.py",
        "shop/discounts.py",
    ]


def test_never_includes_excluded_or_huge_files(repo: Path) -> None:
    log = "venv/lib/dep.py:1: in x\nshop/huge.py:2: in y\n../outside.py:3: in z\n"
    context = select_context(str(repo), log, max_chars=1_000_000)
    files = set(context.source_files) | set(context.test_files)
    assert "venv/lib/dep.py" not in files
    assert "shop/huge.py" not in files
    assert all(not name.startswith("..") for name in files)
