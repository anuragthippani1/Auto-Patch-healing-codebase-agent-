"""LangGraph definition of the AutoPatch loop, and the function that runs it."""

from __future__ import annotations

import time
import uuid

from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph

from . import github_ops, nodes
from .config import redact, settings
from .logging_utils import log_event, write_report
from .models import State


def build_graph() -> CompiledStateGraph:
    """Wire the nodes together as described in SPEC.md section 7."""
    graph = StateGraph(State)
    for node in (
        nodes.clone_repo, nodes.run_baseline_tests, nodes.no_repro, nodes.propose_and_apply,
        nodes.run_tests_after, nodes.open_pr, nodes.give_up,
    ):
        graph.add_node(node.__name__, node)
    graph.add_edge(START, "clone_repo")
    graph.add_edge("clone_repo", "run_baseline_tests")
    graph.add_conditional_edges(
        "run_baseline_tests", nodes.route_after_baseline,
        {"no_repro": "no_repro", "propose": "propose_and_apply", "give_up": "give_up"},
    )
    graph.add_conditional_edges(
        "propose_and_apply", nodes.route_after_apply,
        {"run_tests": "run_tests_after", "retry": "propose_and_apply", "give_up": "give_up"},
    )
    graph.add_conditional_edges(
        "run_tests_after", nodes.route_after_tests,
        {"open_pr": "open_pr", "retry": "propose_and_apply", "give_up": "give_up"},
    )
    for last in ("no_repro", "open_pr", "give_up"):
        graph.add_edge(last, END)
    return graph.compile()


def initial_state(
    repo: str, issue_title: str, issue_body: str, issue_number: int | None, dry_run: bool
) -> State:
    """State for a new run."""
    full_name = github_ops.parse_github_repo(repo)
    return State(
        issue_title=issue_title, issue_body=issue_body, issue_number=issue_number,
        repo_url=f"https://github.com/{full_name}" if full_name else repo,
        repo_path="", default_branch="", test_log="", baseline_log="",
        baseline_failed=False, baseline_exit_code=0, edits=[], last_error="",
        attempts=0, max_attempts=settings.max_attempts, status="running", pr_url=None,
        dry_run=dry_run, run_id=uuid.uuid4().hex[:12], apply_ok=False, reasoning="",
        diff="", history=[], tokens=0, started_at=time.time(), duration_s=0.0,
    )


def run_agent(
    repo: str,
    issue_title: str,
    issue_body: str,
    issue_number: int | None = None,
    dry_run: bool = True,
) -> State:
    """Run the whole loop for one issue. Always writes a report; never raises."""
    state = initial_state(repo, issue_title, issue_body, issue_number, dry_run)
    run_id = state["run_id"]
    mode = "dry run" if dry_run else "real run"
    log_event(run_id, "start", f"Run {run_id} ({mode}): {issue_title}", {"repo": state["repo_url"]})
    config = {"recursion_limit": 10 + 2 * state["max_attempts"]}
    try:
        for snapshot in build_graph().stream(state, config, stream_mode="values"):
            state = snapshot  # keep the latest state so a crash loses nothing
    except Exception as exc:  # any failure must still end in a report
        error = redact(f"{type(exc).__name__}: {exc}")
        state = {**state, "status": "failed", "last_error": error}
        log_event(run_id, "error", error)
    finally:
        github_ops.cleanup(state["repo_path"])
    state["duration_s"] = time.time() - state["started_at"]
    report = write_report(state)
    log_event(
        run_id, "end", f"Status: {state['status']}; report at {report}",
        {"status": state["status"], "attempts": state["attempts"],
         "duration_s": round(state["duration_s"], 2), "pr_url": state["pr_url"]},
    )
    return state
