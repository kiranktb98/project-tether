"""Watch check: Haiku-based intent check with diff chunking."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from typing import Literal

import yaml

from tether.ledger.queries import features_touching_file
from tether.ledger.schema import Ledger
from tether.prompts.templates import (
    INTENT_SYSTEM,
    INTENT_TOOL_NAME,
    INTENT_TOOL_SCHEMA,
    INTENT_USER_TEMPLATE,
)
from tether.watcher_models.base import WatcherModel

IntentVerdict = Literal["aligned", "neutral", "drifted", "looks_intentional"]

# Diffs larger than this get split at function/class boundaries before
# being sent to Haiku. Keep this comfortably below Haiku's context, but
# large enough that typical edits fit in one call.
_DIFF_CHUNK_LINES = 300


@dataclass
class IntentResult:
    verdict: IntentVerdict = "neutral"
    reason: str = ""
    affected_feature_ids: list[str] = field(default_factory=list)
    chunk_verdicts: list[dict] = field(default_factory=list)  # for chunked diffs


def compute_diff(old_content: str, new_content: str, file_path: str) -> str:
    """Return a unified diff string.

    If old_content is empty (file is brand new or watcher hadn't cached it),
    returns an empty string — we don't intent-check full-file dumps; they
    produce noisy, low-signal verdicts and burn tokens.
    """
    if not old_content:
        return ""
    if old_content == new_content:
        return ""
    return "".join(
        difflib.unified_diff(
            old_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"a/{file_path}",
            tofile=f"b/{file_path}",
            lineterm="",
        )
    )


def run_intent_check(
    file_path: str,
    diff: str,
    ledger: Ledger,
    model: WatcherModel,
    failing_test_names: list[str] | None = None,
) -> IntentResult:
    """Send the diff to Haiku and get an intent verdict.

    For diffs > DIFF_CHUNK_LINES lines, splits by function/class boundary
    and runs one check per chunk.
    """
    if not diff.strip():
        return IntentResult(verdict="neutral", reason="Empty diff.")

    affected = features_touching_file(ledger, file_path)
    if not affected:
        return IntentResult(
            verdict="neutral", reason="No features in the ledger touch this file."
        )

    features_yaml = yaml.dump(
        [{"id": f.id, "name": f.name, "description": f.description} for f in affected],
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    )
    failing_str = "\n".join(failing_test_names or []) or "(none)"

    diff_lines = diff.splitlines()
    if len(diff_lines) <= _DIFF_CHUNK_LINES:
        return _check_single_diff(
            file_path, diff, features_yaml, failing_str, model
        )

    # Large diff — chunk it
    chunks = _split_diff_by_boundary(diff, max_lines=_DIFF_CHUNK_LINES)
    chunk_results: list[IntentResult] = []
    for chunk_diff in chunks:
        if not chunk_diff.strip():
            continue
        chunk_result = _check_single_diff(
            file_path, chunk_diff, features_yaml, failing_str, model
        )
        chunk_results.append(chunk_result)

    if not chunk_results:
        return IntentResult(verdict="neutral", reason="No non-empty diff chunks.")

    return _aggregate_chunk_results(chunk_results)


def _check_single_diff(
    file_path: str,
    diff: str,
    features_yaml: str,
    failing_str: str,
    model: WatcherModel,
) -> IntentResult:
    user_msg = INTENT_USER_TEMPLATE.format(
        file_path=file_path,
        diff=diff,
        features_yaml=features_yaml,
        failing_tests=failing_str,
    )
    raw = model.check(
        system=INTENT_SYSTEM,
        user=user_msg,
        tool_name=INTENT_TOOL_NAME,
        tool_schema=INTENT_TOOL_SCHEMA,
    )
    verdict = raw.get("verdict", "neutral")
    if verdict not in ("aligned", "neutral", "drifted", "looks_intentional"):
        verdict = "neutral"
    return IntentResult(
        verdict=verdict,  # type: ignore[arg-type]
        reason=raw.get("reason", ""),
        affected_feature_ids=raw.get("affected_feature_ids", []),
    )


def _aggregate_chunk_results(results: list[IntentResult]) -> IntentResult:
    """Aggregate multiple chunk verdicts into a single result.

    Priority: drifted > looks_intentional > neutral > aligned
    """
    _PRIO = {"drifted": 3, "looks_intentional": 2, "neutral": 1, "aligned": 0}
    highest = max(results, key=lambda r: _PRIO.get(r.verdict, 0))
    all_feature_ids = list({fid for r in results for fid in r.affected_feature_ids})
    all_reasons = [r.reason for r in results if r.reason]

    return IntentResult(
        verdict=highest.verdict,
        reason=" | ".join(all_reasons) if all_reasons else "",
        affected_feature_ids=all_feature_ids,
        chunk_verdicts=[{"verdict": r.verdict, "reason": r.reason} for r in results],
    )


def _split_diff_by_boundary(diff: str, max_lines: int = _DIFF_CHUNK_LINES) -> list[str]:
    """Split a unified diff into chunks bounded by max_lines.

    Prefers to cut at function/class boundary lines. If the current
    buffer exceeds max_lines, forces a split at the next boundary or at
    max_lines + 50% when no boundary is in sight. Always returns at
    least one chunk.
    """
    lines = diff.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []
    hard_cap = int(max_lines * 1.5)

    for line in lines:
        current.append(line)

        stripped = line.lstrip("+-").lstrip()
        is_boundary = (
            stripped.startswith("def ")
            or stripped.startswith("class ")
            or stripped.startswith("async def ")
        )

        # Prefer to cut at a boundary once we're past the soft limit.
        if is_boundary and len(current) >= max_lines:
            # Keep the boundary line as the start of the NEXT chunk so
            # Haiku sees the new function header alongside its body.
            boundary_line = current.pop()
            chunks.append("".join(current))
            current = [boundary_line]
            continue

        # No boundary in sight — force a hard split to avoid 10x-oversized
        # chunks when a diff lacks function headers (e.g. a big YAML change).
        if len(current) >= hard_cap:
            chunks.append("".join(current))
            current = []

    if current:
        chunks.append("".join(current))

    return [c for c in chunks if c] or [diff]
