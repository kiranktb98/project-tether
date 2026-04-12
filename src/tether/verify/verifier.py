"""Verify runner - post-change validation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from rich.console import Console

from tether.config import load_config
from tether.ledger.queries import compute_feature_edge_case_stats, feature_has_generated_tests
from tether.ledger.store import load_ledger, save_ledger, validate_ledger_file
from tether.state.manifest import SessionManifest
from tether.state.store import ensure_tether_dir
from tether.watch.checks.targeted_tests import TestRunResult, run_single_test_file
from tether.whisper.notes_writer import clear_drift_notes

console = Console()


def run_verify(config_path: str | None = None, verbose: bool = False) -> bool:
    """Post-change validation.

    1. Re-run all generated feature tests.
    2. Compute per-feature edge-case stats.
    3. Gate session completion on high-confidence must-handle edge cases.
    4. Update building -> active where appropriate.
    5. Write a session summary report and snapshot the ledger.
    """
    cfg = load_config(config_path)
    tether_dir = ensure_tether_dir(".tether")

    console.print("\n[bold cyan]tether verify[/bold cyan]\n")

    errors = validate_ledger_file(cfg.ledger.path)
    if errors:
        for err in errors:
            console.print(f"[red]Ledger error:[/red] {err}")
        return False

    ledger = load_ledger(cfg.ledger.path)

    console.print("[dim]Running feature tests...[/dim]")
    all_results: list[TestRunResult] = []
    gated_edge_case_failures: list[tuple[str, str, TestRunResult | None]] = []
    features_with_tests = [
        f for f in ledger.features
        if feature_has_generated_tests(f, cfg.ledger.tests_dir)
    ]

    from tether.ledger.queries import feature_tests_dir
    from tether.watch.checks.targeted_tests import _run_pytest_for_feature

    for feature in features_with_tests:
        feature.edge_case_stats = compute_feature_edge_case_stats(
            feature,
            confidence_gate=cfg.verify.confidence_gate_threshold,
        )

        test_dir = feature_tests_dir(feature, cfg.ledger.tests_dir)
        if not test_dir.exists():
            continue

        result = _run_pytest_for_feature(
            feature, test_dir, cfg.verify.max_test_runtime_seconds
        )
        all_results.append(result)

        status_icon = "[green]PASS[/green]" if result.ok else "[red]FAIL[/red]"
        console.print(
            f"  {status_icon} {feature.id}: {feature.name[:40]}  "
            f"({result.passed}p/{result.failed}f/{result.errors}e/{result.skipped}s)"
        )
        if not result.ok and verbose:
            console.print(f"[dim]{result.output[:500]}[/dim]")

        if cfg.verify.require_confident_must_handle_tests:
            for edge_case in feature.edge_cases:
                if not edge_case.must_handle or edge_case.confidence < cfg.verify.confidence_gate_threshold:
                    continue

                if not edge_case.test_file:
                    gated_edge_case_failures.append((feature.id, edge_case.description, None))
                    continue

                edge_case_result = run_single_test_file(
                    feature,
                    edge_case.test_file,
                    cfg.verify.max_test_runtime_seconds,
                )
                if not edge_case_result.ok or edge_case_result.skipped:
                    gated_edge_case_failures.append((feature.id, edge_case.description, edge_case_result))

    if gated_edge_case_failures:
        console.print("\n[red]Confident must-handle edge cases are still failing or missing.[/red]")
        for feature_id, description, result in gated_edge_case_failures[:10]:
            if result is None:
                console.print(f"  [red]*[/red] {feature_id}: {description} (missing generated test)")
            else:
                console.print(
                    f"  [red]*[/red] {feature_id}: {description} "
                    f"({result.passed}p/{result.failed}f/{result.errors}e/{result.skipped}s)"
                )

    promoted = 0
    from tether.ledger.schema import FeatureStatus
    for feature in ledger.features:
        if feature.status != FeatureStatus.building:
            continue

        feature_results = [r for r in all_results if r.feature_id == feature.id]
        blocked_by_gate = any(fid == feature.id for fid, _, _ in gated_edge_case_failures)
        if all(r.ok for r in feature_results) and not blocked_by_gate:
            feature.status = FeatureStatus.active
            feature.add_history("modified", "Auto-promoted building -> active by tether verify")
            promoted += 1

    save_ledger(ledger, cfg.ledger.path, history_dir=cfg.ledger.history_dir, snapshot=True)
    console.print(
        f"\n[green]OK[/green] Ledger saved (v{ledger.version})"
        + (f", {promoted} features promoted to active" if promoted else "")
    )

    all_ok = all(r.ok for r in all_results) and not gated_edge_case_failures
    if all_ok:
        clear_drift_notes(cfg.worker.drift_notes_file)
        console.print("[green]OK[/green] Drift notes cleared - all tests pass.")

    report_path = _write_session_report(
        test_results=all_results,
        ledger=ledger,
        promoted=promoted,
        tether_dir=tether_dir,
        gated_edge_case_failures=gated_edge_case_failures,
    )
    console.print(f"[green]OK[/green] Report written to [cyan]{report_path}[/cyan]")

    total_pass = sum(r.passed for r in all_results)
    total_fail = sum(r.failed + r.errors for r in all_results)
    console.print(
        f"\nVerify complete: "
        f"[green]{total_pass}[/green] passed, [red]{total_fail}[/red] failed "
        f"across {len(all_results)} features.\n"
    )
    return all_ok


def _write_session_report(
    *,
    test_results: list[TestRunResult],
    ledger,
    promoted: int,
    tether_dir: Path,
    gated_edge_case_failures: list[tuple[str, str, TestRunResult | None]],
) -> Path:
    """Write a markdown session summary to .tether/reports/<run_id>.md."""
    reports_dir = tether_dir / "reports"
    reports_dir.mkdir(exist_ok=True)

    manifest = SessionManifest.load(tether_dir)
    run_id = manifest.session_id if manifest else "unknown"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    lines = [
        f"# Tether Verify Report - {ts}",
        "",
        f"**Session:** `{run_id}`  "
        f"**Ledger version:** v{ledger.version}  "
        f"**Features:** {len(ledger.features)}",
        "",
        "## Test results",
        "",
    ]

    for result in test_results:
        status = "PASS" if result.ok else "FAIL"
        lines.append(
            f"| {result.feature_id} | {result.feature_name} | {status} | "
            f"{result.passed}p {result.failed}f {result.errors}e {result.skipped}s |"
        )

    if not test_results:
        lines.append("No tests found. Run `tether bootstrap` to generate tests.")

    lines += [
        "",
        "## Edge case statistics",
        "",
        "| Feature | Total | Must handle | Gated | Avg confidence |",
    ]
    for feature in ledger.features:
        stats = feature.edge_case_stats
        if not stats.total:
            continue
        lines.append(
            f"| {feature.id} | {stats.total} | {stats.must_handle} | {stats.gated} | {stats.average_confidence:.2f} |"
        )

    if gated_edge_case_failures:
        lines += [
            "",
            "## Confident must-handle edge cases still blocking session completion",
            "",
        ]
        for feature_id, description, result in gated_edge_case_failures:
            if result is None:
                lines.append(f"- {feature_id}: {description} (missing generated test)")
            else:
                lines.append(
                    f"- {feature_id}: {description} "
                    f"({result.passed}p {result.failed}f {result.errors}e {result.skipped}s)"
                )

    if promoted:
        lines += [
            "",
            "## Status changes",
            "",
            f"- {promoted} features promoted from `building` to `active`.",
        ]

    if manifest:
        lines += [
            "",
            "## Session stats",
            "",
            f"- Files changed: {manifest.files_changed}",
            f"- Checks run: {manifest.checks_run}",
            f"- Session cost: ${manifest.total_cost_usd:.4f}",
        ]

    report_path = reports_dir / f"{run_id}.md"
    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path
