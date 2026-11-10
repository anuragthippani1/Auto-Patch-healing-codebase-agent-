"""Pick the files most relevant to a failing pytest log."""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path

from .edits import is_test_path

MAX_FILE_BYTES = 20_000
EXCLUDED_DIRS = {".git", "venv", ".venv", "node_modules", "__pycache__", "site-packages"}
SANDBOX_PREFIX = "/work/"
PATH_PATTERNS = [
    re.compile(r"([\w./\\-]+\.py):\d+"),  # src/foo.py:12
    re.compile(r'File "([^"]+\.py)"'),  # File "/work/foo.py", line 3
    re.compile(r"([\w./\\-]+\.py)::"),  # FAILED tests/test_foo.py::test_x
]


@dataclass
class Context:
    """Files chosen for the prompt. Test files are shown to the LLM as read-only."""

    source_files: dict[str, str] = field(default_factory=dict)
    test_files: dict[str, str] = field(default_factory=dict)

    @property
    def total_chars(self) -> int:
        return sum(len(c) for c in (*self.source_files.values(), *self.test_files.values()))


def extract_paths(test_log: str) -> list[str]:
    """Return unique `.py` paths mentioned in a pytest log, in order of appearance."""
    hits: list[tuple[int, str]] = []
    for pattern in PATH_PATTERNS:
        hits.extend((m.start(), m.group(1)) for m in pattern.finditer(test_log))
    return list(dict.fromkeys(path for _, path in sorted(hits)))


def _to_repo_path(root: Path, raw: str) -> str | None:
    """Map a path from a log to a repo-relative path, or None if it is not usable."""
    raw = raw.replace("\\", "/")
    if raw.startswith(SANDBOX_PREFIX):
        raw = raw[len(SANDBOX_PREFIX):]
    target = Path(root, raw).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    rel = target.relative_to(root)
    if EXCLUDED_DIRS.intersection(rel.parts) or target.stat().st_size > MAX_FILE_BYTES:
        return None
    return rel.as_posix()


def _imported_modules(source: str) -> list[str]:
    """Dotted module names imported by a Python source file."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            modules.append(node.module)
            modules.extend(f"{node.module}.{alias.name}" for alias in node.names)
    return modules


def _local_module_files(root: Path, module: str) -> list[str]:
    """Repo files that could define `module` (flat or src/ layout)."""
    parts = module.split(".")
    found = []
    for base in ("", "src"):
        for candidate in (Path(base, *parts).with_suffix(".py"), Path(base, *parts, "__init__.py")):
            rel = _to_repo_path(root, candidate.as_posix())
            if rel:
                found.append(rel)
    return found


def _fallback_sources(root: Path) -> list[str]:
    """Every usable non-test `.py` file in the repo, smallest first."""
    candidates = []
    for path in root.rglob("*.py"):
        rel = _to_repo_path(root, path.relative_to(root).as_posix())
        if rel and not is_test_path(rel):
            candidates.append((path.stat().st_size, rel))
    return [rel for _, rel in sorted(candidates)]


def _candidates(root: Path, test_log: str) -> list[str]:
    """Ordered candidates: files in the log, then modules the failing tests import."""
    from_log = [rel for raw in extract_paths(test_log) if (rel := _to_repo_path(root, raw))]
    imported: list[str] = []
    for rel in filter(is_test_path, from_log):
        source = (root / rel).read_text(encoding="utf-8", errors="replace")
        for module in _imported_modules(source):
            imported.extend(_local_module_files(root, module))
    ordered = list(dict.fromkeys(from_log + imported))
    if not any(not is_test_path(rel) for rel in ordered):
        ordered += _fallback_sources(root)
    return ordered


def select_context(repo_path: str, test_log: str, max_chars: int) -> Context:
    """Choose source and test files for the prompt, within `max_chars` in total."""
    root = Path(repo_path).resolve()
    context = Context()
    for rel in _candidates(root, test_log):
        content = (root / rel).read_text(encoding="utf-8", errors="replace")
        if not content.strip() or context.total_chars + len(content) > max_chars:
            continue
        bucket = context.test_files if is_test_path(rel) else context.source_files
        bucket[rel] = content
    return context
