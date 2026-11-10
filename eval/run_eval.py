"""Run AutoPatch on the seeded bugs and write the results table to eval/results.md.

    python eval/run_eval.py                 # all bugs (needs OPENROUTER_API_KEY)
    python eval/run_eval.py --only 01,02    # a subset
    python eval/run_eval.py --check         # no LLM: only verify each bug makes tests fail
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from rich.console import Console
from rich.table import Table

from autopatch import sandbox
from autopatch.config import ConfigError, settings
from autopatch.github_ops import cleanup, clone, run_git
from autopatch.graph import run_agent
from autopatch.models import SandboxResult

EVAL_DIR = Path(__file__).resolve().parent
CLEAN_REPO = EVAL_DIR / "clean_repo"
BUGS_DIR = EVAL_DIR / "bugs"
RESULTS_FILE = EVAL_DIR / "results.md"
README = EVAL_DIR.parent / "README.md"
README_START, README_END = "<!-- eval-results:start -->", "<!-- eval-results:end -->"
DIFFICULTY = {
    "01": "easy", "02": "easy", "03": "easy", "04": "easy",
    "05": "medium", "06": "medium", "07": "medium", "08": "medium",
    "09": "hard", "10": "hard",
}
console = Console()


@dataclass
class Row:
    """Result of one bug."""

    bug: str
    difficulty: str
    status: str  # fixed | failed | no_repro
    attempts: int
    duration_s: float
    tokens: int

    @property
    def fixed_label(self) -> str:
        """Text for the 'Fixed' column."""
        if self.status == "no_repro":
            return "skipped (baseline tests pass)"
        return "yes" if self.status == "fixed" else "no"


def prepare_repo(bug_id: str, workspace: Path) -> Path:
    """Copy the clean repo, commit it, inject the bug, and commit again."""
    repo = workspace / f"bug-{bug_id}"
    shutil.copytree(CLEAN_REPO, repo, ignore=shutil.ignore_patterns("__pycache__", ".*_cache"))
    run_git(str(repo), "init", "--quiet")
    run_git(str(repo), "add", "-A")
    run_git(str(repo), "commit", "--quiet", "-m", "Clean toolkit")
    run_git(str(repo), "apply", str(BUGS_DIR / f"{bug_id}.patch"))
    run_git(str(repo), "commit", "--quiet", "-am", f"Inject bug {bug_id}")
    return repo


def read_issue(bug_id: str) -> tuple[str, str]:
    """Issue text: the first line is the title, the rest is the body."""
    lines = (BUGS_DIR / f"{bug_id}.md").read_text(encoding="utf-8").strip().splitlines()
    return lines[0].strip(), "\n".join(lines[1:]).strip()


def run_bug(bug_id: str, workspace: Path) -> Row:
    """Run the agent on one bug in dry-run mode."""
    console.rule(f"Bug {bug_id} ({DIFFICULTY[bug_id]})")
    repo = prepare_repo(bug_id, workspace)
    title, body = read_issue(bug_id)
    state = run_agent(str(repo), title, body, dry_run=True)
    return Row(
        bug_id, DIFFICULTY[bug_id], state["status"], state["attempts"],
        state["duration_s"], state["tokens"],
    )


def summary_line(rows: list[Row]) -> str:
    """'Fixed X/N (Y%), avg attempts Z, avg time W s'."""
    fixed = sum(row.status == "fixed" for row in rows)
    ran = [row for row in rows if row.status != "no_repro"] or rows
    attempts = sum(row.attempts for row in ran) / len(ran)
    seconds = sum(row.duration_s for row in ran) / len(ran)
    percent = 100 * fixed / len(rows)
    return (
        f"Fixed {fixed}/{len(rows)} ({percent:.0f}%), "
        f"avg attempts {attempts:.1f}, avg time {seconds:.1f} s"
    )


def render_markdown(rows: list[Row]) -> str:
    """Results table plus the summary line."""
    show_tokens = any(row.tokens for row in rows)
    header, divider = "| Bug | Difficulty | Fixed | Attempts | Time (s) |", "|---|---|---|---|---|"
    if show_tokens:
        header, divider = header + " Tokens |", divider + "---|"
    lines = [header, divider]
    for row in rows:
        line = (
            f"| {row.bug} | {row.difficulty} | {row.fixed_label} | {row.attempts} "
            f"| {row.duration_s:.1f} |"
        )
        lines.append(line + (f" {row.tokens} |" if show_tokens else ""))
    lines += ["", f"**{summary_line(rows)}**", ""]
    lines.append(f"Model: `{settings.openrouter_model}`. Run on {date.today().isoformat()}.")
    return "\n".join(lines)


def update_readme(table: str) -> None:
    """Replace the results block in the README, if the markers are there."""
    if not README.is_file():
        return
    text = README.read_text(encoding="utf-8")
    start, end = text.find(README_START), text.find(README_END)
    if start == -1 or end == -1:
        return
    block = f"{README_START}\n{table}\n"
    README.write_text(text[:start] + block + text[end:], encoding="utf-8")


def sandbox_result(repo: Path) -> SandboxResult:
    """Run the sandbox on a working copy of `repo` (same copy step as the agent uses)."""
    repo_path, _ = clone(str(repo))
    try:
        return sandbox.run_pytest(repo_path)
    finally:
        cleanup(repo_path)


def check_bugs(bug_ids: list[str], workspace: Path) -> int:
    """Without any LLM call: clean tests must pass and every bug must make them fail."""
    clean = sandbox_result(CLEAN_REPO)
    console.print(f"clean repo: {'passes' if clean.passed else 'FAILS'}")
    problems = 0 if clean.passed else 1
    table = Table("Bug", "Difficulty", "Baseline", "First failure")
    for bug_id in bug_ids:
        result = sandbox_result(prepare_repo(bug_id, workspace))
        failed = [line for line in result.stdout.splitlines() if line.startswith("FAILED")]
        problems += result.passed
        outcome = "PASSES (bug not detected)" if result.passed else "fails"
        table.add_row(bug_id, DIFFICULTY[bug_id], outcome, failed[0] if failed else "")
    console.print(table)
    return 1 if problems else 0


def run_all(bug_ids: list[str], workspace: Path) -> int:
    """Run the agent on each bug, then print and save the results."""
    rows = [run_bug(bug_id, workspace) for bug_id in bug_ids]
    table = render_markdown(rows)
    console.rule("Results")
    console.print(table, markup=False)
    if bug_ids == sorted(DIFFICULTY):
        RESULTS_FILE.write_text(f"# AutoPatch evaluation results\n\n{table}\n", encoding="utf-8")
        update_readme(table)
        console.print(f"Saved to {RESULTS_FILE}")
    else:
        console.print("Partial run: eval/results.md was not changed.")
    return 0


def main() -> int:
    """Parse the command line and run the eval or the check. Returns the exit code."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", help="comma-separated bug ids, e.g. 01,02,03")
    parser.add_argument("--check", action="store_true", help="only verify the bugs; no LLM calls")
    args = parser.parse_args()
    bug_ids = sorted(args.only.split(",")) if args.only else sorted(DIFFICULTY)
    unknown = [bug_id for bug_id in bug_ids if bug_id not in DIFFICULTY]
    if unknown:
        parser.error(f"unknown bug id(s): {', '.join(unknown)}")
    try:
        with tempfile.TemporaryDirectory(prefix="autopatch-eval-") as tmp:
            if args.check:
                return check_bugs(bug_ids, Path(tmp))
            settings.require_keys(dry_run=True)
            return run_all(bug_ids, Path(tmp))
    except (ConfigError, sandbox.SandboxError) as exc:
        console.print(f"[red]Error:[/red] {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
