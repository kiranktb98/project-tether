"""Tether CLI — top-level command group and all sub-commands."""

import sys

import click
from rich.console import Console

from tether.env import load_project_env
from tether import __version__

# Ensure stdout/stderr accept Unicode on Windows. This must happen before any
# output is written.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

console = Console()

load_project_env()


@click.group()
@click.version_option(version=__version__)
@click.option("--config", "config_path", default=None, metavar="PATH",
              help="Path to tether config file (default: .tether/config.yaml).")
@click.option("--verbose", is_flag=True, default=False, help="Enable verbose output.")
@click.option("--quiet", is_flag=True, default=False, help="Suppress non-essential output.")
@click.pass_context
def cli(ctx: click.Context, config_path: str | None, verbose: bool, quiet: bool) -> None:
    """Tether — impact-analysis and edge-case engine for coding agents.

    Stops Claude Code from accidentally breaking feature B while fixing feature A.
    """
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config_path
    ctx.obj["verbose"] = verbose
    ctx.obj["quiet"] = quiet


@cli.command()
@click.pass_context
def init(ctx: click.Context) -> None:
    """Interactive setup: create .tether/, write config.yaml, update CLAUDE.md."""
    from tether.config import run_init
    run_init(
        config_path=ctx.obj["config_path"],
        verbose=ctx.obj["verbose"],
    )


@cli.command()
@click.option("--yes", "-y", is_flag=True, default=False,
              help="Auto-accept Haiku's feature proposals without opening an editor.")
@click.pass_context
def bootstrap(ctx: click.Context, yes: bool) -> None:
    """Scan codebase, propose initial feature ledger, generate edge cases and tests."""
    from tether.bootstrap.runner import run_bootstrap
    run_bootstrap(
        config_path=ctx.obj["config_path"],
        verbose=ctx.obj["verbose"],
        yes=yes,
    )


@cli.command()
@click.argument("file_path")
@click.option("--intent", required=True, metavar="DESCRIPTION",
              help="Short description of the planned change.")
@click.pass_context
def plan(ctx: click.Context, file_path: str, intent: str) -> None:
    """Run impact analysis for a planned change. Writes .tether/PLAN.md."""
    from tether.plan.runner import run_plan
    run_plan(
        file_path=file_path,
        intent=intent,
        config_path=ctx.obj["config_path"],
        verbose=ctx.obj["verbose"],
    )


@cli.command()
@click.pass_context
def watch(ctx: click.Context) -> None:
    """Start the file watcher. Runs targeted tests and intent checks on every change."""
    from tether.watch.runner import run_watch
    run_watch(
        config_path=ctx.obj["config_path"],
        verbose=ctx.obj["verbose"],
    )


@cli.command()
@click.pass_context
def verify(ctx: click.Context) -> None:
    """Post-change validation: re-run affected tests, update ledger, write session summary."""
    from tether.verify.verifier import run_verify
    ok = run_verify(
        config_path=ctx.obj["config_path"],
        verbose=ctx.obj["verbose"],
    )
    if not ok:
        raise click.exceptions.Exit(1)


@cli.command("ledger")
@click.pass_context
def show_ledger(ctx: click.Context) -> None:
    """Display the current feature ledger as a rich table."""
    from tether.ledger.display import show_ledger_table
    show_ledger_table(config_path=ctx.obj["config_path"])


@cli.command("log")
@click.argument("feature_id", required=False, default=None)
@click.pass_context
def show_log(ctx: click.Context, feature_id: str | None) -> None:
    """Show history of all features, or a single feature if FEATURE_ID is given."""
    from tether.ledger.display import show_feature_log
    show_feature_log(feature_id=feature_id, config_path=ctx.obj["config_path"])


@cli.command()
@click.pass_context
def status(ctx: click.Context) -> None:
    """Show current session status: files watched, checks run, cost, ledger version."""
    from tether.state.display import show_status
    show_status(config_path=ctx.obj["config_path"])


@cli.command()
@click.pass_context
def report(ctx: click.Context) -> None:
    """Generate a markdown report for the most recent session."""
    from tether.state.display import generate_report
    generate_report(config_path=ctx.obj["config_path"])


@cli.command()
@click.pass_context
def coverage(ctx: click.Context) -> None:
    """Show the edge-case bell curve and must-handle test coverage per feature."""
    from tether.coverage.display import show_coverage
    show_coverage(config_path=ctx.obj["config_path"])


@cli.command()
@click.argument("question")
@click.pass_context
def ask(ctx: click.Context, question: str) -> None:
    """Ask a natural-language question about your project's feature ledger.

    Examples:\n
      tether ask "what features use auth.py?"\n
      tether ask "which features break if I change the rate limiter?"\n
      tether ask "what are the must-handle edge cases for f2?"
    """
    from tether.ask import run_ask
    run_ask(
        question=question,
        config_path=ctx.obj["config_path"],
        verbose=ctx.obj["verbose"],
    )
