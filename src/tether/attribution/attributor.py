"""Drift attribution — diagnose why a change broke a feature's tests."""

from __future__ import annotations

from dataclasses import dataclass

from tether.prompts.templates import (
    ATTRIBUTION_SYSTEM,
    ATTRIBUTION_TOOL_NAME,
    ATTRIBUTION_TOOL_SCHEMA,
    ATTRIBUTION_USER_TEMPLATE,
)
from tether.watcher_models.base import WatcherModel


@dataclass
class AttributionResult:
    source: str
    confidence: str     # high|medium|low
    explanation: str


def attribute_drift(
    file_path: str,
    diff: str,
    feature_id: str,
    feature_name: str,
    test_name: str,
    model: WatcherModel,
    *,
    recent_instructions: str = "(not available)",
    recent_amendments: str = "(not available)",
) -> AttributionResult:
    """Ask Haiku to identify the source of a drift event."""
    user_msg = ATTRIBUTION_USER_TEMPLATE.format(
        file_path=file_path,
        diff=diff,
        feature_id=feature_id,
        feature_name=feature_name,
        test_name=test_name,
        recent_instructions=recent_instructions,
        recent_amendments=recent_amendments,
    )

    raw = model.check(
        system=ATTRIBUTION_SYSTEM,
        user=user_msg,
        tool_name=ATTRIBUTION_TOOL_NAME,
        tool_schema=ATTRIBUTION_TOOL_SCHEMA,
    )

    return AttributionResult(
        source=raw.get("source", "unknown"),
        confidence=raw.get("confidence", "low"),
        explanation=raw.get("explanation", ""),
    )
