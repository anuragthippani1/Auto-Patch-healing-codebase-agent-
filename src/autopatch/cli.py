"""AutoPatch command line interface."""

from __future__ import annotations

import typer

app = typer.Typer(
    name="autopatch",
    help="AutoPatch: reproduce a bug in a sandbox, fix it with an LLM, open a PR.",
    no_args_is_help=True,
    add_completion=False,
)


@app.command()
def fix() -> None:
    """Fix the bug described by an issue (implemented in M5)."""
    raise typer.Exit(code=1)


@app.command(name="eval")
def eval_cmd() -> None:
    """Run the evaluation suite in eval/run_eval.py (implemented in M7)."""
    raise typer.Exit(code=1)


@app.command(name="build-sandbox")
def build_sandbox() -> None:
    """Build the Docker sandbox image (implemented in M2)."""
    raise typer.Exit(code=1)
