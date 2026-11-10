"""Tests for safe edit application."""

from __future__ import annotations

from pathlib import Path

import pytest

from autopatch.edits import EditError, apply_edits, is_test_path
from autopatch.models import Edit

SOURCE = "def add(a, b):\n    return a - b\n\n\ndef sub(a, b):\n    return a - b\n"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A tiny repo with one source file and one test file."""
    (tmp_path / "calc.py").write_text(SOURCE)
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text("def test_add():\n    assert True\n")
    return tmp_path


def test_applies_valid_edit(repo: Path) -> None:
    edit = Edit(
        path="calc.py",
        search="def add(a, b):\n    return a - b",
        replace="def add(a, b):\n    return a + b",
    )
    apply_edits(str(repo), [edit])
    assert "def add(a, b):\n    return a + b\n" in (repo / "calc.py").read_text()
    assert "def sub(a, b):\n    return a - b\n" in (repo / "calc.py").read_text()


def test_two_edits_to_same_file(repo: Path) -> None:
    edits = [
        Edit(path="calc.py", search="def add(a, b):", replace="def add(x, y):"),
        Edit(path="calc.py", search="def sub(a, b):", replace="def sub(x, y):"),
    ]
    apply_edits(str(repo), edits)
    text = (repo / "calc.py").read_text()
    assert "def add(x, y):" in text and "def sub(x, y):" in text


@pytest.mark.parametrize("path", ["../outside.py", "sub/../../outside.py"])
def test_rejects_path_traversal(repo: Path, path: str) -> None:
    (repo.parent / "outside.py").write_text("x = 1\n")
    with pytest.raises(EditError, match="outside the repository"):
        apply_edits(str(repo), [Edit(path=path, search="x = 1", replace="x = 2")])
    assert (repo.parent / "outside.py").read_text() == "x = 1\n"


def test_rejects_absolute_path(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("other") / "outside.py"
    outside.write_text("x = 1\n")
    with pytest.raises(EditError, match="outside the repository"):
        apply_edits(str(repo), [Edit(path=str(outside), search="x = 1", replace="x = 2")])
    assert outside.read_text() == "x = 1\n"


def test_rejects_symlink_out_of_repo(repo: Path, tmp_path_factory: pytest.TempPathFactory) -> None:
    outside = tmp_path_factory.mktemp("other") / "outside.py"
    outside.write_text("x = 1\n")
    (repo / "link.py").symlink_to(outside)
    with pytest.raises(EditError, match="outside the repository"):
        apply_edits(str(repo), [Edit(path="link.py", search="x = 1", replace="x = 2")])
    assert outside.read_text() == "x = 1\n"


@pytest.mark.parametrize(
    "path",
    ["tests/test_calc.py", "tests/helpers.py", "test_calc.py", "calc_test.py", "conftest.py"],
)
def test_rejects_test_file_edits(repo: Path, path: str) -> None:
    target = repo / path
    target.write_text("assert True\n")
    with pytest.raises(EditError, match="test files are read-only"):
        apply_edits(str(repo), [Edit(path=path, search="assert True", replace="pass")])
    assert target.read_text() == "assert True\n"


def test_rejects_symlink_to_test_file(repo: Path) -> None:
    (repo / "alias.py").symlink_to(repo / "tests" / "test_calc.py")
    with pytest.raises(EditError, match="test files are read-only"):
        apply_edits(str(repo), [Edit(path="alias.py", search="assert True", replace="pass")])


def test_rejects_non_python_files(repo: Path) -> None:
    (repo / "pytest.ini").write_text("[pytest]\n")
    with pytest.raises(EditError, match="only .py source files"):
        apply_edits(str(repo), [Edit(path="pytest.ini", search="[pytest]", replace="[x]")])


def test_rejects_missing_file(repo: Path) -> None:
    with pytest.raises(EditError, match="does not exist"):
        apply_edits(str(repo), [Edit(path="nope.py", search="a", replace="b")])


def test_rejects_non_unique_search(repo: Path) -> None:
    with pytest.raises(EditError, match="occurs 2 times"):
        apply_edits(str(repo), [Edit(path="calc.py", search="return a - b", replace="return 0")])
    assert (repo / "calc.py").read_text() == SOURCE


def test_rejects_missing_search_with_hint(repo: Path) -> None:
    edit = Edit(path="calc.py", search="def add(a, c):", replace="def add(a, d):")
    with pytest.raises(EditError, match="0 occurrences") as excinfo:
        apply_edits(str(repo), [edit])
    assert "def add(a, b):" in str(excinfo.value)


def test_rejects_empty_edit_list(repo: Path) -> None:
    with pytest.raises(EditError, match="No edits"):
        apply_edits(str(repo), [])


def test_atomic_one_bad_edit_means_no_change(repo: Path) -> None:
    (repo / "other.py").write_text("y = 1\n")
    edits = [
        Edit(path="other.py", search="y = 1", replace="y = 2"),
        Edit(path="calc.py", search="def add(a, b):", replace="def add(x, y):"),
        Edit(path="calc.py", search="not in file", replace="whatever"),
    ]
    with pytest.raises(EditError):
        apply_edits(str(repo), edits)
    assert (repo / "other.py").read_text() == "y = 1\n"
    assert (repo / "calc.py").read_text() == SOURCE


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("tests/test_a.py", True),
        ("pkg/tests/util.py", True),
        ("Tests/Test_A.py", True),
        ("test_a.py", True),
        ("pkg/a_test.py", True),
        ("conftest.py", True),
        ("pkg/core.py", False),
        ("pkg/testing_utils.py", False),
        ("latest.py", False),
    ],
)
def test_is_test_path(path: str, expected: bool) -> None:
    assert is_test_path(path) is expected
