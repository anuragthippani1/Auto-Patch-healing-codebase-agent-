"""Apply LLM edits safely: inside the repo, never to tests, all-or-nothing."""

from __future__ import annotations

import difflib
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath

from .models import Edit

TEST_DIRS = {"tests", "test"}


class EditError(Exception):
    """An edit was rejected. The message is fed back to the LLM on retry."""


def is_test_path(rel_path: str) -> bool:
    """True for anything under tests/ and for test_*.py, *_test.py, conftest.py."""
    path = PurePosixPath(rel_path.replace("\\", "/").lower())
    if any(part in TEST_DIRS for part in path.parts[:-1]):
        return True
    name = path.name
    return fnmatch(name, "test_*.py") or fnmatch(name, "*_test.py") or name == "conftest.py"


def _resolve_target(root: Path, edit: Edit) -> Path:
    """Validate an edit's path and return the absolute file to change."""
    if not edit.path.strip():
        raise EditError("Edit has an empty path.")
    target = Path(root, edit.path).resolve()
    if not target.is_relative_to(root):
        raise EditError(f"Rejected '{edit.path}': path is outside the repository.")
    rel = target.relative_to(root).as_posix()
    if ".git" in target.relative_to(root).parts:
        raise EditError(f"Rejected '{edit.path}': the .git directory cannot be edited.")
    if is_test_path(edit.path) or is_test_path(rel):
        raise EditError(
            f"Rejected '{edit.path}': test files are read-only. Fix the source code instead."
        )
    if target.suffix != ".py":
        raise EditError(f"Rejected '{edit.path}': only .py source files can be edited.")
    if not target.is_file():
        raise EditError(f"Rejected '{edit.path}': file does not exist.")
    return target


def _nearest_lines(content: str, search: str) -> str:
    """Hint showing the file lines most similar to the first line of `search`."""
    first = next((line.strip() for line in search.splitlines() if line.strip()), "")
    lines = [line.strip() for line in content.splitlines() if line.strip()]
    matches = difflib.get_close_matches(first, lines, n=3, cutoff=0.6)
    if not matches:
        return ""
    return " Nearest lines in the file: " + " | ".join(repr(m) for m in matches)


def _replace_once(content: str, edit: Edit) -> str:
    """Return `content` with the edit applied; `search` must occur exactly once."""
    if not edit.search:
        raise EditError(f"Edit for '{edit.path}' has an empty search string.")
    if edit.search == edit.replace:
        raise EditError(f"Edit for '{edit.path}' changes nothing: search equals replace.")
    count = content.count(edit.search)
    if count == 0:
        raise EditError(
            f"Search text not found in '{edit.path}' (0 occurrences). It must be copied "
            "exactly from the file, including indentation." + _nearest_lines(content, edit.search)
        )
    if count > 1:
        raise EditError(
            f"Search text occurs {count} times in '{edit.path}'; it must occur exactly once. "
            "Include more surrounding lines to make it unique."
        )
    return content.replace(edit.search, edit.replace)


def _read(target: Path, edit: Edit) -> str:
    """Read a file as UTF-8 without translating line endings."""
    try:
        return target.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise EditError(f"Rejected '{edit.path}': file is not valid UTF-8.") from exc


def apply_edits(repo_path: str, edits: list[Edit]) -> None:
    """Validate every edit, then write them all. If one is invalid, nothing is written."""
    if not edits:
        raise EditError("No edits were provided.")
    root = Path(repo_path).resolve()
    pending: dict[Path, str] = {}
    for edit in edits:
        target = _resolve_target(root, edit)
        content = pending[target] if target in pending else _read(target, edit)
        pending[target] = _replace_once(content, edit)
    for target, content in pending.items():
        target.write_bytes(content.encode("utf-8"))
