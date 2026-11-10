"""CLI smoke tests."""

from typer.testing import CliRunner

from autopatch.cli import app

runner = CliRunner()


def test_help_lists_commands() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for command in ("fix", "eval", "build-sandbox"):
        assert command in result.output
