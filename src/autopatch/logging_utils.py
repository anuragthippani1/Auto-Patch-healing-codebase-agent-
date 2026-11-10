"""JSONL event log, live console trace, and the final report.md."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from rich.console import Console
from rich.markup import escape

from .config import settings
from .models import RunReport, State

console = Console()
STATUS_STYLE = {"fixed": "green", "failed": "red", "no_repro": "yellow"}


def run_dir(run_id: str) -> Path:
    """Directory holding everything written for one run."""
    path = Path(settings.runs_dir) / run_id
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_event(run_id: str, node: str, summary: str, data: dict | None = None) -> None:
    """Append one event to events.jsonl and print it to the console."""
    now = datetime.now(UTC)
    record = {
        "ts": now.isoformat(timespec="milliseconds"),
        "node": node,
        "summary": summary,
        "data": data or {},
    }
    with open(run_dir(run_id) / "events.jsonl", "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, default=str) + "\n")
    stamp = now.astimezone().strftime("%H:%M:%S")
    console.print(f"[dim]{stamp}[/dim] [bold cyan]{node:<18}[/bold cyan] {escape(summary)}")


def write_artifact(run_id: str, name: str, content: str) -> Path:
    """Write a text file into the run directory and return its path."""
    path = run_dir(run_id) / name
    path.write_text(content, encoding="utf-8")
    return path


def _fenced(text: str, lang: str = "") -> str:
    """Wrap text in a code fence that the text itself cannot close."""
    fence = "````" if "```" in text else "```"
    return f"{fence}{lang}\n{text.rstrip()}\n{fence}"


def _attempt_section(entry: dict) -> str:
    """Markdown for one attempt: reasoning, edits, and what happened."""
    lines = [f"### Attempt {entry['attempt']}", ""]
    lines.append(f"**Reasoning:** {entry.get('reasoning') or '(none)'}")
    for edit in entry.get("edits", []):
        lines += ["", f"**Edit** `{edit['path']}`", ""]
        lines += ["Search:", _fenced(edit["search"], "python")]
        lines += ["Replace:", _fenced(edit["replace"], "python")]
    if entry.get("error"):
        result = f"not tested. {entry['error']}"
    else:
        result = "tests passed" if entry.get("passed") else "tests failed"
    lines += ["", f"**Result:** {result}"]
    if entry.get("test_tail"):
        lines += ["", "Test output (tail):", _fenced(entry["test_tail"])]
    return "\n".join(lines)


def _header(state: State) -> list[str]:
    """The summary block at the top of the report."""
    number = f"#{state['issue_number']} " if state.get("issue_number") else ""
    pr_line = state.get("pr_url") or ("not opened (dry run)" if state["dry_run"] else "not opened")
    lines = [
        f"# AutoPatch run {state['run_id']}",
        "",
        f"- **Issue:** {number}{state['issue_title']}",
        f"- **Repository:** {state['repo_url']}",
        f"- **Status:** {state['status']}",
        f"- **Attempts:** {state['attempts']} of {state['max_attempts']}",
        f"- **Total duration:** {state['duration_s']:.1f} s",
        f"- **LLM tokens:** {state['tokens'] or 'not reported'}",
        f"- **Pull request:** {pr_line}",
    ]
    if state["status"] != "fixed" and state.get("last_error"):
        lines += ["", "**Last error:**", _fenced(state["last_error"])]
    return lines


def write_report(state: State) -> Path:
    """Write runs/<run_id>/report.md from the final state."""
    lines = _header(state)
    lines += ["", "## Issue", "", state["issue_body"].strip() or "(no description)"]
    lines += ["", "## Attempts", ""]
    if state["history"]:
        lines.append("\n\n".join(_attempt_section(entry) for entry in state["history"]))
    else:
        lines.append("No fix was attempted.")
    return write_artifact(state["run_id"], "report.md", "\n".join(lines) + "\n")


def summarize(state: State) -> RunReport:
    """Condense a final state into a `RunReport`."""
    directory = run_dir(state["run_id"])
    patch_name = "fix.patch" if state["status"] == "fixed" else "last_attempt.patch"
    patch = directory / patch_name
    return RunReport(
        run_id=state["run_id"],
        status=state["status"],
        attempts=state["attempts"],
        duration_s=state["duration_s"],
        tokens=state["tokens"],
        pr_url=state.get("pr_url"),
        patch_path=str(patch) if patch.is_file() else None,
        report_path=str(directory / "report.md"),
    )
