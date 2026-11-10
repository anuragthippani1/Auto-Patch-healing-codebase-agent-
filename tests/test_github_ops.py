"""Git and GitHub operations. Uses local bare repos and fakes; never touches the network."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from pydantic import SecretStr

from autopatch import github_ops
from autopatch.config import settings
from autopatch.github_ops import (
    GitError,
    GitHubError,
    UnsafeBranchError,
    branch_name,
    build_pr_body,
    check_branch_is_safe,
    clone,
    commit_fix,
    parse_github_repo,
    push_branch,
    run_git,
)

TOKEN = "ghp_secret_token_value"
BRANCH = "autopatch/issue-7-abc123"


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "work_dir", str(tmp_path / "work"))
    monkeypatch.setattr(settings, "github_token", SecretStr(TOKEN))


@pytest.fixture
def remote(tmp_path: Path) -> Path:
    """A bare 'GitHub' repo with one commit on main."""
    bare = tmp_path / "remote.git"
    run_git(None, "init", "--quiet", "--bare", "--initial-branch=main", str(bare))
    seed = tmp_path / "seed"
    (seed / "tests").mkdir(parents=True)
    (seed / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    (seed / "tests" / "test_calc.py").write_text("def test_add():\n    assert True\n")
    run_git(str(seed), "init", "--quiet", "--initial-branch=main")
    run_git(str(seed), "add", "-A")
    run_git(str(seed), "commit", "--quiet", "-m", "initial")
    run_git(str(seed), "push", "--quiet", str(bare), "main")
    return bare


@pytest.fixture
def repo(tmp_path: Path, remote: Path) -> Path:
    """A working clone of `remote` with the fix applied but not committed."""
    work = tmp_path / "clone"
    run_git(None, "clone", "--quiet", str(remote), str(work))
    (work / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    return work


def _sha(repo_path: Path, ref: str) -> str:
    return run_git(str(repo_path), "rev-parse", ref).strip()


def _state(repo: Path, **overrides: object) -> dict:
    state = {
        "repo_url": "https://github.com/octo/demo", "repo_path": str(repo), "issue_number": 7,
        "issue_title": "add() subtracts", "run_id": "abc123def456", "default_branch": "main",
        "reasoning": "The operator was wrong.", "attempts": 2,
        "diff": "--- a/calc.py\n+++ b/calc.py\n@@ -1 +1 @@\n-x\n+y\n",
        "test_log": "\n".join(f"line {i}" for i in range(1, 31)),
    }
    return {**state, **overrides}


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://github.com/octo/demo", "octo/demo"),
        ("https://github.com/octo/demo.git", "octo/demo"),
        ("https://github.com/octo/demo/", "octo/demo"),
        ("git@github.com:octo/my.repo-1.git", "octo/my.repo-1"),
        ("https://user:pw@github.com/octo/demo", "octo/demo"),
        ("./local/path", None),
        ("/abs/path/github.com/x", None),
        ("https://gitlab.com/octo/demo", None),
        ("https://github.com/octo", None),
    ],
)
def test_parse_github_repo(url: str, expected: str | None) -> None:
    assert parse_github_repo(url) == expected


def test_branch_name() -> None:
    assert branch_name(7, "abc123def456") == BRANCH


def test_guard_allows_autopatch_branches() -> None:
    check_branch_is_safe(BRANCH, "main")


@pytest.mark.parametrize(
    ("branch", "default"),
    [
        ("main", "main"),
        ("master", "main"),
        ("main", "develop"),
        ("develop", "develop"),
        ("feature/x", "main"),
        ("autopatch/", "main"),
        (BRANCH, BRANCH),
    ],
)
def test_guard_blocks_default_and_foreign_branches(branch: str, default: str) -> None:
    with pytest.raises(UnsafeBranchError):
        check_branch_is_safe(branch, default)


def test_commit_and_push_creates_only_the_autopatch_branch(repo: Path, remote: Path) -> None:
    main_before = _sha(remote, "main")
    commit_fix(str(repo), BRANCH, "main", "add() subtracts")
    push_branch(str(repo), "origin", BRANCH, "main")
    assert _sha(remote, "main") == main_before
    assert _sha(remote, BRANCH) == _sha(repo, "HEAD") != main_before
    assert _sha(repo, "main") == main_before
    subject = run_git(str(remote), "log", "-1", "--format=%s", BRANCH).strip()
    assert subject == "fix: add() subtracts (AutoPatch)"


def test_push_to_default_branch_is_blocked(repo: Path, remote: Path) -> None:
    main_before = _sha(remote, "main")
    run_git(str(repo), "commit", "--quiet", "-am", "a commit sitting on local main")
    assert _sha(repo, "main") != main_before
    for branch in ("main", "master"):
        with pytest.raises(UnsafeBranchError):
            push_branch(str(repo), "origin", branch, "main")
    assert _sha(remote, "main") == main_before


def test_commit_on_default_branch_is_blocked(repo: Path) -> None:
    head_before = _sha(repo, "HEAD")
    with pytest.raises(UnsafeBranchError):
        commit_fix(str(repo), "main", "main", "title")
    assert _sha(repo, "HEAD") == head_before


def test_commit_refuses_changes_to_test_files(repo: Path) -> None:
    (repo / "tests" / "test_calc.py").write_text("def test_add():\n    pass\n")
    with pytest.raises(GitError, match="test files"):
        commit_fix(str(repo), BRANCH, "main", "title")
    assert _sha(repo, "HEAD") == _sha(repo, "main")


def test_commit_refuses_when_nothing_changed(repo: Path) -> None:
    run_git(str(repo), "checkout", "--", ".")
    with pytest.raises(GitError, match="no changes"):
        commit_fix(str(repo), BRANCH, "main", "title")


def test_git_errors_never_contain_the_token(tmp_path: Path) -> None:
    url = f"https://x-access-token:{TOKEN}@localhost:1/octo/demo.git"
    with pytest.raises(GitError) as excinfo:
        run_git(None, "clone", "--quiet", url, str(tmp_path / "dest"))
    assert TOKEN not in str(excinfo.value)


def test_github_clone_uses_token_then_removes_it(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple] = []
    monkeypatch.setattr(github_ops, "run_git", lambda path, *args: calls.append(args) or "")
    github_ops._clone_github("octo/demo")
    assert calls[0][:3] == ("clone", "--quiet", f"https://x-access-token:{TOKEN}@github.com/octo/demo.git")
    assert calls[1] == ("remote", "set-url", "origin", "https://github.com/octo/demo.git")


def test_clone_local_path_copies_and_snapshots(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()
    (source / "calc.py").write_text("x = 1\n")
    repo_path, branch = clone(str(source))
    assert Path(repo_path) != source and Path(repo_path, "calc.py").read_text() == "x = 1\n"
    assert branch == run_git(repo_path, "rev-parse", "--abbrev-ref", "HEAD").strip()
    assert run_git(repo_path, "status", "--porcelain").strip() == ""
    assert not (source / ".git").exists()
    Path(repo_path, "calc.py").write_text("x = 2\n")
    github_ops.reset_worktree(repo_path)
    assert Path(repo_path, "calc.py").read_text() == "x = 1\n"


def test_clone_keeps_uncommitted_changes_of_a_local_git_repo(repo: Path) -> None:
    repo_path, branch = clone(str(repo))
    assert branch == "main"
    github_ops.reset_worktree(repo_path)
    assert "return a + b" in Path(repo_path, "calc.py").read_text()


def test_clone_missing_path_is_a_clear_error() -> None:
    with pytest.raises(GitError, match="not a GitHub URL or a local directory"):
        clone("/definitely/not/here")


def test_clone_when_work_dir_is_inside_the_repo(tmp_path: Path) -> None:
    (tmp_path / "calc.py").write_text("x = 1\n")
    repo_path, _ = clone(str(tmp_path))  # settings.work_dir is tmp_path/work
    assert Path(repo_path).is_relative_to(tmp_path / "work")
    assert Path(repo_path, "calc.py").is_file()
    assert list(Path(repo_path, "work").iterdir()) == []


def test_cleanup_only_removes_autopatch_work_dirs(tmp_path: Path) -> None:
    source = tmp_path / "project"
    source.mkdir()
    (source / "calc.py").write_text("x = 1\n")
    repo_path, _ = clone(str(source))
    github_ops.cleanup(repo_path)
    assert not Path(repo_path).exists()
    keep = tmp_path / "precious" / "repo"
    keep.mkdir(parents=True)
    github_ops.cleanup(str(keep))
    assert keep.exists()


def test_pr_body_has_required_parts(repo: Path) -> None:
    body = build_pr_body(_state(repo))
    assert body.startswith("Fixes #7\n")
    assert "The operator was wrong." in body
    assert "- `calc.py`" in body
    assert "2 attempt(s)" in body
    assert "line 11\n" in body and "line 30" in body and "line 10\n" not in body
    assert body.rstrip().endswith("Generated by AutoPatch. Please review before merging.")


def test_open_pr_pushes_branch_and_creates_pull(
    repo: Path, remote: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    created: dict = {}
    pushed: list[str] = []

    def create_pull(**kwargs: str) -> SimpleNamespace:
        created.update(kwargs)
        return SimpleNamespace(html_url="https://github.com/octo/demo/pull/8")

    def push_to_local_remote(repo_path: str, url: str, branch: str, default: str) -> None:
        pushed.append(url)
        push_branch(repo_path, "origin", branch, default)

    fake = SimpleNamespace(get_repo=lambda name: SimpleNamespace(create_pull=create_pull))
    monkeypatch.setattr(github_ops, "_github", lambda: fake)
    monkeypatch.setattr(github_ops, "push_branch", push_to_local_remote)
    main_before = _sha(remote, "main")

    url = github_ops.open_pr(_state(repo))

    assert url == "https://github.com/octo/demo/pull/8"
    assert pushed == [f"https://x-access-token:{TOKEN}@github.com/octo/demo.git"]
    assert created["head"] == BRANCH and created["base"] == "main"
    assert created["title"] == "[AutoPatch] add() subtracts"
    assert created["body"].startswith("Fixes #7")
    assert _sha(remote, "main") == main_before
    assert _sha(remote, BRANCH) == _sha(repo, "HEAD")


def test_open_pr_needs_issue_number_and_github_repo(repo: Path) -> None:
    with pytest.raises(GitHubError):
        github_ops.open_pr(_state(repo, issue_number=None))
    with pytest.raises(GitHubError):
        github_ops.open_pr(_state(repo, repo_url="/local/path"))


def test_fetch_issue_returns_title_and_body(monkeypatch: pytest.MonkeyPatch) -> None:
    issues = {3: SimpleNamespace(title="Bug", body=None), 4: SimpleNamespace(title="B", body="x")}
    fake = SimpleNamespace(get_repo=lambda name: SimpleNamespace(get_issue=issues.__getitem__))
    monkeypatch.setattr(github_ops, "_github", lambda: fake)
    assert github_ops.fetch_issue("octo/demo", 3) == ("Bug", "")
    assert github_ops.fetch_issue("octo/demo", 4) == ("B", "x")
