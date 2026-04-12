"""Drift notes writer — formats and upserts drift notes into DRIFT.md."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from tether.watch.checks.targeted_tests import TestRunResult
from tether.watch.checks.intent import IntentResult
from tether.watch.checks.invariants import InvariantResult, InvariantViolation

DriftSeverity = Literal["none", "soft", "intentional", "hard", "critical"]

_MARKER_START = "<!-- TETHER:DRIFT START -->"
_MARKER_END = "<!-- TETHER:DRIFT END -->"

_POINTER_MARKER_START = "<!-- TETHER:DRIFT POINTER START -->"
_POINTER_MARKER_END = "<!-- TETHER:DRIFT POINTER END -->"


@dataclass
class DriftNote:
    severity: DriftSeverity
    file_path: str
    intent_result: IntentResult | None = None
    test_results: list[TestRunResult] = field(default_factory=list)
    invariant_result: InvariantResult | None = None
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


def compute_severity(
    intent_result: IntentResult | None,
    test_results: list[TestRunResult],
    invariant_result: InvariantResult | None,
) -> DriftSeverity:
    """Combine the three check outputs into a single severity level."""
    has_failing_tests = any(not r.ok for r in test_results)
    newly_failing = any(r.newly_failing for r in test_results)
    num_failing_features = sum(1 for r in test_results if not r.ok)
    intent_verdict = intent_result.verdict if intent_result else "neutral"
    has_invariant_violations = invariant_result is not None and not invariant_result.ok

    if not has_failing_tests and intent_verdict in ("aligned", "neutral") and not has_invariant_violations:
        return "none"

    if num_failing_features >= 2:
        return "critical"

    if has_failing_tests or has_invariant_violations:
        if intent_verdict == "looks_intentional":
            return "intentional"
        return "hard"

    if intent_verdict == "drifted":
        return "soft"

    return "none"


def write_drift_notes(
    note: DriftNote,
    drift_notes_file: str | Path,
    claude_md_file: str | Path | None = None,
) -> Path:
    """Write the drift note to DRIFT.md and optionally add a pointer to CLAUDE.md."""
    path = Path(drift_notes_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    content = _render_drift_md(note)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        start = existing.find(_MARKER_START)
        end = existing.find(_MARKER_END)
        if start != -1 and end != -1:
            before = existing[:start]
            after = existing[end + len(_MARKER_END):]
            final = before + content + after
        else:
            final = content + "\n\n" + existing
    else:
        final = content

    path.write_text(final, encoding="utf-8")

    # Update the one-line pointer in CLAUDE.md
    if claude_md_file and note.severity != "none":
        _upsert_claude_md_pointer(claude_md_file, drift_notes_file)

    return path


def clear_drift_notes(drift_notes_file: str | Path) -> None:
    """Clear drift notes (used after tether verify succeeds)."""
    path = Path(drift_notes_file)
    if not path.exists():
        return
    existing = path.read_text(encoding="utf-8")
    start = existing.find(_MARKER_START)
    end = existing.find(_MARKER_END)
    if start != -1 and end != -1:
        before = existing[:start]
        after = existing[end + len(_MARKER_END):]
        cleared = (
            _MARKER_START + "\n"
            "# Tether drift log — no current drift\n"
            + _MARKER_END
        )
        path.write_text(before + cleared + after, encoding="utf-8")


def _render_drift_md(note: DriftNote) -> str:
    ts = note.timestamp.strftime("%Y-%m-%d %H:%M:%S UTC")
    severity_header = {
        "none": "No current drift",
        "soft": "Soft drift detected",
        "intentional": "Intentional-looking change (update ledger?)",
        "hard": "Tests broken",
        "critical": "Critical — multiple features broken",
    }.get(note.severity, note.severity)

    lines = [
        _MARKER_START,
        f"# Tether Drift Log — {ts}",
        f"**Severity:** {note.severity.upper()}  **File:** `{note.file_path}`",
        "",
    ]

    if note.severity == "none":
        lines += ["All checks pass. No drift detected.", "", _MARKER_END]
        return "\n".join(lines)

    # Intent check result
    if note.intent_result and note.intent_result.verdict not in ("aligned", "neutral"):
        lines += [
            f"## Intent check: {note.intent_result.verdict}",
            note.intent_result.reason,
            "",
        ]

    # Failing tests
    failing = [r for r in note.test_results if not r.ok]
    if failing:
        lines += ["## Failing tests", ""]
        for r in failing:
            lines.append(f"**Feature {r.feature_id} ({r.feature_name})** — "
                         f"{r.failed} failed, {r.errors} errors")
            for tf in r.newly_failing:
                lines.append(f"  - `{tf}`")
            lines.append("")

    # Invariant violations
    if note.invariant_result and not note.invariant_result.ok:
        lines += ["## Static invariant violations", ""]
        for v in note.invariant_result.violations:
            lines.append(f"- **{v.kind}**: {v.detail}")
        lines.append("")

    # Suggested action
    if note.severity == "intentional":
        lines += [
            "## Suggested action",
            "This change looks deliberate. If you are removing or replacing a feature, "
            "edit `.tether/ledger.yaml` to mark it `removing` or `deprecated`.",
            "",
        ]
    elif note.severity in ("hard", "critical"):
        lines += [
            "## Suggested action",
            "Fix the failing tests, or if this was intentional, "
            "update the ledger to reflect the new reality.",
            "",
        ]

    lines.append(_MARKER_END)
    return "\n".join(lines)


def _upsert_claude_md_pointer(
    claude_md_file: str | Path,
    drift_notes_file: str | Path,
) -> None:
    """Write a one-line pointer to DRIFT.md in CLAUDE.md."""
    path = Path(claude_md_file)
    pointer = (
        f"{_POINTER_MARKER_START}\n"
        f"> **Tether drift alert** — see `{drift_notes_file}` for details.\n"
        f"{_POINTER_MARKER_END}"
    )

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        start = existing.find(_POINTER_MARKER_START)
        end = existing.find(_POINTER_MARKER_END)
        if start != -1 and end != -1:
            before = existing[:start]
            after = existing[end + len(_POINTER_MARKER_END):]
            path.write_text(before + pointer + after, encoding="utf-8")
        else:
            # Prepend to existing content
            path.write_text(pointer + "\n\n" + existing, encoding="utf-8")
    else:
        path.write_text(pointer + "\n", encoding="utf-8")
