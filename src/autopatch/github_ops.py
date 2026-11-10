"""Git and GitHub operations: clone, diff, branch, push, open PR."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from github import Auth, Github, GithubException

from .config import redact, settings
from .edits import is_test_path
from .models import State

GIT_IDENTITY = ["-c", "user.name=AutoPatch", "-c", "user.email=autopatch@users.noreply.github.com"]
WORK_PREFIX = "autopatch-"
BRANCH_PREFIX = "autopatch/"
PROTECTED_BRANCHES = {"main", "master"}
PR_LOG_LINES = 20
COPY_IGNORE = shutil.ignore_patterns(
    ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache"
)
_GITHUB_URL = re.compile(
    r"^(?:https?://(?:[^@/]+@)?github\.com/|git@github\.com:)"
    r"(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(?:\.git)?/?$"
)


class GitError(RuntimeError):
    """A git command failed. The message never contains the GitHub token."""


class GitHubError(RuntimeError):
    """A GitHub API call failed."""


class UnsafeBranchError(RuntimeError):
    """AutoPatch was about to write to a branch it must never touch."""


def run_git(repo_path: str | None, *args: str) -> str:
    """Run a git command and return stdout; raise `GitError` on failure."""
    result = subprocess.run(
        ["git", *GIT_IDENTITY, *args],
        cwd=repo_path,
        capture_output=True,
        text=True,
        env={**os.environ, "GIT_TERMINAL_PROMPT": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise GitError(redact(f"git {args[0]} failed: {detail}"))
    return result.stdout


def parse_github_repo(repo: str) -> str | None:
    """Return 'owner/name' for a GitHub URL, or None for anything else."""
    match = _GITHUB_URL.match(repo.strip())
    return f"{match['owner']}/{match['repo']}" if match else None


def _new_work_dir() -> str:
    """Create a fresh directory to hold one working copy."""
    if settings.work_dir:
        os.makedirs(settings.work_dir, exist_ok=True)
    return tempfile.mkdtemp(prefix=WORK_PREFIX, dir=settings.work_dir or None)


def _clone_github(full_name: str) -> str:
    """Clone a GitHub repo with the token, then drop the token from the remote URL."""
    dest = os.path.join(_new_work_dir(), "repo")
    token = settings.github_token.get_secret_value()
    auth = f"x-access-token:{token}@" if token else ""
    run_git(None, "clone", "--quiet", f"https://{auth}github.com/{full_name}.git", dest)
    run_git(dest, "remote", "set-url", "origin", f"https://github.com/{full_name}.git")
    return dest


def _copy_ignore(work_dir: Path) -> Callable[[str, list[str]], set[str]]:
    """Ignore function for copytree: junk directories, plus the destination itself."""

    def ignore(directory: str, names: list[str]) -> set[str]:
        skipped = set(COPY_IGNORE(directory, names))
        skipped.update(name for name in names if Path(directory, name).resolve() == work_dir)
        return skipped

    return ignore


def _copy_local(path: str) -> str:
    """Copy a local directory to a working copy where every file is committed."""
    source = Path(path).expanduser().resolve()
    if not source.is_dir():
        raise GitError(f"Repository not found: '{path}' is not a GitHub URL or a local directory.")
    work_dir = Path(_new_work_dir()).resolve()
    dest = str(work_dir / "repo")
    # The work dir may be inside the source (e.g. WORK_DIR under the repo): never copy it.
    shutil.copytree(source, dest, symlinks=True, ignore=_copy_ignore(work_dir))
    if not os.path.exists(os.path.join(dest, ".git")):
        run_git(dest, "init", "--quiet")
    run_git(dest, "add", "-A")
    if run_git(dest, "status", "--porcelain").strip():
        run_git(dest, "commit", "--quiet", "-m", "AutoPatch baseline snapshot")
    return dest


def detect_default_branch(repo_path: str) -> str:
    """The remote's default branch, or the current branch for local-only repos."""
    try:
        ref = run_git(repo_path, "symbolic-ref", "--short", "refs/remotes/origin/HEAD")
        return ref.strip().removeprefix("origin/")
    except GitError:
        return run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").strip()


def clone(repo_url_or_path: str) -> tuple[str, str]:
    """Create a working copy. Returns (repo_path, default_branch)."""
    full_name = parse_github_repo(repo_url_or_path)
    repo_path = _clone_github(full_name) if full_name else _copy_local(repo_url_or_path)
    return repo_path, detect_default_branch(repo_path)


def reset_worktree(repo_path: str) -> None:
    """Discard all uncommitted changes to tracked files."""
    run_git(repo_path, "checkout", "--", ".")


def diff(repo_path: str) -> str:
    """Unified diff of uncommitted changes."""
    return run_git(repo_path, "diff")


def changed_files(repo_path: str) -> list[str]:
    """Paths with uncommitted changes."""
    return [line for line in run_git(repo_path, "diff", "--name-only").splitlines() if line]


def cleanup(repo_path: str) -> None:
    """Delete a working copy created by `clone` (and nothing else)."""
    parent = Path(repo_path).parent
    if repo_path and parent.name.startswith(WORK_PREFIX):
        shutil.rmtree(parent, ignore_errors=True)


def _github() -> Github:
    """PyGithub client; anonymous if no token is configured."""
    token = settings.github_token.get_secret_value()
    return Github(auth=Auth.Token(token)) if token else Github()


def _api_error(action: str, exc: GithubException) -> GitHubError:
    """Wrap a PyGithub error in a short, readable message."""
    message = exc.data.get("message", "") if isinstance(exc.data, dict) else str(exc.data)
    return GitHubError(f"{action} failed: HTTP {exc.status} {message}".strip())


def fetch_issue(repo_full_name: str, number: int) -> tuple[str, str]:
    """Return (title, body) of a GitHub issue."""
    try:
        issue = _github().get_repo(repo_full_name).get_issue(number)
    except GithubException as exc:
        raise _api_error(f"Fetching issue #{number} from {repo_full_name}", exc) from exc
    return issue.title, issue.body or ""


def branch_name(issue_number: int, run_id: str) -> str:
    """Branch for a fix: autopatch/issue-<number>-<first 6 chars of run id>."""
    return f"{BRANCH_PREFIX}issue-{issue_number}-{run_id[:6]}"


def check_branch_is_safe(branch: str, default_branch: str) -> None:
    """Guard: AutoPatch only ever writes to autopatch/* branches."""
    if (
        branch == default_branch
        or branch in PROTECTED_BRANCHES
        or not branch.startswith(BRANCH_PREFIX)
        or len(branch) == len(BRANCH_PREFIX)
    ):
        raise UnsafeBranchError(
            f"Refusing to write to branch '{branch}': only {BRANCH_PREFIX}* branches are allowed "
            f"and never the default branch ('{default_branch}')."
        )


def commit_fix(repo_path: str, branch: str, default_branch: str, issue_title: str) -> None:
    """Commit the applied edits on a new autopatch/* branch."""
    check_branch_is_safe(branch, default_branch)
    run_git(repo_path, "checkout", "--quiet", "-b", branch)
    run_git(repo_path, "add", "-A")
    staged = run_git(repo_path, "diff", "--cached", "--name-only").splitlines()
    if not staged:
        raise GitError("There are no changes to commit.")
    protected = [path for path in staged if is_test_path(path)]
    if protected:
        raise GitError(f"Refusing to commit changes to test files: {', '.join(protected)}")
    run_git(repo_path, "commit", "--quiet", "-m", f"fix: {issue_title} (AutoPatch)")


def push_branch(repo_path: str, remote: str, branch: str, default_branch: str) -> None:
    """Push one autopatch/* branch. The refspec is explicit, so nothing else can move."""
    check_branch_is_safe(branch, default_branch)
    run_git(repo_path, "push", "--quiet", remote, f"refs/heads/{branch}:refs/heads/{branch}")


def files_in_diff(diff_text: str) -> list[str]:
    """Paths changed by a unified diff."""
    return re.findall(r"^\+\+\+ b/(.+)$", diff_text, flags=re.MULTILINE)


def build_pr_body(state: State) -> str:
    """Markdown body of the pull request."""
    files = "\n".join(f"- `{path}`" for path in files_in_diff(state["diff"]))
    log_tail = "\n".join(state["test_log"].strip().splitlines()[-PR_LOG_LINES:])
    return "\n".join([
        f"Fixes #{state['issue_number']}",
        "",
        "## What was wrong",
        state["reasoning"].strip() or "(the model gave no explanation)",
        "",
        "## Files changed",
        files,
        "",
        "## Verification",
        f"The test suite passes in the AutoPatch sandbox (Docker, no network) after "
        f"{state['attempts']} attempt(s).",
        "",
        f"Passing test output (last {PR_LOG_LINES} lines):",
        "```",
        log_tail,
        "```",
        "",
        "---",
        "Generated by AutoPatch. Please review before merging.",
    ])


def open_pr(state: State) -> str:
    """Commit the fix on an autopatch/* branch, push it, and open a PR. Returns its URL."""
    full_name = parse_github_repo(state["repo_url"])
    number = state["issue_number"]
    if not full_name or number is None:
        raise GitHubError("Opening a PR needs a GitHub repository URL and an issue number.")
    branch, base = branch_name(number, state["run_id"]), state["default_branch"]
    commit_fix(state["repo_path"], branch, base, state["issue_title"])
    token = settings.github_token.get_secret_value()
    remote = f"https://x-access-token:{token}@github.com/{full_name}.git"
    push_branch(state["repo_path"], remote, branch, base)
    try:
        pull = _github().get_repo(full_name).create_pull(
            title=f"[AutoPatch] {state['issue_title']}",
            body=build_pr_body(state),
            head=branch,
            base=base,
        )
    except GithubException as exc:
        raise _api_error(f"Opening the pull request from {branch}", exc) from exc
    return pull.html_url
