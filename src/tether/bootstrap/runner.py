"""Bootstrap runner — orchestrates the full bootstrap flow."""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Generator

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from tether.config import load_config
from tether.bootstrap.scanner import scan_project
from tether.bootstrap.proposer import propose_features
from tether.bootstrap.reviewer import run_review_flow
from tether.ledger.schema import Feature
from tether.ledger.store import load_ledger, save_ledger
from tether.plan.edge_cases import generate_edge_cases
from tether.plan.test_gen import generate_test_for_edge_case
from tether.state.store import EventLog, ensure_tether_dir
from tether.state.manifest import SessionManifest
from tether.watcher_models import create_watcher_model

console = Console()

_LOCK_FILENAME = "bootstrap.lock"


@contextmanager
def _bootstrap_lock(tether_dir: Path) -> Generator[None, None, None]:
    """Prevent concurrent bootstrap runs via a simple lock file."""
    lock_path = tether_dir / _LOCK_FILENAME
    if lock_path.exists():
        # Check if the PID in the lock is still alive
        try:
            stored_pid = int(lock_path.read_text().strip())
            # On Windows/Unix, sending signal 0 checks if the process exists
            os.kill(stored_pid, 0)
            # Process is still alive
            console.print(
                f"[red]Error:[/red] Another bootstrap is already running (PID {stored_pid}).\n"
                f"If that process has died, delete [cyan]{lock_path}[/cyan] and try again."
            )
            raise SystemExit(1)
        except (ValueError, ProcessLookupError, PermissionError):
            # PID is invalid or process is gone — stale lock, remove it
            lock_path.unlink(missing_ok=True)

    lock_path.write_text(str(os.getpid()))
    try:
        yield
    finally:
        lock_path.unlink(missing_ok=True)


def run_bootstrap(config_path: str | None = None, verbose: bool = False, yes: bool = False) -> None:
    """Full bootstrap flow:

    1. Static scan
    2. Feature proposal (Haiku)
    3. User review (editor)
    4. Edge case backfill (Haiku, per feature)
    5. Test generation (Haiku, per must_handle edge case)
    """
    cfg = load_config(config_path)
    tether_dir = ensure_tether_dir(".tether")

    with _bootstrap_lock(tether_dir):
        _run_bootstrap_inner(cfg, tether_dir, verbose=verbose, yes=yes)


def _run_bootstrap_inner(cfg, tether_dir: Path, *, verbose: bool, yes: bool) -> None:
    """Inner bootstrap logic — called after the lock is held."""
    from tether.env import check_provider_ready
    err = check_provider_ready(cfg.watcher.provider)
    if err:
        console.print(f"[red]Error:[/red] {err}")
        return

    event_log = EventLog(tether_dir)
    manifest = SessionManifest(tether_dir)
    model = create_watcher_model(cfg, event_log=event_log, session_id=manifest.session_id)

    # -------------------------------------------------------------------------
    # Step 1: Static scan
    # -------------------------------------------------------------------------
    console.print("\n[bold cyan]tether bootstrap[/bold cyan]\n")
    console.print("[dim]Step 1/4 — Scanning codebase...[/dim]")

    project_root = Path(cfg.project.root).resolve()
    scan = scan_project(
        project_root,
        ignore_dirs=set(cfg.scan.exclude_dirs) if cfg.scan.exclude_dirs else None,
    )
    console.print(f"  Found [cyan]{len(scan.files)}[/cyan] Python files.")

    if not scan.files:
        console.print(
            "[yellow]No Python files found in the project root.[/yellow] "
            "Is this a Python project?"
        )
        return

    # -------------------------------------------------------------------------
    # Step 2: Feature proposal
    # -------------------------------------------------------------------------
    console.print("[dim]Step 2/4 — Proposing features (Haiku)...[/dim]")

    try:
        proposals = propose_features(scan, model)
    except Exception as e:
        console.print(f"[red]Feature proposal failed:[/red] {e}")
        return

    console.print(
        f"  Haiku proposed [cyan]{len(proposals)}[/cyan] features. "
        f"Cost so far: [dim]${model.session_cost_usd:.4f}[/dim]"
    )

    # -------------------------------------------------------------------------
    # Step 3: User review
    # -------------------------------------------------------------------------
    console.print("[dim]Step 3/4 — User review...[/dim]")

    ledger = run_review_flow(
        proposals,
        ledger_path=cfg.ledger.path,
        history_dir=cfg.ledger.history_dir,
        yes=yes,
    )
    manifest.ledger_version_start = ledger.version

    # -------------------------------------------------------------------------
    # Step 4: Edge case backfill + test generation
    # -------------------------------------------------------------------------
    # Resume semantics: a feature that already has edge cases is assumed to
    # have been through this step on a previous run. Skip it so re-running
    # bootstrap after an interruption doesn't double the edge case list or
    # burn a Haiku call per existing feature.
    needs_edge_cases = [f for f in ledger.features if not f.edge_cases]
    skipped = len(ledger.features) - len(needs_edge_cases)

    if skipped:
        console.print(
            f"[dim]Step 4/4 — Generating edge cases and tests "
            f"({skipped} feature{'s' if skipped != 1 else ''} already have edge cases, skipping)...[/dim]"
        )
    else:
        console.print(f"[dim]Step 4/4 — Generating edge cases and tests...[/dim]")

    errors: list[str] = []

    if needs_edge_cases:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console,
            transient=True,
        ) as progress:
            task = progress.add_task("Generating...", total=len(needs_edge_cases))

            for feature in needs_edge_cases:
                progress.update(task, description=f"Feature {feature.id}: {feature.name[:40]}")

                try:
                    edge_cases = generate_edge_cases(
                        feature,
                        model,
                        project_name=cfg.project.name,
                        count=cfg.plan.edge_case_count,
                    )
                except Exception as e:
                    errors.append(f"{feature.id}: edge case generation failed: {e}")
                    progress.advance(task)
                    continue

                feature.edge_cases.extend(edge_cases)

                # Generate tests for must_handle edge cases only
                for ec in edge_cases:
                    if not ec.must_handle:
                        continue
                    try:
                        generate_test_for_edge_case(
                            feature,
                            ec,
                            model,
                            tests_base_dir=cfg.ledger.tests_dir,
                            project_root=project_root,
                        )
                    except Exception as e:
                        errors.append(f"{feature.id}/{ec.id}: test generation failed: {e}")

                # Persist progress after each feature so interrupted bootstraps
                # still leave behind usable edge case and test metadata.
                save_ledger(
                    ledger,
                    cfg.ledger.path,
                    history_dir=cfg.ledger.history_dir,
                    snapshot=False,
                )
                progress.advance(task)

    # Save a final snapshot once the whole bootstrap run completes.
    save_ledger(ledger, cfg.ledger.path, history_dir=cfg.ledger.history_dir, snapshot=True)
    manifest.ledger_version_end = ledger.version
    manifest.save()

    # -------------------------------------------------------------------------
    # Summary
    # -------------------------------------------------------------------------
    total_must_handle = sum(
        sum(1 for ec in f.edge_cases if ec.must_handle)
        for f in ledger.features
    )
    total_tests = sum(
        sum(1 for ec in f.edge_cases if ec.test_file)
        for f in ledger.features
    )

    console.print(f"\n[green]Bootstrap complete.[/green]")
    console.print(f"  Features:      [cyan]{len(ledger.features)}[/cyan]")
    console.print(f"  Edge cases:    [cyan]{sum(len(f.edge_cases) for f in ledger.features)}[/cyan] "
                  f"([cyan]{total_must_handle}[/cyan] must_handle)")
    console.print(f"  Tests written: [cyan]{total_tests}[/cyan]")
    console.print(f"  Session cost:  [dim]${model.session_cost_usd:.4f}[/dim]")
    console.print(f"  Ledger:        [cyan]{cfg.ledger.path}[/cyan] (v{ledger.version})")

    if errors:
        console.print(f"\n[yellow]Warnings ({len(errors)}):[/yellow]")
        for err in errors[:5]:
            console.print(f"  [yellow]*[/yellow] {err}")
        if len(errors) > 5:
            console.print(f"  ... and {len(errors) - 5} more")

    console.print(
        f"\nRun [cyan]tether watch[/cyan] in one terminal and "
        f"[cyan]claude[/cyan] in another to get started.\n"
    )
