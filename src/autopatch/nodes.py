"""LangGraph node functions and the pure routing functions between them."""

from __future__ import annotations

import json

from . import github_ops, llm, sandbox
from .config import settings
from .edits import EditError, apply_edits
from .localize import Context, select_context
from .logging_utils import log_event, write_artifact
from .models import State

FEEDBACK_TAIL_CHARS = 3000
EVENT_TAIL_CHARS = 2000
NO_TESTS_EXIT_CODE = 5  # pytest: no tests were collected


def clone_repo(state: State) -> dict:
    """Create the working copy and detect the default branch."""
    repo_path, branch = github_ops.clone(state["repo_url"])
    log_event(
        state["run_id"], "clone_repo", f"Working copy ready (default branch: {branch})",
        {"repo_path": repo_path, "default_branch": branch},
    )
    return {"repo_path": repo_path, "default_branch": branch}


def _describe(result: sandbox.SandboxResult) -> str:
    """Short human description of a sandbox result."""
    if result.passed:
        outcome = "passed"
    elif result.timed_out:
        outcome = "timed out"
    else:
        outcome = f"failed (exit code {result.exit_code})"
    return f"{outcome} in {result.duration_s:.1f}s"


def _result_data(result: sandbox.SandboxResult) -> dict:
    """Event payload for a sandbox result."""
    data = result.model_dump(exclude={"stdout"})
    data["log_tail"] = result.stdout[-EVENT_TAIL_CHARS:]
    return data


def run_baseline_tests(state: State) -> dict:
    """Run the tests before any change, to reproduce the failure."""
    result = sandbox.run_pytest(state["repo_path"])
    log_event(
        state["run_id"], "run_baseline_tests", f"Baseline tests {_describe(result)}",
        _result_data(result),
    )
    update = {
        "test_log": result.stdout,
        "baseline_log": result.stdout,
        "baseline_failed": not result.passed,
        "baseline_exit_code": result.exit_code,
    }
    if result.exit_code == NO_TESTS_EXIT_CODE:
        update["last_error"] = "pytest collected no tests, so a fix could not be verified."
    return update


def route_after_baseline(state: State) -> str:
    """Pure: 'no_repro' if tests pass, 'give_up' if there are no tests, else 'propose'."""
    if not state["baseline_failed"]:
        return "no_repro"
    if state["baseline_exit_code"] == NO_TESTS_EXIT_CODE:
        return "give_up"
    return "propose"


def no_repro(state: State) -> dict:
    """The tests already pass; there is nothing to fix."""
    log_event(state["run_id"], "no_repro", "Tests already pass; the issue was not reproduced")
    return {"status": "no_repro"}


def _feedback(state: State) -> str:
    """What the LLM is told about its previous attempt (empty on the first)."""
    if state["attempts"] == 0:
        return ""
    edits = json.dumps(state["edits"], indent=2)
    return f"Edits you proposed last time:\n{edits}\n\nWhat happened:\n{state['last_error']}"


def _context_log(state: State) -> str:
    """Log used to pick files: the baseline plus the latest run, if different."""
    if state["test_log"] == state["baseline_log"]:
        return state["baseline_log"]
    return state["baseline_log"] + "\n" + state["test_log"]


def _attempt(state: State, context: Context) -> dict:
    """Ask the LLM for edits and apply them. Returns this attempt's history entry."""
    entry = {
        "attempt": state["attempts"] + 1, "reasoning": "", "edits": [],
        "error": "", "passed": None, "test_tail": "",
    }
    try:
        reasoning, edits = llm.propose_fix(
            state["issue_title"], state["issue_body"], context.source_files,
            context.test_files, state["baseline_log"], _feedback(state),
        )
        entry.update(reasoning=reasoning, edits=[edit.model_dump() for edit in edits])
        apply_edits(state["repo_path"], edits)
    except EditError as exc:
        entry["error"] = f"Edit rejected: {exc}"
    except llm.LLMError as exc:
        entry["error"] = f"LLM error: {exc}"
    return entry


def propose_and_apply(state: State) -> dict:
    """Reset the repo, get edits from the LLM, and apply them."""
    repo = state["repo_path"]
    github_ops.reset_worktree(repo)
    context = select_context(repo, _context_log(state), settings.max_context_chars)
    tokens_before = llm.tokens_used()
    entry = _attempt(state, context)
    update = {
        "attempts": entry["attempt"],
        "apply_ok": not entry["error"],
        "edits": entry["edits"],
        "reasoning": entry["reasoning"],
        "history": [*state["history"], entry],
        "tokens": state["tokens"] + llm.tokens_used() - tokens_before,
    }
    if entry["error"]:
        update["last_error"] = entry["error"]
        summary = f"Attempt {entry['attempt']}: {entry['error']}"
    else:
        update["diff"] = github_ops.diff(repo)
        files = ", ".join(github_ops.changed_files(repo))
        summary = f"Attempt {entry['attempt']}: applied {len(entry['edits'])} edit(s) to {files}"
    context_files = [*context.source_files, *context.test_files]
    log_event(state["run_id"], "propose_and_apply", summary, {**entry, "context": context_files})
    return update


def route_after_apply(state: State) -> str:
    """Pure: run tests if edits were applied, else retry or give up."""
    if state["apply_ok"]:
        return "run_tests"
    return "retry" if state["attempts"] < state["max_attempts"] else "give_up"


def run_tests_after(state: State) -> dict:
    """Run the tests on the patched repo."""
    result = sandbox.run_pytest(state["repo_path"])
    tail = result.stdout[-FEEDBACK_TAIL_CHARS:]
    last = {**state["history"][-1], "passed": result.passed, "test_tail": tail}
    log_event(
        state["run_id"], "run_tests_after",
        f"Attempt {state['attempts']}: tests {_describe(result)}", _result_data(result),
    )
    return {
        "test_log": result.stdout,
        "last_error": "" if result.passed else f"Tests still fail with your edits applied:\n{tail}",
        "status": "fixed" if result.passed else "running",
        "history": [*state["history"][:-1], last],
    }


def route_after_tests(state: State) -> str:
    """Pure: 'open_pr' if fixed, 'retry' if attempts remain, else 'give_up'."""
    if state["status"] == "fixed":
        return "open_pr"
    return "retry" if state["attempts"] < state["max_attempts"] else "give_up"


def open_pr(state: State) -> dict:
    """Save the fix as a patch; push a branch and open a PR unless this is a dry run."""
    patch = write_artifact(state["run_id"], "fix.patch", state["diff"])
    if state["dry_run"]:
        log_event(state["run_id"], "open_pr", f"Dry run: no PR opened; fix saved to {patch}")
        return {"pr_url": None}
    url = github_ops.open_pr(state)
    log_event(state["run_id"], "open_pr", f"Opened pull request {url}", {"pr_url": url})
    return {"pr_url": url}


def give_up(state: State) -> dict:
    """Stop with status 'failed' and keep the last diff that was tried."""
    summary = f"Giving up after {state['attempts']} attempt(s)"
    if state["diff"]:
        patch = write_artifact(state["run_id"], "last_attempt.patch", state["diff"])
        summary += f"; last attempted diff saved to {patch}"
    log_event(state["run_id"], "give_up", summary, {"last_error": state["last_error"]})
    return {"status": "failed"}
