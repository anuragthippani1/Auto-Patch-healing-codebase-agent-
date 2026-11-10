"""Typed models shared across AutoPatch."""

from __future__ import annotations

from typing import TypedDict

from pydantic import BaseModel


class Edit(BaseModel):
    """One search-and-replace edit proposed by the LLM."""

    path: str  # relative to repo root
    search: str  # exact text to find (must occur exactly once)
    replace: str  # replacement text


class SandboxResult(BaseModel):
    """Outcome of one pytest run inside the sandbox."""

    exit_code: int
    stdout: str
    timed_out: bool
    passed: bool  # exit_code == 0 and not timed_out
    duration_s: float


class State(TypedDict):
    """LangGraph state. Fields below the blank line extend the spec (see DECISIONS.md)."""

    issue_title: str
    issue_body: str
    repo_url: str  # URL or local path
    repo_path: str  # working copy on host
    default_branch: str
    test_log: str
    baseline_failed: bool  # True if tests failed before patching
    edits: list[dict]  # edits of the most recent attempt
    last_error: str  # edit error or test log feedback for next attempt
    attempts: int
    status: str  # running | fixed | failed | no_repro
    pr_url: str | None
    dry_run: bool
    run_id: str

    issue_number: int | None  # None for --issue-file runs
    max_attempts: int  # copied from settings so routing stays pure
    baseline_log: str  # failing log of the unpatched repo
    baseline_exit_code: int
    apply_ok: bool  # False if the last attempt failed before tests could run
    reasoning: str  # LLM reasoning for the most recent attempt
    diff: str  # git diff of the most recently applied edits
    history: list[dict]  # one entry per attempt, used for report.md
    tokens: int  # total LLM tokens used, if the API reports them
    started_at: float
    duration_s: float


class RunReport(BaseModel):
    """Summary of a finished run, shown by the CLI and the eval."""

    run_id: str
    status: str
    attempts: int
    duration_s: float
    tokens: int = 0
    pr_url: str | None = None
    patch_path: str | None = None
    report_path: str | None = None
