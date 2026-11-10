"""AutoPatch command line interface."""

from __future__ import annotations

import typer
from rich.console import Console

from . import sandbox

console = Console()

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
    """Build the Docker sandbox image used to run tests."""
    console.print("Building the sandbox image (first build downloads python:3.11-slim)...")
    try:
        tag = sandbox.build_image()
    except sandbox.SandboxError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(code=1) from exc
    console.print(f"[green]Built {tag}[/green]")
