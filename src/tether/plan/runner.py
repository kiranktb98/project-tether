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

    if cfg.watcher.provider == "anthropic" and not os.environ.get("ANTHROPIC_API_KEY"):
        console.print("[red]Error:[/red] ANTHROPIC_API_KEY is not set.")
        return

    ledger = load_ledger(cfg.ledger.path)
    if not ledger.features:
        console.print(
            "[yellow]Warning:[/yellow] No features in ledger. "
            "Run [cyan]tether bootstrap[/cyan] first."
        )

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

    # Summary
    console.print(f"\n[green]Plan written to[/green] [cyan]{notes_path}[/cyan]")
    console.print(
        f"  Affected features: [cyan]{len(result.affected_features)}[/cyan]  "
        f"Overall risk: [cyan]{result.overall_risk}[/cyan]  "
        f"Cost: [dim]${model.session_cost_usd:.4f}[/dim]"
    )

    if result.ask_user_required:
        console.print(
            "\n[yellow]STOP[/yellow] — plan contains medium/high risks. "
            "Read [cyan].tether/PLAN.md[/cyan] and ask the user before proceeding."
        )
    elif result.affected_features:
        console.print(
            f"\nRead [cyan].tether/PLAN.md[/cyan] for the full analysis."
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
