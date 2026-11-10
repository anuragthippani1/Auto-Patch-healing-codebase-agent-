"""Tests for the evaluation assets and eval/run_eval.py. No real LLM is called."""

from __future__ import annotations

import importlib.util
import json
import re
import shutil
import sys
from collections import Counter
from pathlib import Path
from types import ModuleType

import pytest
from pydantic import SecretStr

from autopatch import llm
from autopatch.config import settings
from autopatch.github_ops import run_git

EVAL = Path(__file__).resolve().parents[1] / "eval"
BUG_IDS = [f"{n:02d}" for n in range(1, 11)]


@pytest.fixture(scope="module")
def run_eval() -> ModuleType:
    """Import eval/run_eval.py, which is a script and not part of the package."""
    spec = importlib.util.spec_from_file_location("run_eval", EVAL / "run_eval.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules["run_eval"] = module
    spec.loader.exec_module(module)
    return module


def _oracle_edits(bug_id: str) -> list[dict]:
    """Edits that undo a bug patch: per hunk, swap the buggy lines for the clean ones."""
    patch = (EVAL / "bugs" / f"{bug_id}.patch").read_text()
    path = re.search(r"^\+\+\+ b/(.+)$", patch, flags=re.MULTILINE).group(1)
    edits = []
    for hunk in re.split(r"^@@.*$", patch, flags=re.MULTILINE)[1:]:
        lines = hunk.strip("\n").split("\n")
        buggy = "\n".join(line[1:] for line in lines if line[:1] in (" ", "+"))
        clean = "\n".join(line[1:] for line in lines if line[:1] in (" ", "-"))
        edits.append({"path": path, "search": buggy, "replace": clean})
    return edits


def test_bug_set_is_complete(run_eval: ModuleType) -> None:
    assert sorted(run_eval.DIFFICULTY) == BUG_IDS
    assert Counter(run_eval.DIFFICULTY.values()) == {"easy": 4, "medium": 4, "hard": 2}
    for bug_id in BUG_IDS:
        title, body = run_eval.read_issue(bug_id)
        assert len(title) > 10 and len(body) > 80, bug_id


@pytest.mark.parametrize("bug_id", BUG_IDS)
def test_patch_applies_to_clean_repo_and_only_touches_source(bug_id: str, tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    shutil.copytree(EVAL / "clean_repo", repo, ignore=shutil.ignore_patterns("__pycache__"))
    run_git(str(repo), "init", "--quiet")
    run_git(str(repo), "add", "-A")
    run_git(str(repo), "commit", "--quiet", "-m", "clean")
    run_git(str(repo), "apply", str(EVAL / "bugs" / f"{bug_id}.patch"))
    changed = run_git(str(repo), "diff", "--name-only").split()
    assert len(changed) == 1
    assert changed[0].startswith("toolkit/") and "test" not in changed[0]


def test_results_table_and_summary_line(run_eval: ModuleType) -> None:
    rows = [
        run_eval.Row("01", "easy", "fixed", 1, 10.0, 0),
        run_eval.Row("02", "easy", "fixed", 3, 20.0, 0),
        run_eval.Row("09", "hard", "failed", 3, 30.0, 0),
        run_eval.Row("10", "hard", "no_repro", 0, 1.0, 0),
    ]
    assert run_eval.summary_line(rows) == "Fixed 2/4 (50%), avg attempts 2.3, avg time 20.0 s"
    table = run_eval.render_markdown(rows)
    assert "| Bug | Difficulty | Fixed | Attempts | Time (s) |\n|---|---|---|---|---|" in table
    assert "| 01 | easy | yes | 1 | 10.0 |" in table
    assert "| 09 | hard | no | 3 | 30.0 |" in table
    assert "| 10 | hard | skipped (baseline tests pass) | 0 | 1.0 |" in table
    assert "**Fixed 2/4 (50%), avg attempts 2.3, avg time 20.0 s**" in table


def test_results_table_shows_tokens_when_reported(run_eval: ModuleType) -> None:
    table = run_eval.render_markdown([run_eval.Row("01", "easy", "fixed", 1, 10.0, 1234)])
    assert "| Time (s) | Tokens |" in table
    assert "| 01 | easy | yes | 1 | 10.0 | 1234 |" in table


def test_update_readme_replaces_only_the_marked_block(
    run_eval: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    readme = tmp_path / "README.md"
    readme.write_text(f"intro\n{run_eval.README_START}\nold table\n{run_eval.README_END}\noutro\n")
    monkeypatch.setattr(run_eval, "README", readme)
    run_eval.update_readme("NEW TABLE")
    assert readme.read_text() == (
        f"intro\n{run_eval.README_START}\nNEW TABLE\n{run_eval.README_END}\noutro\n"
    )


@pytest.mark.docker
def test_check_mode_confirms_every_bug_breaks_the_tests(
    run_eval: ModuleType, tmp_path: Path
) -> None:
    assert run_eval.check_bugs(BUG_IDS, tmp_path) == 0


@pytest.mark.docker
def test_full_pipeline_with_oracle_fixes(
    run_eval: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Scripted 'model' that returns the reverse of each bug patch. Checks the harness and
    that localization puts the buggy file in the prompt; says nothing about a real model."""
    titles = {run_eval.read_issue(bug_id)[0]: bug_id for bug_id in BUG_IDS}
    seen: dict[str, str] = {}

    def oracle(messages: list[dict]) -> str:
        prompt = messages[-1]["content"]
        bug_id = next(bug for title, bug in titles.items() if f"Title: {title}\n" in prompt)
        seen[bug_id] = prompt
        return json.dumps({"reasoning": "oracle", "edits": _oracle_edits(bug_id)})

    readme = tmp_path / "README.md"
    readme.write_text(f"{run_eval.README_START}\n{run_eval.README_END}\n")
    monkeypatch.setattr(llm, "_complete", oracle)
    monkeypatch.setattr(run_eval, "RESULTS_FILE", tmp_path / "results.md")
    monkeypatch.setattr(run_eval, "README", readme)
    monkeypatch.setattr(settings, "runs_dir", str(tmp_path / "runs"))
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("test-key"))

    assert run_eval.run_all(BUG_IDS, tmp_path) == 0

    results = (tmp_path / "results.md").read_text()
    assert "**Fixed 10/10 (100%), avg attempts 1.0," in results
    assert "Fixed 10/10" in readme.read_text()
    for bug_id in BUG_IDS:
        buggy_file = _oracle_edits(bug_id)[0]["path"]
        assert f"### FILE: {buggy_file}\n" in seen[bug_id], f"bug {bug_id}: file not in prompt"
