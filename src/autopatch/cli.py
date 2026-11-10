"""AutoPatch command line interface."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from . import github_ops, sandbox
from .config import ConfigError, redact, settings
from .graph import run_agent
from .logging_utils import STATUS_STYLE, summarize
from .models import RunReport

console = Console()
EXIT_CODES = {"fixed": 0, "failed": 1, "no_repro": 2}

app = typer.Typer(
    name="autopatch",
    help="AutoPatch: reproduce a bug in a sandbox, fix it with an LLM, open a PR.",
    no_args_is_help=True,
    add_completion=False,
)


def _fail(message: str) -> typer.Exit:
    """Print an error and return the exit to raise."""
    console.print(f"[red]Error:[/red] {message}")
    return typer.Exit(code=1)


def read_issue_file(path: Path) -> tuple[str, str]:
    """Read an issue file: the first line is the title, the rest is the body."""
    if not path.is_file():
        raise _fail(f"Issue file not found: {path}")
    lines = path.read_text(encoding="utf-8").strip().splitlines()
    if not lines:
        raise _fail(f"Issue file is empty: {path}")
    return lines[0].lstrip("# ").strip(), "\n".join(lines[1:]).strip()


def _check_arguments(repo: str, issue: int | None, issue_file: Path | None, dry_run: bool) -> None:
    """Reject argument combinations that cannot work, before doing anything."""
    is_github = github_ops.parse_github_repo(repo) is not None
    if (issue is None) == (issue_file is None):
        raise _fail("Give exactly one of --issue or --issue-file.")
    if issue is not None and not is_github:
        raise _fail("--issue needs a GitHub repository URL. For a local path use --issue-file.")
    if not dry_run and (issue is None or not is_github):
        raise _fail("A real run needs a GitHub URL and --issue. Add --dry-run for a local run.")


def _print_summary(report: RunReport) -> None:
    """Print the final summary table."""
    table = Table(title="AutoPatch summary", show_header=False)
    style = STATUS_STYLE.get(report.status, "white")
    table.add_row("Status", f"[{style}]{report.status}[/{style}]")
    table.add_row("Attempts", str(report.attempts))
    table.add_row("Duration", f"{report.duration_s:.1f} s")
    if report.pr_url:
        table.add_row("Pull request", report.pr_url)
    else:
        table.add_row("Patch", report.patch_path or "none")
    table.add_row("Report", report.report_path or "none")
    console.print(table)


@app.command()
def fix(
    repo: str = typer.Option(..., "--repo", help="GitHub URL or local path of the repository."),
    issue: int | None = typer.Option(None, "--issue", help="GitHub issue number."),
    issue_file: Path | None = typer.Option(
        None, "--issue-file", help="Issue text file: first line is the title, the rest the body."
    ),
    dry_run: bool = typer.Option(False, "--dry-run", help="Do not push or open a PR."),
) -> None:
    """Fix the bug described by an issue. Exit code: 0 fixed, 1 failed, 2 no_repro."""
    _check_arguments(repo, issue, issue_file, dry_run)
    try:
        settings.require_keys(dry_run)
        if issue_file is not None:
            title, body = read_issue_file(issue_file)
        else:
            title, body = github_ops.fetch_issue(github_ops.parse_github_repo(repo), issue)
    except ConfigError as exc:
        raise _fail(str(exc)) from exc
    except github_ops.GitHubError as exc:
        raise _fail(redact(str(exc))) from exc
    state = run_agent(repo, title, body, issue_number=issue, dry_run=dry_run)
    _print_summary(summarize(state))
    raise typer.Exit(code=EXIT_CODES.get(state["status"], 1))


@app.command(
    name="eval", context_settings={"allow_extra_args": True, "ignore_unknown_options": True}
)
def eval_cmd(ctx: typer.Context) -> None:
    """Run eval/run_eval.py on the seeded bugs. Extra options are passed through."""
    script = Path("eval") / "run_eval.py"
    if not script.is_file():
        raise _fail("eval/run_eval.py not found. Run this from the AutoPatch repo root.")
    raise typer.Exit(code=subprocess.call([sys.executable, str(script), *ctx.args]))


@app.command(name="build-sandbox")
def build_sandbox() -> None:
    """Build the Docker sandbox image used to run tests."""
    console.print("Building the sandbox image (first build downloads python:3.11-slim)...")
    try:
        tag = sandbox.build_image()
    except sandbox.SandboxError as exc:
        raise _fail(str(exc)) from exc
    console.print(f"[green]Built {tag}[/green]")
