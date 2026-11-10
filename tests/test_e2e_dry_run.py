"""End-to-end dry runs: real CLI, real Docker sandbox, real eval bug; only the LLM is scripted."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from autopatch import llm
from autopatch.cli import app
from autopatch.config import settings
from autopatch.github_ops import run_git

pytestmark = pytest.mark.docker

EVAL = Path(__file__).resolve().parents[1] / "eval"
FIX_GET = {
    "path": "toolkit/cache.py",
    "search": "        return self._data[key]\n",
    "replace": "        value = self._data.pop(key)\n        self._data[key] = value\n"
    "        return value\n",
}
FIX_PUT = {
    "path": "toolkit/cache.py",
    "search": "            self._data[key] = value\n            return\n",
    "replace": "            self._data.pop(key)\n",
}


def _reply(*edits: dict) -> str:
    return json.dumps({"reasoning": "Restore recency tracking.", "edits": list(edits)})


@pytest.fixture
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point runs/ and the work dir at tmp_path and provide a dummy API key."""
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(settings, "work_dir", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "max_attempts", 3)
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("test-key"))
    return tmp_path


def _script(monkeypatch: pytest.MonkeyPatch, replies: list[str]) -> list[str]:
    """Make the LLM return `replies` in order; return the list of prompts it saw."""
    prompts: list[str] = []

    def fake(messages: list[dict]) -> str:
        prompts.append(messages[-1]["content"])
        return replies[min(len(prompts), len(replies)) - 1]

    monkeypatch.setattr(llm, "_complete", fake)
    return prompts


def _buggy_repo(tmp_path: Path, bug_id: str | None) -> Path:
    """The eval clean repo, optionally with one bug patch applied (not a git repo)."""
    repo = tmp_path / "clean_repo_with_bug"
    shutil.copytree(EVAL / "clean_repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
    if bug_id:
        run_git(str(repo), "apply", str(EVAL / "bugs" / f"{bug_id}.patch"))
    return repo


def _fix(repo: Path, bug_id: str) -> tuple[int, str]:
    """Run `autopatch fix --dry-run`; return (exit code, output)."""
    issue = EVAL / "bugs" / f"{bug_id}.md"
    args = ["fix", "--repo", str(repo), "--issue-file", str(issue), "--dry-run"]
    result = CliRunner().invoke(app, args)
    return result.exit_code, result.output


def test_fixes_two_function_bug_on_second_attempt(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _buggy_repo(env, "09")
    buggy_source = (repo / "toolkit" / "cache.py").read_text()
    prompts = _script(monkeypatch, [_reply(FIX_GET), _reply(FIX_GET, FIX_PUT)])

    exit_code, output = _fix(repo, "09")

    assert exit_code == 0, output
    assert len(prompts) == 2
    assert "LRU cache evicts entries that were just used" in prompts[0]
    assert "### FILE: toolkit/cache.py" in prompts[0]
    assert "### TEST FILE (read-only): tests/test_cache.py" in prompts[0]
    assert "test_put_on_existing_key_marks_entry_as_recently_used" in prompts[1]
    (run,) = (env / "runs").iterdir()
    patch = (run / "fix.patch").read_text()
    assert "+        value = self._data.pop(key)" in patch
    assert "+            self._data.pop(key)" in patch
    report = (run / "report.md").read_text()
    assert "**Status:** fixed" in report and "**Attempts:** 2 of 3" in report
    assert (repo / "toolkit" / "cache.py").read_text() == buggy_source

    # The saved patch applies cleanly to the user's (still buggy) copy.
    run_git(str(repo), "apply", str(run / "fix.patch"))
    assert "value = self._data.pop(key)" in (repo / "toolkit" / "cache.py").read_text()


def test_failed_run_exits_1_and_saves_last_attempt(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _buggy_repo(env, "09")
    prompts = _script(monkeypatch, [_reply(FIX_GET)])

    exit_code, output = _fix(repo, "09")

    assert exit_code == 1, output
    assert len(prompts) == 3
    (run,) = (env / "runs").iterdir()
    assert (run / "last_attempt.patch").is_file()
    assert not (run / "fix.patch").exists()
    assert "**Status:** failed" in (run / "report.md").read_text()


def test_clean_repo_exits_2_without_calling_llm(
    env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    prompts = _script(monkeypatch, [_reply(FIX_GET)])

    exit_code, output = _fix(_buggy_repo(env, None), "09")

    assert exit_code == 2, output
    assert prompts == []
    (run,) = (env / "runs").iterdir()
    assert "**Status:** no_repro" in (run / "report.md").read_text()
