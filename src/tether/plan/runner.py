"""Plan runner — impact analysis + edge cases for a planned change."""

from __future__ import annotations

import os
from pathlib import Path

from rich.console import Console

from tether.config import load_config
from tether.ledger.store import load_ledger
from tether.plan.impact import run_impact_analysis
from tether.plan.edge_cases import generate_edge_cases
from tether.plan.notes import write_plan_notes
from tether.state.store import EventLog, ensure_tether_dir
from tether.state.manifest import SessionManifest
from tether.watcher_models import create_watcher_model

console = Console()


def run_plan(
    file_path: str,
    intent: str,
    config_path: str | None = None,
    verbose: bool = False,
) -> None:
    """Run impact analysis for a planned change. Writes .tether/PLAN.md."""
    cfg = load_config(config_path)
    tether_dir = ensure_tether_dir(".tether")

    from tether.env import check_provider_ready
    err = check_provider_ready(cfg.watcher.provider)
    if err:
        console.print(f"[red]Error:[/red] {err}")
        return

    # Validate the target path. Accept paths that don't yet exist (plan is
    # often used *before* creating a new file) but warn — a typo'd path
    # against a nonexistent file wastes a Haiku call for no impact analysis.
    target = Path(file_path)
    if not target.is_absolute():
        target = Path(cfg.project.root).resolve() / file_path
    if not target.exists():
        console.print(
            f"[yellow]Note:[/yellow] [cyan]{file_path}[/cyan] doesn't exist yet. "
            "Proceeding assuming this is a new file."
        )

    ledger = load_ledger(cfg.ledger.path)
    if not ledger.features:
        console.print(
            "[yellow]Warning:[/yellow] No features in ledger.\n"
            "  Run [cyan]tether bootstrap[/cyan] first so impact analysis "
            "has something to compare against."
        )
        return

    event_log = EventLog(tether_dir)
    manifest = SessionManifest.load(tether_dir) or SessionManifest(tether_dir)
    model = create_watcher_model(cfg, event_log=event_log, session_id=manifest.session_id)

    # Impact analysis
    console.print(f"[dim]Analyzing impact of change to [cyan]{file_path}[/cyan]...[/dim]")
    result = run_impact_analysis(
        file_path=file_path,
        intent=intent,
        ledger=ledger,
        model=model,
        ask_threshold=cfg.plan.ask_threshold,
    )

    # Edge case generation for new features
    new_feature_edge_cases = None
    if cfg.plan.edge_case_generation and _looks_like_new_feature(intent):
        console.print("[dim]Detected new feature intent — generating edge cases...[/dim]")
        # Create a temporary feature stub to generate edge cases against
        from tether.ledger.schema import Feature
        stub = Feature(
            id="_new",
            name=_extract_feature_name(intent),
            description=intent,
            files=[file_path],
        )
        try:
            new_feature_edge_cases = generate_edge_cases(
                stub,
                model,
                project_name=cfg.project.name,
                count=cfg.plan.edge_case_count,
            )
        except Exception as e:
            console.print(f"[yellow]Edge case generation skipped:[/yellow] {e}")

    # Write plan notes
    notes_path = write_plan_notes(
        result,
        cfg.worker.plan_notes_file,
        new_feature_edge_cases=new_feature_edge_cases,
    )

    # Summary — risk distribution + confidence
    console.print(f"\n[green]Plan written to[/green] [cyan]{notes_path}[/cyan]")
    _print_risk_distribution(result)
    console.print(f"  Cost: [dim]${model.session_cost_usd:.4f}[/dim]")

    if result.ask_user_required:
        console.print(
            "\n[bold yellow]STOP[/bold yellow] — plan contains medium/high risks. "
            "Read [cyan].tether/PLAN.md[/cyan] and ask the user before proceeding."
        )
    elif result.affected_features:
        console.print(f"\nRead [cyan].tether/PLAN.md[/cyan] for the full analysis.")


def _print_risk_distribution(result) -> None:
    """Print a visual risk-spread bar chart + confidence indicator."""
    from rich.text import Text

    n = len(result.risks)
    if n == 0:
        console.print(
            f"\n  [dim]No features touch [cyan]{result.file_path}[/cyan] — "
            "no impact detected.[/dim]"
        )
        return

    dist = result.risk_distribution
    max_count = max(dist.values()) or 1
    bar_width = 20

    _FULL = "█"
    _EMPTY = "░"

    _RISK_COLORS = {"none": "dim", "low": "green", "medium": "yellow", "high": "red"}
    _RISK_LABELS = {
        "none":   "  none  ",
        "low":    "  low   ",
        "medium": " medium ",
        "high":   "  high  ",
    }
    _THRESHOLD_LABELS = {"medium": " ← ask threshold", "high": " ← STOP"}

    console.print(f"\n  [bold]Risk spread[/bold]  [dim]({n} feature{'s' if n != 1 else ''} analyzed)[/dim]")

    for level in ("none", "low", "medium", "high"):
        count = dist[level]
        color = _RISK_COLORS[level]
        filled = round(bar_width * count / max_count) if count else 0
        bar = _FULL * filled + _EMPTY * (bar_width - filled)

        t = Text()
        t.append(f"  {_RISK_LABELS[level]} ", style=f"bold {color}")
        t.append(bar, style=color)
        t.append(f"  {count}", style=f"bold {color}")
        if level in _THRESHOLD_LABELS and count > 0:
            t.append(_THRESHOLD_LABELS[level], style="dim italic")
        console.print(t)

    # Confidence row
    confidence = result.confidence
    conf_color = {"high": "green", "medium": "yellow", "low": "red"}[confidence]
    conf_desc = {
        "high":   "risks clustered — prediction is reliable",
        "medium": "moderate spread — treat with care",
        "low":    "high variance — Haiku is uncertain, review PLAN.md carefully",
    }[confidence]
    console.print(
        f"\n  Confidence: [bold {conf_color}]{confidence}[/bold {conf_color}]"
        f"  [dim]{conf_desc}[/dim]"
    )


def _looks_like_new_feature(intent: str) -> bool:
    """Heuristic: does the intent describe adding a new feature?"""
    lower = intent.lower()
    new_feature_signals = [
        "add ", "implement ", "create ", "build ", "introduce ",
        "new feature", "adding", "implementing",
    ]
    return any(s in lower for s in new_feature_signals)


def _extract_feature_name(intent: str) -> str:
    """Extract a short feature name from an intent description."""
    # Take first ~6 words
    words = intent.split()
    return " ".join(words[:6]) if len(words) > 6 else intent
