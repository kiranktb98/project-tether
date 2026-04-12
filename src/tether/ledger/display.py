"""Ledger display — rich table views."""

from __future__ import annotations

from rich.console import Console
from rich.table import Table
from rich.text import Text

from tether.config import load_config
from tether.ledger.store import load_ledger

console = Console()

_STATUS_COLORS = {
    "active": "green",
    "building": "yellow",
    "removing": "red",
    "deprecated": "dim",
}


def show_ledger_table(config_path: str | None = None) -> None:
    """Display all features in a rich table."""
    cfg = load_config(config_path)
    ledger = load_ledger(cfg.ledger.path)

    if not ledger.features:
        console.print(
            "[yellow]Ledger is empty.[/yellow] Run [cyan]tether bootstrap[/cyan] to populate it."
        )
        return

    table = Table(title=f"Feature Ledger (v{ledger.version})", show_header=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Name")
    table.add_column("Status", no_wrap=True)
    table.add_column("Files", no_wrap=False)
    table.add_column("Edge Cases", no_wrap=True)

    for f in ledger.features:
        status_color = _STATUS_COLORS.get(f.status.value, "white")
        must_handle = sum(1 for ec in f.edge_cases if ec.must_handle)
        ec_text = f"{len(f.edge_cases)} ({must_handle} must_handle)"

        table.add_row(
            f.id,
            f.name,
            Text(f.status.value, style=status_color),
            "\n".join(f.files) if f.files else "(none)",
            ec_text,
        )

    console.print(table)
    console.print(
        f"\n[dim]Last updated: {ledger.last_updated.strftime('%Y-%m-%d %H:%M UTC')}[/dim]"
    )


def show_feature_log(feature_id: str | None = None, config_path: str | None = None) -> None:
    """Show the history of all features, or one specific feature."""
    cfg = load_config(config_path)
    ledger = load_ledger(cfg.ledger.path)

    if not ledger.features:
        console.print("[yellow]Ledger is empty.[/yellow]")
        return

    features = (
        [f for f in ledger.features if f.id == feature_id]
        if feature_id
        else ledger.features
    )

    if feature_id and not features:
        console.print(f"[red]Feature '{feature_id}' not found in ledger.[/red]")
        return

    for feature in features:
        console.print(f"\n[bold cyan]{feature.id}[/bold cyan]: {feature.name}")
        console.print(f"  Status: {feature.status.value}  |  Files: {', '.join(feature.files) or '(none)'}")
        if feature.description:
            console.print(f"  {feature.description}")

        if feature.history:
            table = Table(show_header=True, box=None, padding=(0, 1))
            table.add_column("Action", style="dim")
            table.add_column("At", style="dim")
            table.add_column("Reason")
            for h in feature.history:
                table.add_row(
                    h.action,
                    h.at.strftime("%Y-%m-%d %H:%M"),
                    h.reason or "(no reason)",
                )
            console.print(table)
        else:
            console.print("  [dim](no history)[/dim]")
