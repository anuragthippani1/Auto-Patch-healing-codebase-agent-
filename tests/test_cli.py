"""CLI tests that need neither Docker nor the network."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr
from typer.testing import CliRunner

from autopatch import cli
from autopatch.cli import app, read_issue_file
from autopatch.config import settings

runner = CliRunner()


@pytest.fixture
def issue_file(tmp_path: Path) -> Path:
    path = tmp_path / "issue.md"
    path.write_text("add() subtracts\n\nadd(2, 3) returns -1.\nExpected 5.\n")
    return path


@pytest.fixture
def no_agent(monkeypatch: pytest.MonkeyPatch) -> list:
    """Fail the test if the agent starts; these tests must stop before that."""
    calls: list = []
    monkeypatch.setattr(cli, "run_agent", lambda *args, **kwargs: calls.append(args))
    return calls


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("fix", "eval", "build-sandbox"):
        assert command in result.output


def test_read_issue_file_splits_title_and_body(issue_file: Path) -> None:
    title, body = read_issue_file(issue_file)
    assert title == "add() subtracts"
    assert body == "add(2, 3) returns -1.\nExpected 5."


def test_dry_run_needs_openrouter_key_but_not_github_token(
    issue_file: Path, no_agent: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr(""))
    monkeypatch.setattr(settings, "github_token", SecretStr(""))
    args = ["fix", "--repo", ".", "--issue-file", str(issue_file), "--dry-run"]
    result = runner.invoke(app, args)
    assert result.exit_code == 1
    assert "OPENROUTER_API_KEY" in result.output
    assert "GITHUB_TOKEN" not in result.output
    assert no_agent == []


def test_real_run_needs_github_token(no_agent: list, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "openrouter_api_key", SecretStr("key"))
    monkeypatch.setattr(settings, "github_token", SecretStr(""))
    result = runner.invoke(app, ["fix", "--repo", "https://github.com/octo/demo", "--issue", "3"])
    assert result.exit_code == 1
    assert "GITHUB_TOKEN" in result.output
    assert no_agent == []


@pytest.mark.parametrize(
    ("args", "message"),
    [
        (["--repo", "."], "exactly one of --issue or --issue-file"),
        (["--repo", ".", "--issue", "3", "--issue-file", "x.md"], "exactly one of"),
        (["--repo", ".", "--issue", "3", "--dry-run"], "--issue needs a GitHub repository URL"),
        (["--repo", ".", "--issue-file", "x.md"], "A real run needs a GitHub URL and --issue"),
        (
            ["--repo", "https://github.com/octo/demo", "--issue-file", "x.md"],
            "A real run needs a GitHub URL and --issue",
        ),
    ],
)
def test_rejects_bad_argument_combinations(
    args: list[str], message: str, no_agent: list
) -> None:
    result = runner.invoke(app, ["fix", *args])
    assert result.exit_code == 1
    assert message in " ".join(result.output.split())
    assert no_agent == []
