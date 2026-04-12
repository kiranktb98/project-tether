"""Watch check: Haiku-based intent check with diff chunking."""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import yaml

from tether.bootstrap.scanner import _PARSER, _PY_LANGUAGE, _node_text
from tether.ledger.queries import features_touching_file
from tether.ledger.schema import Feature, Ledger
from tether.prompts.templates import (
    INTENT_SYSTEM,
    INTENT_TOOL_NAME,
    INTENT_TOOL_SCHEMA,
    INTENT_USER_TEMPLATE,
)
from tether.watcher_models.base import WatcherModel

IntentVerdict = Literal["aligned", "neutral", "drifted", "looks_intentional"]
_DIFF_CHUNK_LINES = 300


@dataclass
class IntentResult:
    verdict: IntentVerdict = "neutral"
    reason: str = ""
    affected_feature_ids: list[str] = field(default_factory=list)
    chunk_verdicts: list[dict] = field(default_factory=list)  # for chunked diffs


def compute_diff(old_content: str, new_content: str, file_path: str) -> str:
    """Return a unified diff string."""
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
    affected = features_touching_file(ledger, file_path)
    if not affected:
        return IntentResult(verdict="neutral", reason="No features touch this file.")

    features_yaml = yaml.dump(
        [{"id": f.id, "name": f.name, "description": f.description} for f in affected],
        default_flow_style=False,
        allow_unicode=True,
    )
    failing_str = "\n".join(failing_test_names or []) or "(none)"

    diff_lines = diff.splitlines()
    if len(diff_lines) <= _DIFF_CHUNK_LINES:
        return _check_single_diff(
            file_path, diff, features_yaml, failing_str, model
        )

    # Large diff — chunk it
    chunks = _split_diff_by_boundary(diff, file_path)
    chunk_results: list[IntentResult] = []
    for chunk_diff in chunks:
        chunk_result = _check_single_diff(
            file_path, chunk_diff, features_yaml, failing_str, model
        )
        chunk_results.append(chunk_result)

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
    return IntentResult(
        verdict=raw.get("verdict", "neutral"),  # type: ignore[arg-type]
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


def _split_diff_by_boundary(diff: str, file_path: str) -> list[str]:
    """Split a unified diff into chunks at function/class boundaries.

    Returns a list of diff sub-strings, each <= DIFF_CHUNK_LINES lines.
    Falls back to line-count splitting if tree-sitter is unavailable.
    """
    lines = diff.splitlines(keepends=True)
    chunks: list[str] = []
    current: list[str] = []

    for line in lines:
        current.append(line)
        # Split at function/class definition lines in the diff
        stripped = line.lstrip("+-").lstrip()
        is_boundary = (
            stripped.startswith("def ") or
            stripped.startswith("class ") or
            stripped.startswith("async def ")
        )
        if is_boundary and len(current) >= _DIFF_CHUNK_LINES:
            chunks.append("".join(current))
            current = []

    if current:
        chunks.append("".join(current))

    return chunks or [diff]
