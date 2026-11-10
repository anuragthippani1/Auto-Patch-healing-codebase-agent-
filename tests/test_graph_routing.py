"""Routing functions (pure) and the full graph with a fake sandbox and a fake LLM."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import SecretStr

from autopatch import github_ops, llm, sandbox
from autopatch.config import settings
from autopatch.graph import run_agent
from autopatch.models import SandboxResult
from autopatch.nodes import route_after_apply, route_after_baseline, route_after_tests

BUGGY = "def add(a, b):\n    return a - b\n"
TEST = "from calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n"
FAIL_LOG = (
    "tests/test_calc.py:5: in test_add\n    assert add(2, 3) == 5\nE   assert -1 == 5\n"
    "FAILED tests/test_calc.py::test_add - assert -1 == 5\n1 failed in 0.01s\n"
)


def _reply(replace: str, path: str = "calc.py", search: str = "return a - b") -> str:
    """A well-formed model reply with one edit."""
    edit = {"path": path, "search": search, "replace": replace}
    return json.dumps({"reasoning": f"Use {replace!r}.", "edits": [edit]})


GOOD = _reply("return a + b")
WRONG = _reply("return a * b")
TOUCHES_TEST = _reply("assert True", path="tests/test_calc.py", search="assert add(2, 3) == 5")


@pytest.mark.parametrize(
    ("status", "attempts", "expected"),
    [
        ("fixed", 1, "open_pr"),
        ("fixed", 3, "open_pr"),
        ("running", 1, "retry"),
        ("running", 2, "retry"),
        ("running", 3, "give_up"),
        ("running", 4, "give_up"),
    ],
)
def test_route_after_tests(status: str, attempts: int, expected: str) -> None:
    state = {"status": status, "attempts": attempts, "max_attempts": 3}
    assert route_after_tests(state) == expected


@pytest.mark.parametrize(
    ("apply_ok", "attempts", "expected"),
    [(True, 1, "run_tests"), (True, 3, "run_tests"), (False, 2, "retry"), (False, 3, "give_up")],
)
def test_route_after_apply(apply_ok: bool, attempts: int, expected: str) -> None:
    state = {"apply_ok": apply_ok, "attempts": attempts, "max_attempts": 3}
    assert route_after_apply(state) == expected


@pytest.mark.parametrize(
    ("failed", "exit_code", "expected"),
    [(False, 0, "no_repro"), (True, 1, "propose"), (True, 2, "propose"), (True, 5, "give_up")],
)
def test_route_after_baseline(failed: bool, exit_code: int, expected: str) -> None:
    state = {"baseline_failed": failed, "baseline_exit_code": exit_code}
    assert route_after_baseline(state) == expected


class Harness:
    """A buggy repo plus fakes for the sandbox and the LLM."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        self.repo = tmp_path / "project"
        (self.repo / "tests").mkdir(parents=True)
        (self.repo / "calc.py").write_text(BUGGY)
        (self.repo / "tests" / "test_calc.py").write_text(TEST)
        self.runs = tmp_path / "runs"
        self.work = tmp_path / "work"
        self.prompts: list[str] = []
        self.replies: list[str] = []
        monkeypatch.setattr(settings, "runs_dir", str(self.runs))
        monkeypatch.setattr(settings, "work_dir", str(self.work))
        monkeypatch.setattr(settings, "max_attempts", 3)
        monkeypatch.setattr(sandbox, "run_pytest", self._run_pytest)
        monkeypatch.setattr(llm, "_complete", self._complete)

    def _run_pytest(self, repo_path: str, timeout: int | None = None) -> SandboxResult:
        """Stand-in for Docker: 'passes' when calc.py contains the right code."""
        assert Path(repo_path, "tests", "test_calc.py").read_text() == TEST
        fixed = "return a + b" in Path(repo_path, "calc.py").read_text()
        return SandboxResult(
            exit_code=0 if fixed else 1, stdout="1 passed in 0.01s\n" if fixed else FAIL_LOG,
            timed_out=False, passed=fixed, duration_s=0.01,
        )

    def _complete(self, messages: list[dict]) -> str:
        self.prompts.append(messages[-1]["content"])
        return self.replies[len(self.prompts) - 1]

    def run(self, replies: list[str], dry_run: bool = True) -> dict:
        self.replies = replies
        number = None if dry_run else 7
        repo = str(self.repo) if dry_run else "https://github.com/octo/demo"
        return run_agent(repo, "add() subtracts", "add(2, 3) gives -1.", number, dry_run)

    def run_file(self, state: dict, name: str) -> Path:
        return self.runs / state["run_id"] / name

    def nodes(self, state: dict) -> list[str]:
        lines = self.run_file(state, "events.jsonl").read_text().splitlines()
        return [json.loads(line)["node"] for line in lines]


@pytest.fixture
def harness(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Harness:
    return Harness(tmp_path, monkeypatch)


def test_fixed_on_first_attempt(harness: Harness) -> None:
    state = harness.run([GOOD])
    assert state["status"] == "fixed"
    assert state["attempts"] == 1
    assert state["pr_url"] is None
    assert "+    return a + b" in harness.run_file(state, "fix.patch").read_text()
    report = harness.run_file(state, "report.md").read_text()
    assert "**Status:** fixed" in report and "### Attempt 1" in report
    assert harness.nodes(state) == [
        "start", "clone_repo", "run_baseline_tests", "propose_and_apply",
        "run_tests_after", "open_pr", "end",
    ]


def test_original_repo_untouched_and_workdir_removed(harness: Harness) -> None:
    harness.run([GOOD])
    assert (harness.repo / "calc.py").read_text() == BUGGY
    assert not (harness.repo / ".git").exists()
    assert list(harness.work.iterdir()) == []


def test_retries_with_feedback_until_fixed(harness: Harness) -> None:
    state = harness.run([TOUCHES_TEST, WRONG, GOOD])
    assert state["status"] == "fixed"
    assert state["attempts"] == 3
    assert "Previous feedback" not in harness.prompts[0]
    assert "test files are read-only" in harness.prompts[1]
    assert "Tests still fail with your edits applied" in harness.prompts[2]
    assert "return a * b" in harness.prompts[2]
    assert "### FILE: calc.py\ndef add(a, b):\n    return a - b" in harness.prompts[2]
    patch = harness.run_file(state, "fix.patch").read_text()
    assert "+    return a + b" in patch and "a * b" not in patch and "test_calc" not in patch
    assert [entry["passed"] for entry in state["history"]] == [None, False, True]


def test_gives_up_after_max_attempts(harness: Harness) -> None:
    state = harness.run([WRONG, WRONG, WRONG, GOOD])
    assert state["status"] == "failed"
    assert state["attempts"] == 3
    assert len(harness.prompts) == 3
    assert "+    return a * b" in harness.run_file(state, "last_attempt.patch").read_text()
    assert not harness.run_file(state, "fix.patch").exists()
    assert "**Status:** failed" in harness.run_file(state, "report.md").read_text()
    assert harness.nodes(state)[-2:] == ["give_up", "end"]


def test_edit_errors_count_as_attempts(harness: Harness) -> None:
    state = harness.run([TOUCHES_TEST, "not json", "still not json", TOUCHES_TEST])
    assert state["status"] == "failed"
    assert state["attempts"] == 3
    assert "run_tests_after" not in harness.nodes(state)
    assert not harness.run_file(state, "last_attempt.patch").exists()


def test_no_repro_when_tests_already_pass(harness: Harness) -> None:
    (harness.repo / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    state = harness.run([GOOD])
    assert state["status"] == "no_repro"
    assert state["attempts"] == 0
    assert harness.prompts == []
    assert harness.run_file(state, "report.md").exists()


def test_no_tests_collected_fails_without_calling_llm(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    empty = SandboxResult(
        exit_code=5, stdout="no tests ran", timed_out=False, passed=False, duration_s=0.01
    )
    monkeypatch.setattr(sandbox, "run_pytest", lambda repo_path, timeout=None: empty)
    state = harness.run([GOOD])
    assert state["status"] == "failed"
    assert harness.prompts == []
    assert "collected no tests" in state["last_error"]


def test_crash_still_writes_report_and_cleans_up(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    def boom(repo_path: str, timeout: int | None = None) -> SandboxResult:
        raise sandbox.SandboxError("Cannot reach the Docker daemon. Is Docker running?")

    monkeypatch.setattr(sandbox, "run_pytest", boom)
    state = harness.run([GOOD])
    assert state["status"] == "failed"
    assert "Cannot reach the Docker daemon" in state["last_error"]
    assert "Cannot reach the Docker daemon" in harness.run_file(state, "report.md").read_text()
    assert list(harness.work.iterdir()) == []


def test_real_run_calls_open_pr_with_fixed_state(
    harness: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: dict = {}

    def fake_open_pr(state: dict) -> str:
        seen.update(state)
        return "https://github.com/octo/demo/pull/8"

    def fake_clone(repo: str) -> tuple[str, str]:
        return github_ops._copy_local(str(harness.repo)), "main"

    monkeypatch.setattr(settings, "github_token", SecretStr("ghp_test_token"))
    monkeypatch.setattr(github_ops, "clone", fake_clone)
    monkeypatch.setattr(github_ops, "open_pr", fake_open_pr)
    state = harness.run([GOOD], dry_run=False)
    assert state["status"] == "fixed"
    assert state["pr_url"] == "https://github.com/octo/demo/pull/8"
    assert seen["issue_number"] == 7 and seen["status"] == "fixed"
    assert "+    return a + b" in seen["diff"]
    assert "pull/8" in harness.run_file(state, "report.md").read_text()
