"""State display — session status and report generation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console
from rich.table import Table

from tether.config import load_config
from tether.ledger.store import load_ledger
from tether.state.manifest import SessionManifest
from tether.state.store import EventLog, ensure_tether_dir

console = Console()


def show_status(config_path: str | None = None) -> None:
    """Show current session status."""
    cfg = load_config(config_path)
    tether_dir = Path(".tether")

    manifest = SessionManifest.load(tether_dir)
    if manifest is None:
        console.print(
            "[yellow]No active session.[/yellow] "
            "Run [cyan]tether watch[/cyan] to start one."
        )
        return

    ledger = load_ledger(cfg.ledger.path)
    event_log = EventLog(tether_dir)
    session_cost = event_log.session_cost_usd(manifest.session_id)

    table = Table(title="Tether Session Status", show_header=False)
    table.add_column("Key", style="dim")
    table.add_column("Value")

    table.add_row("Session ID", manifest.session_id)
    table.add_row("Ledger version", f"v{ledger.version}")
    table.add_row("Features", str(len(ledger.features)))
    table.add_row("Files changed", str(manifest.files_changed))
    table.add_row("Checks run", str(manifest.checks_run))
    table.add_row("Session cost", f"${session_cost:.4f}")

    drift = manifest.drift_events
    drift_str = ", ".join(f"{k}={v}" for k, v in drift.items() if v > 0) or "none"
    table.add_row("Drift events", drift_str)

    console.print(table)


def generate_report(config_path: str | None = None) -> None:
    """Print the most recent session report or generate a new one."""
    tether_dir = Path(".tether")
    reports_dir = tether_dir / "reports"

    if not reports_dir.exists():
        console.print("[yellow]No reports directory found.[/yellow] Run [cyan]tether verify[/cyan] to generate one.")
        return

    report_files = sorted(reports_dir.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not report_files:
        console.print("[yellow]No reports found.[/yellow] Run [cyan]tether verify[/cyan] to generate one.")
        return

    latest = report_files[0]
    content = latest.read_text(encoding="utf-8")
    console.print(content)
    console.print(f"\n[dim]Report: {latest}[/dim]")
