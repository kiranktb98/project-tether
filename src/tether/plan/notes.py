"""Plan Phase: write structured analysis to .tether/PLAN.md."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from tether.plan.impact import ImpactResult
from tether.ledger.schema import EdgeCase

_MARKER_START = "<!-- TETHER:PLAN START -->"
_MARKER_END = "<!-- TETHER:PLAN END -->"


def write_plan_notes(
    result: ImpactResult,
    plan_notes_file: str | Path,
    *,
    new_feature_edge_cases: list[EdgeCase] | None = None,
) -> Path:
    """Format the impact analysis (and optional edge cases) and write PLAN.md.

    Uses marker-based upsert so repeated calls replace the previous content.
    Returns the path written.
    """
    path = Path(plan_notes_file)
    path.parent.mkdir(parents=True, exist_ok=True)

    content = _render_plan_md(result, new_feature_edge_cases)

    if path.exists():
        existing = path.read_text(encoding="utf-8")
        start_idx = existing.find(_MARKER_START)
        end_idx = existing.find(_MARKER_END)
        if start_idx != -1 and end_idx != -1:
            before = existing[:start_idx]
            after = existing[end_idx + len(_MARKER_END):]
            final = before + content + after
        else:
            final = content + "\n\n" + existing
    else:
        final = content

    path.write_text(final, encoding="utf-8")
    return path


def _render_plan_md(
    result: ImpactResult,
    edge_cases: list[EdgeCase] | None,
) -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    lines = [
        _MARKER_START,
        f"# Tether Plan — {ts}",
        "",
        f"**Planned change:** {result.intent}",
        f"**Affected file:** `{result.file_path}`",
        "",
    ]

    if not result.affected_features:
        lines += [
            "No features in the ledger touch this file. Proceeding is safe.",
            "",
            _MARKER_END,
        ]
        return "\n".join(lines)

    # -------------------------------------------------------------------------
    # STOP header if ask_user_required
    # -------------------------------------------------------------------------
    if result.ask_user_required:
        lines += [
            "## STOP — Ask user about these risks before proceeding",
            "",
        ]
    else:
        lines += [
            f"## Impact analysis (overall risk: **{result.overall_risk}**)",
            "",
        ]

    # -------------------------------------------------------------------------
    # Per-feature risks
    # -------------------------------------------------------------------------
    for risk in result.risks:
        if risk.level == "none":
            continue
        icon = {"low": "INFO", "medium": "WARNING", "high": "HIGH RISK"}.get(
            risk.level, risk.level.upper()
        )
        lines += [
            f"### {icon}: {risk.feature_id} ({risk.feature_name})",
            risk.reason,
            "",
        ]
        if risk.mitigation:
            lines += [f"**Mitigation:** {risk.mitigation}", ""]

    # Low-risk features (advisory, no stop)
    low_risks = [r for r in result.risks if r.level == "low"]
    if low_risks and not result.ask_user_required:
        lines += ["---", ""]
        for risk in low_risks:
            lines += [
                f"- **Low risk: {risk.feature_id} ({risk.feature_name})** — {risk.reason}",
            ]
        lines.append("")

    # -------------------------------------------------------------------------
    # Decision required section
    # -------------------------------------------------------------------------
    if result.ask_user_required:
        lines += [
            "## Decision required",
            "",
            "Before proceeding, please ask the user:",
        ]
        for i, risk in enumerate((r for r in result.risks if r.level in ("medium", "high")), start=1):
            lines.append(f"{i}. How should the change interact with **{risk.feature_name}**?")
        lines.append("")

    # -------------------------------------------------------------------------
    # New feature edge cases (if provided)
    # -------------------------------------------------------------------------
    if edge_cases:
        must_handle = [ec for ec in edge_cases if ec.must_handle]
        advisory = [ec for ec in edge_cases if not ec.must_handle]

        lines += [
            "## Edge cases for new feature",
            "",
            f"Tether identified {len(edge_cases)} edge cases. "
            f"**{len(must_handle)} must be handled** before shipping.",
            "",
        ]

        if must_handle:
            lines += ["### Must handle (implement these)", ""]
            for ec in must_handle:
                lines += [
                    f"- **[{ec.frequency.value}]** {ec.description}",
                    f"  *{ec.rationale}*",
                    "",
                ]

        if advisory:
            lines += ["### Advisory (consider these)", ""]
            for ec in advisory:
                lines.append(f"- [{ec.frequency.value}] {ec.description}")
            lines.append("")

    lines.append(_MARKER_END)
    return "\n".join(lines)
