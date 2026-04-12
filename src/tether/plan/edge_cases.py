"""Shared edge case generation module.

Used by both bootstrap (backfill) and plan (new feature analysis).
"""

from __future__ import annotations

from tether.ledger.queries import apply_must_handle_rule, compute_edge_case_confidence
from tether.ledger.schema import EdgeCase, EdgeCaseFrequency, Feature
from tether.prompts.templates import (
    EDGE_CASE_SYSTEM,
    EDGE_CASE_TOOL_NAME,
    EDGE_CASE_TOOL_SCHEMA,
    EDGE_CASE_USER_TEMPLATE,
)
from tether.watcher_models.base import WatcherModel


def generate_edge_cases(
    feature: Feature,
    model: WatcherModel,
    *,
    project_name: str = "",
    count: int = 12,
) -> list[EdgeCase]:
    """Ask Haiku to enumerate edge cases for a feature.

    Applies the must_handle rule programmatically — never trusts the model
    to set must_handle directly.

    Returns a list of EdgeCase objects (without test_file set yet).
    """
    system = EDGE_CASE_SYSTEM.format(count=count)
    user = EDGE_CASE_USER_TEMPLATE.format(
        feature_name=feature.name,
        feature_description=feature.description or "(no description)",
        feature_files=", ".join(feature.files) or "(unknown)",
        project_name=project_name or "(unknown)",
        count=count,
    )

    result = model.check(
        system=system,
        user=user,
        tool_name=EDGE_CASE_TOOL_NAME,
        tool_schema=EDGE_CASE_TOOL_SCHEMA,
    )

    edge_cases: list[EdgeCase] = []
    existing_ids = {ec.id for ec in feature.edge_cases}

    for i, raw in enumerate(result.get("edge_cases", []), start=1):
        # Generate a unique edge case ID
        base_id = f"e{i}"
        eid = base_id
        n = 2
        while eid in existing_ids:
            eid = f"{base_id}_{n}"
            n += 1
        existing_ids.add(eid)

        try:
            freq = EdgeCaseFrequency(raw.get("frequency", "low"))
        except ValueError:
            freq = EdgeCaseFrequency.low

        ec = EdgeCase(
            id=eid,
            description=raw.get("description", ""),
            frequency=freq,
            rationale=raw.get("rationale", ""),
            must_handle=False,  # will be set below
            confidence=0.5,
        )
        ec.must_handle = apply_must_handle_rule(ec)
        ec.confidence = compute_edge_case_confidence(ec)
        edge_cases.append(ec)

    return edge_cases
